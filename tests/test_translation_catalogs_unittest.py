"""Check that shipped catalogs resolve the contexts used by the UI."""

import json
from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ET


UI = Path(__file__).resolve().parents[1] / "display-source" / "carui"


class TranslationCatalogTests(unittest.TestCase):
    def test_current_ui_strings_are_translated_in_their_context(self):
        required = set()
        literal = r'"(?:\\.|[^"\\])*"'
        for path in UI.glob("*.qml"):
            for context, source in re.findall(
                rf"qsTranslate\(\s*({literal})\s*,\s*({literal})\s*\)",
                path.read_text(encoding="utf-8"),
            ):
                required.add((json.loads(context), json.loads(source)))
        for source in re.findall(
            rf"\btr\(\s*({literal})\s*\)",
            (UI / "main.cpp").read_text(encoding="utf-8"),
        ):
            required.add(("CarUiController", json.loads(source)))
        self.assertTrue(required)
        catalogs = list((UI / "translations").glob("*.ts"))
        self.assertEqual(len(catalogs), 5)
        for path in catalogs:
            messages = {}
            for context in ET.parse(path).findall("context"):
                for message in context.findall("message"):
                    messages[(context.findtext("name"), message.findtext("source"))] = message
            for key in sorted(required):
                with self.subTest(catalog=path.name, context=key[0], source=key[1]):
                    self.assertIn(key, messages)
                    translation = messages[key].find("translation")
                    self.assertIsNotNone(translation)
                    self.assertNotIn(translation.get("type"), ("unfinished", "vanished", "obsolete"))
                    text = "".join(translation.itertext())
                    self.assertTrue(text.strip())
                    self.assertEqual(sorted(re.findall(r"%\d+", key[1])),
                                     sorted(re.findall(r"%\d+", text)))


if __name__ == "__main__":
    unittest.main()
