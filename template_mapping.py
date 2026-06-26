from __future__ import annotations

# Fallback cell targets for templates that do not include the Excel-based
# "Field Mapping" sheet. Prefer editing that sheet in templates/upload_template.xlsx.
TEMPLATE_CELL_MAPPING: dict[str, str | dict[str, str | None]] = {
    "issuer": "B2",
    "isin": "B3",
    "currency": "B4",
    "product_type": "B5",
    "issue_date": "B6",
    "maturity_date": "B7",
    "underlying": "B8",
    "nominal_amount": "B9",
    "coupon_rate": "B10",
    "barrier": "B11",
    "observation_frequency": "B12",
}
