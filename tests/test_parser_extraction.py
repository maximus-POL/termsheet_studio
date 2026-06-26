from __future__ import annotations

import unittest

from parser import parse_product_text
from schema import coerce_number, get_path


class ParserExtractionTests(unittest.TestCase):
    def test_number_parsing_handles_thousands_and_decimals(self) -> None:
        self.assertEqual(coerce_number("EUR 1,000"), 1000.0)
        self.assertEqual(coerce_number("CHF 86.3"), 86.3)
        self.assertEqual(coerce_number("EUR 10,000,000"), 10000000.0)

    def test_ubs_line_table_extraction(self) -> None:
        text = """
6.95% p.a. EUR Express Certificate with Memory
Linked to Carl Zeiss Meditec AG
Issued by UBS AG, Zurich and Basel, Switzerland, acting through its London Branch
Cash or physical settled; Kick In observation at expiry
Valor: 124777728 / ISIN: DE000UBS9WH1 / WKN: UBS9WH
Underlying
Carl Zeiss Meditec AG
Product Details
Denomination / Nominal Amount
EUR 1,000
Issue Price
EUR 1,000 per unit (unit quotation)
Fixing Date
02 February 2023
Initial Payment Date (Issue Date)
09 February 2023
Expiration Date
02 February 2029 (subject to market disruption event provisions)
Maturity Date
09 February 2029 (subject to market disruption event provisions)
Coupon Observation Date(i)
i=1
02 February 2024
09 February 2024
i=2
02 February 2025
10 February 2025
Early Redemption Observation Date(j)
j=1
02 February 2024
09 February 2024
j=2
02 February 2025
10 February 2025
"""

        product = parse_product_text(text)

        self.assertEqual(get_path(product, "identity.isin"), "DE000UBS9WH1")
        self.assertEqual(get_path(product, "economics.denomination"), 1000.0)
        self.assertEqual(get_path(product, "economics.issue_price_percent"), 100.0)
        self.assertEqual(get_path(product, "dates.initial_fixing_date"), "02 February 2023")
        self.assertEqual(get_path(product, "dates.issue_date"), "09 February 2023")
        self.assertEqual(get_path(product, "dates.final_valuation_date"), "02 February 2029")
        self.assertEqual(get_path(product, "dates.maturity_date"), "09 February 2029")
        self.assertEqual(get_path(product, "autocall.first_autocall_date"), "02 February 2024")
        self.assertEqual(get_path(product, "autocall.autocall_frequency"), "annual")
        self.assertEqual(product["review"]["missing_required"], [])


if __name__ == "__main__":
    unittest.main()
