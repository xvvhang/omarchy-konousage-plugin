"""Exercise the actual UI queue helpers offline, without desktop commands."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest


@unittest.skipUnless(shutil.which("node"), "Node.js is needed for QML JavaScript transition tests")
class RefreshTests(unittest.TestCase):
    def evaluate(self, script):
        source = Path(__file__).with_name("RefreshState.js").read_text().replace(".pragma library", "", 1)
        result = subprocess.run(["node", "-e", source + "\n" + script], check=True,
                                capture_output=True, text=True, timeout=10)
        return json.loads(result.stdout)

    def test_pending_refresh_released_after_timeout_then_success_clears_failure(self):
        result = self.evaluate('''
const first = request(false);
const queued = request(true);
const timeout = settle(124, 0, queued.queue);
const next = timeout.retry ? request(false) : null;
const success = settle(0, 0, next.queue);
console.log(JSON.stringify({first, queued, timeout, next, success}));
''')
        self.assertTrue(result["first"]["start"])
        self.assertFalse(result["queued"]["start"])
        self.assertTrue(result["timeout"]["retry"])
        self.assertEqual(result["timeout"]["status"], "Collection timed out")
        self.assertTrue(result["next"]["start"])
        self.assertFalse(result["success"]["retry"])
        self.assertEqual(result["success"]["status"], "")

    def test_crash_and_nonzero_failure_settle_without_automatic_retry_loop(self):
        result = self.evaluate('console.log(JSON.stringify([settle(0, 1, false), settle(1, 0, false)]));')
        self.assertEqual(result, [{"status": "Collection failed", "retry": False}] * 2)


if __name__ == "__main__":
    unittest.main()
