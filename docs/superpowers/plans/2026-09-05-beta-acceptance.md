# Sentinel beta candidate acceptance

Spec: accepted conversation plan, 2026-09-05. Baseline dc52ed4 on codex/product-readiness. Goal: a traceable local candidate that can be installed, used for a complete disposable-scene workflow, and rolled back without losing user data.

## Global constraints

- Preserve main checkout, existing GUI documents, settings, plugin IDs and tag schemas. No publication/push or paid service provisioning.
- Changes occur in the existing isolated worktree. Full CLAUDE.md read was completed centrally in the preceding stabilization task; its main-thread, no-modal HTTP/MessageData and full-restart rules still bind this task.
- Installation requires closed target C4D; do not reload Python plugins or replace a live GUI payload. Prepare reviewable package/backup first if restart needs user input.
- Use stdlib for installation/packaging. No invented platform certification or licensing permissions. Windows acceptance needs a real reachable Windows/C4D host.
- Regression tests must preserve existing assertions. No feature expansion beyond accepted acceptance/candidate work.

### Task 1: Reversible installation and traceable local candidate

Ownership: install.py, new packaging CLI if needed, tests/test_install.py and packaging regressions, installation/release instructions. You are not alone; root owns host acceptance and docs/audit. Do not revert others' changes.

Outcome: normal installer stages and validates before replacing Sentinel; successful updates retain a recoverable prior payload outside C4D's scanned plugin directory. Explicit rollback CLI restores a recorded previous payload, including pre-stabilization versions lacking the newly bundled license/notices, with integrity validation. Copy/rename/verification failure leaves the old installation usable or reports precise recoverable state; no automatic deletion of backups. No touching real installed plugins during implementation. Keep API/CLI backward compatibility.

Candidate builder: produce a local zip containing install.py, plugin/ and concise install/rollback instructions, with commit/build identity and per-file SHA256 manifest. Output is excluded from git, no runtime dependency or commercial release. Build from a known committed source so identity is honest. Reuse actual payload verifier/exclusion rules; refuse incomplete source. Root generates final artifact after integration.

Evidence: meaningful failure-injection regressions for staged copy, activation and rollback, clean install/update/rollback round-trip with old payload byte-for-byte, invalid backup rejection, archive extraction and payload/hash verification. Read task report contract from controller.

### Task 2: Actual host acceptance

Root owns tests/c4d_runner acceptance and isolated GUI exploration. Inspect live state first; preserve original unsaved document. Exercise actual EXR converter, Frame/Pin/Variants/AOV/Undo and production Notes/Collect/Watch in a fresh host; attempt embedded webview with isolated prefs if supported. No unsupported claim that mocks or pure tests certify GUI. Any reproduced bug gets smallest reviewed regression fix.

### Task 3: Review, artifact, Windows handoff

Independent review of new change, full relevant suite/build and actual temporary update/rollback. Commit local changes and generate final archive plus digest. Record exact acceptance evidence and pending host/platform cases. Real Windows unavailable is an explicit blocker to certification, not grounds to install a VM or acquire software. Deliver concise Spanish status with concrete artifact and outstanding action if needed.
