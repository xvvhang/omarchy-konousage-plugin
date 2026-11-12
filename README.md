# Konousage

Part of **Konochi**, a personal Omarchy plugin series by Alec Xu.

User-owned Omarchy bar plugin derived from Omarchy's MIT-licensed agents plugin.

Two list views: **Harness** has one row per tool (OpenCode / Codex), showing
only its currently selected AI and the corresponding account's quota or balance.
**Accounts** lists each discovered account's usage, including saved inactive accounts;
it does not group by harness. There are no per-account tabs or detail pages.
Harness rows use the tool name as the primary title and AI/model as the subtitle.
Account rows use AI plus account label as the primary title (to distinguish
multiple accounts for the same AI), and list all associated harnesses underneath.
List headers include bundled brand icons, following Omarchy Agents: harness icons
for OpenCode/Codex and AI icons for ChatGPT/Claude/DeepSeek/ZAI accounts. Monochrome
marks adapt to light/dark popup surfaces; unknown brands use the generic AI glyph.
Icons are local assets only and never trigger network requests. Omarchy-derived
assets retain the attribution in LICENSE.
Compact 20-unit icons accompany each header. Quota windows retain remaining-allowance
progress bars and reset countdowns, highlighting usage at or above 90%; balance-only
accounts show amounts without inferring a total allowance.
The same ChatGPT account shared across clients appears once in Accounts and is
queried once per refresh. Harness entries show shared account quota, **not** usage
attributed to that tool. OpenCode's selection is read from the first recent model
in `${XDG_STATE_HOME:-~/.local/state}/opencode/model.json` (the most recently selected
model across clients). Codex uses `$CODEX_HOME/config.toml`, including the selected
profile's model/provider overrides. This is not per-window live session tracking:
concurrent sessions can use different models, and Codex CLI model overrides are
not inferred. If selection cannot be determined, usage is shown as unknown rather
than falling back to every configured provider.
Account labels come from OpenCode; a short stable fingerprint distinguishes duplicates.
Other AI providers/API-key credentials are listed with an explicit unsupported
status, not a misleading zero. Currently supports ChatGPT OAuth quotas and
DeepSeek API-key balances (not historical spending). ZAI and other providers are
listed but their usage lookup is not yet implemented. Different API keys cannot
be identified as belonging to the same billing account, so they remain separate.
Quota percentages and meters show remaining allowance, not consumed allowance.
Click the bar icon to open; select Harness/Accounts, h/l or v to switch views,
j/k or scroll to move through the list, r to refresh, Esc to close. At 90% usage,
the icon becomes urgent. Refreshes every five minutes and when opened.

`collect.py` reads stored credentials through OpenCode V2's local
`GET /api/credential` API and Codex's `$CODEX_HOME/auth.json` (default ~/.codex).
Credentials are held in memory only and never persisted by the plugin. Expired credentials must be refreshed by their
own client. The OpenCode API command may start its background service if stopped.
Codex OS-keyring-only sign-in is not currently supported.

## Preview

![Native Konousage Harness and Accounts list views with compact brand icons, remaining-quota meters and multiple associated harnesses; synthetic demo data](preview.png)

The preview renders the production QML with synthetic account data, not real
credentials. Reproduce on an Omarchy Wayland desktop with
`python3 -B tools/render_preview.py` (development-only: ImageMagick and Fontconfig).
Only the data component is substituted; the panel and SVGs are rendered by Qt.
Use `--light --output /tmp/opencode/konousage-light.png` to exercise light-surface icon variants.

## Credentials, network access, and caching

Queries https://chatgpt.com/backend-api/wham/usage with each account's own bearer
token and account header, with redirects disabled. This internal upstream endpoint
may change. Also queries the documented https://api.deepseek.com/user/balance
endpoint for DeepSeek API keys, with the same timeout, size bound and redirect refusal.
ChatGPT usage measures coding quota, not all ChatGPT chat limits. Windows are
labelled from the server's duration, not assumed to always be five hours and a week.

Only sanitized usage records and display labels are atomically cached in
`${XDG_STATE_HOME:-~/.local/state}/omarchy/ai-usage/inventory.json`, with mode 0600.
Raw account IDs and keys are replaced by one-way fingerprints. Legacy per-client
cache files are ignored. Discovery failure clears the old client/account association;
stale quota is reused only after identifying the exact same account.
On failure the panel labels last successful values as stale. Token-level local
statistics are intentionally not merged between the accounts. No OAuth refresh,
account switching, or credential writes are performed by this plugin. Cross-device
transcript syncing is not used: these are account quotas, not local token counts.

## Collector lifecycle and input contracts

