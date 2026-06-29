from __future__ import annotations

import json
import html
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
    COUPON_CLEAN_DIRTY_TYPES,
    COUPON_FREQUENCIES,
    COUPON_TYPES,
    CURRENCIES,
    DOCUMENT_TYPES,
    EVENT_STATUSES,
    ISSUER_OPTIONS,
    LIFECYCLE_EVENT_TYPES,
    NOTATION_TYPES,
    PRODUCT_FAMILIES,
    REVIEW_STATUSES,
    STRIKE_TYPES,
    UNDERLYING_ASSET_CLASSES,
    create_empty_product,
    finalize_compact_product,
    get_path,
    normalize_issuer,
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
FIELD_STATUSES = ("extracted", "needs_review", "missing", "approved", "unsupported")
FIELD_EDITOR_SPECS: tuple[tuple[str, str, str, str], ...] = (
    ("Document", "Document type", "document.document_type", "text"),
    ("Document", "Language", "document.language", "text"),
    ("Identity", "Product name", "identity.product_name", "text"),
    ("Identity", "ISIN", "identity.isin", "text"),
    ("Identity", "Valor", "identity.valor", "text"),
    ("Identity", "WKN", "identity.wkn", "text"),
    ("Identity", "Internal product ID", "identity.internal_product_id", "text"),
    ("Parties", "Issuer", "parties.issuer", "text"),
    ("Parties", "Guarantor", "parties.guarantor", "text"),
    ("Parties", "Calculation agent", "parties.calculation_agent", "text"),
    ("Classification", "Product family", "classification.product_family", "text"),
    ("Classification", "Asset class", "classification.asset_class", "text"),
    ("Classification", "Is reverse convertible", "classification.is_reverse_convertible", "boolean"),
    ("Classification", "Is autocallable", "autocall.is_autocallable", "boolean"),
    ("Classification", "Has barrier", "classification.has_barrier", "boolean"),
    ("Classification", "Has memory coupon", "classification.has_memory_coupon", "boolean"),
    ("Classification", "Has physical delivery", "classification.has_physical_delivery", "boolean"),
    ("Economics", "Currency", "economics.issue_currency", "text"),
    ("Economics", "Notation", "economics.notation", "text"),
    ("Economics", "Denomination", "economics.denomination", "number"),
    ("Economics", "No. certificates issued", "economics.number_of_certificates", "number"),
    ("Economics", "Nominal amount", "economics.nominal_amount", "number"),
    ("Economics", "Issue price %", "economics.issue_price_percent", "number"),
    ("Economics", "Minimum investment", "economics.minimum_investment", "number"),
    ("Economics", "Strike type", "economics.strike_type", "text"),
    ("Dates", "Trade date", "dates.trade_date", "text"),
    ("Dates", "Initial fixing date", "dates.initial_fixing_date", "text"),
    ("Dates", "Issue date", "dates.issue_date", "text"),
    ("Dates", "Payment date", "dates.payment_date", "text"),
    ("Dates", "Final valuation date", "dates.final_valuation_date", "text"),
    ("Dates", "Maturity date", "dates.maturity_date", "text"),
    ("Dates", "Redemption date", "dates.redemption_date", "text"),
    ("Coupon", "Coupon payoff type", "coupon.coupon_type", "text"),
    ("Coupon", "Coupon clean/dirty", "coupon.coupon_clean_dirty", "text"),
    ("Coupon", "Coupon rate % p.a.", "coupon.coupon_rate_percent_pa", "number"),
    ("Coupon", "Coupon frequency", "coupon.coupon_frequency", "text"),
    ("Coupon", "Coupon trigger %", "coupon.coupon_trigger_percent", "number"),
    ("Coupon", "Memory feature", "coupon.memory_feature", "boolean"),
    ("Barrier", "Barrier type", "barrier.barrier_type", "text"),
    ("Barrier", "Barrier level %", "barrier.level_percent", "number"),
    ("Barrier", "Barrier observation start", "barrier.observation_start_date", "text"),
    ("Barrier", "Barrier observation end", "barrier.observation_end_date", "text"),
    ("Autocall", "First autocall date", "autocall.first_autocall_date", "text"),
    ("Autocall", "Autocall frequency", "autocall.autocall_frequency", "text"),
    ("Autocall", "Autocall trigger %", "autocall.autocall_trigger_percent", "number"),
    ("Listing", "Listing exchange", "listing.exchange", "text"),
)
SUMMARY_FIELD_SPECS: tuple[tuple[str, str, str], ...] = (
    ("Product", "identity.product_name", "text"),
    ("ISIN", "identity.isin", "text"),
    ("Issuer", "parties.issuer", "text"),
    ("Currency", "economics.issue_currency", "text"),
    ("Notation", "economics.notation", "text"),
    ("No. certificates issued", "economics.number_of_certificates", "number"),
    ("Nominal amount", "economics.nominal_amount", "number"),
    ("Maturity", "dates.maturity_date", "text"),
)


