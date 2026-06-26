from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from schema import (
    COMPACT_PRODUCT_JSON_SCHEMA,
    REQUIRED_FIELDS,
    finalize_compact_product,
    normalize_compact_product,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_MAX_TEXT_CHARS = 120_000
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
PRODUCT_FIELDS_JSON_SCHEMA = COMPACT_PRODUCT_JSON_SCHEMA
FALLBACK_PROVIDER_NONE = "none"
FALLBACK_PROVIDER_OPENAI_API = "openai_api"
FALLBACK_PROVIDER_SELENIUM_COPILOT = "selenium_copilot"
FALLBACK_PROVIDERS = (
    FALLBACK_PROVIDER_NONE,
    FALLBACK_PROVIDER_OPENAI_API,
    FALLBACK_PROVIDER_SELENIUM_COPILOT,
)
SELENIUM_COPILOT_URL = "https://m365.cloud.microsoft/chat"
COPY_BUTTON_XPATH = "//button[@data-testid='CopyButtonTestId']"

DEVELOPER_PROMPT = """
You extract a compact internal operational schema for structured product termsheets.

Return exactly the provided compact schema. Use the enum values exactly as defined.
Return null for values that are not clearly present. Do not guess contractual terms.
Use current_fields_from_regex as high-confidence hints, but correct them if the text is clear.

Do not generate lifecycle_events unless the termsheet contains an explicit observation
or payment schedule table. Python will generate scheduled lifecycle events later from
dates and frequencies where possible.

Extract dates, coupon terms, barrier terms, autocall terms, first autocall date, and
frequencies when clearly stated. If payoff logic is complex or unsupported, add a
plain warning to review.warnings instead of inventing fields.
""".strip()


class OpenAIFallbackError(RuntimeError):
    pass


def is_openai_configured() -> bool:
    return bool(os.getenv("OPENAI_API_KEY"))


def is_selenium_configured() -> bool:
    return importlib.util.find_spec("selenium") is not None


def is_fallback_provider_configured(provider: str | None) -> bool:
    normalized = normalize_fallback_provider(provider)
    if normalized == FALLBACK_PROVIDER_NONE:
        return False
    if normalized == FALLBACK_PROVIDER_OPENAI_API:
        return is_openai_configured()
    if normalized == FALLBACK_PROVIDER_SELENIUM_COPILOT:
        return is_selenium_configured()
    return False


def normalize_fallback_provider(provider: str | None) -> str:
    normalized = (provider or FALLBACK_PROVIDER_OPENAI_API).strip().lower()
    aliases = {
        "off": FALLBACK_PROVIDER_NONE,
        "disabled": FALLBACK_PROVIDER_NONE,
        "openai": FALLBACK_PROVIDER_OPENAI_API,
        "api": FALLBACK_PROVIDER_OPENAI_API,
        "selenium": FALLBACK_PROVIDER_SELENIUM_COPILOT,
        "copilot": FALLBACK_PROVIDER_SELENIUM_COPILOT,
        "m365": FALLBACK_PROVIDER_SELENIUM_COPILOT,
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in FALLBACK_PROVIDERS:
        raise OpenAIFallbackError(
            f"Unknown fallback provider {provider!r}. Expected one of: "
            + ", ".join(FALLBACK_PROVIDERS)
        )
    return normalized


def enrich_product_data(
    *,
    pdf_path: Path,
    extracted_text: str,
    current_fields: dict[str, Any],
    missing_fields: list[str],
    provider: str | None = None,
    raise_errors: bool = False,
) -> dict[str, Any]:
    normalized_provider = normalize_fallback_provider(provider)
    if normalized_provider == FALLBACK_PROVIDER_NONE:
        return dict(current_fields)

    if not is_fallback_provider_configured(normalized_provider):
        if missing_fields:
            logger.warning(
                "LLM fallback provider %s skipped for %s because it is not configured. Missing fields: %s",
                normalized_provider,
                pdf_path.name,
                ", ".join(missing_fields),
            )
        else:
            logger.info(
                "LLM fallback provider %s skipped for %s because it is not configured.",
                normalized_provider,
                pdf_path.name,
            )
        return dict(current_fields)

    try:
        model_fields = extract_fields_with_provider(
            provider=normalized_provider,
            pdf_path=pdf_path,
            extracted_text=extracted_text,
            current_fields=current_fields,
            missing_fields=missing_fields,
        )
    except Exception:
        logger.exception("LLM fallback provider %s failed for %s", normalized_provider, pdf_path.name)
        if raise_errors:
            raise
        return dict(current_fields)

    merged_fields = merge_fields(current_fields, model_fields, prefer_model=True)
    logger.info("LLM fallback provider %s completed for %s", normalized_provider, pdf_path.name)
    return merged_fields


def extract_fields_with_provider(
    *,
    provider: str,
    pdf_path: Path,
    extracted_text: str,
    current_fields: dict[str, Any],
    missing_fields: list[str],
) -> dict[str, Any]:
    if provider == FALLBACK_PROVIDER_OPENAI_API:
        return extract_fields_with_openai(
            pdf_path=pdf_path,
            extracted_text=extracted_text,
            current_fields=current_fields,
            missing_fields=missing_fields,
        )
    if provider == FALLBACK_PROVIDER_SELENIUM_COPILOT:
        return extract_fields_with_selenium_copilot(
            pdf_path=pdf_path,
            extracted_text=extracted_text,
            current_fields=current_fields,
            missing_fields=missing_fields,
        )

    raise OpenAIFallbackError(f"Unsupported fallback provider: {provider}")


def extract_fields_with_openai(
    *,
    pdf_path: Path,
    extracted_text: str,
    current_fields: dict[str, Any],
    missing_fields: list[str],
) -> dict[str, Any]:
    response = call_openai_responses_api(
        build_openai_payload(
            pdf_path=pdf_path,
            extracted_text=extracted_text,
            current_fields=current_fields,
            missing_fields=missing_fields,
        ),
    )

    output_text = extract_output_text_from_api_response(response)

    try:
        fields = json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise OpenAIFallbackError(f"OpenAI response was not valid JSON: {output_text}") from exc

    if not isinstance(fields, dict):
        raise OpenAIFallbackError("OpenAI response JSON must be an object")

    return validate_model_fields(fields)


def extract_fields_with_selenium_copilot(
    *,
    pdf_path: Path,
    extracted_text: str,
    current_fields: dict[str, Any],
    missing_fields: list[str],
) -> dict[str, Any]:
    prompt = build_selenium_copilot_prompt(
        pdf_path=pdf_path,
        extracted_text=extracted_text,
        current_fields=current_fields,
        missing_fields=missing_fields,
    )
    response_text = run_selenium_copilot_prompt(prompt)
    json_text = extract_json_object_text(response_text)

    try:
        fields = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise OpenAIFallbackError(
            f"Selenium Copilot response was not valid JSON: {response_text}"
        ) from exc

    if not isinstance(fields, dict):
        raise OpenAIFallbackError("Selenium Copilot response JSON must be an object")

    return validate_model_fields(fields)


def build_selenium_copilot_prompt(
    *,
    pdf_path: Path,
    extracted_text: str,
    current_fields: dict[str, Any],
    missing_fields: list[str],
) -> str:
    user_payload = build_fallback_user_payload(
        pdf_path=pdf_path,
        extracted_text=extracted_text,
        current_fields=current_fields,
        missing_fields=missing_fields,
    )
    return (
        f"{DEVELOPER_PROMPT}\n\n"
        "Return only raw JSON. Do not include markdown, code fences, comments, or explanation.\n"
        "The JSON must match this schema:\n"
        f"{json.dumps(PRODUCT_FIELDS_JSON_SCHEMA, ensure_ascii=False)}\n\n"
        "Input payload:\n"
        f"{json.dumps(user_payload, ensure_ascii=False, indent=2)}"
    )


def run_selenium_copilot_prompt(prompt: str) -> str:
    driver = None
    try:
        driver = build_selenium_driver()
        driver.get(os.getenv("SELENIUM_COPILOT_URL", SELENIUM_COPILOT_URL))
        time.sleep(float_env("SELENIUM_COPILOT_INITIAL_WAIT_SECONDS", 10.0))

        before_count = len(find_copy_buttons(driver))
        input_box = find_copilot_input(driver)
        input_box.send_keys(prompt)

        from selenium.webdriver.common.keys import Keys

        input_box.send_keys(Keys.ENTER)
        copy_button = wait_for_latest_copy_button(driver, before_count)
        driver.execute_script("arguments[0].click();", copy_button)
        time.sleep(float_env("SELENIUM_COPILOT_CLIPBOARD_WAIT_SECONDS", 1.0))
        return read_browser_clipboard(driver)
    finally:
        if driver is not None and not bool_env("SELENIUM_COPILOT_KEEP_BROWSER_OPEN", False):
            try:
                driver.quit()
            except Exception:
                pass


def build_selenium_driver() -> Any:
    try:
        from selenium.webdriver import Chrome
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
    except ImportError as exc:
        raise OpenAIFallbackError(
            "selenium is not installed. Run: pip install -r requirements.txt"
        ) from exc

    prefs = {"profile.default_content_setting_values.clipboard": 1}
    chrome_options = Options()
    chrome_options.add_experimental_option("prefs", prefs)
    chrome_options.add_argument("--disable-notifications")

    user_data_dir = os.getenv("SELENIUM_CHROME_USER_DATA_DIR")
    if user_data_dir:
        chrome_options.add_argument(f"--user-data-dir={user_data_dir}")

    profile_directory = os.getenv("SELENIUM_CHROME_PROFILE_DIRECTORY")
    if profile_directory:
        chrome_options.add_argument(f"--profile-directory={profile_directory}")

    if bool_env("SELENIUM_HEADLESS", False):
        chrome_options.add_argument("--headless=new")

    driver_path = os.getenv("SELENIUM_CHROMEDRIVER_PATH") or os.getenv("CHROMEDRIVER_PATH")
    if driver_path:
        return Chrome(service=Service(driver_path), options=chrome_options)

    return Chrome(options=chrome_options)


def find_copilot_input(driver: Any) -> Any:
    selectors = [
        "[role='textbox']",
        "textarea",
        "div[contenteditable='true']",
    ]
    for selector in selectors:
        for element in driver.find_elements("css selector", selector):
            try:
                if element.is_displayed() and element.is_enabled():
                    element.click()
                    return element
            except Exception:
                continue

    return driver.switch_to.active_element


def wait_for_latest_copy_button(driver: Any, before_count: int) -> Any:
    from selenium.webdriver.support.ui import WebDriverWait

    timeout = float_env("SELENIUM_COPILOT_RESPONSE_TIMEOUT_SECONDS", 120.0)
    poll_frequency = float_env("SELENIUM_COPILOT_POLL_SECONDS", 1.0)

    def latest_copy_button(browser: Any) -> Any | bool:
        buttons = find_copy_buttons(browser)
        if len(buttons) > before_count:
            return buttons[-1]
        return False

    try:
        return WebDriverWait(driver, timeout, poll_frequency=poll_frequency).until(
            latest_copy_button
        )
    except Exception:
        buttons = find_copy_buttons(driver)
        if buttons:
            return buttons[-1]
        raise


def find_copy_buttons(driver: Any) -> list[Any]:
    return driver.find_elements("xpath", COPY_BUTTON_XPATH)


def read_browser_clipboard(driver: Any) -> str:
    script = """
        const done = arguments[0];
        navigator.clipboard.readText()
          .then(text => done({text}))
          .catch(error => done({error: String(error)}));
    """
    result = driver.execute_async_script(script)
    if isinstance(result, dict) and result.get("text"):
        return str(result["text"])

    fallback_text = read_system_clipboard()
    if fallback_text:
        return fallback_text

    error = result.get("error") if isinstance(result, dict) else result
    raise OpenAIFallbackError(f"Could not read browser clipboard: {error}")


def read_system_clipboard() -> str:
    commands = system_clipboard_commands()
    for command in commands:
        try:
            completed = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except Exception:
            continue

        text = completed.stdout.strip()
        if text:
            return text

    return ""


def system_clipboard_commands() -> list[list[str]]:
    if sys.platform == "darwin":
        return [["pbpaste"]]
    if sys.platform.startswith("win"):
        return [["powershell", "-NoProfile", "-Command", "Get-Clipboard"]]
    return [["wl-paste"], ["xclip", "-selection", "clipboard", "-o"], ["xsel", "-b", "-o"]]


def call_openai_responses_api(payload: dict[str, Any]) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise OpenAIFallbackError("OPENAI_API_KEY is not set")

    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        os.getenv("OPENAI_RESPONSES_URL", OPENAI_RESPONSES_URL),
        data=body,
        headers=openai_request_headers(api_key),
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=openai_timeout_seconds()) as response:
            response_body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise OpenAIFallbackError(
            f"OpenAI API request failed with HTTP {exc.code}: {error_body}"
        ) from exc
    except urllib.error.URLError as exc:
        raise OpenAIFallbackError(f"OpenAI API request failed: {exc.reason}") from exc

    try:
        parsed = json.loads(response_body)
    except json.JSONDecodeError as exc:
        raise OpenAIFallbackError(f"OpenAI API response was not valid JSON: {response_body}") from exc

    if not isinstance(parsed, dict):
        raise OpenAIFallbackError("OpenAI API response JSON must be an object")

    return parsed


def openai_request_headers(api_key: str) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    organization = os.getenv("OPENAI_ORG_ID")
    if organization:
        headers["OpenAI-Organization"] = organization

    project = os.getenv("OPENAI_PROJECT_ID")
    if project:
        headers["OpenAI-Project"] = project

    return headers


def openai_timeout_seconds() -> float:
    raw_timeout = os.getenv("OPENAI_FALLBACK_TIMEOUT_SECONDS", "90")
    try:
        return float(raw_timeout)
    except ValueError:
        return 90.0


def extract_output_text_from_api_response(response: dict[str, Any]) -> str:
    direct_output_text = response.get("output_text")
    if isinstance(direct_output_text, str) and direct_output_text.strip():
        return direct_output_text

    output_parts: list[str] = []

    for item in response.get("output", []) or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []) or []:
            if not isinstance(content, dict):
                continue
            refusal = content.get("refusal")
            if refusal:
                raise OpenAIFallbackError(f"OpenAI model refused: {refusal}")

            text = content.get("text")
            if text:
                output_parts.append(text)

    output_text = "".join(output_parts).strip()
    if not output_text:
        raise OpenAIFallbackError(f"OpenAI response did not contain output text: {response}")

    return output_text


