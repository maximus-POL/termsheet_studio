from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal, TypedDict

from excel_writer import write_product_excel
from fallback_copilot import enrich_product_data, is_openai_configured
from parser import PARSER_VERSION, get_missing_required_fields, parse_product_text
from pdf_extract import extract_pdf_text
from schema import finalize_compact_product
from template_profiles import TemplateProfile

ProductStatus = Literal["draft", "stored", "failed"]

VALID_PRODUCT_STATUSES: set[str] = {"draft", "stored", "failed"}


class ProcessingDraft(TypedDict):
    source_pdf: str
    processed_at: str
    parser_version: str
    fallback_used: bool
    fallback_error: str | None
    missing_required: list[str]
    template: dict[str, str] | None
    fields: dict[str, str]
    extracted_text: str


def parse_pdf_to_draft(
    pdf_path: Path,
    *,
    template_profile: TemplateProfile | None = None,
    use_llm: bool = True,
) -> dict[str, Any]:
    extracted_text = extract_pdf_text(pdf_path)
    fields = parse_product_text(extracted_text)
    fields["document"]["file_name"] = pdf_path.name
    missing_required = get_missing_required_fields(fields)

    fallback_used = False
    fallback_error: str | None = None

    if use_llm and is_openai_configured():
        fallback_used = True
        try:
            fields = enrich_product_data(
                pdf_path=pdf_path,
                extracted_text=extracted_text,
                current_fields=fields,
                missing_fields=missing_required,
            )
        except Exception as exc:
            fallback_error = str(exc)

    fields = finalize_compact_product(fields)
    missing_required = get_missing_required_fields(fields)

    draft: ProcessingDraft = {
        "source_pdf": pdf_path.name,
        "processed_at": timestamp_iso(),
        "parser_version": PARSER_VERSION,
        "fallback_used": fallback_used,
        "fallback_error": fallback_error,
        "missing_required": missing_required,
        "template": template_to_dict(template_profile),
        "fields": fields,
        "extracted_text": extracted_text,
    }
    return dict(draft)


def build_product_record_from_draft(
    draft: dict[str, Any],
    *,
    product_id: str,
    status: str = "draft",
) -> dict[str, Any]:
    normalized_status = normalize_product_status(status)
    now = timestamp_iso()

    return {
        "product_id": product_id,
        "created_at": draft.get("created_at") or now,
        "updated_at": now,
        "status": normalized_status,
        "source_pdf": draft.get("source_pdf"),
        "processed_at": draft.get("processed_at"),
        "parser_version": draft.get("parser_version", PARSER_VERSION),
        "fallback_used": bool(draft.get("fallback_used", False)),
        "fallback_error": draft.get("fallback_error"),
        "missing_required": normalize_string_list(draft.get("missing_required")),
        "template": normalize_mapping(draft.get("template")),
        "fields": finalize_compact_product(normalize_mapping(draft.get("fields"))),
        "generated_files": normalize_string_list(draft.get("generated_files")),
    }


def export_product_excel(
    product_record: dict[str, Any],
    template_profile: TemplateProfile,
    output_path: Path,
) -> Path:
    return write_product_excel(
        product_data=product_record,
        template_path=template_profile.template_path,
        output_path=output_path,
    )


def template_to_dict(template_profile: TemplateProfile | None) -> dict[str, str] | None:
    if template_profile is None:
        return None

    return {
        "name": template_profile.name,
        "path": template_profile.template_path.as_posix(),
    }


def timestamp_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def normalize_product_status(status: str) -> ProductStatus:
    normalized = str(status or "draft").strip().lower()
    if normalized not in VALID_PRODUCT_STATUSES:
        raise ValueError(
            f"Invalid product status: {status!r}. Expected one of: "
            + ", ".join(sorted(VALID_PRODUCT_STATUSES))
        )

    return normalized  # type: ignore[return-value]


def normalize_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []

    return [item for item in value if isinstance(item, str) and item]
