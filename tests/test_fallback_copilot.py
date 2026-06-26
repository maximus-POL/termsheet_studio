from __future__ import annotations

import unittest

from fallback_copilot import (
    FALLBACK_PROVIDER_NONE,
    FALLBACK_PROVIDER_OPENAI_API,
    FALLBACK_PROVIDER_SELENIUM_COPILOT,
    extract_json_object_text,
    normalize_fallback_provider,
)


class FallbackCopilotTests(unittest.TestCase):
    def test_normalize_fallback_provider_aliases(self) -> None:
        self.assertEqual(normalize_fallback_provider("off"), FALLBACK_PROVIDER_NONE)
        self.assertEqual(normalize_fallback_provider("openai"), FALLBACK_PROVIDER_OPENAI_API)
        self.assertEqual(
            normalize_fallback_provider("copilot"),
            FALLBACK_PROVIDER_SELENIUM_COPILOT,
        )

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
