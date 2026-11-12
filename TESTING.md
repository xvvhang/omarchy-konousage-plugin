# Validation record

## QML owner destruction — 1.1.3 / 2026-11-12

- **42 offline tests pass**, including the original collector/input/queue tests.
- Two new tests start the real `supervise` path in a synthetic subprocess and
  directly SIGKILL that supervisor, matching native QProcess destruction rather
  than taking the graceful SIGTERM path. One waits until `collect.refresh` is
  blocked inside an account-query thread; the other waits for a finite CLI which
  has started a fake persistent managed service.
- Linux pidfds verify the worker exits after supervisor death and the finite CLI
  exits after worker death, while the fake persistent service remains alive. Only
  fixture-owned processes are signalled during test cleanup, using pinned pidfds
  to avoid PID-reuse races. Each case then runs a normal supervised fixture
  collection successfully; the previous inventory remains unchanged on owner death.
- Additional tests check parent mismatch rejects target execution, an expired
  startup budget rejects target execution, and a standalone worker with no
  supervising watchdog still terminates a blocked account-thread wait through
  its independent kernel SIGALRM deadline.
- These are real offline process/signal tests, not claims that the test suite
  executed a desktop reload or native Quickshell destruction. No real client,
  credentials or network is used. The new tests require Linux pidfd support.
- Plugin manifest validation and `git diff --check` pass. A separate live
  `python3 -B collect.py` completes successfully with the new worker guards.
- The prior native preview remains representative; no UI layout or asset changed.

## Collector completion prerequisites — 1.1.2 / 2026-11-12

Environment: Omarchy 4.5.0-3, Quickshell 0.3.2.r7.g2b4501a-1, Linux.

- **37 offline tests pass** using `python3 -B -m unittest discover -v`.
  Tests do not read real credentials, invoke OpenCode/Codex, access the network,
  or run desktop commands. Node.js is needed for the optional JS-helper tests.
- Real temporary FIFOs held open are rejected immediately by the descriptor-
  checked input helper, including the Codex auth/config and OpenCode model paths.
  Oversized and post-fstat-growing regular files are capped; regular-file symlinks
  remain supported and FIFO symlinks are rejected.
- Real synthetic CLI workers flooding either stdout or stderr are stopped at
  their byte cap. A stalled CLI is killed/reaped, followed by a successful command.
- A stalled account-query thread is stopped by the whole-invocation supervisor;
  a subsequent supervised fixture collection succeeds and writes the inventory.
  The JS transitions used by Main.qml separately verify that a pending refresh
  is released after code 124 and that the next success clears the failure state.
- A fake persistent service survives collection cancellation while the finite
  CLI stops. A SIGTERM-ignoring worker exercises SIGKILL escalation and the Linux
  parent-death signal still stops its finite CLI. No process groups are killed.
  Registered temporary files are cleaned up on ordinary deadline cancellation.
- Worker failure returns code 1; deadline expiry returns 124. Oversized cache
  serialization cannot replace the last successful inventory.
- Manifest validation passes. Qt 6 qmllint with a temporary `qs` import alias
  exits 0 with no import/syntax/unresolved-type errors; dynamic kit warnings remain.
- Live `python3 -B collect.py` completes successfully using the supervised path.
  This is separate from the offline suite and does use the configured clients.
- `preview.png` has been replaced by native Qt renders of the production
  Harness/Accounts panel using a fixture-only Main.qml, clearly labelled demo data.
  The collector and real account files are never used by the preview helper.
  Native dark and light-surface renders were visually inspected: OpenCode, Codex,
  DeepSeek and ZAI marks load, and monochrome light-surface variants switch.
  This is not a claim of a complete SVG/security or whole-runtime approval.
- Credential/client, runtime dependency and vendored-asset provenance contracts
  are documented in README. Stock install/uninstall is not re-run over this live
  development checkout; maintainer installation/listing/final-state gates remain
  for independent review.

## List header icons — 2026-11-12

- Release 1.1.1 uses compact 20-unit header icons and restores remaining-quota
  progress bars with the 90%-used warning threshold and reset countdowns.
- Added local Omarchy Agents SVGs for OpenCode, DeepSeek and ZAI, reusing the
  existing Codex/ChatGPT and Claude assets. Attribution remains in LICENSE.
- 22 offline tests pass (icon-helper checks require Node.js), including harness
  versus account mapping, unknown/malicious-name fallback, theme luminance,
  candidate asset existence and SVG parsing.
- Manifest validation and Qt 6 qmllint (temporary `qs` alias) exit 0; no import,
  syntax or unresolved-type diagnostics. Dynamic kit-property warnings remain.
- Shell restarted and account-view IPC succeeds, with no icon-load or binding
  errors in the startup log. Manual light/dark visual inspection remains pending.

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
