#!/usr/bin/env python3
"""Discover harness credentials in memory; persist only account-scoped usage."""
import concurrent.futures
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import time
import tomllib
import urllib.request
from datetime import datetime, timezone
from runtime import MAX_CACHE, bounded_command, read_local, supervise, track_temporary, untrack_temporary

STATE = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "omarchy/ai-usage"
MAX_RESPONSE = 1024 * 1024
PROVIDERS = {"openai": "ChatGPT", "anthropic": "Claude", "deepseek": "DeepSeek", "zai": "ZAI"}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def text(value):
    return str(value or "")[:160]


def identity(provider, account):
    return hashlib.sha256((provider + ":" + account).encode()).hexdigest()[:24]


def opencode_entries():
    output = bounded_command(["opencode", "api", "get", "/api/credential"])
    return json.loads(output)["data"][:128]


def codex_entry():
    home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    auth = json.loads(read_local(home / "auth.json"))
    tokens = auth.get("tokens") or {}
    if tokens.get("access_token") and tokens.get("account_id"):
        return {"id": "codex", "integrationID": "openai", "label": "", "active": True,
                "value": {"type": "oauth", "access": tokens["access_token"],
                          "metadata": {"accountID": tokens["account_id"]}}}
    if auth.get("OPENAI_API_KEY"):
        return {"id": "codex", "integrationID": "openai", "label": "API key", "active": True,
                "value": {"type": "key", "key": auth["OPENAI_API_KEY"]}}
    raise ValueError("No supported sign-in")


def current_model(source):
    """Read the last selected OpenCode model / Codex configured model, not all integrations."""
    if source == "opencode":
        state = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
        recent = json.loads(read_local(state / "opencode/model.json")).get("recent") or []
        if recent:
            return text(recent[0]["providerID"]), text(recent[0]["modelID"])
        raise ValueError("No selected model")
    home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    config = tomllib.loads(read_local(home / "config.toml"))
    profile = (config.get("profiles") or {}).get(config.get("profile"), {})
    provider = profile.get("model_provider", config.get("model_provider", "openai"))
    model = profile.get("model", config.get("model"))
    if not model:
        raise ValueError("No configured model")
    return text(provider), text(model)


def read_usage(value, account):
    if value.get("expires") and value["expires"] < time.time() * 1000:
        raise ValueError("Expired credential")
    request = urllib.request.Request(
        "https://chatgpt.com/backend-api/wham/usage",
        headers={"Authorization": "Bearer " + value["access"],
                 "ChatGPT-Account-Id": account,
                 "User-Agent": "codex-cli", "Accept": "application/json"})
    with urllib.request.build_opener(NoRedirect).open(request, timeout=20) as response:
        raw = response.read(MAX_RESPONSE + 1)
    if len(raw) > MAX_RESPONSE:
        raise ValueError("Oversized response")
    data = json.loads(raw)
    limits = []
    groups = [("", data.get("rate_limit") or {})]
    for extra in (data.get("additional_rate_limits") or [])[:32]:
        groups.append((text(extra.get("limit_name") or "Model") + " · ", extra.get("rate_limit") or {}))
    for prefix, group in groups:
        for key in ("primary_window", "secondary_window"):
            window = group.get(key)
            if not window or window.get("used_percent") is None:
                continue
            percent = float(window["used_percent"]) / 100
            seconds = float(window.get("limit_window_seconds", 0))
            if not math.isfinite(percent) or not 0 <= percent <= 1 or not math.isfinite(seconds):
                raise ValueError("Invalid quota")
            label = ("Weekly" if seconds == 604800 else "Monthly" if seconds >= 2419200
                     else str(round(seconds / 3600, 1)) + "h window")
            reset = window.get("reset_at")
            limits.append({"label": prefix + label, "title": prefix + label, "percent": percent,
                           "resetsAt": datetime.fromtimestamp(reset, timezone.utc).isoformat() if reset else ""})
    return {"tierLabel": text(data.get("plan_type", "Subscription")), "limits": limits,
            "updatedAt": datetime.now(timezone.utc).isoformat()}


def read_balance(value):
    request = urllib.request.Request("https://api.deepseek.com/user/balance",
        headers={"Authorization": "Bearer " + value["key"], "Accept": "application/json"})
    with urllib.request.build_opener(NoRedirect).open(request, timeout=20) as response:
        raw = response.read(MAX_RESPONSE + 1)
    if len(raw) > MAX_RESPONSE:
        raise ValueError("Oversized response")
    balances = json.loads(raw).get("balance_infos") or []
    if not balances:
        raise ValueError("No balance returned")
    # The API currently returns the account's settlement currency. Never sum
    # different currencies or mistake topped_up_balance for lifetime funding.
    balance = balances[0]
    remaining = float(balance["total_balance"])
    currency = balance["currency"]
    if not math.isfinite(remaining) or remaining < 0 or currency not in ("CNY", "USD"):
        raise ValueError("Invalid balance")
    return {"balance": {"remaining": remaining, "currency": currency, "funded": 0},
            "tierLabel": "API balance", "updatedAt": datetime.now(timezone.utc).isoformat()}


