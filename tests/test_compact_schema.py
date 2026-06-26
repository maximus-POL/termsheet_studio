from __future__ import annotations

import unittest

from schema import (
    SchemaValidationError,
    create_empty_product,
    finalize_compact_product,
    generate_lifecycle_events,
)


def valid_product() -> dict:
    product = create_empty_product("sample.pdf")
    product["identity"]["product_name"] = "Autocallable Note on SMI"
    product["identity"]["isin"] = "CH1234567890"
    product["parties"]["issuer"] = "UBS AG"
    product["classification"]["product_family"] = "autocallable"
    product["classification"]["asset_class"] = "index"
    product["classification"]["is_autocallable"] = True
    product["economics"]["issue_currency"] = "CHF"
    product["economics"]["denomination"] = 1000
    product["economics"]["issue_price_percent"] = 100
    product["dates"]["initial_fixing_date"] = "2026-01-02"
    product["dates"]["issue_date"] = "2026-01-09"
    product["dates"]["final_valuation_date"] = "2027-01-02"
    product["dates"]["maturity_date"] = "2027-01-09"
    product["underlyings"] = [{"name": "SMI Index"}]
    product["autocall"]["is_autocallable"] = True
    product["autocall"]["first_autocall_date"] = "2026-04-02"
    product["autocall"]["autocall_frequency"] = "quarterly"
    product["autocall"]["autocall_trigger_percent"] = 100
    return product


class CompactSchemaTests(unittest.TestCase):
    def test_validation_accepts_valid_compact_product(self) -> None:
        product = finalize_compact_product(valid_product())

        self.assertEqual(product["review"]["status"], "extracted")
        self.assertEqual(product["review"]["missing_required"], [])

    def test_validation_rejects_unknown_enum_values(self) -> None:
        product = valid_product()
        product["classification"]["product_family"] = "made_up_family"

        with self.assertRaises(SchemaValidationError):
            finalize_compact_product(product)

    def test_autocall_at_maturity_frequency_normalizes_to_unknown(self) -> None:
        product = valid_product()
        product["autocall"]["autocall_frequency"] = "at_maturity"

        product = finalize_compact_product(product)

        self.assertEqual(product["autocall"]["autocall_frequency"], "unknown")

    def test_missing_required_sets_review_required(self) -> None:
        product = valid_product()
        product["parties"]["issuer"] = None

        product = finalize_compact_product(product)

        self.assertEqual(product["review"]["status"], "review_required")
        self.assertIn("parties.issuer", product["review"]["missing_required"])

    def test_lifecycle_generation_creates_minimum_events(self) -> None:
        product = finalize_compact_product(valid_product())
        event_types = {event["event_type"] for event in generate_lifecycle_events(product)}

        self.assertTrue(
            {"issue", "initial_fixing", "final_valuation", "maturity", "redemption"}.issubset(
                event_types
            )
        )

    def test_autocall_lifecycle_generation(self) -> None:
        product = finalize_compact_product(valid_product())
        events = generate_lifecycle_events(product)
        autocall_events = [
            event for event in events if event["event_type"] == "autocall_observation"
        ]

        self.assertGreaterEqual(len(autocall_events), 2)
        self.assertTrue(all(event["status"] == "scheduled" for event in autocall_events))

    def test_streamlit_facing_object_has_required_sections(self) -> None:
        product = finalize_compact_product(valid_product())

        for section in (
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
        ):
            self.assertIn(section, product)


if __name__ == "__main__":
    unittest.main()
