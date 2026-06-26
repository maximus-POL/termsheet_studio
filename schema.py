from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

SCHEMA_VERSION = "1.0"

DOCUMENT_TYPES = (
    "termsheet",
    "final_terms",
    "indicative_terms",
    "kid",
    "unknown",
)
PRODUCT_FAMILIES = (
    "reverse_convertible",
    "barrier_reverse_convertible",
    "autocallable",
    "phoenix_autocall",
    "express_certificate",
    "capital_protected_note",
    "participation_note",
    "tracker_certificate",
    "discount_certificate",
    "bonus_certificate",
    "other",
    "unknown",
)
ASSET_CLASSES = (
    "equity",
    "index",
    "fund",
    "etf",
    "fx",
    "rates",
    "commodity",
    "credit",
    "multi_asset",
    "unknown",
)
COUPON_TYPES = (
    "none",
    "fixed",
    "conditional",
    "memory",
    "phoenix",
    "guaranteed",
    "floating",
    "unknown",
)
COUPON_FREQUENCIES = (
    "monthly",
    "quarterly",
    "semi_annual",
    "annual",
    "at_maturity",
    "custom",
    "unknown",
)
BARRIER_TYPES = (
    "none",
    "european",
    "american",
    "continuous",
    "daily_close",
    "discrete",
    "unknown",
)
AUTOCALL_FREQUENCIES = (
    "monthly",
    "quarterly",
    "semi_annual",
    "annual",
    "custom",
    "unknown",
)
LIFECYCLE_EVENT_TYPES = (
    "issue",
    "initial_fixing",
    "coupon_observation",
    "coupon_payment",
    "autocall_observation",
    "autocall_redemption",
    "barrier_observation",
    "final_valuation",
    "maturity",
    "redemption",
)
EVENT_STATUSES = (
    "scheduled",
    "triggered",
    "not_triggered",
    "paid",
    "cancelled",
    "unknown",
)
REVIEW_STATUSES = (
    "extracted",
    "review_required",
    "reviewed",
    "approved",
    "rejected",
)

ENUM_FIELDS: dict[str, tuple[str, ...]] = {
    "document.document_type": DOCUMENT_TYPES,
    "classification.product_family": PRODUCT_FAMILIES,
    "classification.asset_class": ASSET_CLASSES,
    "coupon.coupon_type": COUPON_TYPES,
    "coupon.coupon_frequency": COUPON_FREQUENCIES,
    "barrier.barrier_type": BARRIER_TYPES,
    "autocall.autocall_frequency": AUTOCALL_FREQUENCIES,
    "review.status": REVIEW_STATUSES,
}

EVENT_ENUM_FIELDS: dict[str, tuple[str, ...]] = {
    "event_type": LIFECYCLE_EVENT_TYPES,
    "status": EVENT_STATUSES,
}

REQUIRED_PATHS = (
    "identity.product_name",
    "parties.issuer",
    "classification.product_family",
    "classification.asset_class",
    "economics.issue_currency",
    "economics.denomination",
    "economics.issue_price_percent",
    "dates.initial_fixing_date",
    "dates.issue_date",
    "dates.final_valuation_date",
    "dates.maturity_date",
)
REQUIRED_FIELDS = REQUIRED_PATHS

STRING_OR_NULL = {"type": ["string", "null"]}
NUMBER_OR_NULL = {"type": ["number", "null"]}
BOOLEAN_FIELD = {"type": "boolean"}

UNDERLYING_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "name": STRING_OR_NULL,
        "ticker": STRING_OR_NULL,
        "isin": STRING_OR_NULL,
        "currency": STRING_OR_NULL,
        "initial_fixing": NUMBER_OR_NULL,
        "strike_price": NUMBER_OR_NULL,
        "weight_percent": NUMBER_OR_NULL,
    },
    "required": [
        "name",
        "ticker",
        "isin",
        "currency",
        "initial_fixing",
        "strike_price",
        "weight_percent",
    ],
}

LIFECYCLE_EVENT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "event_type": {"type": ["string", "null"], "enum": [*LIFECYCLE_EVENT_TYPES, None]},
        "event_date": STRING_OR_NULL,
        "payment_date": STRING_OR_NULL,
        "amount_percent": NUMBER_OR_NULL,
        "status": {"type": ["string", "null"], "enum": [*EVENT_STATUSES, None]},
    },
    "required": [
        "event_type",
        "event_date",
        "payment_date",
        "amount_percent",
        "status",
    ],
}

