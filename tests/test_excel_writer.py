from __future__ import annotations

import unittest

from excel_writer import (
    ExcelTemplateError,
    apply_cell_mapping,
    load_template_cell_mapping,
    normalize_cell_reference,
    remove_mapping_sheet,
)


class ExcelWriterTests(unittest.TestCase):
    def test_load_template_cell_mapping_from_field_mapping_sheet(self) -> None:
        book = FakeBook(
            [
                FakeSheet("Output"),
                FakeSheet(
                    "Field Mapping",
                    [
                        ["field_name", "sheet", "cell"],
                        ["identity.isin", "Output", "B2"],
                        ["parties.issuer", "Output", "B3"],
                    ],
                ),
            ]
        )

        mapping = load_template_cell_mapping(book)

        self.assertEqual(mapping["identity.isin"], {"sheet": "Output", "cell": "B2"})
        self.assertEqual(mapping["parties.issuer"], {"sheet": "Output", "cell": "B3"})

    def test_apply_cell_mapping_writes_values_to_target_sheets(self) -> None:
        output = FakeSheet("Output")
        book = FakeBook([output, FakeSheet("Field Mapping")])
        mapping = {"identity.isin": {"sheet": "Output", "cell": "b2"}}

        apply_cell_mapping(book, mapping, {"identity.isin": "DE1234567890"})

        self.assertEqual(output.cells["B2"], "DE1234567890")

    def test_remove_mapping_sheet_deletes_field_mapping_sheet(self) -> None:
        mapping_sheet = FakeSheet("Field Mapping")
        book = FakeBook([FakeSheet("Output"), mapping_sheet])

        remove_mapping_sheet(book)

        self.assertTrue(mapping_sheet.deleted)

    def test_remove_mapping_sheet_requires_output_sheet(self) -> None:
        book = FakeBook([FakeSheet("Field Mapping")])

        with self.assertRaises(ExcelTemplateError):
            remove_mapping_sheet(book)

    def test_normalize_cell_reference(self) -> None:
        self.assertEqual(normalize_cell_reference("$b$12"), "B12")
        with self.assertRaises(ExcelTemplateError):
            normalize_cell_reference("not-a-cell")


class FakeBook:
    def __init__(self, sheets: list["FakeSheet"]) -> None:
        self.sheets = FakeSheets(sheets)


class FakeSheets:
    def __init__(self, sheets: list["FakeSheet"]) -> None:
        self._sheets = sheets
        self.active = sheets[0] if sheets else None

    def __iter__(self):
        return iter(self._sheets)

    def __getitem__(self, name: str) -> "FakeSheet":
        for sheet in self._sheets:
            if sheet.name == name:
                return sheet
        raise KeyError(name)


class FakeSheet:
    def __init__(self, name: str, used_values=None) -> None:
        self.name = name
        self.used_range = FakeUsedRange(used_values)
        self.cells: dict[str, object] = {}
        self.deleted = False

    def range(self, cell: str) -> "FakeRange":
        return FakeRange(self, cell)

    def delete(self) -> None:
        self.deleted = True


class FakeUsedRange:
    def __init__(self, value=None) -> None:
        self.value = value


class FakeRange:
    def __init__(self, sheet: FakeSheet, cell: str) -> None:
        self.sheet = sheet
        self.cell = cell

    @property
    def value(self):
        return self.sheet.cells.get(self.cell)

    @value.setter
    def value(self, new_value) -> None:
        self.sheet.cells[self.cell] = new_value


if __name__ == "__main__":
    unittest.main()
