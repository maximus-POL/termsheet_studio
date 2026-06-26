from __future__ import annotations

import argparse
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from schema import COMPACT_PRODUCT_JSON_SCHEMA, finalize_compact_product

logger = logging.getLogger(__name__)

URL_COPILOT = "https://m365.cloud.microsoft/chat"
COPY_BUTTON_XPATH = "//button[@data-testid='CopyButtonTestId']"

PREPROMPT = f"""
Extract this termsheet into the compact JSON schema below.

Return only raw JSON. Do not use markdown. Do not explain anything.
Use null when a value is not clearly present. Do not guess.

Schema:
{json.dumps(COMPACT_PRODUCT_JSON_SCHEMA, ensure_ascii=False)}

Full parsed PDF text:
""".strip()


class CopilotFallbackError(RuntimeError):
    pass


def is_copilot_configured() -> bool:
    try:
        import pyperclip  # noqa: F401
        from selenium.webdriver import Chrome  # noqa: F401
    except ImportError:
        return False
    return True


def enrich_product_data(
    *,
    pdf_path: Path,
    extracted_text: str,
    current_fields: dict[str, Any],
    missing_fields: list[str],
    raise_errors: bool = False,
) -> dict[str, Any]:
    try:
        return extract_fields_with_copilot(extracted_text)
    except Exception:
        logger.exception("Selenium Copilot fallback failed for %s", pdf_path.name)
        if raise_errors:
            raise
        return dict(current_fields)


def extract_fields_with_copilot(extracted_text: str) -> dict[str, Any]:
    response = run_copilot_prompt(f"{PREPROMPT}\n\n{extracted_text}")
    fields = json.loads(extract_json_object_text(response))
    if not isinstance(fields, dict):
        raise CopilotFallbackError("Copilot response JSON must be an object")
    return finalize_compact_product(fields)


def run_copilot_prompt(prompt: str) -> str:
    from selenium.webdriver import Chrome
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.keys import Keys
    import pyperclip

    driver_path = os.getenv("SELENIUM_CHROMEDRIVER_PATH", "chromedriver-win64/chromedriver.exe")
    service = Service(driver_path)

    prefs = {"profile.default_content_setting_values.clipboard": 1}
    chrome_options = Options()
    chrome_options.add_experimental_option("prefs", prefs)

    driver = Chrome(service=service, options=chrome_options)
    try:
        driver.get(os.getenv("SELENIUM_COPILOT_URL", URL_COPILOT))
        time.sleep(float(os.getenv("SELENIUM_COPILOT_INITIAL_WAIT_SECONDS", "10")))

        input_box = driver.switch_to.active_element
        input_box.send_keys(prompt)
        input_box.send_keys(Keys.ENTER)

        time.sleep(float(os.getenv("SELENIUM_COPILOT_RESPONSE_WAIT_SECONDS", "10")))

        copy_buttons = driver.find_elements("xpath", COPY_BUTTON_XPATH)
        if not copy_buttons:
            raise CopilotFallbackError("Could not find Copilot copy button")

        driver.execute_script("arguments[0].click();", copy_buttons[-1])
        time.sleep(1)

        return pyperclip.paste()
    finally:
        if os.getenv("SELENIUM_COPILOT_KEEP_BROWSER_OPEN", "").lower() not in {"1", "true", "yes"}:
            driver.quit()


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
    raise SystemExit(main())
