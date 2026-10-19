# Validation record

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