def build_openai_payload(
    *,
    pdf_path: Path,
    extracted_text: str,
    current_fields: dict[str, Any],
    missing_fields: list[str],
) -> dict[str, Any]:
    model = os.getenv("OPENAI_MODEL", DEFAULT_MODEL)
    max_output_tokens = int(os.getenv("OPENAI_FALLBACK_MAX_OUTPUT_TOKENS", "2400"))

    user_payload = build_fallback_user_payload(
        pdf_path=pdf_path,
        extracted_text=extracted_text,
        current_fields=current_fields,
        missing_fields=missing_fields,
    )

    return {
        "model": model,
        "store": False,
        "max_output_tokens": max_output_tokens,
        "input": [
            {
                "role": "developer",
                "content": DEVELOPER_PROMPT,
            },
            {
                "role": "user",
                "content": (
                    "Extract the termsheet as compact operational JSON matching the schema.\n\n"
                    + json.dumps(user_payload, ensure_ascii=False, indent=2)
                ),
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "compact_termsheet_product",
                "strict": True,
                "schema": PRODUCT_FIELDS_JSON_SCHEMA,
            }
        },
    }


def build_fallback_user_payload(
    *,
    pdf_path: Path,
    extracted_text: str,
    current_fields: dict[str, Any],
    missing_fields: list[str],
) -> dict[str, Any]:
    return {
        "source_pdf": pdf_path.name,
        "schema_version": "1.0",
        "required_fields_before_approval": list(REQUIRED_FIELDS),
        "missing_fields_after_regex": missing_fields,
        "current_fields_from_regex": normalize_compact_product(current_fields),
        "termsheet_text": trim_termsheet_text(extracted_text),
    }