COMPACT_PRODUCT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "schema_version": {"type": "string"},
        "document": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "file_name": STRING_OR_NULL,
                "document_type": {"type": "string", "enum": list(DOCUMENT_TYPES)},
                "language": STRING_OR_NULL,
            },
            "required": ["file_name", "document_type", "language"],
        },
        "identity": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "product_name": STRING_OR_NULL,
                "isin": STRING_OR_NULL,
                "valor": STRING_OR_NULL,
                "wkn": STRING_OR_NULL,
                "internal_product_id": STRING_OR_NULL,
            },
            "required": [
                "product_name",
                "isin",
                "valor",
                "wkn",
                "internal_product_id",
            ],
        },
        "parties": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "issuer": STRING_OR_NULL,
                "guarantor": STRING_OR_NULL,
                "calculation_agent": STRING_OR_NULL,
            },
            "required": ["issuer", "guarantor", "calculation_agent"],
        },
        "classification": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "product_family": {"type": "string", "enum": list(PRODUCT_FAMILIES)},
                "asset_class": {"type": "string", "enum": list(ASSET_CLASSES)},
                "is_autocallable": BOOLEAN_FIELD,
                "has_barrier": BOOLEAN_FIELD,
                "has_memory_coupon": BOOLEAN_FIELD,
                "has_physical_delivery": BOOLEAN_FIELD,
            },
            "required": [
                "product_family",
                "asset_class",
                "is_autocallable",
                "has_barrier",
                "has_memory_coupon",
                "has_physical_delivery",
            ],
        },
        "economics": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "issue_currency": STRING_OR_NULL,
                "denomination": NUMBER_OR_NULL,
                "nominal_amount": NUMBER_OR_NULL,
                "issue_price_percent": NUMBER_OR_NULL,
                "minimum_investment": NUMBER_OR_NULL,
            },
            "required": [
                "issue_currency",
                "denomination",
                "nominal_amount",
                "issue_price_percent",
                "minimum_investment",
            ],
        },
        "dates": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "trade_date": STRING_OR_NULL,
                "initial_fixing_date": STRING_OR_NULL,
                "issue_date": STRING_OR_NULL,
                "payment_date": STRING_OR_NULL,
                "final_valuation_date": STRING_OR_NULL,
                "maturity_date": STRING_OR_NULL,
                "redemption_date": STRING_OR_NULL,
            },
            "required": [
                "trade_date",
                "initial_fixing_date",
                "issue_date",
                "payment_date",
                "final_valuation_date",
                "maturity_date",
                "redemption_date",
            ],
        },
        "underlyings": {
            "type": "array",
            "items": UNDERLYING_JSON_SCHEMA,
        },
        "coupon": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "coupon_type": {"type": "string", "enum": list(COUPON_TYPES)},
                "coupon_rate_percent_pa": NUMBER_OR_NULL,
                "coupon_frequency": {"type": "string", "enum": list(COUPON_FREQUENCIES)},
                "coupon_trigger_percent": NUMBER_OR_NULL,
                "memory_feature": BOOLEAN_FIELD,
            },
            "required": [
                "coupon_type",
                "coupon_rate_percent_pa",
                "coupon_frequency",
                "coupon_trigger_percent",
                "memory_feature",
            ],
        },
        "barrier": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "barrier_type": {"type": "string", "enum": list(BARRIER_TYPES)},
                "level_percent": NUMBER_OR_NULL,
                "observation_start_date": STRING_OR_NULL,
                "observation_end_date": STRING_OR_NULL,
            },
            "required": [
                "barrier_type",
                "level_percent",
                "observation_start_date",
                "observation_end_date",
            ],
        },
        "autocall": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "is_autocallable": BOOLEAN_FIELD,
                "first_autocall_date": STRING_OR_NULL,
                "autocall_frequency": {"type": "string", "enum": list(AUTOCALL_FREQUENCIES)},
                "autocall_trigger_percent": NUMBER_OR_NULL,
            },
            "required": [
                "is_autocallable",
                "first_autocall_date",
                "autocall_frequency",
                "autocall_trigger_percent",
            ],
        },
        "lifecycle_events": {
            "type": "array",
            "items": LIFECYCLE_EVENT_JSON_SCHEMA,
        },
        "review": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "status": {"type": "string", "enum": list(REVIEW_STATUSES)},
                "missing_required": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "warnings": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["status", "missing_required", "warnings"],
        },
    },
    "required": [
        "schema_version",
        "document",
        "identity",
        "parties",
        "classification",
        "economics",
        "dates",
        "underlyings",
        "coupon",
        "barrier",
        "autocall",
        "lifecycle_events",
        "review",
    ],
}

