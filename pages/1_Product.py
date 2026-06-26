from __future__ import annotations

import json
import os
import re
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import streamlit as st

from config import TEMPLATE_DIR
from schema import (
    ASSET_CLASSES,
    AUTOCALL_FREQUENCIES,
    BARRIER_TYPES,
    COUPON_FREQUENCIES,
    COUPON_TYPES,
    DOCUMENT_TYPES,
    EVENT_STATUSES,
    LIFECYCLE_EVENT_TYPES,
    PRODUCT_FAMILIES,
    REVIEW_STATUSES,
    create_empty_product,
    finalize_compact_product,
    get_path,
    parse_date_value,
)
from services.processor import (
    build_product_record_from_draft,
    export_product_excel,
    parse_pdf_to_draft,
)
from services.file_opener import FileOpenError, open_local_file
from services.storage import (
    create_product_workspace,
    load_product_record,
    save_extracted_text,
    save_generated_excel,
    save_product_record,
    save_source_pdf_from_bytes,
)
from template_profiles import (
    DEFAULT_TEMPLATE_NAME,
    TemplateProfile,
    TemplateProfileError,
    discover_template_profiles,
    resolve_template_profile,
)
from fallback_copilot import SELENIUM_COPILOT_URL


def render() -> None:
    st.title("Product")
    st.caption("Upload one PDF, parse it, review the compact schema, and generate Excel.")

    template_identifier, template_profile = template_selector()
    use_copilot, fallback_settings = fallback_selector()
    uploaded_file = st.file_uploader("PDF termsheet", type=["pdf"])

    if st.button("Parse PDF", type="primary"):
        parse_uploaded_pdf(uploaded_file, template_profile, use_copilot, fallback_settings)

    draft = st.session_state.get("active_draft")
    if not draft:
        return

    show_draft_summary(draft)
    render_export_controls(template_identifier)
    render_review_form(draft)
    render_debug_expanders()


def template_selector() -> tuple[str, TemplateProfile | None]:
    profiles = discover_template_profiles()
    options = build_template_options(profiles)
    selected = st.selectbox("Template", options=options, index=0)

    try:
        profile = resolve_template_profile(selected)
    except TemplateProfileError as exc:
        st.error(str(exc))
        return selected, None

    st.caption(f"Selected template: {profile.template_path}")
    if profile.template_path.suffix.lower() == ".xlsm":
        st.caption(
            "Macro-enabled output will be saved as .xlsm with the VBA project preserved. "
            "Excel may still block unsigned or downloaded macros until the file/location is trusted."
        )
    return selected, profile


def build_template_options(profiles: list[TemplateProfile]) -> list[str]:
    options = [DEFAULT_TEMPLATE_NAME]
    for profile in profiles:
        identifier = template_option_identifier(profile)
        if identifier not in options:
            options.append(identifier)
    return options


def template_option_identifier(profile: TemplateProfile) -> str:
    try:
        return profile.template_path.relative_to(TEMPLATE_DIR).as_posix()
    except ValueError:
        return str(profile.template_path)


def fallback_selector() -> tuple[bool, dict[str, Any]]:
    use_copilot = st.toggle("Use Microsoft 365 Copilot via Selenium", value=False)
    settings: dict[str, Any] = {}
    if use_copilot:
        with st.expander("Selenium Copilot settings", expanded=True):
            st.caption(
                "Requires Chrome, Selenium Manager/ChromeDriver, and a Microsoft 365 chat session "
                "that can answer prompts."
            )
            settings["copilot_url"] = st.text_input(
                "Copilot URL",
                value=os.getenv("SELENIUM_COPILOT_URL", SELENIUM_COPILOT_URL),
            )
            settings["chromedriver_path"] = st.text_input(
                "ChromeDriver path",
                value=os.getenv(
                    "SELENIUM_CHROMEDRIVER_PATH",
                    "chromedriver-win64/chromedriver.exe",
                ),
            )
            col1, col2 = st.columns(2)
            settings["initial_wait_seconds"] = col1.number_input(
                "Initial wait seconds",
                min_value=0,
                max_value=300,
                value=int(float(os.getenv("SELENIUM_COPILOT_INITIAL_WAIT_SECONDS", "10"))),
            )
            settings["response_wait_seconds"] = col2.number_input(
                "Response wait seconds",
                min_value=1,
                max_value=600,
                value=int(float(os.getenv("SELENIUM_COPILOT_RESPONSE_WAIT_SECONDS", "10"))),
            )

    return use_copilot, settings


