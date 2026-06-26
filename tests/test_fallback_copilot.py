from __future__ import annotations

import unittest

from fallback_copilot import extract_json_object_text


class FallbackCopilotTests(unittest.TestCase):
    def test_extract_json_object_text_from_markdown_response(self) -> None:
        response = """```json
{"identity": {"isin": "DE1234567890"}}
```"""

        self.assertEqual(
            extract_json_object_text(response),
            '{"identity": {"isin": "DE1234567890"}}',
        )

    def test_extract_json_object_text_ignores_surrounding_text(self) -> None:
        response = 'Here is the JSON: {"a": {"b": "}"}} done'

        self.assertEqual(extract_json_object_text(response), '{"a": {"b": "}"}}')


if __name__ == "__main__":
    unittest.main()
