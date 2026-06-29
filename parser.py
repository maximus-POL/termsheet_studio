from __future__ import annotations

import logging
import re
from typing import Any

from schema import (
    PRODUCT_SCHEMA,
    FieldSpec,
    calculate_missing_required,
    coerce_number,
    create_empty_product,
    finalize_compact_product,
    infer_asset_class,
    infer_frequency,
    infer_product_family,
    normalize_currency,
    normalize_date_value,
    normalize_isin,
    parse_percent,
    parse_date_value,
    set_path,
)

logger = logging.getLogger(__name__)

PARSER_VERSION = "1.0.0"
DATE_PATTERN = re.compile(
    r"(?:\d{1,2}[./-]\d{1,2}[./-]\d{2,4}"
    r"|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}"
    r"|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})",
    re.IGNORECASE,
)


def parse_product_text(text: str) -> dict[str, Any]:
    product = create_empty_product()

    for field in PRODUCT_SCHEMA:
        value = extract_field_value(text, field)
        if value not in (None, ""):
            set_path(product, field.name, value)
            logger.debug("Parsed field %s=%r", field.name, value)

    apply_regex_heuristics(product, text)
    return finalize_compact_product(product)


def apply_regex_heuristics(product: dict[str, Any], text: str) -> None:
    lower = text.lower()
    lines = [line.strip() for line in text.splitlines()]
    product_name = product["identity"].get("product_name") or ""
    combined = f"{product_name}\n{text[:4000]}"

    if "final terms" in lower:
        product["document"]["document_type"] = "final_terms"
    elif "indicative" in lower:
        product["document"]["document_type"] = "indicative_terms"
    elif "key information document" in lower or re.search(r"\bkid\b", lower):
        product["document"]["document_type"] = "kid"
    elif "termsheet" in lower or "term sheet" in lower:
        product["document"]["document_type"] = "termsheet"

    if any(token in lower for token in ("emittent", "barriere", "rueckzahlung", "rückzahlung")):
        product["document"]["language"] = "de"
    elif any(token in lower for token in ("issuer", "redemption", "underlying", "maturity")):
        product["document"]["language"] = "en"

    product["classification"]["product_family"] = infer_product_family(combined)
    if product["underlyings"]:
        product["classification"]["asset_class"] = infer_asset_class(
            str(product["underlyings"][0].get("name") or "")
        )
    else:
        product["classification"]["asset_class"] = infer_asset_class(combined)

    product["classification"]["is_autocallable"] = contains_any(
        lower, ("autocall", "auto-call", "early redemption")
    )
    product["autocall"]["is_autocallable"] = product["classification"]["is_autocallable"]
    product["classification"]["has_barrier"] = contains_any(
        lower, ("barrier", "knock-in", "knock in", "protection barrier")
    ) or product["barrier"].get("level_percent") is not None
    product["classification"]["has_memory_coupon"] = "memory" in lower
    product["coupon"]["memory_feature"] = product["classification"]["has_memory_coupon"]
    product["classification"]["has_physical_delivery"] = contains_any(
        lower, ("physical delivery", "physische lieferung")
    )

    if product["classification"]["has_barrier"]:
        product["barrier"]["barrier_type"] = infer_barrier_type(lower)

    apply_line_table_heuristics(product, lines)

    product["coupon"]["coupon_type"] = infer_coupon_type(lower, product)
    frequency = infer_frequency(text)
    if frequency != "unknown":
        product["coupon"]["coupon_frequency"] = frequency
        if product["autocall"]["is_autocallable"] and frequency != "at_maturity":
            product["autocall"]["autocall_frequency"] = frequency

    coupon_dates = extract_indexed_observation_dates(lines, "i")
    early_redemption_dates = extract_indexed_observation_dates(lines, "j")
    coupon_frequency = infer_frequency_from_date_strings(coupon_dates)
    autocall_frequency = infer_frequency_from_date_strings(early_redemption_dates)
    if coupon_frequency != "unknown":
        product["coupon"]["coupon_frequency"] = coupon_frequency
    if early_redemption_dates:
        product["autocall"]["is_autocallable"] = True
        product["classification"]["is_autocallable"] = True
        product["autocall"]["first_autocall_date"] = early_redemption_dates[0]
    if autocall_frequency != "unknown":
        product["autocall"]["autocall_frequency"] = autocall_frequency


