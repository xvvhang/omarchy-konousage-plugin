#!/usr/bin/env python3
"""Read current client credentials; cache only account usage, never secrets."""
import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

STATE = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "omarchy/ai-usage"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def credentials(source):
    if source == "opencode":
        proc = subprocess.run(["opencode", "api", "get", "/api/credential"],
                              capture_output=True, text=True, timeout=25)
        if proc.returncode:
            raise ValueError("OpenCode credential API unavailable")
        entries = json.loads(proc.stdout)["data"]
        value = next(e["value"] for e in entries
                     if e.get("integrationID") == "openai" and e.get("active"))
        if value.get("type") != "oauth":
            raise ValueError("OpenCode requires ChatGPT OAuth sign-in")
        if value.get("expires", 0) < time.time() * 1000:
            raise ValueError("OpenCode token expired; use OpenCode to refresh sign-in")
        return value["access"], value["metadata"]["accountID"]
    home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    value = json.loads((home / "auth.json").read_text())["tokens"]
    return value["access_token"], value["account_id"]


def collect(source, name):
    record = {"id": source, "name": name, "ready": True,
              "hasLocalStats": False, "hasPromptStats": False, "limits": [],
              "updatedAt": datetime.now(timezone.utc).isoformat()}
    try:
        token, account = credentials(source)
        request = urllib.request.Request(
            "https://chatgpt.com/backend-api/wham/usage",
            headers={"Authorization": "Bearer " + token,
                     "ChatGPT-Account-Id": account,
                     "User-Agent": "codex-cli", "Accept": "application/json"})
        with urllib.request.build_opener(NoRedirect).open(request, timeout=20) as response:
            data = json.load(response)
        record["tierLabel"] = str(data.get("plan_type", "Subscription"))
        groups = [("", data.get("rate_limit") or {})]
        for extra in data.get("additional_rate_limits") or []:
            groups.append((str(extra.get("limit_name") or "Model") + " · ",
                           extra.get("rate_limit") or {}))
        for prefix, group in groups:
            for key in ("primary_window", "secondary_window"):
                window = group.get(key)
                if not window or window.get("used_percent") is None:
                    continue
                seconds = window.get("limit_window_seconds", 0)
                label = ("Weekly" if seconds == 604800 else
                         "Monthly" if seconds >= 2419200 else
                         str(round(seconds / 3600, 1)) + "h window")
                reset = window.get("reset_at")
                record["limits"].append({"label": prefix + label, "title": prefix + label,
                    "percent": float(window["used_percent"]) / 100,
                    "resetsAt": datetime.fromtimestamp(reset, timezone.utc).isoformat() if reset else ""})
        if not record["limits"]:
            record["usageStatusText"] = "No quota windows reported"
            record["authHelpText"] = "The service did not return quota windows for this account."
    except Exception as error:
        if isinstance(error, urllib.error.HTTPError):
            message = "Usage endpoint HTTP " + str(error.code)
        elif isinstance(error, ValueError):
            message = str(error) if str(error).startswith("OpenCode") else "Invalid usage response"
        else:
            message = "Credentials or endpoint unavailable (" + type(error).__name__ + ")"
        record["usageStatusText"] = "Unable to refresh"
        record["authHelpText"] = message + ". Open the corresponding client to check sign-in."
        try:
            old = json.loads((STATE / (source + ".json")).read_text())
            record["limits"] = old.get("limits", [])
            record["tierLabel"] = old.get("tierLabel", "")
            record["updatedAt"] = old.get("updatedAt", "")
            record["authHelpText"] += " Showing last successful values."
        except (OSError, ValueError):
            pass
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=STATE, prefix=".usage-")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(record, stream)
        os.replace(temporary, STATE / (source + ".json"))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


if __name__ == "__main__":
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda pair: collect(*pair),
                      [("opencode", "OpenCode"), ("codex", "Codex")]))
