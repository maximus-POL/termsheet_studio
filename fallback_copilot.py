from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from schema import (
    COMPACT_PRODUCT_JSON_SCHEMA,
    REQUIRED_FIELDS,
    finalize_compact_product,
    normalize_compact_product,
)

logger = logging.getLogger(__name__)

DEFAULT_MAX_TEXT_CHARS = 120_000
SELENIUM_COPILOT_URL = "https://m365.cloud.microsoft/chat"
COPY_BUTTON_XPATH = "//button[@data-testid='CopyButtonTestId']"

PROMPT = """
You extract a compact internal operational schema for structured product termsheets.

Return only raw JSON matching the provided compact schema. Do not include markdown,
comments, explanations, or code fences. Use enum values exactly as defined.
Return null for values that are not clearly present. Do not guess contractual terms.
Use current_fields_from_regex as high-confidence hints, but correct them if the text is clear.

Do not generate lifecycle_events unless the termsheet contains an explicit observation
or payment schedule table. Python will generate scheduled lifecycle events later.
""".strip()


class CopilotFallbackError(RuntimeError):
    pass


def is_copilot_configured() -> bool:
    return importlib.util.find_spec("selenium") is not None


def enrich_product_data(
    *,
    pdf_path: Path,
    extracted_text: str,
    current_fields: dict[str, Any],
    missing_fields: list[str],
    raise_errors: bool = False,
) -> dict[str, Any]:
    if not is_copilot_configured():
        logger.warning("Selenium Copilot fallback skipped because selenium is not installed.")
        return dict(current_fields)

    try:
        model_fields = extract_fields_with_copilot(
            pdf_path=pdf_path,
            extracted_text=extracted_text,
            current_fields=current_fields,
            missing_fields=missing_fields,
        )
    except Exception:
        logger.exception("Selenium Copilot fallback failed for %s", pdf_path.name)
        if raise_errors:
            raise
        return dict(current_fields)

    return merge_fields(current_fields, model_fields, prefer_model=True)


def extract_fields_with_copilot(
    *,
    pdf_path: Path,
    extracted_text: str,
    current_fields: dict[str, Any],
    missing_fields: list[str],
) -> dict[str, Any]:
    response = run_copilot_prompt(
        build_prompt(
            pdf_path=pdf_path,
            extracted_text=extracted_text,
            current_fields=current_fields,
            missing_fields=missing_fields,
        )
    )
    fields = json.loads(extract_json_object_text(response))
    if not isinstance(fields, dict):
        raise CopilotFallbackError("Copilot response JSON must be an object")
    return finalize_compact_product(fields)


