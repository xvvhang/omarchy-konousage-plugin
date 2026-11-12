# Validation record

## Harness/account views — 2026-11-12

List-layout correction:
- Harness list has exactly one row per tool and only links the credential for
  the selected AI. Verified live: OpenCode gpt-6.1-sol, Codex gpt-6-astra.
- Account list contains four independent account rows, with no harness grouping
  or account tabs. All plugin-owned text sinks explicitly use PlainText.
- 18 offline tests pass, including selected-provider filtering, unknown selection,
  OpenCode recent model selection and Codex profile overrides.
- Qt 6 qmllint with a temporary `qs` import alias exits 0; dynamic kit property
  warnings remain. Manifest validation passes. Shell restarted; IPC view routing
  works and startup logs have no plugin-specific binding errors.
- Selection reflects OpenCode's last selected model and Codex configuration,
  not every running session or CLI override. Manual visual inspection is pending.

- 14 offline Python tests pass: shared-account deduplication, inactive accounts,
  stale values scoped to account identity, account switching/removal, unsupported
  providers, alternate client credentials, markup-shaped labels, bounded responses,
  quota/balance parsing, expiration, permissions, and redirect refusal.
- Plugin manifest validation passes. Qt 6 qmllint reports no errors, but retains
  unqualified-access warnings in the inherited panel and a var warning in Agent.qml.
- Live ChatGPT quota refresh succeeds for both configured accounts; live DeepSeek
  balance refresh also succeeds. ZAI displays the explicit unsupported status.
- Shell restarted after hot reload retained the old IPC interface; the new
  `view account` route succeeds after restart.
- Manual mouse/keyboard interaction and multi-monitor coverage remain pending.
- The shared PanelHero/Button kit on this system uses Text.PlainText, so labels
  are passed literally (not HTML-escaped, which would show entities to the user).

Checked 2026-10-19 on Omarchy 4.0.5-1, Qt 6.12.0.

- Manifest validation and Qt 6 qmllint: passed for all QML files.
- Four offline Python tests: passed (quota parsing, cache permissions,
  stale fallback, missing credentials, and redirect refusal).
- Running shell: enabled; shell summon/hide calls succeeded.
- No real credentials were read by the test suite; live provider responses
  and credential refresh were not tested.

Full manual click/Escape, multi-monitor behavior, restart, and destructive
uninstall testing remain to be performed before requesting marketplace approval.
The shell log contained duplicate IPC-handler warnings for this plugin (also
seen for built-in panels); these did not prevent the tested shell routes.
