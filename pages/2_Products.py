from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import streamlit as st

from schema import get_path
from services.storage import get_product_paths, list_products, load_product_record


def render() -> None:
    st.title("Products")
    st.caption("Browse products saved through the Streamlit workflow.")

    products = list_products()
    if not products:
        st.info("No saved products found.")
        return

    search = st.text_input("Search by ISIN, issuer, product name, or source PDF")
    rows = filter_rows(build_rows(products), search)

    if not rows:
        st.warning("No products match the current search.")
        return

    st.dataframe(
        rows,
        use_container_width=True,
        hide_index=True,
        column_order=["created_at", "status", "isin", "issuer", "product_name", "source_pdf"],
    )

    selected_product_id = st.selectbox(
        "Select product",
        options=[row["product_id"] for row in rows],
        format_func=lambda product_id: product_label(product_id, rows),
    )

    record = load_product_record(selected_product_id)
    show_product_details(record)
    show_downloads(record)


def build_rows(products: list[dict[str, Any]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for product in products:
        fields = product.get("fields") if isinstance(product.get("fields"), dict) else {}
        source_pdf = str(product.get("source_pdf") or "")
        rows.append(
            {
                "product_id": str(product.get("product_id") or ""),
                "created_at": str(product.get("created_at") or ""),
                "status": str(product.get("status") or ""),
                "isin": str(get_path(fields, "identity.isin") or ""),
                "issuer": str(get_path(fields, "parties.issuer") or ""),
                "product_name": str(
                    get_path(fields, "identity.product_name")
                    or get_path(fields, "classification.product_family")
                    or source_pdf
                ),
                "source_pdf": source_pdf,
            }
        )
    return rows


def filter_rows(rows: list[dict[str, str]], search: str) -> list[dict[str, str]]:
    needle = search.strip().lower()
    if not needle:
        return rows

    searchable_columns = ("isin", "issuer", "product_name", "source_pdf", "product_id")
    return [
        row
        for row in rows
        if any(needle in row[column].lower() for column in searchable_columns)
    ]


def product_label(product_id: str, rows: list[dict[str, str]]) -> str:
    for row in rows:
        if row["product_id"] == product_id:
            label_parts = [
                row["isin"] or product_id,
                row["issuer"],
                row["product_name"],
            ]
            return " | ".join(part for part in label_parts if part)
    return product_id


def show_product_details(record: dict[str, Any]) -> None:
    fields = record.get("fields") if isinstance(record.get("fields"), dict) else {}

    st.subheader("Details")
    left, right = st.columns(2)
    with left:
        st.text_input("Product ID", value=str(record.get("product_id") or ""), disabled=True)
        st.text_input("Status", value=str(record.get("status") or ""), disabled=True)
        st.text_input("Source PDF", value=str(record.get("source_pdf") or ""), disabled=True)
    with right:
        st.text_input("ISIN", value=str(get_path(fields, "identity.isin") or ""), disabled=True)
        st.text_input("Issuer", value=str(get_path(fields, "parties.issuer") or ""), disabled=True)
        st.text_input(
            "Product",
            value=str(
                get_path(fields, "identity.product_name")
                or get_path(fields, "classification.product_family")
                or ""
            ),
            disabled=True,
        )

    with st.expander("Product JSON"):
        st.code(json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False), language="json")


def show_downloads(record: dict[str, Any]) -> None:
    product_id = str(record.get("product_id") or "")
    if not product_id:
        return

    paths = get_product_paths(product_id)
    st.subheader("Downloads")

    if paths.source_pdf.exists():
        st.download_button(
            "Download source PDF",
            data=paths.source_pdf.read_bytes(),
            file_name=str(record.get("source_pdf") or paths.source_pdf.name),
            mime="application/pdf",
        )

    if paths.product_json.exists():
        st.download_button(
            "Download product.json",
            data=paths.product_json.read_bytes(),
            file_name="product.json",
            mime="application/json",
        )

    generated_files = generated_file_paths(record)
    if not generated_files:
        st.caption("No generated Excel files saved for this product.")
        return

    for path in generated_files:
        if not path.exists():
            continue
        st.download_button(
            f"Download {path.name}",
            data=path.read_bytes(),
            file_name=path.name,
            mime=excel_mime_type(path),
        )


def generated_file_paths(record: dict[str, Any]) -> list[Path]:
    product_id = str(record.get("product_id") or "")
    paths = get_product_paths(product_id)
    generated_files = record.get("generated_files")

    if isinstance(generated_files, list) and generated_files:
        return [paths.root / item for item in generated_files if isinstance(item, str)]

    if not paths.generated_dir.exists():
        return []

    return sorted(path for path in paths.generated_dir.iterdir() if path.is_file())


def excel_mime_type(path: Path) -> str:
    if path.suffix.lower() == ".xlsm":
        return "application/vnd.ms-excel.sheet.macroEnabled.12"
    return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


render()
