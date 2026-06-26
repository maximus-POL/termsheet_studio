from __future__ import annotations

import json
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from config import PRODUCTS_DIR
from schema import finalize_compact_product, is_compact_product, migrate_legacy_record

ProductStatus = Literal["draft", "stored", "failed"]

VALID_PRODUCT_STATUSES: set[str] = {"draft", "stored", "failed"}
SOURCE_PDF_FILENAME = "source.pdf"
EXTRACTED_TEXT_FILENAME = "extracted_text.txt"
PRODUCT_RECORD_FILENAME = "product.json"
GENERATED_DIR_NAME = "generated"
ERRORS_DIR_NAME = "errors"


class ProductStorageError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProductPaths:
    product_id: str
    root: Path
    source_pdf: Path
    extracted_text: Path
    product_json: Path
    generated_dir: Path
    errors_dir: Path


def create_product_workspace(
    source_filename: str | None = None,
    products_dir: Path = PRODUCTS_DIR,
) -> ProductPaths:
    products_dir.mkdir(parents=True, exist_ok=True)

    for _ in range(100):
        product_id = generate_product_id(source_filename)
        paths = get_product_paths(product_id, products_dir)
        if not paths.root.exists():
            ensure_product_directories(paths)
            return paths

    raise ProductStorageError("Could not create a unique product workspace")


def save_source_pdf_from_path(
    product_id: str,
    source_path: Path,
    products_dir: Path = PRODUCTS_DIR,
) -> Path:
    if not source_path.exists():
        raise ProductStorageError(f"Source PDF does not exist: {source_path}")

    paths = get_product_paths(product_id, products_dir)
    ensure_product_directories(paths)
    shutil.copy2(source_path, paths.source_pdf)
    return paths.source_pdf


def save_source_pdf_from_bytes(
    product_id: str,
    content: bytes,
    products_dir: Path = PRODUCTS_DIR,
) -> Path:
    paths = get_product_paths(product_id, products_dir)
    ensure_product_directories(paths)
    paths.source_pdf.write_bytes(content)
    return paths.source_pdf


def save_extracted_text(
    product_id: str,
    text: str,
    products_dir: Path = PRODUCTS_DIR,
) -> Path:
    paths = get_product_paths(product_id, products_dir)
    ensure_product_directories(paths)
    paths.extracted_text.write_text(text, encoding="utf-8")
    return paths.extracted_text