def trim_termsheet_text(text: str) -> str:
    max_chars = int(
        os.getenv(
            "SELENIUM_COPILOT_MAX_TEXT_CHARS",
            os.getenv("OPENAI_FALLBACK_MAX_TEXT_CHARS", str(DEFAULT_MAX_TEXT_CHARS)),
        )
    )
    if len(text) <= max_chars:
        return text

    head_chars = int(max_chars * 0.75)
    tail_chars = max_chars - head_chars
    return (
        text[:head_chars]
        + "\n\n[... termsheet text truncated for API fallback ...]\n\n"
        + text[-tail_chars:]
    )


def validate_model_fields(fields: dict[str, Any]) -> dict[str, Any]:
    return finalize_compact_product(fields)


def merge_fields(
    current_fields: dict[str, Any],
    model_fields: dict[str, Any],
    *,
    prefer_model: bool = False,
) -> dict[str, Any]:
    current = normalize_compact_product(current_fields)
    model = normalize_compact_product(model_fields)
    merged = merge_values(current, model, prefer_model=prefer_model)
    return finalize_compact_product(merged)


def merge_values(current: Any, model: Any, *, prefer_model: bool) -> Any:
    if isinstance(current, dict) and isinstance(model, dict):
        result = dict(current)
        for key, value in model.items():
            result[key] = merge_values(result.get(key), value, prefer_model=prefer_model)
        return result

    if isinstance(current, list) and isinstance(model, list):
        if model and (prefer_model or not current):
            return model
        return current

    if prefer_model and not is_empty_model_value(model):
        return model
    if is_empty_model_value(current):
        return model
    return current