def parse_uploaded_pdf(
    uploaded_file: Any,
    template_profile: TemplateProfile | None,
    use_copilot: bool,
    fallback_settings: dict[str, Any],
) -> None:
    if uploaded_file is None:
        st.warning("Upload a PDF before parsing.")
        return

    if template_profile is None:
        st.warning("Select a valid template before parsing.")
        return

    uploaded_bytes = uploaded_file.getvalue()
    source_name = Path(uploaded_file.name).name
    apply_fallback_settings(use_copilot, fallback_settings)

    try:
        with TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / source_name
            pdf_path.write_bytes(uploaded_bytes)
            draft = parse_pdf_to_draft(
                pdf_path,
                template_profile=template_profile,
                use_llm=use_copilot,
            )
    except Exception as exc:
        st.error(f"Could not parse PDF: {exc}")
        return

    st.session_state.active_draft = draft
    st.session_state.active_pdf_bytes = uploaded_bytes
    st.session_state.active_pdf_name = source_name
    st.session_state.saved_product_id = None
    st.session_state.active_product_record = None
    st.session_state.generated_excel_path = None
    st.success("PDF parsed. Review the sections below.")


def apply_fallback_settings(use_copilot: bool, settings: dict[str, Any]) -> None:
    if not use_copilot:
        return

    set_env_if_value("SELENIUM_COPILOT_URL", settings.get("copilot_url"))
    set_env_if_value("SELENIUM_CHROMEDRIVER_PATH", settings.get("chromedriver_path"))
    set_env_if_value(
        "SELENIUM_COPILOT_INITIAL_WAIT_SECONDS",
        settings.get("initial_wait_seconds"),
    )
    set_env_if_value(
        "SELENIUM_COPILOT_RESPONSE_WAIT_SECONDS",
        settings.get("response_wait_seconds"),
    )


def set_env_if_value(name: str, value: Any) -> None:
    text = "" if value is None else str(value).strip()
    if text:
        os.environ[name] = text
    else:
        os.environ.pop(name, None)


def show_draft_summary(draft: dict[str, Any]) -> None:
    fields = compact_fields_from_draft(draft)
    missing_required = fields["review"].get("missing_required") or []
    if missing_required:
        st.warning("Missing required fields: " + ", ".join(missing_required))
    else:
        st.success("All required fields are present for approval.")

    if draft.get("fallback_error"):
        st.warning(f"Copilot fallback issue: {draft['fallback_error']}")

    st.caption(
        f"Source: {draft.get('source_pdf')} | "
        f"Parser: {draft.get('parser_version')} | "
        f"Copilot fallback used: {draft.get('fallback_used')}"
    )


def render_review_form(draft: dict[str, Any]) -> None:
    fields = compact_fields_from_draft(draft)

    with st.form("compact_product_form"):
        st.subheader("Actions")
        save_col, reviewed_col, approve_col, reject_col = st.columns(4)
        save_clicked = save_col.form_submit_button("Save", type="primary")
        reviewed_clicked = reviewed_col.form_submit_button("Mark reviewed")
        approve_clicked = approve_col.form_submit_button("Approve")
        reject_clicked = reject_col.form_submit_button("Reject")
        st.divider()

        edited_fields = render_compact_schema_sections(fields)

    action_status = None
    if reviewed_clicked:
        action_status = "reviewed"
    elif approve_clicked:
        action_status = "approved"
    elif reject_clicked:
        action_status = "rejected"

    if save_clicked or action_status:
        if action_status:
            edited_fields["review"]["status"] = action_status
        save_active_product(draft, edited_fields)