def render() -> None:
    inject_compact_css()

    st.markdown(
        """
        <div class="top-spacer"></div>
        <section class="page-header">
          <div class="page-title">Term Sheet Extraction</div>
          <div class="page-subtitle">
            Upload a term sheet, extract structured data, review and approve the product,
            then generate the Excel file from your selected template.
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )

    render_upload_workspace()

    draft = st.session_state.get("active_draft")
    if not draft:
        return

    render_review_workflow(draft, compact_mode=True)


def inject_compact_css() -> None:
    st.markdown(
        """
        <style>
        header[data-testid="stHeader"] {
            height: 0;
            visibility: hidden;
        }
        div[data-testid="stToolbar"] {
            display: none;
        }
        .block-container {
            padding-top: 0;
            padding-bottom: 1.2rem;
            max-width: 1320px;
        }
        .top-spacer {
            height: 4.25rem;
        }
        .page-header {
            padding: 0.2rem 0 0.55rem 0;
        }
        .page-title {
            font-size: 1.55rem !important;
            font-weight: 700;
            line-height: 1.25 !important;
            margin: 0 0 0.25rem 0 !important;
            padding: 0 !important;
        }
        .page-subtitle {
            font-size: 0.9rem;
            line-height: 1.35;
            color: rgba(49, 51, 63, 0.76);
            max-width: 860px;
        }
        h2, h3 {
            font-size: 1.05rem !important;
            margin-top: 0.55rem !important;
            margin-bottom: 0.35rem !important;
        }
        div[data-testid="stVerticalBlock"] {
            gap: 0.5rem;
        }
        div[data-testid="stHorizontalBlock"] {
            gap: 0.6rem;
        }
        div[data-testid="stFileUploader"] section {
            padding: 1.25rem;
            min-height: 7rem;
            border-radius: 8px;
        }
        div[data-testid="stFileUploader"] small {
            display: none;
        }
        div[data-baseweb="input"] input,
        textarea,
        div[data-baseweb="select"] {
            min-height: 2rem !important;
        }
        button[kind],
        div[data-testid="stDownloadButton"] button {
            min-height: 2.25rem;
            border-radius: 7px;
            padding-top: 0.2rem;
            padding-bottom: 0.2rem;
        }
        div[data-testid="stExpander"] details {
            padding-top: 0.15rem;
            padding-bottom: 0.15rem;
        }
        div[data-testid="stMetric"] {
            border: 1px solid rgba(49, 51, 63, 0.14);
            border-radius: 8px;
            padding: 0.55rem 0.65rem;
            background: rgba(250, 250, 252, 0.9);
        }
        .workflow-card {
            border: 1px solid rgba(49, 51, 63, 0.14);
            border-radius: 8px;
            padding: 0.75rem 0.85rem;
            background: rgba(250, 250, 252, 0.92);
            min-height: 100%;
        }
        .workflow-card-title {
            font-weight: 700;
            font-size: 0.92rem;
            margin-bottom: 0.45rem;
        }
        .status-row {
            display: flex;
            justify-content: space-between;
            gap: 0.8rem;
            border-top: 1px solid rgba(49, 51, 63, 0.1);
            padding: 0.42rem 0 0.1rem 0;
            font-size: 0.82rem;
        }
        .status-label {
            color: rgba(49, 51, 63, 0.68);
        }
        .status-value {
            font-weight: 600;
            text-align: right;
        }
        .compact-action {
            border: 1px solid rgba(49, 51, 63, 0.18);
            border-radius: 6px;
            padding: 0.45rem 0.55rem;
            margin: 0.25rem 0 0.45rem 0;
        }
        .compact-title {
            font-weight: 700;
            font-size: 0.95rem;
            line-height: 1.2;
        }
        .compact-meta {
            color: rgba(49, 51, 63, 0.72);
            font-size: 0.78rem;
            line-height: 1.25;
            margin-top: 0.1rem;
        }
        .warning-list {
            font-size: 0.82rem;
            margin: 0.15rem 0 0.35rem 0;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_upload_workspace() -> Any:
    st.markdown(
        "<div class='workflow-card-title'>Upload term sheet</div>",
        unsafe_allow_html=True,
    )
    uploaded_file = st.file_uploader("PDF term sheet", type=["pdf"])
    if st.button(
        "Extract data",
        type="primary",
        use_container_width=True,
        disabled=uploaded_file is None,
    ):
        parse_uploaded_pdf(
            uploaded_file,
            template_profile=None,
            use_copilot=False,
            fallback_settings={},
        )

    return uploaded_file


def render_export_template_selector() -> tuple[str, TemplateProfile | None]:
    profiles = discover_template_profiles()
    options = build_template_options(profiles)
    selected = st.selectbox("Template", options=options, index=0, key="export_template")

    try:
        profile = resolve_template_profile(selected)
    except TemplateProfileError as exc:
        st.error(str(exc))
        return selected, None

    with st.expander("Template details", expanded=False):
        st.caption(profile.name)
        st.code(str(profile.template_path), language=None)
        if profile.template_path.suffix.lower() == ".xlsm":
            st.caption("Macro-enabled output will be saved as .xlsm.")

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


def parse_uploaded_pdf(
    uploaded_file: Any,
    template_profile: TemplateProfile | None,
    use_copilot: bool,
    fallback_settings: dict[str, Any],
) -> None:
    if uploaded_file is None:
        st.warning("Upload a PDF before parsing.")
        return

    uploaded_bytes = uploaded_file.getvalue()
    source_name = Path(uploaded_file.name).name
    apply_fallback_settings(use_copilot, fallback_settings)
    st.session_state.extraction_status = "Extracting"

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
        st.session_state.extraction_status = "Failed"
        st.error(f"Could not parse PDF: {exc}")
        return

    st.session_state.active_draft = draft
    st.session_state.active_pdf_bytes = uploaded_bytes
    st.session_state.active_pdf_name = source_name
    st.session_state.saved_product_id = None
    st.session_state.active_product_record = None
    st.session_state.generated_excel_path = None
    st.session_state.extraction_status = "Extracted"
    st.success("PDF parsed. Review the sections below.")


def parse_current_pdf_with_copilot() -> None:
    uploaded_bytes = st.session_state.get("active_pdf_bytes")
    source_name = st.session_state.get("active_pdf_name")
    if not uploaded_bytes or not source_name:
        st.error("Parse a PDF first before using Microsoft 365 Copilot.")
        return

    st.session_state.extraction_status = "Extracting with Copilot"

    try:
        with TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / str(source_name)
            pdf_path.write_bytes(uploaded_bytes)
            draft = parse_pdf_to_draft(
                pdf_path,
                template_profile=None,
                use_llm=True,
            )
    except Exception as exc:
        st.session_state.extraction_status = "Copilot failed"
        st.error(f"Could not parse PDF with Copilot: {exc}")
        return

    st.session_state.active_draft = draft
    st.session_state.saved_product_id = None
    st.session_state.active_product_record = None
    st.session_state.generated_excel_path = None
    st.session_state.extraction_status = "Extracted with Copilot"
    st.success("Copilot extraction complete. Review the updated fields below.")


def apply_fallback_settings(use_copilot: bool, settings: dict[str, Any]) -> None:
    if not use_copilot:
        return

    if "copilot_url" in settings:
        set_env_if_value("SELENIUM_COPILOT_URL", settings.get("copilot_url"))
    if "chromedriver_path" in settings:
        set_env_if_value("SELENIUM_CHROMEDRIVER_PATH", settings.get("chromedriver_path"))
    if "initial_wait_seconds" in settings:
        set_env_if_value(
            "SELENIUM_COPILOT_INITIAL_WAIT_SECONDS",
            settings.get("initial_wait_seconds"),
        )
    if "response_wait_seconds" in settings:
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


def render_review_workflow(
    draft: dict[str, Any],
    compact_mode: bool,
) -> None:
    fields = compact_fields_from_draft(draft)
    warnings = collect_review_warnings(fields)

    if draft.get("fallback_error"):
        st.warning(f"Copilot fallback issue: {draft['fallback_error']}")

    actions_container = st.container()
    edited_fields, edited_status_rows = render_review_tabs(draft, fields, warnings, compact_mode)
    with actions_container:
        render_workflow_actions(draft, edited_fields, edited_status_rows)


def render_review_tabs(
    draft: dict[str, Any],
    fields: dict[str, Any],
    warnings: list[str],
    compact_mode: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    summary_tab, fields_tab, lifecycle_tab, warnings_tab, raw_text_tab = st.tabs(
        ["Summary", "Extracted fields", "Lifecycle events", "Warnings", "Raw text"]
    )

    with summary_tab:
        edited_summary_rows = render_summary_overview(fields, warnings)
    with fields_tab:
        edited_status_rows = render_scalar_field_editor(fields, compact_mode)
        edited_underlyings = render_underlyings_value_editor(
            fields,
            compact_mode,
            key="review_underlyings_editor",
        )
    with lifecycle_tab:
        edited_lifecycle_events = render_lifecycle_value_editor(fields, compact_mode)
    with warnings_tab:
        render_warnings_tab(fields, warnings)
    with raw_text_tab:
        render_raw_text_tab(draft)

    edited_fields = build_product_from_review_editor(
        fields,
        edited_summary_rows,
        edited_status_rows,
        edited_underlyings,
        edited_lifecycle_events,
    )
    return edited_fields, edited_status_rows


def render_summary_overview(fields: dict[str, Any], warnings: list[str]) -> list[dict[str, Any]]:
    summary_rows = [
        {
            "Field": label,
            "Path": path,
            "Kind": kind,
            "Value": field_editor_display_value(get_path(fields, path), kind),
        }
        for label, path, kind in SUMMARY_FIELD_SPECS
    ]
    edited_rows = normalize_editor_rows(
        st.data_editor(
            summary_rows,
            hide_index=True,
            num_rows="fixed",
            use_container_width=True,
            disabled=["Field"],
            column_order=("Field", "Value"),
            height=editor_height(len(summary_rows), True),
            key=editor_key("summary_overview", fields),
            column_config={
                "Field": st.column_config.TextColumn("Field", width="medium"),
                "Value": st.column_config.TextColumn("Value", width="large"),
            },
        )
    )

    if warnings:
        st.warning(f"{len(warnings)} warning(s) need review before approval.")
    else:
        st.success("No obvious review warnings.")

    return edited_rows


def render_scalar_field_editor(
    fields: dict[str, Any],
    compact_mode: bool,
) -> list[dict[str, Any]]:
    rows = build_field_editor_rows(fields)
    issuer_value = normalize_issuer(get_path(fields, "parties.issuer")) or "UBS AG London"
    issuer_choice = st.selectbox(
        "Issuer",
        ISSUER_OPTIONS,
        index=option_index(ISSUER_OPTIONS, issuer_value),
        key=editor_key("issuer_choice", fields),
    )
    set_field_editor_row_value(rows, "parties.issuer", issuer_choice)
    notation_value = get_path(fields, "economics.notation") or "unknown"
    notation_choice = st.selectbox(
        "Notation",
        NOTATION_TYPES,
        index=option_index(NOTATION_TYPES, notation_value),
        key=editor_key("notation_choice", fields),
    )
    set_field_editor_row_value(rows, "economics.notation", notation_choice)

    edited_rows = normalize_editor_rows(
        st.data_editor(
            rows,
            hide_index=True,
            num_rows="fixed",
            use_container_width=True,
            height=editor_height(16, compact_mode),
            disabled=["Section", "Field"],
            column_order=("Section", "Field", "Value", "Status"),
            key=editor_key("flat_field_editor", fields),
            column_config={
                "Section": st.column_config.TextColumn("Section", width="small"),
                "Field": st.column_config.TextColumn("Field", width="medium"),
                "Value": st.column_config.TextColumn("Value", width="large"),
                "Status": st.column_config.SelectboxColumn(
                    "Status", options=FIELD_STATUSES, width="small"
                ),
            },
        )
    )
    set_field_editor_row_value(edited_rows, "parties.issuer", issuer_choice)
    set_field_editor_row_value(edited_rows, "economics.notation", notation_choice)

    st.caption("Underlyings")
    return edited_rows


def issued_amount_summary(fields: dict[str, Any]) -> str:
    notation = get_path(fields, "economics.notation")
    if notation == "units":
        return number_summary(
            get_path(fields, "economics.number_of_certificates"),
            "Missing certificates",
        )
    if notation == "nominal":
        return number_summary(get_path(fields, "economics.nominal_amount"), "Missing nominal")
    return "Select notation"


def number_summary(value: Any, fallback: str) -> str:
    number = number_value(value)
    if value in (None, ""):
        return fallback
    if number.is_integer():
        return f"{int(number):,}"
    return f"{number:,.2f}"


def set_field_editor_row_value(
    rows: list[dict[str, Any]],
    path: str,
    value: Any,
) -> None:
    for row in rows:
        if row.get("Path") == path:
            row["Value"] = field_editor_display_value(value, "text")
            return


def render_underlyings_value_editor(
    fields: dict[str, Any],
    compact_mode: bool,
    *,
    key: str,
) -> list[dict[str, Any]]:
    return normalize_editor_rows(
        st.data_editor(
            fields.get("underlyings") or [empty_underlying()],
            num_rows="dynamic",
            use_container_width=True,
            height=editor_height(4, compact_mode),
            key=editor_key(key, fields),
            column_config={
                "name": st.column_config.TextColumn("Name", width="medium"),
                "bloomberg_code": st.column_config.TextColumn(
                    "Bloomberg code", width="medium"
                ),
                "ticker": st.column_config.TextColumn("Ticker", width="small"),
                "asset_class": st.column_config.SelectboxColumn(
                    "Class", options=UNDERLYING_ASSET_CLASSES, width="small"
                ),
                "isin": st.column_config.TextColumn("ISIN", width="medium"),
                "currency": st.column_config.SelectboxColumn(
                    "Currency", options=("", *CURRENCIES), width="small"
                ),
                "initial_fixing": st.column_config.NumberColumn("Initial fixing"),
                "strike_price": st.column_config.NumberColumn("Strike"),
                "weight_percent": st.column_config.NumberColumn("Weight %"),
            },
        )
    )


def render_lifecycle_value_editor(
    fields: dict[str, Any],
    compact_mode: bool,
) -> list[dict[str, Any]]:
    return normalize_editor_rows(
        st.data_editor(
            fields.get("lifecycle_events") or [],
            num_rows="dynamic",
            use_container_width=True,
            height=editor_height(10, compact_mode),
            key=editor_key("workflow_lifecycle_events_editor", fields),
            column_config={
                "event_type": st.column_config.SelectboxColumn(
                    "event_type", options=LIFECYCLE_EVENT_TYPES
                ),
                "status": st.column_config.SelectboxColumn("status", options=EVENT_STATUSES),
            },
        )
    )


def render_warnings_tab(fields: dict[str, Any], warnings: list[str]) -> None:
    missing_required = get_path(fields, "review.missing_required") or []
    if missing_required:
        st.warning("Missing required fields")
        st.dataframe(
            [{"Field": field_name} for field_name in missing_required],
            hide_index=True,
            use_container_width=True,
        )

    if warnings:
        st.warning("Review warnings")
        st.dataframe(
            [{"Warning": warning} for warning in warnings],
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.success("No warnings.")


def render_raw_text_tab(draft: dict[str, Any]) -> None:
    st.text_area(
        "Extracted text",
        value=str(draft.get("extracted_text") or ""),
        height=360,
        disabled=True,
        label_visibility="collapsed",
    )

    with st.expander("Raw draft JSON", expanded=False):
        show_raw_json(draft)

    record = st.session_state.get("active_product_record")
    if record:
        with st.expander("Saved product JSON", expanded=False):
            show_raw_json(record)


def render_workflow_actions(
    draft: dict[str, Any],
    edited_fields: dict[str, Any],
    edited_status_rows: list[dict[str, Any]],
) -> None:
    status_counts = count_field_statuses(edited_status_rows)

    save_col, copilot_col, template_col, excel_col = st.columns(
        [1, 1.35, 1.15, 1]
    )
    if save_col.button("Save", type="primary", use_container_width=True):
        fields_to_save = finalize_compact_product(edited_fields)
        save_active_product(draft, fields_to_save)

    if copilot_col.button("Use Microsoft 365 Copilot", use_container_width=True):
        parse_current_pdf_with_copilot()

    with template_col:
        template_identifier, template_profile = render_export_template_selector()

    if excel_col.button(
        "Generate Excel",
        type="primary",
        use_container_width=True,
        disabled=template_profile is None,
    ):
        fields_to_export = finalize_compact_product(edited_fields)
        if save_active_product(draft, fields_to_export, show_success=False):
            generate_excel_for_current_product(template_identifier)

    if status_counts.get("missing", 0):
        st.caption("Excel can be generated with missing fields; review warnings remain visible.")


def build_field_editor_rows(fields: dict[str, Any]) -> list[dict[str, Any]]:
    missing_required = set(get_path(fields, "review.missing_required") or [])
    review_status = get_path(fields, "review.status")
    return [
        {
            "Section": section,
            "Field": label,
            "Path": path,
            "Kind": kind,
            "Value": field_editor_display_value(get_path(fields, path), kind),
            "Status": infer_field_status(fields, path, kind, missing_required, review_status),
        }
        for section, label, path, kind in FIELD_EDITOR_SPECS
    ]


def infer_field_status(
    fields: dict[str, Any],
    path: str,
    kind: str,
    missing_required: set[str],
    review_status: Any,
) -> str:
    value = get_path(fields, path)
    if review_status == "approved" and not field_value_missing(value, kind):
        return "approved"
    if path in missing_required:
        return "missing"
    if path in {
        "classification.product_family",
        "classification.asset_class",
        "economics.notation",
        "economics.strike_type",
        "coupon.coupon_clean_dirty",
        "coupon.coupon_type",
        "coupon.coupon_frequency",
        "barrier.barrier_type",
        "autocall.autocall_frequency",
    } and text_value(value).strip().lower() == "unknown":
        return "needs_review"
    if field_value_missing(value, kind):
        return "unsupported"
    return "extracted"


def field_value_missing(value: Any, kind: str) -> bool:
    if kind == "boolean":
        return False
    return value in (None, "", [], "unknown")


def field_editor_display_value(value: Any, kind: str) -> str:
    if value is None:
        return ""
    if kind == "boolean":
        return "true" if bool(value) else "false"
    return str(value)


def count_field_statuses(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {status: 0 for status in FIELD_STATUSES}
    for row in rows:
        status = str(row.get("Status") or "unsupported")
        if status not in counts:
            status = "unsupported"
        counts[status] += 1
    return counts


def build_product_from_review_editor(
    base_fields: dict[str, Any],
    *args: list[dict[str, Any]],
) -> dict[str, Any]:
    if len(args) == 3:
        summary_rows: list[dict[str, Any]] = []
        field_rows, underlyings, lifecycle_events = args
    elif len(args) == 4:
        summary_rows, field_rows, underlyings, lifecycle_events = args
    else:
        raise TypeError(
            "build_product_from_review_editor expects base fields plus "
            "field rows, underlyings, lifecycle events, and optional summary rows"
        )

    edited = create_empty_product(base_fields["document"].get("file_name"))
    edited["schema_version"] = base_fields.get("schema_version", "1.0")

    for index, (_, _, path, kind) in enumerate(FIELD_EDITOR_SPECS):
        row = field_rows[index] if index < len(field_rows) else {}
        set_nested_value(edited, path, coerce_editor_value(row.get("Value"), kind))

    for row in summary_rows:
        path = row.get("Path")
        kind = row.get("Kind") or "text"
        if isinstance(path, str) and path:
            set_nested_value(edited, path, coerce_editor_value(row.get("Value"), str(kind)))

    edited["underlyings"] = underlyings
    edited["lifecycle_events"] = lifecycle_events
    edited["review"]["status"] = get_path(base_fields, "review.status") or "extracted"
    edited["review"]["missing_required"] = list(get_path(base_fields, "review.missing_required") or [])
    edited["review"]["warnings"] = list(get_path(base_fields, "review.warnings") or [])
    return finalize_compact_product(edited)


def current_generated_excel_path() -> Path | None:
    generated_path = st.session_state.get("generated_excel_path")
    if not generated_path:
        return None
    path = Path(generated_path)
    return path if path.exists() else None


def render_summary_tab(
    edited: dict[str, Any],
    fields: dict[str, Any],
    compact_mode: bool,
) -> None:
    edited["document"]["document_type"] = st.selectbox(
        "Document type",
        DOCUMENT_TYPES,
        index=enum_index(DOCUMENT_TYPES, get_path(fields, "document.document_type")),
    )

    apply_field_editor(
        edited,
        fields,
        [
            ("Language", "document.language", "text"),
            ("Product name", "identity.product_name", "text"),
            ("ISIN", "identity.isin", "text"),
            ("Valor", "identity.valor", "text"),
            ("WKN", "identity.wkn", "text"),
            ("Internal product ID", "identity.internal_product_id", "text"),
            ("Issuer", "parties.issuer", "text"),
            ("Guarantor", "parties.guarantor", "text"),
            ("Calculation agent", "parties.calculation_agent", "text"),
        ],
        key="identity_editor",
        compact_mode=compact_mode,
    )

    render_summary_product_setup(edited, fields)

    apply_field_editor(
        edited,
        fields,
        [
            ("Denomination", "economics.denomination", "number"),
            ("Nominal amount", "economics.nominal_amount", "number"),
            ("Issue price %", "economics.issue_price_percent", "number"),
            ("Minimum investment", "economics.minimum_investment", "number"),
        ],
        key="economics_editor",
        compact_mode=compact_mode,
    )

    render_underlyings_editor(edited, fields, compact_mode, key="summary_underlyings_editor")

    apply_field_editor(
        edited,
        fields,
        [
            ("Trade date", "dates.trade_date", "text"),
            ("Initial fixing date", "dates.initial_fixing_date", "text"),
            ("Issue date", "dates.issue_date", "text"),
            ("Payment date", "dates.payment_date", "text"),
            ("Final valuation date", "dates.final_valuation_date", "text"),
            ("Maturity date", "dates.maturity_date", "text"),
            ("Redemption date", "dates.redemption_date", "text"),
        ],
        key="dates_editor",
        compact_mode=compact_mode,
    )

    review = fields.get("review") or {}
    edited["review"]["status"] = st.selectbox(
        "Review status",
        REVIEW_STATUSES,
        index=enum_index(REVIEW_STATUSES, review.get("status")),
    )
    edited["review"]["missing_required"] = split_lines(
        st.text_area(
            "Missing required",
            value="\n".join(review.get("missing_required") or []),
            height=72 if compact_mode else 100,
        )
    )
    edited["review"]["warnings"] = split_lines(
        st.text_area(
            "Warnings",
            value="\n".join(review.get("warnings") or []),
            height=82 if compact_mode else 120,
        )
    )


def render_summary_product_setup(edited: dict[str, Any], fields: dict[str, Any]) -> None:
    edited["classification"]["is_reverse_convertible"] = st.checkbox(
        "Is reverse convertible",
        value=bool(get_path(fields, "classification.is_reverse_convertible")),
        key=editor_key("summary_is_reverse_convertible", fields),
    )
    edited["autocall"]["is_autocallable"] = st.checkbox(
        "Is autocallable",
        value=bool(get_path(fields, "autocall.is_autocallable")),
        key=editor_key("summary_is_autocallable", fields),
    )
    edited["classification"]["is_autocallable"] = edited["autocall"]["is_autocallable"]

    currency_options = ("", *CURRENCIES)
    currency = st.selectbox(
        "Currency",
        currency_options,
        index=option_index(currency_options, get_path(fields, "economics.issue_currency")),
        key=editor_key("summary_currency", fields),
    )
    edited["economics"]["issue_currency"] = currency or None

    edited["economics"]["strike_type"] = st.selectbox(
        "Strike type",
        STRIKE_TYPES,
        index=enum_index(STRIKE_TYPES, get_path(fields, "economics.strike_type")),
        key=editor_key("summary_strike_type", fields),
    )
    edited["coupon"]["coupon_clean_dirty"] = st.selectbox(
        "Coupon type",
        COUPON_CLEAN_DIRTY_TYPES,
        index=enum_index(
            COUPON_CLEAN_DIRTY_TYPES,
            get_path(fields, "coupon.coupon_clean_dirty"),
        ),
        key=editor_key("summary_coupon_clean_dirty", fields),
    )
    edited["listing"]["exchange"] = st.text_input(
        "Listing exchange",
        value=text_value(get_path(fields, "listing.exchange")),
        key=editor_key("summary_listing_exchange", fields),
    ).strip() or None


def render_payoff_tab(edited: dict[str, Any], fields: dict[str, Any]) -> None:
    edited["classification"]["product_family"] = st.selectbox(
        "Product family",
        PRODUCT_FAMILIES,
        index=enum_index(PRODUCT_FAMILIES, get_path(fields, "classification.product_family")),
    )
    edited["classification"]["asset_class"] = st.selectbox(
        "Asset class",
        ASSET_CLASSES,
        index=enum_index(ASSET_CLASSES, get_path(fields, "classification.asset_class")),
    )

    edited["classification"]["has_barrier"] = st.checkbox(
        "Has barrier", value=bool(get_path(fields, "classification.has_barrier"))
    )
    edited["classification"]["has_memory_coupon"] = st.checkbox(
        "Has memory coupon", value=bool(get_path(fields, "classification.has_memory_coupon"))
    )
    edited["classification"]["has_physical_delivery"] = st.checkbox(
        "Has physical delivery",
        value=bool(get_path(fields, "classification.has_physical_delivery")),
    )

    st.subheader("Coupon")
    edited["coupon"]["coupon_type"] = st.selectbox(
        "Coupon type",
        COUPON_TYPES,
        index=enum_index(COUPON_TYPES, get_path(fields, "coupon.coupon_type")),
    )
    edited["coupon"]["coupon_rate_percent_pa"] = st.number_input(
        "Coupon rate % p.a.",
        value=number_value(get_path(fields, "coupon.coupon_rate_percent_pa")),
        min_value=0.0,
    )
    edited["coupon"]["coupon_frequency"] = st.selectbox(
        "Coupon frequency",
        COUPON_FREQUENCIES,
        index=enum_index(COUPON_FREQUENCIES, get_path(fields, "coupon.coupon_frequency")),
    )
    edited["coupon"]["coupon_trigger_percent"] = st.number_input(
        "Coupon trigger %",
        value=number_value(get_path(fields, "coupon.coupon_trigger_percent")),
        min_value=0.0,
    )
    edited["coupon"]["memory_feature"] = st.checkbox(
        "Memory feature", value=bool(get_path(fields, "coupon.memory_feature"))
    )

    st.subheader("Barrier")
    edited["barrier"]["barrier_type"] = st.selectbox(
        "Barrier type",
        BARRIER_TYPES,
        index=enum_index(BARRIER_TYPES, get_path(fields, "barrier.barrier_type")),
    )
    edited["barrier"]["level_percent"] = st.number_input(
        "Barrier level %",
        value=number_value(get_path(fields, "barrier.level_percent")),
        min_value=0.0,
    )
    edited["barrier"]["observation_start_date"] = date_input_value(
        st, "Barrier observation start", get_path(fields, "barrier.observation_start_date")
    )
    edited["barrier"]["observation_end_date"] = date_input_value(
        st, "Barrier observation end", get_path(fields, "barrier.observation_end_date")
    )

    st.subheader("Autocall")
    edited["autocall"]["first_autocall_date"] = date_input_value(
        st, "First autocall date", get_path(fields, "autocall.first_autocall_date")
    )
    edited["autocall"]["autocall_frequency"] = st.selectbox(
        "Autocall frequency",
        AUTOCALL_FREQUENCIES,
        index=enum_index(AUTOCALL_FREQUENCIES, get_path(fields, "autocall.autocall_frequency")),
    )
    edited["autocall"]["autocall_trigger_percent"] = st.number_input(
        "Autocall trigger %",
        value=number_value(get_path(fields, "autocall.autocall_trigger_percent")),
        min_value=0.0,
    )


def render_underlyings_tab(
    edited: dict[str, Any],
    fields: dict[str, Any],
    compact_mode: bool,
) -> None:
    render_underlyings_editor(edited, fields, compact_mode, key="underlyings_editor")


def render_underlyings_editor(
    edited: dict[str, Any],
    fields: dict[str, Any],
    compact_mode: bool,
    *,
    key: str,
) -> None:
    edited["underlyings"] = normalize_editor_rows(
        st.data_editor(
            fields.get("underlyings") or [empty_underlying()],
            num_rows="dynamic",
            use_container_width=True,
            height=editor_height(4, compact_mode),
            key=editor_key(key, fields),
            column_config={
                "name": st.column_config.TextColumn("Name", width="medium"),
                "bloomberg_code": st.column_config.TextColumn(
                    "Bloomberg code", width="medium"
                ),
                "ticker": st.column_config.TextColumn("Ticker", width="small"),
                "asset_class": st.column_config.SelectboxColumn(
                    "Class", options=UNDERLYING_ASSET_CLASSES, width="small"
                ),
                "isin": st.column_config.TextColumn("ISIN", width="medium"),
                "currency": st.column_config.SelectboxColumn(
                    "Currency", options=("", *CURRENCIES), width="small"
                ),
                "initial_fixing": st.column_config.NumberColumn("Initial fixing"),
                "strike_price": st.column_config.NumberColumn("Strike"),
                "weight_percent": st.column_config.NumberColumn("Weight %"),
            },
        )
    )


def render_lifecycle_tab(
    edited: dict[str, Any],
    fields: dict[str, Any],
    compact_mode: bool,
) -> None:
    edited["lifecycle_events"] = normalize_editor_rows(
        st.data_editor(
            fields.get("lifecycle_events") or [],
            num_rows="dynamic",
            use_container_width=True,
            height=editor_height(7, compact_mode),
            key=editor_key("lifecycle_events_editor", fields),
            column_config={
                "event_type": st.column_config.SelectboxColumn(
                    "event_type", options=LIFECYCLE_EVENT_TYPES
                ),
                "status": st.column_config.SelectboxColumn("status", options=EVENT_STATUSES),
            },
        )
    )


def render_source_tab(draft: dict[str, Any]) -> None:
    with st.expander("Extracted text"):
        st.text_area(
            "Extracted text",
            value=str(draft.get("extracted_text") or ""),
            height=220,
            disabled=True,
            label_visibility="collapsed",
        )

    with st.expander("Raw draft JSON"):
        show_raw_json(draft)

    record = st.session_state.get("active_product_record")
    if record:
        with st.expander("Saved product JSON"):
            show_raw_json(record)


def handle_review_action(
    action: str | None,
    draft: dict[str, Any],
    edited_fields: dict[str, Any],
    template_identifier: str,
) -> None:
    if not action:
        return

    if action == "excel":
        generate_excel_for_current_product(template_identifier)
        return

    if action in {"reviewed", "approved", "rejected"}:
        edited_fields["review"]["status"] = action

    save_active_product(draft, edited_fields)


def generate_excel_for_current_product(template_identifier: str) -> None:
    product_id = st.session_state.get("saved_product_id")
    record = st.session_state.get("active_product_record")
    if not product_id or not record:
        st.info("Save the product before generating Excel.")
        return

    try:
        template_profile = resolve_template_profile(template_identifier)
        generated_path = generate_excel_for_saved_product(record, template_profile)
    except Exception as exc:
        st.error(f"Could not generate Excel: {exc}")
        return

    st.session_state.generated_excel_path = generated_path
    st.session_state.active_product_record = load_product_record(product_id)
    st.success(f"Excel generated: {generated_path.name}")
    st.caption(f"Saved to: {generated_path}")
    open_generated_excel(generated_path)


def render_generated_excel_controls() -> None:
    generated_path = st.session_state.get("generated_excel_path")
    if not generated_path:
        return

    path = Path(generated_path)
    if not path.exists():
        return

    download_col, open_col = st.columns(2)
    download_col.download_button(
        "Download Excel",
        data=path.read_bytes(),
        file_name=path.name,
        mime=excel_mime_type(path),
        use_container_width=True,
    )
    if open_col.button("Open Excel", use_container_width=True):
        open_generated_excel(path)


def collect_review_warnings(fields: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    review = fields.get("review") or {}
    warnings.extend(str(item) for item in review.get("warnings") or [] if item)

    missing_required = review.get("missing_required") or []
    for field_name in missing_required:
        warnings.append(f"Missing required field: {field_name}")

    if not get_path(fields, "identity.isin"):
        warnings.append("Missing ISIN.")

    issuer = text_value(get_path(fields, "parties.issuer")).strip()
    if not issuer:
        warnings.append("Missing issuer.")
    elif len(issuer) < 5 or "..." in issuer or "…" in issuer:
        warnings.append(f"Issuer may be truncated: {issuer}")

    for path, label in (
        ("dates.initial_fixing_date", "initial fixing date"),
        ("dates.issue_date", "issue date"),
        ("dates.final_valuation_date", "final valuation date"),
        ("dates.maturity_date", "maturity date"),
    ):
        if not get_path(fields, path):
            warnings.append(f"Missing {label}.")

    if underlyings_empty(fields.get("underlyings")):
        warnings.append("No underlying is populated.")

    has_barrier = bool(get_path(fields, "classification.has_barrier")) or (
        get_path(fields, "barrier.barrier_type") not in (None, "", "unknown")
    )
    if has_barrier and is_zero_value(get_path(fields, "barrier.level_percent")):
        warnings.append("Suspicious 0.00 barrier level.")

    is_autocallable = bool(get_path(fields, "classification.is_autocallable")) or bool(
        get_path(fields, "autocall.is_autocallable")
    )
    if is_autocallable:
        if is_zero_value(get_path(fields, "autocall.autocall_trigger_percent")):
            warnings.append("Suspicious 0.00 autocall trigger.")
        if not get_path(fields, "autocall.first_autocall_date"):
            warnings.append("Autocallable product has no first autocall date.")

    return dedupe_preserve_order(warnings)


def apply_field_editor(
    edited: dict[str, Any],
    fields: dict[str, Any],
    specs: list[tuple[str, str, str]],
    *,
    key: str,
    compact_mode: bool,
) -> None:
    rows = [
        {
            "Field": label,
            "Value": editor_display_value(get_path(fields, path), kind),
        }
        for label, path, kind in specs
    ]
    edited_rows = normalize_editor_rows(
        st.data_editor(
            rows,
            hide_index=True,
            use_container_width=True,
            num_rows="fixed",
            disabled=["Field"],
            height=editor_height(len(rows), compact_mode),
            key=editor_key(key, fields),
            column_config={
                "Field": st.column_config.TextColumn("Field", width="medium"),
                "Value": st.column_config.TextColumn("Value", width="large"),
            },
        )
    )

    for index, (_, path, kind) in enumerate(specs):
        value = edited_rows[index].get("Value") if index < len(edited_rows) else None
        set_nested_value(edited, path, coerce_editor_value(value, kind))


def editor_display_value(value: Any, kind: str) -> Any:
    if kind == "number":
        return "" if value in (None, "") else value
    return text_value(value)


def coerce_editor_value(value: Any, kind: str) -> Any:
    if kind == "number":
        if value in (None, ""):
            return None
        return number_value(value)
    if kind == "boolean":
        if isinstance(value, bool):
            return value
        text = text_value(value).strip().lower()
        return text in {"1", "true", "yes", "y", "on"}
    text = text_value(value).strip()
    return text or None


def set_nested_value(target: dict[str, Any], path: str, value: Any) -> None:
    current = target
    parts = path.split(".")
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = value


def normalize_editor_rows(value: Any) -> list[dict[str, Any]]:
    if hasattr(value, "to_dict"):
        return [dict(row) for row in value.to_dict("records")]
    if isinstance(value, list):
        return [dict(row) for row in value if isinstance(row, dict)]
    if isinstance(value, dict):
        keys = list(value.keys())
        row_count = max((len(item) for item in value.values() if isinstance(item, list)), default=0)
        rows: list[dict[str, Any]] = []
        for index in range(row_count):
            row: dict[str, Any] = {}
            for key in keys:
                column = value.get(key)
                if isinstance(column, list) and index < len(column):
                    row[key] = column[index]
            rows.append(row)
        return rows
    return []


def editor_key(name: str, fields: dict[str, Any]) -> str:
    source = get_path(fields, "document.file_name") or get_path(fields, "identity.isin") or "draft"
    return f"{name}_{safe_filename(str(source))}"


def editor_height(row_count: int, compact_mode: bool) -> int:
    row_height = 30 if compact_mode else 38
    return min(360, max(112, (row_count + 1) * row_height))


def short_value(value: Any, fallback: str, max_length: int) -> str:
    text = text_value(value).strip() or fallback
    if len(text) <= max_length:
        return text
    return text[: max_length - 1] + "…"


def underlyings_empty(value: Any) -> bool:
    if not isinstance(value, list) or not value:
        return True
    for item in value:
        if not isinstance(item, dict):
            continue
        if any(item.get(key) for key in ("name", "bloomberg_code", "ticker", "isin")):
            return False
    return True


def is_zero_value(value: Any) -> bool:
    if value in (None, ""):
        return False
    try:
        return float(value) == 0.0
    except (TypeError, ValueError):
        return False


def dedupe_preserve_order(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def save_active_product(
    draft: dict[str, Any],
    fields: dict[str, Any],
    *,
    show_success: bool = True,
) -> bool:
    uploaded_bytes = st.session_state.get("active_pdf_bytes")
    source_name = st.session_state.get("active_pdf_name") or draft.get("source_pdf")
    product_id = st.session_state.get("saved_product_id")

    try:
        if product_id:
            workspace_id = str(product_id)
        else:
            if not uploaded_bytes:
                st.error("Uploaded PDF bytes are not available. Parse the PDF again.")
                return False
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
        return False

    st.session_state.saved_product_id = workspace_id
    st.session_state.active_product_record = record
    st.session_state.active_draft = draft
    if show_success:
        st.success(f"Product saved: {workspace_id}")
    return True


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
        "bloomberg_code": None,
        "ticker": None,
        "asset_class": "unknown",
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


def option_index(options: tuple[str, ...], value: Any) -> int:
    if value in options:
        return options.index(value)
    return 0


def split_lines(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip()]


def show_raw_json(value: dict[str, Any]) -> None:
    st.code(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False), language="json")


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