def apply_line_table_heuristics(product: dict[str, Any], lines: list[str]) -> None:
    if not product.get("underlyings"):
        linked_underlying = linked_to_underlying(lines)
        if linked_underlying:
            product["underlyings"] = [{"name": linked_underlying}]

    denomination = money_after_label(
        lines,
        (
            "Denomination / Nominal Amount",
            "Denomination / Calculation Amount",
            "Specified Denomination",
            "Denomination",
            "Calculation Amount",
        ),
    )
    if denomination is not None:
        product["economics"]["denomination"] = denomination

    issue_price_line = value_after_label(lines, ("Issue Price", "Offer Price"))
    if issue_price_line:
        issue_price_lower = issue_price_line.lower()
        if "unit quotation" in issue_price_lower or "per unit" in issue_price_lower:
            product["economics"]["notation"] = "units"
        elif "nominal quotation" in issue_price_lower or "nominal" in issue_price_lower:
            product["economics"]["notation"] = "nominal"

        issue_price_percent = parse_percent(issue_price_line) if "%" in issue_price_line else None
        if issue_price_percent is None:
            issue_price_amount = money_from_text(issue_price_line)
            if issue_price_amount is not None and product["economics"].get("denomination"):
                issue_price_percent = (
                    issue_price_amount / float(product["economics"]["denomination"])
                ) * 100
        if issue_price_percent is not None:
            product["economics"]["issue_price_percent"] = round(issue_price_percent, 6)

    certificates_issued = money_after_label(
        lines,
        (
            "Number of Certificates Issued",
            "No. of Certificates Issued",
            "Certificates Issued",
            "Number of Certificates",
            "Number of Units",
            "Units Issued",
        ),
    )
    if certificates_issued is not None:
        product["economics"]["number_of_certificates"] = certificates_issued
        product["economics"]["notation"] = "units"

    if not product["dates"].get("initial_fixing_date"):
        product["dates"]["initial_fixing_date"] = date_after_label(
            lines,
            ("Initial Fixing Date", "Fixing Date", "Strike Date"),
        )
    if not product["dates"].get("issue_date"):
        product["dates"]["issue_date"] = date_after_label(
            lines,
            ("Initial Payment Date (Issue Date)", "Issue Date", "Settlement Date"),
        )
    if not product["dates"].get("payment_date"):
        product["dates"]["payment_date"] = date_after_label(
            lines,
            ("Initial Payment Date (Issue Date)", "Payment Date"),
        )
    if not product["dates"].get("final_valuation_date"):
        product["dates"]["final_valuation_date"] = date_after_label(
            lines,
            ("Expiration Date", "Final Valuation Date", "Final Fixing Date"),
        )
    if not product["dates"].get("maturity_date"):
        product["dates"]["maturity_date"] = date_after_label(
            lines,
            ("Maturity Date", "Redemption Date"),
        )
    if not product["dates"].get("redemption_date"):
        product["dates"]["redemption_date"] = product["dates"].get("maturity_date")

    if product["coupon"].get("coupon_rate_percent_pa") is None:
        title_coupon_rate = coupon_rate_from_title(lines[:5])
        if title_coupon_rate is not None:
            product["coupon"]["coupon_rate_percent_pa"] = title_coupon_rate
    if product["coupon"].get("coupon_rate_percent_pa") is None and product["economics"].get("denomination"):
        coupon_amount_line = value_after_label(lines, ("Coupon Amount",), max_ahead=2)
        coupon_amount = money_from_text(coupon_amount_line or "")
        if coupon_amount is not None:
            product["coupon"]["coupon_rate_percent_pa"] = round(
                (coupon_amount / float(product["economics"]["denomination"])) * 100,
                6,
            )

    if product["barrier"].get("level_percent") is None:
        kick_in_level = percent_after_label(lines, ("Kick In Level", "Barrier Level"))
        if kick_in_level is not None:
            product["barrier"]["level_percent"] = kick_in_level
            product["classification"]["has_barrier"] = True


def value_after_label(
    lines: list[str],
    labels: tuple[str, ...],
    *,
    max_ahead: int = 4,
) -> str | None:
    for candidate in values_after_label(lines, labels, max_ahead=max_ahead):
        return candidate
    return None


def values_after_label(
    lines: list[str],
    labels: tuple[str, ...],
    *,
    max_ahead: int = 4,
) -> list[str]:
    normalized_labels = tuple(normalize_label(label) for label in labels)
    values: list[str] = []
    for index, line in enumerate(lines):
        normalized_line = normalize_label(line)
        if not any(normalized_line == label for label in normalized_labels):
            continue

        for offset in range(1, max_ahead + 1):
            candidate_index = index + offset
            if candidate_index >= len(lines):
                break
            candidate = lines[candidate_index].strip()
            if candidate:
                values.append(candidate)
                break
    return values


def date_after_label(lines: list[str], labels: tuple[str, ...]) -> str | None:
    for value in values_after_label(lines, labels):
        match = DATE_PATTERN.search(value)
        if match:
            return normalize_date_value(match.group(0))
    return None