DEFAULT_PRODUCT: dict[str, Any] = {
    "schema_version": SCHEMA_VERSION,
    "document": {
        "file_name": None,
        "document_type": "unknown",
        "language": None,
    },
    "identity": {
        "product_name": None,
        "isin": None,
        "valor": None,
        "wkn": None,
        "internal_product_id": None,
    },
    "parties": {
        "issuer": None,
        "guarantor": None,
        "calculation_agent": None,
    },
    "classification": {
        "product_family": "unknown",
        "asset_class": "unknown",
        "is_autocallable": False,
        "has_barrier": False,
        "has_memory_coupon": False,
        "has_physical_delivery": False,
    },
    "economics": {
        "issue_currency": None,
        "denomination": None,
        "nominal_amount": None,
        "issue_price_percent": None,
        "minimum_investment": None,
    },
    "dates": {
        "trade_date": None,
        "initial_fixing_date": None,
        "issue_date": None,
        "payment_date": None,
        "final_valuation_date": None,
        "maturity_date": None,
        "redemption_date": None,
    },
    "underlyings": [],
    "coupon": {
        "coupon_type": "unknown",
        "coupon_rate_percent_pa": None,
        "coupon_frequency": "unknown",
        "coupon_trigger_percent": None,
        "memory_feature": False,
    },
    "barrier": {
        "barrier_type": "none",
        "level_percent": None,
        "observation_start_date": None,
        "observation_end_date": None,
    },
    "autocall": {
        "is_autocallable": False,
        "first_autocall_date": None,
        "autocall_frequency": "unknown",
        "autocall_trigger_percent": None,
    },
    "lifecycle_events": [],
    "review": {
        "status": "extracted",
        "missing_required": [],
        "warnings": [],
    },
}

DATE_VALUE = (
    r"(?:\d{1,2}[./-]\d{1,2}[./-]\d{2,4}"
    r"|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}"
    r"|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})"
)
PERCENT_VALUE = r"(?P<value>\d+(?:[.,]\d+)?)\s*%"
MONEY_VALUE = r"(?P<value>[A-Z]{3}\s*[\d,.' ]+|\d[\d,.' ]*)"
DEFAULT_REGEX_FLAGS = re.IGNORECASE | re.MULTILINE


@dataclass(frozen=True)
class FieldSpec:
    name: str
    required: bool
    patterns: tuple[str, ...]
    value_type: str = "text"
    flags: int = DEFAULT_REGEX_FLAGS


