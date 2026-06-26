from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from config import (
    BASE_DIR,
    FAILED_DIR,
    INPUT_DIR,
    LOG_FILE,
    PROCESSED_DIR,
    STAGING_DIR,
    ensure_directories,
)
from excel_writer import write_product_excel
from fallback_copilot import enrich_product_data, is_openai_configured
from parser import PARSER_VERSION, get_missing_required_fields, parse_product_text
from pdf_extract import extract_pdf_text
from template_profiles import (
    DEFAULT_TEMPLATE_NAME,
    TemplateProfile,
    TemplateProfileError,
    discover_template_profiles,
    resolve_template_profile,
)

logger = logging.getLogger(__name__)


class ProcessingError(RuntimeError):
    """Raised when a PDF cannot be turned into a complete product record."""


class MissingRequiredFieldsError(ProcessingError):
    def __init__(self, fields: list[str]) -> None:
        self.fields = fields
        super().__init__(
            "Missing required fields after regex parsing and fallback: "
            + ", ".join(fields)
        )


@dataclass(frozen=True)
class ProcessingResult:
    pdf_path: Path
    success: bool
    output_dir: Path | None
    error: str | None = None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Turn PDF termsheets into upload-ready Excel files.",
    )
    parser.add_argument(
        "--template",
        default=DEFAULT_TEMPLATE_NAME,
        help=(
            "Template name or .xlsx/.xlsm path to use. Defaults to 'default', "
            "which points to templates/upload_template.xlsx or templates/upload_template.xlsm."
        ),
    )
    parser.add_argument(
        "--list-templates",
        action="store_true",
        help="List discovered templates and exit without processing PDFs.",
    )
    return parser.parse_args(argv)


def configure_logging() -> None:
    ensure_directories()
    handlers: list[logging.Handler] = [logging.StreamHandler()]

    try:
        handlers.append(logging.FileHandler(LOG_FILE, encoding="utf-8"))
    except OSError as exc:
        logging.basicConfig(level=logging.INFO)
        logger.warning("Could not attach file logger at %s: %s", LOG_FILE, exc)
        return

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )


def find_input_pdfs() -> list[Path]:
    if not INPUT_DIR.exists():
        return []

    return sorted(
        path for path in INPUT_DIR.iterdir() if path.is_file() and path.suffix.lower() == ".pdf"
    )


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
    return cleaned or "termsheet"


def safe_stem(path: Path) -> str:
    return safe_name(path.stem)


def unique_dir(parent: Path, base_name: str) -> Path:
    candidate = parent / base_name
    if not candidate.exists():
        return candidate

    for index in range(1, 1000):
        candidate = parent / f"{base_name}_{index:03d}"
        if not candidate.exists():
            return candidate

    raise ProcessingError(f"Could not allocate unique output directory for {base_name}")


def build_product_record(
    *,
    pdf_path: Path,
    template_profile: TemplateProfile,
    fields: dict[str, str],
    fallback_used: bool,
    missing_required: list[str],
) -> dict:
    return {
        "source_pdf": pdf_path.name,
        "processed_at": datetime.now().isoformat(timespec="seconds"),
        "parser_version": PARSER_VERSION,
        "fallback_used": fallback_used,
        "missing_required": missing_required,
        "template": {
            "name": template_profile.name,
            "path": display_path(template_profile.template_path),
        },
        "fields": fields,
    }


def display_path(path: Path) -> str:
    try:
        return path.relative_to(BASE_DIR).as_posix()
    except ValueError:
        return str(path)


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def write_failure_artifacts(pdf_path: Path, target_dir: Path, exc: BaseException) -> bool:
    try:
        target_dir.mkdir(parents=True, exist_ok=False)
        shutil.copy2(pdf_path, target_dir / pdf_path.name)

        error_text = (
            f"{type(exc).__name__}: {exc}\n\n"
            f"Traceback:\n{traceback.format_exc()}"
        )
        (target_dir / "error.txt").write_text(error_text, encoding="utf-8")
    except Exception:
        logger.exception("Could not write failure artifacts for %s", pdf_path.name)
        return False

    return True


def clean_input_pdf(pdf_path: Path) -> None:
    try:
        if pdf_path.exists():
            pdf_path.unlink()
    except OSError:
        logger.exception("Processed output exists, but could not remove input PDF: %s", pdf_path)