def build_prompt(
    *,
    pdf_path: Path,
    extracted_text: str,
    current_fields: dict[str, Any],
    missing_fields: list[str],
) -> str:
    payload = {
        "source_pdf": pdf_path.name,
        "required_fields_before_approval": list(REQUIRED_FIELDS),
        "missing_fields_after_regex": missing_fields,
        "current_fields_from_regex": normalize_compact_product(current_fields),
        "termsheet_text": trim_text(extracted_text),
    }
    return (
        f"{PROMPT}\n\n"
        "Compact JSON schema:\n"
        f"{json.dumps(COMPACT_PRODUCT_JSON_SCHEMA, ensure_ascii=False)}\n\n"
        "Input:\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def run_copilot_prompt(prompt: str) -> str:
    driver = None
    try:
        driver = build_driver()
        driver.get(os.getenv("SELENIUM_COPILOT_URL", SELENIUM_COPILOT_URL))
        time.sleep(float_env("SELENIUM_COPILOT_INITIAL_WAIT_SECONDS", 10))

        copy_count = len(driver.find_elements("xpath", COPY_BUTTON_XPATH))
        input_box = find_input(driver)
        input_box.send_keys(prompt)

        from selenium.webdriver.common.keys import Keys

        input_box.send_keys(Keys.ENTER)
        copy_button = wait_for_copy_button(driver, copy_count)
        driver.execute_script("arguments[0].click();", copy_button)
        time.sleep(float_env("SELENIUM_COPILOT_CLIPBOARD_WAIT_SECONDS", 1))
        return read_clipboard(driver)
    finally:
        if driver is not None and not bool_env("SELENIUM_COPILOT_KEEP_BROWSER_OPEN", False):
            driver.quit()


def build_driver() -> Any:
    try:
        from selenium.webdriver import Chrome
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
    except ImportError as exc:
        raise CopilotFallbackError("selenium is not installed") from exc

    options = Options()
    options.add_experimental_option(
        "prefs",
        {"profile.default_content_setting_values.clipboard": 1},
    )
    options.add_argument("--disable-notifications")

    user_data_dir = os.getenv("SELENIUM_CHROME_USER_DATA_DIR")
    if user_data_dir:
        options.add_argument(f"--user-data-dir={user_data_dir}")

    driver_path = os.getenv("SELENIUM_CHROMEDRIVER_PATH") or os.getenv("CHROMEDRIVER_PATH")
    if driver_path:
        return Chrome(service=Service(driver_path), options=options)
    return Chrome(options=options)


def find_input(driver: Any) -> Any:
    for selector in ("[role='textbox']", "textarea", "div[contenteditable='true']"):
        for element in driver.find_elements("css selector", selector):
            if element.is_displayed() and element.is_enabled():
                element.click()
                return element
    return driver.switch_to.active_element


def wait_for_copy_button(driver: Any, previous_count: int) -> Any:
    from selenium.webdriver.support.ui import WebDriverWait

    def latest_button(browser: Any) -> Any | bool:
        buttons = browser.find_elements("xpath", COPY_BUTTON_XPATH)
        if len(buttons) > previous_count:
            return buttons[-1]
        return False

    timeout = float_env("SELENIUM_COPILOT_RESPONSE_TIMEOUT_SECONDS", 120)
    return WebDriverWait(driver, timeout, poll_frequency=1).until(latest_button)


def read_clipboard(driver: Any) -> str:
    result = driver.execute_async_script(
        """
        const done = arguments[0];
        navigator.clipboard.readText()
          .then(text => done({text}))
          .catch(error => done({error: String(error)}));
        """
    )
    if isinstance(result, dict) and result.get("text"):
        return str(result["text"])

    text = read_system_clipboard()
    if text:
        return text

    raise CopilotFallbackError(f"Could not read clipboard: {result}")


def read_system_clipboard() -> str:
    commands = {
        "darwin": [["pbpaste"]],
        "win32": [["powershell", "-NoProfile", "-Command", "Get-Clipboard"]],
    }.get(sys.platform, [["wl-paste"], ["xclip", "-selection", "clipboard", "-o"]])

    for command in commands:
        try:
            result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=5)
        except Exception:
            continue
        if result.stdout.strip():
            return result.stdout.strip()
    return ""


def extract_json_object_text(text: str) -> str:
    text = strip_markdown_fence(text.strip())
    start = text.find("{")
    if start < 0:
        raise CopilotFallbackError(f"Response did not contain JSON: {text}")

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise CopilotFallbackError(f"Response JSON was incomplete: {text}")


def strip_markdown_fence(text: str) -> str:
    lines = text.splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def trim_text(text: str) -> str:
    max_chars = int(os.getenv("SELENIUM_COPILOT_MAX_TEXT_CHARS", str(DEFAULT_MAX_TEXT_CHARS)))
    if len(text) <= max_chars:
        return text
    head_chars = int(max_chars * 0.75)
    return text[:head_chars] + "\n\n[... termsheet text truncated ...]\n\n" + text[-(max_chars - head_chars) :]


def merge_fields(current_fields: dict[str, Any], model_fields: dict[str, Any], *, prefer_model: bool) -> dict[str, Any]:
    current = normalize_compact_product(current_fields)
    model = normalize_compact_product(model_fields)
    return finalize_compact_product(merge_values(current, model, prefer_model=prefer_model))


def merge_values(current: Any, model: Any, *, prefer_model: bool) -> Any:
    if isinstance(current, dict) and isinstance(model, dict):
        result = dict(current)
        for key, value in model.items():
            result[key] = merge_values(result.get(key), value, prefer_model=prefer_model)
        return result
    if isinstance(current, list) and isinstance(model, list):
        return model if model and (prefer_model or not current) else current
    if prefer_model and model not in (None, "", [], "unknown"):
        return model
    return model if current in (None, "", [], "unknown") else current


def float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract termsheet fields with Selenium Copilot.")
    parser.add_argument("pdf_path", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    from parser import get_missing_required_fields, parse_product_text
    from pdf_extract import extract_pdf_text

    extracted_text = extract_pdf_text(args.pdf_path)
    current_fields = parse_product_text(extracted_text)
    fields = enrich_product_data(
        pdf_path=args.pdf_path,
        extracted_text=extracted_text,
        current_fields=current_fields,
        missing_fields=get_missing_required_fields(current_fields),
    )
    result = {
        "source_pdf": args.pdf_path.name,
        "fallback_used": is_copilot_configured(),
        "missing_required": get_missing_required_fields(fields),
        "fields": fields,
    }

    result_json = json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(result_json + "\n", encoding="utf-8")
    else:
        print(result_json)
    return 1 if result["missing_required"] else 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(main())