def render_compact_schema_sections(fields: dict[str, Any]) -> dict[str, Any]:
    edited = create_empty_product(fields["document"].get("file_name"))
    edited["schema_version"] = fields.get("schema_version", "1.0")

    st.subheader("A. Identity")
    col1, col2, col3 = st.columns(3)
    edited["document"]["document_type"] = col1.selectbox(
        "Document type",
        DOCUMENT_TYPES,
        index=enum_index(DOCUMENT_TYPES, get_path(fields, "document.document_type")),
    )
    edited["document"]["language"] = col2.text_input(
        "Language", value=text_value(get_path(fields, "document.language"))
    )
    edited["identity"]["product_name"] = col3.text_input(
        "Product name", value=text_value(get_path(fields, "identity.product_name"))
    )

    col1, col2, col3, col4 = st.columns(4)
    edited["identity"]["isin"] = col1.text_input(
        "ISIN", value=text_value(get_path(fields, "identity.isin"))
    )
    edited["identity"]["valor"] = col2.text_input(
        "Valor", value=text_value(get_path(fields, "identity.valor"))
    )
    edited["identity"]["wkn"] = col3.text_input(
        "WKN", value=text_value(get_path(fields, "identity.wkn"))
    )
    edited["identity"]["internal_product_id"] = col4.text_input(
        "Internal product ID",
        value=text_value(get_path(fields, "identity.internal_product_id")),
    )

    col1, col2, col3 = st.columns(3)
    edited["parties"]["issuer"] = col1.text_input(
        "Issuer", value=text_value(get_path(fields, "parties.issuer"))
    )
    edited["parties"]["guarantor"] = col2.text_input(
        "Guarantor", value=text_value(get_path(fields, "parties.guarantor"))
    )
    edited["parties"]["calculation_agent"] = col3.text_input(
        "Calculation agent",
        value=text_value(get_path(fields, "parties.calculation_agent")),
    )

    st.subheader("B. Product setup")
    col1, col2 = st.columns(2)
    edited["classification"]["product_family"] = col1.selectbox(
        "Product family",
        PRODUCT_FAMILIES,
        index=enum_index(PRODUCT_FAMILIES, get_path(fields, "classification.product_family")),
    )
    edited["classification"]["asset_class"] = col2.selectbox(
        "Asset class",
        ASSET_CLASSES,
        index=enum_index(ASSET_CLASSES, get_path(fields, "classification.asset_class")),
    )
    col1, col2, col3 = st.columns(3)
    edited["economics"]["issue_currency"] = col1.text_input(
        "Issue currency",
        value=text_value(get_path(fields, "economics.issue_currency")),
    )
    edited["economics"]["denomination"] = col2.number_input(
        "Denomination",
        value=number_value(get_path(fields, "economics.denomination")),
        min_value=0.0,
    )
    edited["economics"]["nominal_amount"] = col3.number_input(
        "Nominal amount",
        value=number_value(get_path(fields, "economics.nominal_amount")),
        min_value=0.0,
    )
    col1, col2 = st.columns(2)
    edited["economics"]["issue_price_percent"] = col1.number_input(
        "Issue price %",
        value=number_value(get_path(fields, "economics.issue_price_percent")),
        min_value=0.0,
    )
    edited["economics"]["minimum_investment"] = col2.number_input(
        "Minimum investment",
        value=number_value(get_path(fields, "economics.minimum_investment")),
        min_value=0.0,
    )

    st.subheader("C. Dates")
    col1, col2, col3, col4 = st.columns(4)
    edited["dates"]["trade_date"] = date_input_value(
        col1, "Trade date", get_path(fields, "dates.trade_date")
    )
    edited["dates"]["initial_fixing_date"] = date_input_value(
        col2, "Initial fixing date", get_path(fields, "dates.initial_fixing_date")
    )
    edited["dates"]["issue_date"] = date_input_value(
        col3, "Issue date", get_path(fields, "dates.issue_date")
    )
    edited["dates"]["payment_date"] = date_input_value(
        col4, "Payment date", get_path(fields, "dates.payment_date")
    )
    col1, col2, col3 = st.columns(3)
    edited["dates"]["final_valuation_date"] = date_input_value(
        col1, "Final valuation date", get_path(fields, "dates.final_valuation_date")
    )
    edited["dates"]["maturity_date"] = date_input_value(
        col2, "Maturity date", get_path(fields, "dates.maturity_date")
    )
    edited["dates"]["redemption_date"] = date_input_value(
        col3, "Redemption date", get_path(fields, "dates.redemption_date")
    )

    st.subheader("D. Underlyings")
    edited["underlyings"] = st.data_editor(
        fields.get("underlyings") or [empty_underlying()],
        num_rows="dynamic",
        use_container_width=True,
        key="underlyings_editor",
    )

    st.subheader("E. Payoff")
    col1, col2, col3, col4 = st.columns(4)
    edited["coupon"]["coupon_type"] = col1.selectbox(
        "Coupon type",
        COUPON_TYPES,
        index=enum_index(COUPON_TYPES, get_path(fields, "coupon.coupon_type")),
    )
    edited["coupon"]["coupon_rate_percent_pa"] = col2.number_input(
        "Coupon rate % p.a.",
        value=number_value(get_path(fields, "coupon.coupon_rate_percent_pa")),
        min_value=0.0,
    )
    edited["coupon"]["coupon_frequency"] = col3.selectbox(
        "Coupon frequency",
        COUPON_FREQUENCIES,
        index=enum_index(COUPON_FREQUENCIES, get_path(fields, "coupon.coupon_frequency")),
    )
    edited["coupon"]["coupon_trigger_percent"] = col4.number_input(
        "Coupon trigger %",
        value=number_value(get_path(fields, "coupon.coupon_trigger_percent")),
        min_value=0.0,
    )

    col1, col2, col3, col4 = st.columns(4)
    edited["coupon"]["memory_feature"] = col1.checkbox(
        "Memory feature", value=bool(get_path(fields, "coupon.memory_feature"))
    )
    edited["classification"]["has_barrier"] = col2.checkbox(
        "Has barrier", value=bool(get_path(fields, "classification.has_barrier"))
    )
    edited["classification"]["has_memory_coupon"] = col3.checkbox(
        "Has memory coupon",
        value=bool(get_path(fields, "classification.has_memory_coupon")),
    )
    edited["classification"]["has_physical_delivery"] = col4.checkbox(
        "Has physical delivery",
        value=bool(get_path(fields, "classification.has_physical_delivery")),
    )

    col1, col2, col3, col4 = st.columns(4)
    edited["barrier"]["barrier_type"] = col1.selectbox(
        "Barrier type",
        BARRIER_TYPES,
        index=enum_index(BARRIER_TYPES, get_path(fields, "barrier.barrier_type")),
    )
    edited["barrier"]["level_percent"] = col2.number_input(
        "Barrier level %",
        value=number_value(get_path(fields, "barrier.level_percent")),
        min_value=0.0,
    )
    edited["barrier"]["observation_start_date"] = date_input_value(
        col3,
        "Barrier observation start",
        get_path(fields, "barrier.observation_start_date"),
    )
    edited["barrier"]["observation_end_date"] = date_input_value(
        col4,
        "Barrier observation end",
        get_path(fields, "barrier.observation_end_date"),
    )

    col1, col2, col3, col4 = st.columns(4)
    edited["autocall"]["is_autocallable"] = col1.checkbox(
        "Is autocallable", value=bool(get_path(fields, "autocall.is_autocallable"))
    )
    edited["classification"]["is_autocallable"] = edited["autocall"]["is_autocallable"]
    edited["autocall"]["first_autocall_date"] = date_input_value(
        col2, "First autocall date", get_path(fields, "autocall.first_autocall_date")
    )
    edited["autocall"]["autocall_frequency"] = col3.selectbox(
        "Autocall frequency",
        AUTOCALL_FREQUENCIES,
        index=enum_index(AUTOCALL_FREQUENCIES, get_path(fields, "autocall.autocall_frequency")),
    )
    edited["autocall"]["autocall_trigger_percent"] = col4.number_input(
        "Autocall trigger %",
        value=number_value(get_path(fields, "autocall.autocall_trigger_percent")),
        min_value=0.0,
    )

    st.subheader("F. Lifecycle")
    edited["lifecycle_events"] = st.data_editor(
        fields.get("lifecycle_events") or [],
        num_rows="dynamic",
        use_container_width=True,
        key="lifecycle_events_editor",
        column_config={
            "event_type": st.column_config.SelectboxColumn(
                "event_type", options=LIFECYCLE_EVENT_TYPES
            ),
            "status": st.column_config.SelectboxColumn("status", options=EVENT_STATUSES),
        },
    )

    st.subheader("G. Review")
    review = fields.get("review") or {}
    edited["review"]["status"] = st.selectbox(
        "Review status",
        REVIEW_STATUSES,
        index=enum_index(REVIEW_STATUSES, review.get("status")),
    )
    missing_text = st.text_area(
        "Missing required",
        value="\n".join(review.get("missing_required") or []),
        height=90,
    )
    warnings_text = st.text_area(
        "Warnings",
        value="\n".join(review.get("warnings") or []),
        height=120,
    )
    edited["review"]["missing_required"] = split_lines(missing_text)
    edited["review"]["warnings"] = split_lines(warnings_text)

    return finalize_compact_product(edited)


