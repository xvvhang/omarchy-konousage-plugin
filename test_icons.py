"""Offline checks for bundled icon mapping, theme selection and URL safety."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).parent


@unittest.skipUnless(shutil.which("node"), "Node.js is needed to exercise QML JavaScript helpers")
class IconTests(unittest.TestCase):
    def evaluate(self, expression):
        source = (ROOT / "Icons.js").read_text().replace(".pragma library", "", 1)
        result = subprocess.run(["node", "-e", source + "\nconsole.log(JSON.stringify(" + expression + "));"],
                                check=True, capture_output=True, text=True, timeout=10)
        return json.loads(result.stdout)

    def test_harness_icons_follow_tool_not_selected_ai(self):
        self.assertEqual(self.evaluate('[iconKey("harness", "opencode", "ChatGPT"), '
                                       'iconKey("harness", "codex", "DeepSeek")]'), ["opencode", "codex"])

    def test_account_icons_follow_ai_not_hashed_id(self):
        self.assertEqual(self.evaluate('["ChatGPT", "Claude", "DeepSeek", "ZAI"].map('
            'function(ai) { return iconKey("account", "opaque-account-id", ai) })'),
            ["codex", "claude", "deepseek", "zai"])

    def test_untrusted_names_cannot_become_image_urls(self):
        for value in ('../../secret', 'https://example.invalid/tracker.svg',
                      '<img src="https://example.invalid/tracker">', '__proto__', 'constructor'):
            with self.subTest(value=value):
                quoted = json.dumps(value)
                self.assertEqual(self.evaluate('iconKey("account", "", ' + quoted + ')'), "")
                self.assertEqual(self.evaluate('candidates(' + quoted + ', true)'), [])

    def test_theme_selection_and_bundled_candidates(self):
        self.assertEqual(self.evaluate('lightSurface(1, 1, 1)'), True)
        self.assertEqual(self.evaluate('lightSurface(0, 0, 0)'), False)
        self.assertEqual(self.evaluate('candidates("opencode", true)'),
                         ["assets/opencode-light.svg", "assets/opencode.svg"])
        self.assertEqual(self.evaluate('candidates("zai", false)'), ["assets/zai.svg"])
        paths = self.evaluate('["opencode", "codex", "claude", "deepseek", "zai"].flatMap('
            'function(key) { return candidates(key, true) })')
        for path in paths:
            self.assertTrue((ROOT / path).is_file(), path)
            document = ET.parse(ROOT / path)
            for element in document.iter():
                self.assertNotIn(element.tag.rsplit("}", 1)[-1], ("script", "image", "foreignObject"))


if __name__ == "__main__":
    unittest.main()