def atomic_write(record):
    payload = json.dumps(record, allow_nan=False).encode("utf-8")
    if len(payload) > MAX_CACHE:
        raise ValueError("Usage inventory exceeds byte limit")
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=STATE, prefix=".usage-")
    track_temporary(temporary)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
        os.replace(temporary, STATE / "inventory.json")
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
        untrack_temporary(temporary)


def refresh():
    try:
        previous = json.loads(read_local(STATE / "inventory.json", MAX_CACHE))
    except (OSError, ValueError):
        previous = {}
    old_accounts = {a["id"]: a for a in previous.get("accounts", []) if a.get("id")}
    accounts, candidates, harnesses = {}, {}, []
    sources = (("opencode", "OpenCode", opencode_entries), ("codex", "Codex", lambda: [codex_entry()]))
    for source, name, discover in sources:
        harness = {"id": source, "name": name, "limits": []}
        harnesses.append(harness)
        try:
            selected_provider, selected_model = current_model(source)
            harness.update(aiName=PROVIDERS.get(selected_provider, selected_provider), modelName=selected_model)
        except Exception:
            selected_provider = ""
            harness.update(usageStatusText="Current AI unknown",
                           authHelpText="Choose a model in the client; no current model could be determined.")
        try:
            entries = discover()
        except Exception:
            # Never retain an old harness/account association on discovery failure.
            harness.update(ready=False, usageStatusText="Sign-in unavailable",
                           authHelpText="Open the client to check sign-in; account discovery failed.")
            continue
        for entry in entries:
            provider = text(entry.get("integrationID"))
            value = entry.get("value") or {}
            account = str((value.get("metadata") or {}).get("accountID") or "")
            # Raw keys and account IDs never leave memory.
            fingerprint = account or str(value.get("key") or value.get("access") or source + ":" + str(entry.get("id")))
            key = identity(provider, fingerprint)
            brand = PROVIDERS.get(provider, provider)
            if key not in accounts:
                label = text(entry.get("label")) or brand + " · " + key[:6]
                accounts[key] = {"id": key, "name": label, "aiName": brand,
                                 "ready": True, "limits": [], "harnesses": [], "activeHarnesses": [],
                                 "hasLocalStats": False, "hasPromptStats": False}
                candidates[key] = []
            record = accounts[key]
            if name not in record["harnesses"]:
                record["harnesses"].append(name)
            candidates[key].append((provider, value, account))
            if entry.get("active"):
                if name not in record["activeHarnesses"]:
                    record["activeHarnesses"].append(name)
                if provider == selected_provider:
                    harness["accountKey"] = key
        if selected_provider and "accountKey" not in harness:
            harness.update(usageStatusText="Current account unavailable",
                           authHelpText="No active credential was found for the selected AI.")

    def query(key):
        record = accounts[key]
        supported = [(p, v, a) for p, v, a in candidates[key]
                     if (p == "openai" and v.get("type") == "oauth" and a)
                     or (p == "deepseek" and v.get("type") == "key" and v.get("key"))]
        if not supported:
            record.update(usageStatusText="Usage lookup not supported",
                          authHelpText="This credential has no supported usage API yet. Usage is unknown, not zero.")
            return
        for provider, value, account in supported:
            try:
                record.update(read_balance(value) if provider == "deepseek" else read_usage(value, account))
                if not record["limits"] and not record.get("balance"):
                    record.update(usageStatusText="No quota windows reported",
                                  authHelpText="The service did not return quota windows for this account.")
                return
            except Exception:
                pass
        record.update(usageStatusText="Unable to refresh",
                      authHelpText="Check sign-in and network in the client. No credentials were refreshed.")
        old = old_accounts.get(key, {})
        if old.get("limits") or old.get("balance"):
            for field in ("limits", "balance", "tierLabel", "updatedAt"):
                if field in old:
                    record[field] = old[field]
            record["authHelpText"] += " Showing last successful values for this account."

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(query, accounts))
    result = {"schemaVersion": 2, "accounts": list(accounts.values()), "harnesses": harnesses}
    atomic_write(result)
    return result


if __name__ == "__main__":
    # os._exit avoids multiprocessing's implicit unbounded atexit joins after
    # escalation. The parent holds no secrets and writes no cache on failure.
    try:
        code = supervise(refresh)
    except BaseException:
        code = 1
    os._exit(code)