def save_active_product(draft: dict[str, Any], fields: dict[str, Any]) -> None:
    uploaded_bytes = st.session_state.get("active_pdf_bytes")
    source_name = st.session_state.get("active_pdf_name") or draft.get("source_pdf")
    product_id = st.session_state.get("saved_product_id")

    try:
        if product_id:
            workspace_id = str(product_id)
        else:
            if not uploaded_bytes:
                st.error("Uploaded PDF bytes are not available. Parse the PDF again.")
                return
            workspace = create_product_workspace(source_name)
            workspace_id = workspace.product_id
            save_source_pdf_from_bytes(workspace_id, uploaded_bytes)
            save_extracted_text(workspace_id, str(draft.get("extracted_text") or ""))

        draft["fields"] = fields
        draft["missing_required"] = fields["review"]["missing_required"]
        draft["source_pdf"] = source_name
        record = build_product_record_from_draft(
            draft,
            product_id=workspace_id,
            status="stored",
        )
        save_product_record(workspace_id, record)
        record = load_product_record(workspace_id)
    except Exception as exc:
        st.error(f"Could not save product: {exc}")
        return

    st.session_state.saved_product_id = workspace_id
    st.session_state.active_product_record = record
    st.session_state.active_draft = draft
    st.success(f"Product saved: {workspace_id}")