- Each invocation runs a finite worker under a **45-second wall-clock supervisor**,
  including model discovery, credential/config/cache reads, all network jobs and
  the atomic cache write. Cleanup has a separate maximum one-second budget:
  terminate the worker, then escalate to SIGKILL if it does not settle.
- The worker kills/reaps its own finite CLI by PID on cancellation. An exec shim
  sets Linux `PR_SET_PDEATHSIG` on that CLI, so even a forced worker kill cannot
  leave it running. No process-group signals are used. The kernel clears the
  parent-death setting on fork; OpenCode's intentionally persistent managed
  service is not terminated by the collector.
- CLI stdout is capped at 1 MiB and stderr at 64 KiB **while produced**, drained
  together via nonblocking descriptors with a 25-second CLI deadline. stderr is
  discarded, never logged. This bounds this plugin's buffers; the native
  `opencode api` client itself buffers its HTTP response internally.
- All credential, model and config inputs use `O_NONBLOCK | O_CLOEXEC`, then
  `fstat` on the opened descriptor to accept only regular files. Reads are
  bounded to 1 MiB (4 MiB for the usage inventory), including a file growing
  after `fstat`. Symlinks to regular files are supported; FIFOs/devices/directories
  are rejected. No path-only type check is relied upon.
- Successful inventory writes are size-checked before atomic replacement. Whole
  worker failures leave the previous inventory intact, exit with a nonzero code
  (124 for the deadline), and label displayed values as cached with the current
  account association unconfirmed. A queued refresh is released on process exit;
  a later success clears the error. No credential-bearing exception is logged.

### Client and dependency contract

Runtime requires Linux/Omarchy Quattro, Quickshell and Python **3.11+**, including
the standard-library `tomllib`, `multiprocessing` (Linux fork), `selectors`,
`ctypes`/system libc and HTTPS certificate store. No pip dependencies or custom
installer are required. Node.js is only used by optional icon/refresh-helper tests.

OpenCode must be on PATH. Its V2 `opencode api get /api/credential` command handles
service discovery/authentication and may start or recover its managed service.
The expected response is `{data: [{id, integrationID, label, active, value}]}`;
OAuth values use `access`, optional `expires` (milliseconds) and
`metadata.accountID`, and API-key values use `type: "key"` and `key`.
The endpoint returns stored secrets, including inactive entries, into the finite
worker's memory. The plugin never activates credentials or refreshes OAuth.
Native API behavior was cross-referenced to OpenCode v2.2.7,
`fedc6f208aa2bd54c1019227214568083f6380ad`, and the installed service OpenAPI
schema; this is a client contract, not a claim of a complete upstream audit.

Codex must use file-based `$CODEX_HOME/auth.json` (default `~/.codex`) with
`tokens.access_token`/`tokens.account_id`, or `OPENAI_API_KEY` (listed but no
ChatGPT quota lookup). The selected `config.toml` profile overrides root
`model`/`model_provider`. OS-keyring-only auth, environment-only credentials,
custom provider endpoints and per-invocation model overrides are not inferred.
Unsupported/missing inputs are shown explicitly, not as zero usage.

Vendored SVGs come from Omarchy's `shell/plugins/agents/assets/` (OpenCode,
Codex/ChatGPT, Claude, DeepSeek, ZAI and the inherited Fireworks asset). They
remain local, use fixed allowlisted paths and retain Omarchy attribution in
LICENSE. No external image/font URL is constructed from account text.

Settings: `refreshIntervalSec` in this widget's shell.json entry.
IPC: `omarchy-shell konochi.konousage refresh` (also open/close/toggle/next),
`omarchy-shell konochi.konousage view account` (or `harness`). `next` scrolls the list.

To remove from the bar: `omarchy plugin disable konochi.konousage`.

## Install and remove

Requires Omarchy Quattro, Python 3.11+ (standard library only), and the signed-in
Codex and/or OpenCode V2 clients described above. No privileged setup or installer.

```sh
omarchy plugin add https://github.com/xvvhang/omarchy-konousage-plugin --enable
omarchy plugin disable konochi.konousage
omarchy plugin remove konochi.konousage
```

Removal leaves the sanitized usage cache in the state directory above; client
credentials are never removed. Back up unpushed development changes before removal.

## Validation

From this repository directory on Omarchy Quattro:

```sh
omarchy plugin validate .
python3 -B -m unittest discover -v
```

Use Qt 6's qmllint, not the Qt 5 executable that may be first on PATH.
For standalone qmllint, expose `/usr/share/omarchy/shell` as `qs` via a symlink
inside a temporary import directory, then pass `-I` that directory. This supplies
the namespace Quickshell normally creates. Dynamic kit-property warnings may remain.
MIT licensed; derived components and assets retain Omarchy's attribution in LICENSE.
