from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

from schema import flatten_compact_product, is_compact_product
from template_mapping import TEMPLATE_CELL_MAPPING

MAPPING_SHEET_NAME = "Field Mapping"
SUPPORTED_EXCEL_TEMPLATE_SUFFIXES = {".xlsx", ".xlsm"}


class ExcelTemplateError(RuntimeError):
    pass


def write_product_excel(product_data: dict[str, Any], template_path: Path, output_path: Path) -> Path:
    if not template_path.exists():
        raise ExcelTemplateError(f"Template not found: {template_path}")

    if template_path.suffix.lower() not in SUPPORTED_EXCEL_TEMPLATE_SUFFIXES:
        raise ExcelTemplateError(f"Unsupported Excel template type: {template_path.suffix}")

    try:
        import xlwings as xw
    except ImportError as exc:
        raise ExcelTemplateError(
            "xlwings is not installed. Run: pip install -r requirements.txt"
        ) from exc

    output_path = output_path.with_suffix(template_path.suffix.lower())
    fields = resolve_product_fields(product_data)
    if not isinstance(fields, dict):
        raise ExcelTemplateError("product_data must contain a 'fields' dictionary")

    if template_path.resolve() == output_path.resolve():
        raise ExcelTemplateError("Output path must be different from the template path")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()
    shutil.copyfile(template_path, output_path)

    app = None
    book = None
    try:
        app = xw.App(visible=False, add_book=False)
        configure_excel_app(app)
        book = app.books.open(str(output_path), update_links=False, read_only=False)

        cell_mapping = load_template_cell_mapping(book)
        apply_cell_mapping(book, cell_mapping, fields)
        remove_mapping_sheet(book)

        book.save()
        return output_path
    except Exception as exc:
        if isinstance(exc, ExcelTemplateError):
            raise
        raise ExcelTemplateError(f"Could not write Excel output with xlwings: {exc}") from exc
    finally:
        close_xlwings_book(book)
        quit_xlwings_app(app)


def configure_excel_app(app: Any) -> None:
    set_xlwings_property(app, "display_alerts", False)
    set_xlwings_property(app, "screen_updating", False)
    set_xlwings_property(app, "enable_events", False)


def set_xlwings_property(obj: Any, name: str, value: Any) -> None:
    try:
        setattr(obj, name, value)
    except Exception:
        return


def close_xlwings_book(book: Any) -> None:
    if book is None:
        return
    try:
        book.close()
    except Exception:
        return


def quit_xlwings_app(app: Any) -> None:
    if app is None:
        return
    try:
        app.quit()
    except Exception:
        return


def resolve_product_fields(product_data: dict[str, Any]) -> dict[str, Any]:
    fields = product_data.get("fields", {})
    if isinstance(fields, dict) and is_compact_product(fields):
        return flatten_compact_product(fields)
    return fields


def load_template_cell_mapping(book: Any) -> dict[str, str | dict[str, str | None]]:
    mapping_sheet = get_sheet(book, MAPPING_SHEET_NAME)
    if mapping_sheet is None:
        return TEMPLATE_CELL_MAPPING

    rows = normalize_used_range_values(mapping_sheet.used_range.value)
    if not rows:
        raise ExcelTemplateError(f"'{MAPPING_SHEET_NAME}' sheet does not define any mappings")

    headers = get_mapping_headers(rows[0])
    field_col = headers.get("field_name")
    cell_col = headers.get("cell")
    sheet_col = headers.get("sheet")

    if field_col is None or cell_col is None:
        raise ExcelTemplateError(
            f"'{MAPPING_SHEET_NAME}' sheet must have 'field_name' and 'cell' headers"
        )

    mapping: dict[str, dict[str, str | None]] = {}
    for row_number, row in enumerate(rows[1:], start=2):
        field_name = normalize_cell_text(row_value(row, field_col))
        if not field_name:
            continue

        cell = normalize_cell_text(row_value(row, cell_col))
        if not cell:
            raise ExcelTemplateError(
                f"'{MAPPING_SHEET_NAME}' row {row_number} has field_name "
                f"'{field_name}' but no target cell"
            )

        sheet_name = normalize_cell_text(row_value(row, sheet_col)) if sheet_col is not None else ""
        mapping[field_name] = {"sheet": sheet_name or None, "cell": cell}

    if not mapping:
        raise ExcelTemplateError(f"'{MAPPING_SHEET_NAME}' sheet does not define any mappings")

    return mapping


def normalize_used_range_values(value: Any) -> list[list[Any]]:
    if value is None:
        return []

    if not isinstance(value, list):
        return [[value]]

    if not value:
        return []

    if any(isinstance(item, list) for item in value):
        return [item if isinstance(item, list) else [item] for item in value]

    return [value]


def get_mapping_headers(header_row: list[Any]) -> dict[str, int]:
    headers: dict[str, int] = {}
    for index, value in enumerate(header_row):
        header = normalize_header(value)
        if header:
            headers[header] = index
    return headers


def row_value(row: list[Any], index: int | None) -> Any:
    if index is None or index >= len(row):
        return None
    return row[index]


def normalize_header(value: Any) -> str:
    return normalize_cell_text(value).lower().replace(" ", "_")


def normalize_cell_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def apply_cell_mapping(
    book: Any,
    cell_mapping: dict[str, str | dict[str, str | None]],
    fields: dict[str, Any],
) -> None:
    for field_name, target in cell_mapping.items():
        value = fields.get(field_name)
        if value in (None, ""):
            continue

        sheet, cell = resolve_target(book, target)
        sheet.range(cell).value = value


def resolve_target(book: Any, target: str | dict[str, str | None]) -> tuple[Any, str]:
    if isinstance(target, str):
        return active_output_sheet(book), normalize_cell_reference(target)

    sheet_name = target.get("sheet")
    cell = target.get("cell")
    if not cell:
        raise ExcelTemplateError(f"Invalid template mapping target: {target}")

    if sheet_name:
        sheet = get_sheet(book, sheet_name)
        if sheet is None:
            raise ExcelTemplateError(f"Template sheet not found: {sheet_name}")
        return sheet, normalize_cell_reference(cell)

    return active_output_sheet(book), normalize_cell_reference(cell)


def active_output_sheet(book: Any) -> Any:
    try:
        active_sheet = book.sheets.active
        if active_sheet.name != MAPPING_SHEET_NAME:
            return active_sheet
    except Exception:
        pass

    for sheet in iter_sheets(book):
        if sheet.name != MAPPING_SHEET_NAME:
            return sheet

    raise ExcelTemplateError(
        f"Template must contain at least one output sheet besides '{MAPPING_SHEET_NAME}'"
    )


def remove_mapping_sheet(book: Any) -> None:
    mapping_sheet = get_sheet(book, MAPPING_SHEET_NAME)
    if mapping_sheet is None:
        return

    if len(list(iter_sheets(book))) <= 1:
        raise ExcelTemplateError(
            f"Template must contain at least one output sheet besides '{MAPPING_SHEET_NAME}'"
        )

    mapping_sheet.delete()


def get_sheet(book: Any, sheet_name: str) -> Any | None:
    try:
        return book.sheets[sheet_name]
    except Exception:
        return None


def iter_sheets(book: Any) -> list[Any]:
    return [sheet for sheet in book.sheets]


def normalize_cell_reference(cell: str) -> str:
    normalized = str(cell).replace("$", "").strip().upper()
    if not re.fullmatch(r"[A-Z]{1,3}[1-9][0-9]*", normalized):
        raise ExcelTemplateError(f"Invalid target cell reference: {cell}")
    return normalized