def render_export_controls(template_identifier: str) -> None:
    product_id = st.session_state.get("saved_product_id")
    record = st.session_state.get("active_product_record")
    if not product_id or not record:
        st.info("Save the product before generating Excel.")
        return

    if st.button("Generate Excel"):
        try:
            template_profile = resolve_template_profile(template_identifier)
            generated_path = generate_excel_for_saved_product(record, template_profile)
        except Exception as exc:
            st.error(f"Could not generate Excel: {exc}")
            return

        st.session_state.generated_excel_path = generated_path
        st.session_state.active_product_record = load_product_record(product_id)
        st.success(f"Excel generated: {generated_path.name}")

    generated_path = st.session_state.get("generated_excel_path")
    if generated_path:
        path = Path(generated_path)
        if path.exists():
            download_col, open_col = st.columns(2)
            download_col.download_button(
                "Download generated Excel",
                data=path.read_bytes(),
                file_name=path.name,
                mime=excel_mime_type(path),
            )
            if open_col.button("Open generated Excel"):
                open_generated_excel(path)


def open_generated_excel(path: Path) -> None:
    try:
        open_local_file(path)
    except (OSError, FileOpenError) as exc:
        st.error(f"Could not open Excel file: {exc}")
        return

    st.success(f"Opened {path.name}")


def generate_excel_for_saved_product(
    product_record: dict[str, Any],
    template_profile: TemplateProfile,
) -> Path:
    product_id = str(product_record["product_id"])
    output_name = excel_output_name(product_record, template_profile)

    with TemporaryDirectory() as tmp:
        temp_output = Path(tmp) / output_name
        written_path = export_product_excel(product_record, template_profile, temp_output)
        return save_generated_excel(product_id, written_path, filename=written_path.name)


def compact_fields_from_draft(draft: dict[str, Any]) -> dict[str, Any]:
    fields = draft.get("fields")
    if not isinstance(fields, dict):
        fields = create_empty_product(draft.get("source_pdf"))
    return finalize_compact_product(fields)


def empty_underlying() -> dict[str, Any]:
    return {
        "name": None,
        "ticker": None,
        "isin": None,
        "currency": None,
        "initial_fixing": None,
        "strike_price": None,
        "weight_percent": None,
    }


def text_value(value: Any) -> str:
    return "" if value is None else str(value)


def number_value(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def date_input_value(container: Any, label: str, value: Any) -> str | None:
    if isinstance(value, str) and value.lower() == "open end":
        return container.text_input(label, value=value)

    parsed = parse_date_value(value)
    selected = container.date_input(label, value=parsed, format="YYYY-MM-DD")
    if selected is None:
        return None
    if isinstance(selected, date):
        return selected.isoformat()
    return str(selected)


def enum_index(options: tuple[str, ...], value: Any) -> int:
    if value in options:
        return options.index(value)
    return options.index("unknown") if "unknown" in options else 0


def split_lines(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip()]


def show_raw_json(value: dict[str, Any]) -> None:
    st.code(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False), language="json")


def render_debug_expanders() -> None:
    draft = st.session_state.get("active_draft") or {}
    with st.expander("Extracted text"):
        st.text_area(
            "Extracted text",
            value=str(draft.get("extracted_text") or ""),
            height=300,
            disabled=True,
            label_visibility="collapsed",
        )

    with st.expander("Raw draft JSON"):
        show_raw_json(draft)

    record = st.session_state.get("active_product_record")
    if record:
        with st.expander("Saved product JSON"):
            show_raw_json(record)


def excel_output_name(product_record: dict[str, Any], template_profile: TemplateProfile) -> str:
    fields = product_record.get("fields") if isinstance(product_record.get("fields"), dict) else {}
    source_name = (
        get_path(fields, "identity.isin")
        or product_record.get("source_pdf")
        or "termsheet"
    )
    template_name = safe_filename(template_profile.name)
    suffix = template_profile.template_path.suffix.lower() or ".xlsx"
    return f"{safe_filename(Path(str(source_name)).stem)}_{template_name}{suffix}"


def safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
    return cleaned or "termsheet"


def excel_mime_type(path: Path) -> str:
    if path.suffix.lower() == ".xlsm":
        return "application/vnd.ms-excel.sheet.macroEnabled.12"
    return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


render()