PRODUCT_SCHEMA: tuple[FieldSpec, ...] = (
    FieldSpec(
        name="identity.isin",
        required=True,
        value_type="isin",
        patterns=(
            r"\bISIN\s*[:\-]?\s*(?P<value>[A-Z]{2}[A-Z0-9]{9}\d)\b",
            r"\b(?P<value>[A-Z]{2}[A-Z0-9]{9}\d)\b",
        ),
    ),
    FieldSpec(
        name="identity.valor",
        required=False,
        patterns=(
            r"\b(?:Valor|Valor Number|Security Number)\s*[:\-]?\s*(?P<value>\d{5,12})\b",
        ),
    ),
    FieldSpec(
        name="identity.wkn",
        required=False,
        patterns=(
            r"\bWKN\s*[:\-]?\s*(?P<value>[A-Z0-9]{6})\b",
        ),
    ),
    FieldSpec(
        name="identity.product_name",
        required=True,
        patterns=(
            r"^(?P<value>(?:\d+(?:[.,]\d+)?%\s*p\.a\.\s+)?(?:[A-Z]{3}\s+)?[^\n\r]*(?:Certificate|Zertifikat|Airbag|Discount Certificate)[^\n\r]*)$",
            r"\b(?:Product Name|Name of Product|Security Name)\s*[:\-]\s*(?P<value>[^\n\r]+)",
            r"\b(?P<value>(?:Autocallable|Phoenix|Express(?:\s+(?:Certificate|Step|Airbag|Zertifikat))?|Barrier Reverse Convertible|"
            r"Reverse Convertible|Tracker Certificate|Capital Protected Note|Discount Certificate)[^\n\r]*)",
        ),
    ),
    FieldSpec(
        name="parties.issuer",
        required=True,
        patterns=(
            r"\bIssuer\s*[:\-]\s*(?P<value>[^\n\r]+)",
            r"^\s*Issuer\s*$\s*(?P<value>[^\n\r]+)",
            r"^\s*Emittentin\s*$\s*(?P<value>[^\n\r]+)",
            r"^\s*Emittent\s*$\s*(?P<value>[^\n\r]+)",
            r"\bIssued by\s*(?P<value>[^\n\r]+)",
        ),
    ),
    FieldSpec(
        name="parties.guarantor",
        required=False,
        patterns=(r"\bGuarantor\s*[:\-]\s*(?P<value>[^\n\r]+)",),
    ),
    FieldSpec(
        name="parties.calculation_agent",
        required=False,
        patterns=(r"\bCalculation Agent\s*[:\-]\s*(?P<value>[^\n\r]+)",),
    ),
    FieldSpec(
        name="economics.issue_currency",
        required=True,
        value_type="currency",
        patterns=(
            r"\b(?:Issue Currency|Settlement Currency|Denomination Currency|Currency)\s*[:\-]\s*(?P<value>[A-Z]{3})\b",
            r"\b(?P<value>USD|EUR|GBP|CHF|JPY|PLN|AUD|CAD|NOK|SEK)\b",
        ),
    ),
    FieldSpec(
        name="economics.denomination",
        required=True,
        value_type="number",
        patterns=(
            rf"\b(?:Denomination|Specified Denomination)\s*[:\-]\s*{MONEY_VALUE}",
        ),
    ),
    FieldSpec(
        name="economics.nominal_amount",
        required=False,
        value_type="number",
        patterns=(
            rf"\b(?:Nominal Amount|Aggregate Nominal Amount|Issue Size|Notional Amount)\s*[:\-]\s*{MONEY_VALUE}",
        ),
    ),
    FieldSpec(
        name="economics.issue_price_percent",
        required=True,
        value_type="percent",
        patterns=(
            rf"\b(?:Issue Price|Issue Price Percent|Offer Price)\s*[:\-]\s*{PERCENT_VALUE}",
        ),
    ),
    FieldSpec(
        name="economics.minimum_investment",
        required=False,
        value_type="number",
        patterns=(
            rf"\b(?:Minimum Investment|Minimum Trading Size|Minimum Subscription)\s*[:\-]\s*{MONEY_VALUE}",
        ),
    ),
    FieldSpec(
        name="dates.trade_date",
        required=False,
        value_type="date",
        patterns=(rf"\bTrade Date\s*[:\-]\s*(?P<value>{DATE_VALUE})",),
    ),
    FieldSpec(
        name="dates.initial_fixing_date",
        required=True,
        value_type="date",
        patterns=(
            rf"\b(?:Initial Fixing Date|Strike Date|Fixing Date|Fixierung)\s*[:\-]\s*(?P<value>{DATE_VALUE})",
        ),
    ),
    FieldSpec(
        name="dates.issue_date",
        required=True,
        value_type="date",
        patterns=(
            rf"\b(?:Issue Date|Initial Payment Date|Settlement Date|Liberierung)\s*[:\-]\s*(?P<value>{DATE_VALUE})",
        ),
    ),
    FieldSpec(
        name="dates.payment_date",
        required=False,
        value_type="date",
        patterns=(rf"\b(?:Payment Date|Initial Payment Date)\s*[:\-]\s*(?P<value>{DATE_VALUE})",),
    ),
    FieldSpec(
        name="dates.final_valuation_date",
        required=True,
        value_type="date",
        patterns=(
            rf"\b(?:Final Valuation Date|Final Fixing Date|Final Observation Date|Verfall)\s*[:\-]\s*(?P<value>{DATE_VALUE})",
        ),
    ),
    FieldSpec(
        name="dates.maturity_date",
        required=True,
        value_type="date",
        patterns=(
            rf"\b(?:Maturity Date|Redemption Date|Maturity|Rückzahlungstag|Rueckzahlungstag)\s*[:\-]\s*(?P<value>{DATE_VALUE}|Open End)",
        ),
    ),
    FieldSpec(
        name="dates.redemption_date",
        required=False,
        value_type="date",
        patterns=(rf"\bRedemption Date\s*[:\-]\s*(?P<value>{DATE_VALUE})",),
    ),
    FieldSpec(
        name="underlyings.0.name",
        required=True,
        patterns=(
            r"\b(?:Underlying|Underlying Asset|Reference Asset|Basket)\s*[:\-]\s*(?P<value>[^\n\r]+)",
        ),
    ),
    FieldSpec(
        name="coupon.coupon_rate_percent_pa",
        required=False,
        value_type="percent",
        patterns=(
            rf"\b(?:Coupon Rate|Coupon|Interest Rate)\s*[:\-]?\s*{PERCENT_VALUE}",
        ),
    ),
    FieldSpec(
        name="coupon.coupon_trigger_percent",
        required=False,
        value_type="percent",
        patterns=(
            rf"\b(?:Coupon Trigger|Coupon Barrier|Coupon Threshold)\s*[:\-]?\s*{PERCENT_VALUE}",
        ),
    ),
    FieldSpec(
        name="barrier.level_percent",
        required=False,
        value_type="percent",
        patterns=(
            rf"\b(?:Barrier|Knock-In Barrier|Protection Barrier)\s*[:\-]?\s*{PERCENT_VALUE}",
        ),
    ),
    FieldSpec(
        name="autocall.autocall_trigger_percent",
        required=False,
        value_type="percent",
        patterns=(
            rf"\b(?:Autocall Trigger|Autocall Barrier|Early Redemption Level)\s*[:\-]?\s*{PERCENT_VALUE}",
        ),
    ),
    FieldSpec(
        name="autocall.first_autocall_date",
        required=False,
        value_type="date",
        patterns=(
            rf"\b(?:First Autocall Date|First Early Redemption Date)\s*[:\-]\s*(?P<value>{DATE_VALUE})",
        ),
    ),
)