def save_product_record(
    product_id: str,
    record: dict[str, Any],
    products_dir: Path = PRODUCTS_DIR,
) -> Path:
    paths = get_product_paths(product_id, products_dir)
    ensure_product_directories(paths)

    normalized = normalize_product_record(product_id, record, paths)
    paths.product_json.write_text(
        json.dumps(normalized, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return paths.product_json


def load_product_record(
    product_id: str,
    products_dir: Path = PRODUCTS_DIR,
) -> dict[str, Any]:
    paths = get_product_paths(product_id, products_dir)
    if not paths.product_json.exists():
        raise ProductStorageError(f"Product record does not exist: {paths.product_json}")

    try:
        payload = json.loads(paths.product_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProductStorageError(f"Product record is not valid JSON: {paths.product_json}") from exc

    if not isinstance(payload, dict):
        raise ProductStorageError(f"Product record must be a JSON object: {paths.product_json}")

    payload.setdefault("product_id", product_id)
    return migrate_legacy_record(payload)


def list_products(
    products_dir: Path = PRODUCTS_DIR,
) -> list[dict[str, Any]]:
    if not products_dir.exists():
        return []

    products: list[dict[str, Any]] = []
    for product_dir in sorted(products_dir.iterdir()):
        if not product_dir.is_dir():
            continue

        record_path = product_dir / PRODUCT_RECORD_FILENAME
        if not record_path.exists():
            continue

        try:
            record = load_product_record(product_dir.name, products_dir)
        except ProductStorageError:
            continue

        products.append(record)

    return sorted(products, key=lambda item: str(item.get("updated_at") or ""), reverse=True)


def save_generated_excel(
    product_id: str,
    excel_path: Path,
    products_dir: Path = PRODUCTS_DIR,
    filename: str | None = None,
) -> Path:
    if not excel_path.exists():
        raise ProductStorageError(f"Generated Excel file does not exist: {excel_path}")

    paths = get_product_paths(product_id, products_dir)
    ensure_product_directories(paths)
    target_name = safe_filename(filename or excel_path.name)
    target_path = unique_path(paths.generated_dir / target_name)
    shutil.copy2(excel_path, target_path)
    register_generated_file(paths, target_path)
    return target_path


def save_error(
    product_id: str,
    error_text: str,
    products_dir: Path = PRODUCTS_DIR,
    filename: str | None = None,
) -> Path:
    paths = get_product_paths(product_id, products_dir)
    ensure_product_directories(paths)

    if filename:
        target_name = safe_filename(filename)
    else:
        target_name = f"{timestamp_for_filename()}_error.txt"

    error_path = unique_path(paths.errors_dir / target_name)
    error_path.write_text(error_text, encoding="utf-8")
    register_error_file(paths, error_path)
    return error_path


def get_product_paths(
    product_id: str,
    products_dir: Path = PRODUCTS_DIR,
) -> ProductPaths:
    validate_product_id(product_id)
    root = products_dir / product_id
    return ProductPaths(
        product_id=product_id,
        root=root,
        source_pdf=root / SOURCE_PDF_FILENAME,
        extracted_text=root / EXTRACTED_TEXT_FILENAME,
        product_json=root / PRODUCT_RECORD_FILENAME,
        generated_dir=root / GENERATED_DIR_NAME,
        errors_dir=root / ERRORS_DIR_NAME,
    )


def normalize_product_record(
    product_id: str,
    record: dict[str, Any],
    paths: ProductPaths,
) -> dict[str, Any]:
    existing_record = read_existing_record(paths)
    now = timestamp_iso()
    normalized = dict(record)

    normalized["product_id"] = product_id
    normalized["created_at"] = normalized.get("created_at") or existing_record.get("created_at") or now
    normalized["updated_at"] = now
    normalized["status"] = normalize_status(normalized.get("status", "draft"))
    normalized["source_pdf"] = normalized.get("source_pdf") or existing_record.get("source_pdf")
    fields = normalize_mapping(normalized.get("fields"))
    if is_compact_product(fields):
        normalized["fields"] = finalize_compact_product(fields)
    else:
        migrated = migrate_legacy_record({"product_id": product_id, "fields": fields})
        normalized["fields"] = migrated["fields"]
        if "raw_extraction" not in normalized:
            normalized["raw_extraction"] = migrated.get("raw_extraction")

    normalized["missing_required"] = normalize_string_list(
        normalized["fields"].get("review", {}).get("missing_required")
    )
    normalized["template"] = normalize_mapping(normalized.get("template"))
    normalized["generated_files"] = normalize_string_list(
        normalized.get("generated_files", existing_record.get("generated_files"))
    )

    return normalized


def register_generated_file(paths: ProductPaths, generated_path: Path) -> None:
    record = read_existing_record(paths)
    relative_path = generated_path.relative_to(paths.root).as_posix()
    generated_files = normalize_string_list(record.get("generated_files"))
    if relative_path not in generated_files:
        generated_files.append(relative_path)

    record["generated_files"] = generated_files
    if "status" not in record:
        record["status"] = "stored"
    save_product_record(paths.product_id, record, paths.root.parent)


def register_error_file(paths: ProductPaths, error_path: Path) -> None:
    record = read_existing_record(paths)
    relative_path = error_path.relative_to(paths.root).as_posix()
    error_files = normalize_string_list(record.get("error_files"))
    if relative_path not in error_files:
        error_files.append(relative_path)

    record["error_files"] = error_files
    record["status"] = "failed"
    save_product_record(paths.product_id, record, paths.root.parent)


def read_existing_record(paths: ProductPaths) -> dict[str, Any]:
    if not paths.product_json.exists():
        return {}

    try:
        payload = json.loads(paths.product_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}

    return payload if isinstance(payload, dict) else {}


def ensure_product_directories(paths: ProductPaths) -> None:
    paths.generated_dir.mkdir(parents=True, exist_ok=True)
    paths.errors_dir.mkdir(parents=True, exist_ok=True)


def generate_product_id(source_filename: str | None = None) -> str:
    timestamp = timestamp_for_filename()
    token = uuid.uuid4().hex[:8]
    source_stem = safe_stem(source_filename) if source_filename else "product"
    return f"{timestamp}_{token}_{source_stem}"


def timestamp_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def timestamp_for_filename() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")


def safe_stem(filename: str | None) -> str:
    if not filename:
        return "product"

    return safe_filename(Path(filename).stem)


def safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
    return cleaned or "file"


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path

    for index in range(1, 1000):
        candidate = path.with_name(f"{path.stem}_{index:03d}{path.suffix}")
        if not candidate.exists():
            return candidate

    raise ProductStorageError(f"Could not allocate unique file path for {path.name}")


def validate_product_id(product_id: str) -> None:
    if not product_id or safe_filename(product_id) != product_id:
        raise ProductStorageError(f"Invalid product_id: {product_id!r}")


def normalize_status(value: Any) -> ProductStatus:
    status = str(value or "draft").strip().lower()
    if status not in VALID_PRODUCT_STATUSES:
        raise ProductStorageError(
            f"Invalid product status: {value!r}. Expected one of: "
            + ", ".join(sorted(VALID_PRODUCT_STATUSES))
        )

    return status  # type: ignore[return-value]


def normalize_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []

    return [item for item in value if isinstance(item, str) and item]
