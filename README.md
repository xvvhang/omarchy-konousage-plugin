# AI Usage

User-owned Omarchy bar plugin derived from Omarchy's MIT-licensed agents plugin.

Shows the ChatGPT coding subscription currently signed in to each client: Codex and OpenCode.
Quota percentages and meters show remaining allowance, not consumed allowance.
Click the bar icon to open; click account tabs or use h/l to switch, r to refresh,
Esc to close. Hover reset countdowns for exact local timestamps. At 90% usage,
the icon becomes urgent. Refreshes every five minutes and when opened.

`collect.py` reads the active OpenAI OAuth credential through OpenCode V2's local
`GET /api/credential` API and Codex's `$CODEX_HOME/auth.json` (default ~/.codex).
No credential is copied or written. Expired credentials must be refreshed by their
own client. The OpenCode API command may start its background service if stopped.
Codex OS-keyring-only sign-in is not currently supported.

Queries https://chatgpt.com/backend-api/wham/usage with each account's own bearer
token and account header, with redirects disabled. This internal upstream endpoint
may change. It measures coding quota, not all ChatGPT chat limits. Windows are
labelled from the server's duration, not assumed to always be five hours and a week.

Only sanitized usage records are atomically cached in
`${XDG_STATE_HOME:-~/.local/state}/omarchy/ai-usage/`, with mode 0600.
On failure the panel labels last successful values as stale. Token-level local
statistics are intentionally not merged between the accounts. No OAuth refresh,
account switching, or credential writes are performed by this plugin.

Settings: `refreshIntervalSec` in this widget's shell.json entry.
IPC: `omarchy-shell xvvhang.ai-usage refresh` (also open/close/toggle/next).

To remove from the bar: `omarchy plugin disable xvvhang.ai-usage`.

## Install and remove

Requires Omarchy Quattro, Python 3 (standard library only), and the signed-in
Codex and/or OpenCode V2 clients described above. No privileged setup or installer.

```sh
omarchy plugin add https://github.com/xvvhang/omarchy-ai-usage --enable
omarchy plugin disable xvvhang.ai-usage
omarchy plugin remove xvvhang.ai-usage
```

Removal leaves the sanitized usage cache in the state directory above; client
credentials are never removed. Back up unpushed development changes before removal.

## Validation

From this repository directory on Omarchy Quattro:

```sh
omarchy plugin validate .
/usr/lib/qt6/bin/qmllint -I /usr/share/omarchy/shell ./*.qml
python3 -B -m unittest discover -v
```

Use Qt 6's qmllint, not the Qt 5 executable that may be first on PATH.
MIT licensed; derived components and assets retain Omarchy's attribution in LICENSE.