class SchemaValidationError(ValueError):
    pass


def create_empty_product(file_name: str | None = None) -> dict[str, Any]:
    product = copy.deepcopy(DEFAULT_PRODUCT)
    product["document"]["file_name"] = file_name
    return product


def normalize_compact_product(product: dict[str, Any] | None) -> dict[str, Any]:
    normalized = create_empty_product()
    if isinstance(product, dict):
        deep_update(normalized, product)

    normalized["schema_version"] = str(normalized.get("schema_version") or SCHEMA_VERSION)
    ensure_list(normalized, "underlyings")
    ensure_list(normalized, "lifecycle_events")
    normalize_underlyings(normalized)
    normalize_lifecycle_events(normalized)
    normalize_booleans(normalized)
    normalize_enums(normalized)
    return normalized


def validate_compact_product(product: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_compact_product(product)
    validate_enums(normalized)
    missing_required = calculate_missing_required(normalized)
    warnings = build_review_warnings(normalized, missing_required)
    normalized["review"]["missing_required"] = missing_required
    normalized["review"]["warnings"] = warnings
    if missing_required:
        normalized["review"]["status"] = "review_required"
    return normalized


def finalize_compact_product(product: dict[str, Any], *, generate_events: bool = True) -> dict[str, Any]:
    normalized = validate_compact_product(product)
    if generate_events:
        explicit_events = list(normalized.get("lifecycle_events") or [])
        generated_events = generate_lifecycle_events(normalized)
        normalized["lifecycle_events"] = merge_lifecycle_events(explicit_events, generated_events)
    return validate_compact_product(normalized)


def calculate_missing_required(product: dict[str, Any]) -> list[str]:
    missing = [path for path in REQUIRED_PATHS if is_missing_value(get_path(product, path))]

    if is_missing_value(get_path(product, "identity.isin")) and is_missing_value(
        get_path(product, "identity.internal_product_id")
    ):
        missing.append("identity.isin_or_internal_product_id")

    underlyings = product.get("underlyings") or []
    if not any(not is_missing_value(item.get("name")) for item in underlyings if isinstance(item, dict)):
        missing.append("underlyings[0].name")

    if not has_payoff_data(product):
        missing.append("payoff_data")

    return missing


def build_review_warnings(product: dict[str, Any], missing_required: list[str]) -> list[str]:
    warnings = [f"Missing required field: {path}" for path in missing_required]

    if product["classification"]["product_family"] == "unknown":
        warnings.append("Product family is unknown and needs review.")
    if product["classification"]["asset_class"] == "unknown":
        warnings.append("Asset class is unknown and needs review.")
    if (
        product["autocall"]["is_autocallable"]
        and not product["autocall"]["first_autocall_date"]
    ):
        warnings.append("Autocallable product has no first autocall date.")

    return dedupe_strings(warnings)


def has_payoff_data(product: dict[str, Any]) -> bool:
    coupon = product.get("coupon") or {}
    barrier = product.get("barrier") or {}
    autocall = product.get("autocall") or {}
    classification = product.get("classification") or {}

    coupon_data = (
        coupon.get("coupon_type") not in (None, "", "none", "unknown")
        or not is_missing_value(coupon.get("coupon_rate_percent_pa"))
        or not is_missing_value(coupon.get("coupon_trigger_percent"))
    )
    barrier_data = (
        barrier.get("barrier_type") not in (None, "", "none", "unknown")
        or not is_missing_value(barrier.get("level_percent"))
        or bool(classification.get("has_barrier"))
    )
    autocall_data = (
        bool(autocall.get("is_autocallable"))
        or bool(classification.get("is_autocallable"))
        or not is_missing_value(autocall.get("autocall_trigger_percent"))
    )
    return coupon_data or barrier_data or autocall_data or bool(
        classification.get("has_physical_delivery")
    )


def generate_lifecycle_events(product: dict[str, Any]) -> list[dict[str, Any]]:
    product = normalize_compact_product(product)
    dates = product["dates"]
    coupon = product["coupon"]
    autocall = product["autocall"]
    events: list[dict[str, Any]] = []

    add_event(events, "issue", dates.get("issue_date"))
    add_event(events, "initial_fixing", dates.get("initial_fixing_date"))
    add_event(events, "final_valuation", dates.get("final_valuation_date"))
    add_event(events, "maturity", dates.get("maturity_date"))
    add_event(
        events,
        "redemption",
        dates.get("redemption_date") or dates.get("maturity_date"),
        payment_date=dates.get("redemption_date") or dates.get("maturity_date"),
    )

    coupon_frequency = coupon.get("coupon_frequency")
    if coupon_frequency in FREQUENCY_MONTHS:
        start = parse_date_value(dates.get("payment_date")) or parse_date_value(dates.get("issue_date"))
        end = parse_date_value(dates.get("final_valuation_date")) or parse_date_value(dates.get("maturity_date"))
        for event_date in iter_schedule_dates(start, end, FREQUENCY_MONTHS[coupon_frequency]):
            date_text = event_date.isoformat()
            add_event(events, "coupon_observation", date_text)
            add_event(
                events,
                "coupon_payment",
                date_text,
                payment_date=date_text,
                amount_percent=coupon.get("coupon_rate_percent_pa"),
            )

    autocall_frequency = autocall.get("autocall_frequency")
    if autocall.get("is_autocallable") and autocall_frequency in FREQUENCY_MONTHS:
        start = parse_date_value(autocall.get("first_autocall_date"))
        end = parse_date_value(dates.get("final_valuation_date"))
        for event_date in iter_schedule_dates(start, end, FREQUENCY_MONTHS[autocall_frequency]):
            add_event(events, "autocall_observation", event_date.isoformat())

    return events


FREQUENCY_MONTHS = {
    "monthly": 1,
    "quarterly": 3,
    "semi_annual": 6,
    "annual": 12,
}


def add_event(
    events: list[dict[str, Any]],
    event_type: str,
    event_date: Any,
    *,
    payment_date: Any = None,
    amount_percent: Any = None,
) -> None:
    if is_missing_value(event_date):
        return
    events.append(
        {
            "event_type": event_type,
            "event_date": str(event_date),
            "payment_date": None if is_missing_value(payment_date) else str(payment_date),
            "amount_percent": coerce_number(amount_percent),
            "status": "scheduled",
        }
    )


def iter_schedule_dates(start: date | None, end: date | None, months: int) -> list[date]:
    if not start or not end or months <= 0:
        return []

    dates: list[date] = []
    current = start
    for _ in range(240):
        if current > end:
            break
        dates.append(current)
        current = add_months(current, months)
    return dates


def add_months(value: date, months: int) -> date:
    month = value.month - 1 + months
    year = value.year + month // 12
    month = month % 12 + 1
    day = min(value.day, days_in_month(year, month))
    return date(year, month, day)


def days_in_month(year: int, month: int) -> int:
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    return (next_month - date(year, month, 1)).days


def parse_date_value(value: Any) -> date | None:
    if is_missing_value(value):
        return None

    text = str(value).strip()
    if text.lower() == "open end":
        return None

    formats = (
        "%Y-%m-%d",
        "%d.%m.%Y",
        "%d.%m.%y",
        "%d/%m/%Y",
        "%d/%m/%y",
        "%d-%m-%Y",
        "%d-%m-%y",
        "%d %B %Y",
        "%d %b %Y",
        "%B %d, %Y",
        "%b %d, %Y",
    )
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def merge_lifecycle_events(
    explicit_events: list[dict[str, Any]],
    generated_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str | None]] = set()
    for event in [*explicit_events, *generated_events]:
        if not isinstance(event, dict):
            continue
        normalized = normalize_lifecycle_event(event)
        key = (
            str(normalized.get("event_type")),
            str(normalized.get("event_date")),
            normalized.get("payment_date"),
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(normalized)
    return merged


def normalize_lifecycle_event(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_type": event.get("event_type"),
        "event_date": event.get("event_date"),
        "payment_date": event.get("payment_date"),
        "amount_percent": coerce_number(event.get("amount_percent")),
        "status": event.get("status") or "scheduled",
    }


def migrate_legacy_fields(fields: dict[str, Any]) -> dict[str, Any]:
    if is_compact_product(fields):
        return finalize_compact_product(fields)

    product = create_empty_product()
    legacy = fields if isinstance(fields, dict) else {}
    mappings = {
        "issuer": "parties.issuer",
        "isin": "identity.isin",
        "currency": "economics.issue_currency",
        "issue_date": "dates.issue_date",
        "maturity_date": "dates.maturity_date",
        "nominal_amount": "economics.nominal_amount",
    }
    for source, target in mappings.items():
        if legacy.get(source):
            set_path(product, target, legacy[source])

    if legacy.get("product_name"):
        set_path(product, "identity.product_name", legacy["product_name"])
    elif legacy.get("product_type"):
        set_path(product, "identity.product_name", legacy["product_type"])

    if legacy.get("product_type"):
        family = infer_product_family(str(legacy["product_type"]))
        set_path(product, "classification.product_family", family)

    if legacy.get("underlying"):
        product["underlyings"] = [{"name": legacy["underlying"]}]
        product["classification"]["asset_class"] = infer_asset_class(str(legacy["underlying"]))

    coupon_rate = parse_percent(legacy.get("coupon_rate"))
    if coupon_rate is not None:
        product["coupon"]["coupon_rate_percent_pa"] = coupon_rate
        product["coupon"]["coupon_type"] = "fixed"

    barrier_level = parse_percent(legacy.get("barrier"))
    if barrier_level is not None:
        product["barrier"]["level_percent"] = barrier_level
        product["barrier"]["barrier_type"] = "discrete"
        product["classification"]["has_barrier"] = True

    if legacy.get("observation_frequency"):
        frequency = infer_frequency(str(legacy["observation_frequency"]))
        product["coupon"]["coupon_frequency"] = frequency
        product["autocall"]["autocall_frequency"] = frequency

    return finalize_compact_product(product)


def is_compact_product(value: Any) -> bool:
    return isinstance(value, dict) and (
        value.get("schema_version") == SCHEMA_VERSION
        or {"document", "identity", "classification", "economics", "dates"}.issubset(value.keys())
    )


def migrate_legacy_record(record: dict[str, Any]) -> dict[str, Any]:
    migrated = dict(record)
    fields = migrated.get("fields")
    if isinstance(fields, dict) and not is_compact_product(fields):
        migrated["raw_extraction"] = {"legacy_fields": fields}
        migrated["fields"] = migrate_legacy_fields(fields)
    elif isinstance(fields, dict):
        migrated["fields"] = finalize_compact_product(fields)
    else:
        migrated["fields"] = finalize_compact_product(create_empty_product())

    migrated["missing_required"] = migrated["fields"]["review"]["missing_required"]
    return migrated


def flatten_compact_product(product: dict[str, Any]) -> dict[str, Any]:
    compact = migrate_legacy_fields(product) if not is_compact_product(product) else normalize_compact_product(product)
    underlying = compact["underlyings"][0] if compact["underlyings"] else {}
    return {
        "issuer": compact["parties"].get("issuer"),
        "isin": compact["identity"].get("isin"),
        "currency": compact["economics"].get("issue_currency"),
        "product_name": compact["identity"].get("product_name"),
        "product_type": compact["classification"].get("product_family"),
        "issue_date": compact["dates"].get("issue_date"),
        "maturity_date": compact["dates"].get("maturity_date"),
        "underlying": underlying.get("name") if isinstance(underlying, dict) else None,
        "nominal_amount": compact["economics"].get("nominal_amount"),
        "coupon_rate": compact["coupon"].get("coupon_rate_percent_pa"),
        "barrier": compact["barrier"].get("level_percent"),
        "observation_frequency": compact["coupon"].get("coupon_frequency"),
    }


def deep_update(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            deep_update(target[key], value)
        else:
            target[key] = copy.deepcopy(value)


def set_path(product: dict[str, Any], path: str, value: Any) -> None:
    if value in (None, ""):
        return

    parts = path.split(".")
    current: Any = product
    for part in parts[:-1]:
        if part.isdigit():
            index = int(part)
            while len(current) <= index:
                current.append({})
            current = current[index]
            continue

        if part not in current:
            current[part] = [] if parts[parts.index(part) + 1].isdigit() else {}
        current = current[part]

    final = parts[-1]
    current[final] = value


def get_path(product: dict[str, Any], path: str) -> Any:
    current: Any = product
    for part in path.split("."):
        if isinstance(current, list) and part.isdigit():
            index = int(part)
            if index >= len(current):
                return None
            current = current[index]
            continue
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def is_missing_value(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == "unknown"


def ensure_list(product: dict[str, Any], key: str) -> None:
    if not isinstance(product.get(key), list):
        product[key] = []


def normalize_underlyings(product: dict[str, Any]) -> None:
    normalized: list[dict[str, Any]] = []
    for item in product.get("underlyings") or []:
        if isinstance(item, str):
            item = {"name": item}
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "name": item.get("name"),
                "ticker": item.get("ticker"),
                "isin": normalize_isin(item.get("isin")),
                "currency": normalize_currency(item.get("currency")),
                "initial_fixing": coerce_number(item.get("initial_fixing")),
                "strike_price": coerce_number(item.get("strike_price")),
                "weight_percent": coerce_number(item.get("weight_percent")),
            }
        )
    product["underlyings"] = normalized


def normalize_lifecycle_events(product: dict[str, Any]) -> None:
    product["lifecycle_events"] = [
        normalize_lifecycle_event(event)
        for event in product.get("lifecycle_events") or []
        if isinstance(event, dict)
    ]


def normalize_booleans(product: dict[str, Any]) -> None:
    for path in (
        "classification.is_autocallable",
        "classification.has_barrier",
        "classification.has_memory_coupon",
        "classification.has_physical_delivery",
        "coupon.memory_feature",
        "autocall.is_autocallable",
    ):
        set_path(product, path, bool(get_path(product, path)))

    if get_path(product, "autocall.is_autocallable"):
        set_path(product, "classification.is_autocallable", True)
    if get_path(product, "coupon.memory_feature"):
        set_path(product, "classification.has_memory_coupon", True)
    if not is_missing_value(get_path(product, "barrier.level_percent")):
        set_path(product, "classification.has_barrier", True)


def normalize_enums(product: dict[str, Any]) -> None:
    for path, values in ENUM_FIELDS.items():
        value = get_path(product, path)
        if value in (None, ""):
            default = "none" if "barrier_type" in path else "unknown"
            if path == "review.status":
                default = "extracted"
            set_path(product, path, default)
            continue
        if isinstance(value, str):
            if path == "autocall.autocall_frequency" and enum_token(value) == "at_maturity":
                set_path(product, path, "unknown")
                continue
            set_path(product, path, normalize_enum_value(value, values))

    for event in product.get("lifecycle_events") or []:
        for key, values in EVENT_ENUM_FIELDS.items():
            if isinstance(event.get(key), str):
                event[key] = normalize_enum_value(event[key], values)


def validate_enums(product: dict[str, Any]) -> None:
    for path, values in ENUM_FIELDS.items():
        value = get_path(product, path)
        if value not in values:
            raise SchemaValidationError(
                f"Invalid enum value at {path}: {value!r}. Expected one of {', '.join(values)}"
            )

    for index, event in enumerate(product.get("lifecycle_events") or []):
        if not isinstance(event, dict):
            continue
        for key, values in EVENT_ENUM_FIELDS.items():
            value = event.get(key)
            if value is not None and value not in values:
                raise SchemaValidationError(
                    f"Invalid enum value at lifecycle_events[{index}].{key}: {value!r}"
                )


def normalize_enum_value(value: str, values: tuple[str, ...]) -> str:
    normalized = enum_token(value)
    return normalized if normalized in values else value


def enum_token(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def coerce_number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value)
    text = re.sub(r"[A-Z]{3}", "", text.upper())
    text = text.replace("'", "").replace(" ", "").replace("%", "")
    text = re.sub(r"[^0-9,.\-]", "", text)
    if "," in text and "." in text:
        text = text.replace(",", "")
    elif "," in text:
        comma_parts = text.split(",")
        if len(comma_parts) > 2 or len(comma_parts[-1]) == 3:
            text = "".join(comma_parts)
        else:
            text = text.replace(",", ".")
    text = re.sub(r"[^0-9.\-]", "", text)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_percent(value: Any) -> float | None:
    if value in (None, ""):
        return None
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*%", str(value))
    if not match:
        return coerce_number(value)
    return coerce_number(match.group(1))


def normalize_isin(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value).replace(" ", "").upper()


def normalize_currency(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value).strip().upper()[:3]


def normalize_date_value(value: str) -> str:
    cleaned = " ".join(value.replace("\xa0", " ").split()).strip(" :-;")
    if "open end" in cleaned.lower():
        return "Open End"
    return re.sub(r"\s+\([^)]*\)$", "", cleaned).strip()


def infer_product_family(text: str) -> str:
    lower = text.lower()
    if "phoenix" in lower and ("autocall" in lower or "auto-call" in lower):
        return "phoenix_autocall"
    if "express" in lower:
        return "express_certificate"
    if "autocall" in lower or "auto-call" in lower:
        return "autocallable"
    if "barrier reverse convertible" in lower:
        return "barrier_reverse_convertible"
    if "reverse convertible" in lower:
        return "reverse_convertible"
    if "capital protected" in lower:
        return "capital_protected_note"
    if "tracker" in lower:
        return "tracker_certificate"
    if "discount" in lower:
        return "discount_certificate"
    if "bonus" in lower:
        return "bonus_certificate"
    if "participation" in lower:
        return "participation_note"
    return "unknown"


def infer_asset_class(text: str) -> str:
    lower = text.lower()
    if "basket" in lower or "," in text:
        return "multi_asset"
    if "index" in lower:
        return "index"
    if "fund" in lower:
        return "fund"
    if "etf" in lower:
        return "etf"
    if any(token in lower for token in ("fx", "eur/", "usd/", "chf/")):
        return "fx"
    if any(token in lower for token in ("gold", "silver", "oil", "commodity")):
        return "commodity"
    return "equity" if text.strip() else "unknown"


def infer_frequency(text: str) -> str:
    lower = text.lower()
    if "monthly" in lower:
        return "monthly"
    if "quarter" in lower:
        return "quarterly"
    if "semi" in lower or "half-year" in lower:
        return "semi_annual"
    if "annual" in lower or "yearly" in lower:
        return "annual"
    if "maturity" in lower:
        return "at_maturity"
    return "unknown"


def dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
