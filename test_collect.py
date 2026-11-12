"""Offline tests: never read actual credentials or call the usage endpoint."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import collect


def entry(account="account-one", active=True, label="Personal", provider="openai"):
    return {"id": "credential-" + account, "integrationID": provider, "active": active,
            "label": label, "value": {"type": "oauth", "access": "test-secret",
                                       "metadata": {"accountID": account}}}


class UsageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name)
        for target, kwargs in (
            ("STATE", {"new": self.state}),
            ("opencode_entries", {"return_value": [entry()]}),
            ("codex_entry", {"return_value": entry()}),
            ("current_model", {"return_value": ("openai", "gpt-test")}),
            ("read_usage", {"return_value": {"limits": [{"percent": 0.25}], "tierLabel": "pro", "updatedAt": "before"}}),
        ):
            mock = patch.object(collect, target, **kwargs)
            setattr(self, target, mock.start())
            self.addCleanup(mock.stop)

    def test_shared_account_deduplicated_and_private(self):
        result = collect.refresh()
        self.assertEqual(len(result["accounts"]), 1)
        self.assertEqual(len(result["harnesses"]), 2)
        self.assertEqual(self.read_usage.call_count, 1)
        self.assertEqual(result["accounts"][0]["harnesses"], ["OpenCode", "Codex"])
        raw = (self.state / "inventory.json").read_text()
        for secret in ("test-secret", "account-one", "credential-"):
            self.assertNotIn(secret, raw)
        self.assertEqual((self.state / "inventory.json").stat().st_mode & 0o777, 0o600)
        self.assertEqual(list(self.state.glob(".usage-*")), [])

    def test_distinct_and_inactive_accounts(self):
        self.opencode_entries.return_value = [entry(), entry("account-two", False)]
        result = collect.refresh()
        self.assertEqual(len(result["accounts"]), 2)
        self.assertEqual(len(result["harnesses"]), 2)
        self.assertEqual(result["accounts"][1]["activeHarnesses"], [])

    def test_harness_only_shows_selected_ai(self):
        self.opencode_entries.return_value = [entry(), entry("other", provider="zai")]
        result = collect.refresh()
        self.assertEqual([h["name"] for h in result["harnesses"]], ["OpenCode", "Codex"])
        self.assertEqual(len(result["accounts"]), 2)
        self.assertEqual(result["harnesses"][0]["accountKey"], collect.identity("openai", "account-one"))
        self.current_model.side_effect = lambda source: ("zai", "glm-test") if source == "opencode" else ("openai", "gpt-test")
        result = collect.refresh()
        self.assertEqual(result["harnesses"][0]["accountKey"], collect.identity("zai", "other"))
        self.assertEqual(result["harnesses"][0]["modelName"], "glm-test")
        self.assertEqual(len(result["harnesses"]), 2)

    def test_unknown_current_ai_does_not_pick_any_active_credential(self):
        self.current_model.side_effect = ValueError("unknown")
        result = collect.refresh()
        self.assertEqual(len(result["accounts"]), 1)
        self.assertEqual(len(result["harnesses"]), 2)
        for harness in result["harnesses"]:
            self.assertNotIn("accountKey", harness)
            self.assertEqual(harness["usageStatusText"], "Current AI unknown")

    def test_stale_cache_is_account_scoped(self):
        collect.refresh()
        self.read_usage.side_effect = RuntimeError("test-secret")
        result = collect.refresh()
        account = result["accounts"][0]
        self.assertEqual(account["limits"], [{"percent": 0.25}])
        self.assertEqual(account["updatedAt"], "before")
        self.assertIn("last successful", account["authHelpText"])
        self.assertNotIn("test-secret", json.dumps(result))
        self.opencode_entries.return_value = [entry("new-account")]
        self.codex_entry.return_value = entry("new-account")
        account = collect.refresh()["accounts"][0]
        self.assertEqual(account["limits"], [])
        self.assertNotIn("updatedAt", account)

    def test_removed_accounts_disappear(self):
        collect.refresh()
        self.opencode_entries.return_value = []
        self.codex_entry.side_effect = FileNotFoundError()
        result = collect.refresh()
        self.assertEqual(result["accounts"], [])
        self.assertTrue(all("accountKey" not in h for h in result["harnesses"]))

    def test_unsupported_provider_not_zero(self):
        self.opencode_entries.return_value = [entry(provider="zai")]
        result = collect.refresh()
        unsupported = next(a for a in result["accounts"] if a["aiName"] == "ZAI")
        self.assertEqual(unsupported["limits"], [])
        self.assertIn("not supported", unsupported["usageStatusText"])

    def test_deepseek_balance(self):
        credential = entry(provider="deepseek")
        credential["value"] = {"type": "key", "key": "deepseek-secret"}
        self.opencode_entries.return_value = [credential]
        with patch.object(collect, "read_balance", return_value={"balance": {"remaining": 12.5, "currency": "CNY"}}):
            result = collect.refresh()
        account = next(a for a in result["accounts"] if a["aiName"] == "DeepSeek")
        self.assertEqual(account["balance"]["remaining"], 12.5)
        self.assertNotIn("deepseek-secret", json.dumps(result))

    def test_second_harness_credential_can_recover(self):
        self.read_usage.side_effect = [ValueError("expired"), {"limits": [{"percent": 0.5}]}]
        self.assertEqual(collect.refresh()["accounts"][0]["limits"][0]["percent"], 0.5)

    def test_markup_label_stays_data(self):
        self.opencode_entries.return_value = [entry(label='<img src="https://example.invalid/tracker">')]
        result = collect.refresh()
        self.assertTrue(result["accounts"][0]["name"].startswith("<img"))
        panel = Path(__file__).with_name("Panel.qml").read_text()
        self.assertIn("textFormat: Text.PlainText", panel)
        self.assertIn("text: usageRow.modelData.providerName", panel)
        self.assertNotIn("PanelHero", panel)


class ModelSelectionTests(unittest.TestCase):
    def test_opencode_uses_last_selected_model_not_all_recent_models(self):
        payload = {"recent": [{"providerID": "zai", "modelID": "glm-test"},
                              {"providerID": "openai", "modelID": "gpt-test"}]}
        with patch.object(collect, "read_local", return_value=json.dumps(payload)):
            self.assertEqual(collect.current_model("opencode"), ("zai", "glm-test"))

    def test_codex_profile_overrides_default(self):
        config = 'model = "default"\nprofile = "work"\n[profiles.work]\nmodel = "selected"\nmodel_provider = "custom"\n'
        with patch.object(collect, "read_local", return_value=config):
            self.assertEqual(collect.current_model("codex"), ("custom", "selected"))


class EndpointTests(unittest.TestCase):
    def usage(self, percent=25):
        return {"plan_type": "pro", "rate_limit": {"primary_window": {
            "used_percent": percent, "limit_window_seconds": 18000, "reset_at": 1800000000}}}

    def query(self, payload):
        with patch.object(collect.urllib.request, "build_opener") as opener:
            opener.return_value.open.return_value = io.BytesIO(json.dumps(payload).encode())
            result = collect.read_usage({"access": "test-secret"}, "test-account")
            request = opener.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url, "https://chatgpt.com/backend-api/wham/usage")
            return result

    def test_quota_parsing(self):
        result = self.query(self.usage())
        self.assertEqual(result["limits"][0]["percent"], 0.25)
        self.assertEqual(result["limits"][0]["label"], "5.0h window")

    def test_balance_parsing_does_not_infer_spending(self):
        payload = {"balance_infos": [{"currency": "CNY", "total_balance": "12.50", "topped_up_balance": "10"}]}
        with patch.object(collect.urllib.request, "build_opener") as opener:
            opener.return_value.open.return_value = io.BytesIO(json.dumps(payload).encode())
            result = collect.read_balance({"key": "secret"})
            self.assertEqual(result["balance"], {"remaining": 12.5, "currency": "CNY", "funded": 0})

    def test_invalid_percent_rejected(self):
        for value in (float("nan"), float("inf"), -1, 101):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.query(self.usage(value))

    def test_response_bounded(self):
        with patch.object(collect.urllib.request, "build_opener") as opener:
            opener.return_value.open.return_value = io.BytesIO(b" " * (collect.MAX_RESPONSE + 1))
            with self.assertRaises(ValueError):
                collect.read_usage({"access": "secret"}, "account")

    def test_expired_credentials_do_not_make_requests(self):
        with patch.object(collect.urllib.request, "build_opener") as opener:
            with self.assertRaises(ValueError):
                collect.read_usage({"access": "secret", "expires": 1}, "account")
            opener.assert_not_called()

    def test_redirects_are_refused(self):
        self.assertIsNone(collect.NoRedirect().redirect_request(
            None, None, 302, "redirect", {}, "https://example.invalid"))


if __name__ == "__main__":
    unittest.main()
