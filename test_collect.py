"""Offline tests: never read actual credentials or call the usage endpoint."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import collect


class UsageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name)
        self.state_patch = patch.object(collect, "STATE", self.state)
        self.state_patch.start()
        self.addCleanup(self.state_patch.stop)

    def read(self):
        return json.loads((self.state / "codex.json").read_text())

    def test_usage_and_cache_permissions(self):
        payload = {"plan_type": "pro", "rate_limit": {"primary_window": {
            "used_percent": 25, "limit_window_seconds": 18000,
            "reset_at": 1800000000}}}
        response = io.StringIO(json.dumps(payload))
        with patch.object(collect, "credentials", return_value=("test-secret", "test-account")), \
                patch.object(collect.urllib.request, "build_opener") as opener:
            opener.return_value.open.return_value = response
            collect.collect("codex", "Codex")
            request = opener.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url, "https://chatgpt.com/backend-api/wham/usage")
        record = self.read()
        self.assertEqual(record["limits"][0]["percent"], 0.25)
        self.assertEqual(record["limits"][0]["label"], "5.0h window")
        self.assertNotIn("test-secret", json.dumps(record))
        self.assertNotIn("test-account", json.dumps(record))
        self.assertEqual((self.state / "codex.json").stat().st_mode & 0o777, 0o600)
        self.assertEqual(list(self.state.glob(".usage-*")), [])

    def test_failure_preserves_stale_usage_without_secrets(self):
        previous = {"limits": [{"percent": 0.4}], "tierLabel": "pro", "updatedAt": "before"}
        (self.state / "codex.json").write_text(json.dumps(previous))
        with patch.object(collect, "credentials", side_effect=RuntimeError("test-secret")):
            collect.collect("codex", "Codex")
        record = self.read()
        self.assertEqual(record["limits"], previous["limits"])
        self.assertEqual(record["updatedAt"], "before")
        self.assertIn("last successful", record["authHelpText"])
        self.assertNotIn("test-secret", json.dumps(record))

    def test_missing_credentials_reports_error(self):
        with patch.object(collect, "credentials", side_effect=FileNotFoundError()):
            collect.collect("codex", "Codex")
        self.assertEqual(self.read()["usageStatusText"], "Unable to refresh")
        self.assertEqual(self.read()["limits"], [])

    def test_redirects_are_refused(self):
        self.assertIsNone(collect.NoRedirect().redirect_request(
            None, None, 302, "redirect", {}, "https://example.invalid"))


if __name__ == "__main__":
    unittest.main()