def money_after_label(lines: list[str], labels: tuple[str, ...]) -> float | None:
    for value in values_after_label(lines, labels):
        amount = money_from_text(value)
        if amount is not None:
            return amount
    return None


def percent_after_label(lines: list[str], labels: tuple[str, ...]) -> float | None:
    for value in values_after_label(lines, labels):
        if "%" not in value:
            continue
        percent = parse_percent(value)
        if percent is not None:
            return percent
    return None


def money_from_text(value: str) -> float | None:
    match = re.search(r"(?:[A-Z]{3}\s*)?\d[\d,.' ]*(?:\.\d+)?", value)
    if not match:
        return None
    return coerce_number(match.group(0))


def coupon_rate_from_title(lines: list[str]) -> float | None:
    for line in lines:
        match = re.search(r"(?P<value>\d+(?:[.,]\d+)?)\s*%\s*p\.a\.", line, re.IGNORECASE)
        if match:
            return parse_percent(match.group(0))
    return None


def linked_to_underlying(lines: list[str]) -> str | None:
    for line in lines[:20]:
        match = re.search(r"\bLinked to\s+(?P<value>[^\n\r]+)", line, re.IGNORECASE)
        if match:
            return match.group("value").strip()
    return None


def extract_indexed_observation_dates(lines: list[str], index_prefix: str) -> list[str]:
    dates: list[str] = []
    pattern = re.compile(rf"^{re.escape(index_prefix)}\s*=\s*\d+\s*$", re.IGNORECASE)
    for index, line in enumerate(lines):
        if not pattern.match(line.strip()):
            continue
        date_text = first_date_in_lines(lines[index + 1 : index + 5])
        if date_text:
            dates.append(date_text)
    return dates


def first_date_in_lines(lines: list[str]) -> str | None:
    for line in lines:
        match = DATE_PATTERN.search(line)
        if match:
            return normalize_date_value(match.group(0))
    return None


def infer_frequency_from_date_strings(date_strings: list[str]) -> str:
    parsed = [parse_date_value(value) for value in date_strings[:3]]
    parsed = [value for value in parsed if value is not None]
    if len(parsed) < 2:
        return "unknown"

    month_delta = (parsed[1].year - parsed[0].year) * 12 + parsed[1].month - parsed[0].month
    if 1 <= month_delta <= 2:
        return "monthly"
    if 3 <= month_delta <= 4:
        return "quarterly"
    if 6 <= month_delta <= 7:
        return "semi_annual"
    if 11 <= month_delta <= 13:
        return "annual"
    return "custom"


def normalize_label(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)


def infer_coupon_type(text: str, product: dict[str, Any]) -> str:
    if "phoenix" in text:
        return "phoenix"
    if "memory" in text:
        return "memory"
    if "conditional coupon" in text or "coupon trigger" in text:
        return "conditional"
    if "guaranteed coupon" in text:
        return "guaranteed"
    if "floating" in text or "libor" in text or "saron" in text or "euribor" in text:
        return "floating"
    if product["coupon"].get("coupon_rate_percent_pa") is not None:
        return "fixed"
    return "none"


def infer_barrier_type(text: str) -> str:
    if "daily close" in text:
        return "daily_close"
    if "continuous" in text or "continuously" in text:
        return "continuous"
    if "american" in text:
        return "american"
    if "european" in text:
        return "european"
    if "observation" in text or "observed" in text:
        return "discrete"
    return "unknown"


def extract_field_value(text: str, field: FieldSpec) -> Any:
    for pattern in field.patterns:
        match = re.search(pattern, text, field.flags)
        if not match:
            continue

        value = value_from_match(match)
        value = normalize_value(value, field.value_type)
        if value not in (None, ""):
            return value

    return None


def value_from_match(match: re.Match[str]) -> str:
    groupdict = match.groupdict()
    if "value" in groupdict:
        return groupdict["value"]

    for group in match.groups():
        if group:
            return group

    return match.group(0)


def normalize_value(value: str | None, value_type: str = "text") -> Any:
    if value is None:
        return None

    cleaned = " ".join(value.replace("\xa0", " ").split()).strip(" :-;")
    if not cleaned:
        return None

    if value_type == "isin":
        return normalize_isin(cleaned)

    if value_type == "currency":
        return normalize_currency(cleaned)

    if value_type == "date":
        return normalize_date_value(cleaned)

    if value_type == "number":
        return coerce_number(cleaned)

    if value_type == "percent":
        return parse_percent(cleaned)

    return cleaned


def get_missing_required_fields(fields: dict[str, Any]) -> list[str]:
    return calculate_missing_required(fields)