def excel_output_name(pdf_path: Path, template_profile: TemplateProfile) -> str:
    template_suffix = safe_name(template_profile.name)
    workbook_suffix = template_profile.template_path.suffix.lower() or ".xlsx"
    if template_suffix in {DEFAULT_TEMPLATE_NAME, "upload_template"}:
        return f"{safe_stem(pdf_path)}{workbook_suffix}"

    return f"{safe_stem(pdf_path)}_{template_suffix}{workbook_suffix}"


def process_pdf(pdf_path: Path, template_profile: TemplateProfile) -> ProcessingResult:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    job_name = f"{safe_stem(pdf_path)}_{safe_name(template_profile.name)}_{timestamp}"
    staging_dir = unique_dir(STAGING_DIR, job_name)

    try:
        logger.info(
            "Processing %s with template %s (%s)",
            pdf_path.name,
            template_profile.name,
            display_path(template_profile.template_path),
        )

        extracted_text = extract_pdf_text(pdf_path)
        fields = parse_product_text(extracted_text)
        missing_required = get_missing_required_fields(fields)

        fallback_used = False
        if is_openai_configured() or missing_required:
            fallback_used = is_openai_configured()
            fields = enrich_product_data(
                pdf_path=pdf_path,
                extracted_text=extracted_text,
                current_fields=fields,
                missing_fields=missing_required,
            )
            missing_required = get_missing_required_fields(fields)

        if missing_required:
            raise MissingRequiredFieldsError(missing_required)

        staging_dir.mkdir(parents=True, exist_ok=False)
        shutil.copy2(pdf_path, staging_dir / pdf_path.name)

        product_record = build_product_record(
            pdf_path=pdf_path,
            template_profile=template_profile,
            fields=fields,
            fallback_used=fallback_used,
            missing_required=missing_required,
        )
        write_json(staging_dir / "product.json", product_record)
        write_product_excel(
            product_data=product_record,
            template_path=template_profile.template_path,
            output_path=staging_dir / excel_output_name(pdf_path, template_profile),
        )

        final_dir = unique_dir(PROCESSED_DIR, job_name)
        shutil.move(str(staging_dir), str(final_dir))
        clean_input_pdf(pdf_path)

        logger.info("Processed %s -> %s", pdf_path.name, final_dir)
        return ProcessingResult(pdf_path=pdf_path, success=True, output_dir=final_dir)

    except Exception as exc:
        logger.exception("Failed to process %s", pdf_path.name)

        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)

        failed_dir = unique_dir(FAILED_DIR, job_name)
        failure_saved = write_failure_artifacts(pdf_path, failed_dir, exc)
        if failure_saved:
            clean_input_pdf(pdf_path)
            output_dir: Path | None = failed_dir
        else:
            output_dir = None

        return ProcessingResult(
            pdf_path=pdf_path,
            success=False,
            output_dir=output_dir,
            error=str(exc),
        )


def validate_environment(pdfs: list[Path], template_profile: TemplateProfile) -> bool:
    if not pdfs:
        return True

    if not template_profile.template_path.exists():
        logger.error(
            "Excel template is missing. Add your template at %s before running.",
            template_profile.template_path,
        )
        return False

    return True


def print_available_templates() -> None:
    profiles = discover_template_profiles()
    if not profiles:
        print("No Excel templates found in templates/.")
        return

    default_path = resolve_template_profile(DEFAULT_TEMPLATE_NAME).template_path
    print("Available templates:")
    for profile in profiles:
        default_marker = " (default)" if profile.template_path == default_path else ""
        print(f"- {profile.name}{default_marker}: {display_path(profile.template_path)}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    configure_logging()
    ensure_directories()

    if args.list_templates:
        print_available_templates()
        return 0

    try:
        template_profile = resolve_template_profile(args.template)
    except TemplateProfileError as exc:
        logger.error("%s", exc)
        return 1

    pdfs = find_input_pdfs()
    if not pdfs:
        logger.info("No PDFs found in %s", INPUT_DIR)
        return 0

    if not validate_environment(pdfs, template_profile):
        return 1

    results = [process_pdf(pdf_path, template_profile) for pdf_path in pdfs]
    processed_count = sum(result.success for result in results)
    failed_count = len(results) - processed_count

    logger.info(
        "Batch complete: %s processed, %s failed",
        processed_count,
        failed_count,
    )

    return 1 if failed_count else 0


if __name__ == "__main__":
    sys.exit(main())
