from __future__ import annotations

import argparse
import json
import logging
import os
import sys
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


def enrich_product_data(
    *,
    pdf_path: Path,
    extracted_text: str,
    current_fields: dict[str, Any],
    missing_fields: list[str],
) -> dict[str, Any]:
    if not is_openai_configured():
        if missing_fields:
            logger.warning(
                "OpenAI fallback skipped for %s because OPENAI_API_KEY is not set. Missing fields: %s",
                pdf_path.name,
                ", ".join(missing_fields),
            )
        else:
            logger.info("OpenAI fallback skipped for %s because OPENAI_API_KEY is not set.", pdf_path.name)
        return dict(current_fields)

    try:
        model_fields = extract_fields_with_openai(
            pdf_path=pdf_path,
            extracted_text=extracted_text,
            current_fields=current_fields,
            missing_fields=missing_fields,
        )
    except Exception:
        logger.exception("OpenAI fallback failed for %s", pdf_path.name)
        return dict(current_fields)

    merged_fields = merge_fields(current_fields, model_fields, prefer_model=True)
    logger.info("OpenAI fallback completed for %s", pdf_path.name)
    return merged_fields


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

    user_payload = {
        "source_pdf": pdf_path.name,
        "schema_version": "1.0",
        "required_fields_before_approval": list(REQUIRED_FIELDS),
        "missing_fields_after_regex": missing_fields,
        "current_fields_from_regex": normalize_compact_product(current_fields),
        "termsheet_text": trim_termsheet_text(extracted_text),
    }

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


def trim_termsheet_text(text: str) -> str:
    max_chars = int(os.getenv("OPENAI_FALLBACK_MAX_TEXT_CHARS", str(DEFAULT_MAX_TEXT_CHARS)))
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract termsheet product fields with the OpenAI fallback only.",
    )
    parser.add_argument("pdf_path", type=Path)
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
    )

    result = {
        "source_pdf": args.pdf_path.name,
        "fallback_used": is_openai_configured(),
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