def is_empty_model_value(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == "unknown"


def extract_json_object_text(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = strip_markdown_fence(stripped)

    start = stripped.find("{")
    if start < 0:
        raise OpenAIFallbackError(f"Response did not contain a JSON object: {text}")

    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(stripped)):
        char = stripped[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return stripped[start : index + 1]

    raise OpenAIFallbackError(f"Response JSON object was not complete: {text}")


def strip_markdown_fence(text: str) -> str:
    lines = text.splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


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
    parser = argparse.ArgumentParser(
        description="Extract termsheet product fields with an LLM fallback.",
    )
    parser.add_argument("pdf_path", type=Path)
    parser.add_argument(
        "--provider",
        choices=[FALLBACK_PROVIDER_OPENAI_API, FALLBACK_PROVIDER_SELENIUM_COPILOT],
        default=FALLBACK_PROVIDER_OPENAI_API,
        help="LLM fallback provider to use.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON output path. Prints to stdout when omitted.",
    )
    args = parser.parse_args(argv)

    from parser import get_missing_required_fields, parse_product_text
    from pdf_extract import extract_pdf_text

    extracted_text = extract_pdf_text(args.pdf_path)
    current_fields = parse_product_text(extracted_text)
    missing_fields = get_missing_required_fields(current_fields)
    fields = enrich_product_data(
        pdf_path=args.pdf_path,
        extracted_text=extracted_text,
        current_fields=current_fields,
        missing_fields=missing_fields,
        provider=args.provider,
    )

    result = {
        "source_pdf": args.pdf_path.name,
        "fallback_used": is_fallback_provider_configured(args.provider),
        "fallback_provider": args.provider,
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
