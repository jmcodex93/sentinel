# Sentinel product readiness — stabilization plan

> Execute the accepted audit/action plan with subagent-driven development, focused reviews and recorded verification. The user authorized implementation on 2026-09-05.

**Goal:** preserve artist data and scene identity, prevent false QC/delivery success, restore live features, and provide a reproducible distribution baseline before expanding the product.

**Architecture:** keep the Python engines, C4D adapters, main-thread queue and React SPA. Tighten contracts at filesystem, document and HTTP boundaries. No new commercial features or generalized framework.

**Reference:** conversation audit of `9b4424e` and the approved four-block action plan; project rules and empirically verified contracts in `CLAUDE.md` (read in full before implementation).

## Global constraints

- Keep existing C4D plugin IDs, stored tag schemas, baseline location identity and legacy imports compatible.
- C4D calls and mutations belong on the main thread. No modal dialogs in HTTP, Timer or MessageData operations. Draw remains read-only.
- Colorspace writes remain restricted to SRGB/RAW. Auto/conflict/foreign are informational; unreadable graphs must never imply verified clean.
- Preserve files on failed writes and reject stale or ambiguous document targets. Do not silently overwrite existing deliveries.
- Keep runtime dependencies within C4D Python's standard library. Preserve native fallbacks.
- Add regression tests exercising real production paths; do not weaken existing assertions. Correct incomplete test fixtures only with explicit explanation.
- Rebuild and include `plugin/web/` with SPA changes. Restart C4D after package/class changes; no reload-based verification.
- No release publication, push, new licensing system, payment feature, telemetry or QC #14 in this iteration.

### Task 1: Durable sidecars and trustworthy Collect

**Ownership:** `notes.py`, `versioning.py`, collect/save portions of `ui/flows.py`, collect job handling in `ui/hub_ops.py`, regression tests. Preserve snapshot portions of flows for Task 4.

- [x] Failpoint tests → writing/replace failures preserve previous notes/history byte-for-byte and clean temporary files.
- [x] Atomic writes following existing manifest/baseline conventions → focused persistence tests pass.
- [x] Version status grammar round trips alphanumeric statuses including leading digits → subsequent numbering and sidecar bases stay shared; read already-generated names correctly.
- [x] Collect collision and manifest failure tests → effective scene, summary and manifest agree; old files stay intact; job reports incomplete/error instead of success if manifest fails.
- [x] Bind queued Collect to its original document/preflight context → switching documents before execution cannot collect another scene under stale QC.

**Interfaces:** ordinary successful Collect result stays compatible; failures expose a clear error and all callers handle it. No new writes before collision guards. No source scene deletion or automatic overwrites.

### Task 2: Honest material QC and gate semantics

**Ownership:** `checks/matgraph.py`, `matgraph_c4d.py`, relevant QC scoring/gate/report adapters and focused tests.

- [x] Reproduce unreadable graph and generic-name sampler→Bump→BRDF cases with full adapter/check paths.
- [x] Preserve scan failure as visible unverified coverage through check, scoring, report and gate; baseline acceptance cannot turn unreadable data into clean.
- [x] Stop inference at semantic utility inputs such as `bumpmap.input` → generic-name sRGB normal is detected under Standard/OpenPBR.
- [x] Prove no false changes for clean materials, informational auto/conflict/foreign results, disabled checks and existing baseline behavior.

### Task 3: Document-safe forms and coherent SPA snapshots

**Ownership:** Notes ops in `ui/web_ops.py`, `ui/reports_dialog.py`, stamp/read adapters where necessary, `web/src/` and tests. Coordinate shared hub/panel files with completed tasks.

- [x] Notes state/submit carry an opaque sidecar context; A→B submit is rejected and draft survives; same-base version changes remain valid. Reject changed underlying notes revisions rather than losing concurrent edits.
- [x] Snapshot and stamp originate in one main-thread dispatch; preserve existing callers with opt-in envelopes if needed.
- [x] Recovery and race tests → first valid stamp after an error triggers reload; late A responses never replace B; one subview cannot mark another's stale snapshot current.
- [x] Hub refresh invalidates metadata/variants for same-path file replacement and newly available resolution siblings, without unbounded polling work.
- [x] Full web tests/typecheck/lint/build → committed payload reflects source.

### Task 4: Restore Snapshot Watch safely

**Ownership:** `snapshots.py`, snapshot portions of `ui/flows.py`, `ui/frame_sync.py` or shared host pump, minimal snapshot status adapter/UI and tests.

- [x] Integration test drives real scheduler from host pump → enabled watch actually processes a new settled snapshot exactly once; backlog is ignored.
- [x] Capture immutable output/context on main thread; slow conversion runs without C4D references on a worker; document changes cannot retarget output.
- [x] Bounded pending work, off/changed-directory behavior and visible failure reporting → no duplicate conversion, blocking modal or repeated failed-file storm.

### Task 5: Distribution and diagnostic boundaries

**Ownership:** installer/Doctor/payload validation, HTTP/runtime error handling, build scripts/config and CI, focused tests. Controller may do this independently alongside one worker.

- [x] Real minimal-package tests → missing index or referenced built assets fail verification; installer and Doctor use consistent requirements.
- [x] Validate source before copying; keep backups/cache/development debris out of distribution; preserve existing installation on rejected source.
- [x] Real queue→HTTP failure test → generic client error and no traceback; logged routes never contain token query strings.
- [x] Restore JS toolchain and establish repeatable Python/web checks and source/build consistency in CI; document platform limits honestly.

### Task 6: Product handoff and final verification

**Ownership:** `README.md`, `ROADMAP.md`, `CLAUDE.md`, installation/testing docs and audit completion record; final build payload.

- [x] Reconcile completed features, active backlog and historical notes; remove incorrect current claims without erasing measured API lessons.
- [x] Record product launch prerequisites based on actual repository evidence: supported C4D/OS matrix, installation/update/rollback verification, third-party attribution and ownership confirmation, support diagnostics.
- [x] Full Python/web/typecheck/lint/build, clean diff check, independent whole-change review and fixes.
- [x] Live C4D verification completed in fresh standalone processes with disposable scenes, preserving the existing GUI documents. Embedded webview/manual regression smoke and broader platform certification remain explicitly deferred in the audit record.
- [x] Record final counts, failures, remaining risks and branch/artifact locations; no claims of Windows or commercial release readiness without evidence.

## Execution rulings

- The accepted conversational plan is the specification; no further approval is needed for reversible implementation or verification.
- Full CLAUDE reading completed by the rules reader in 14 non-truncated segments before the first repository modification.
- Existing installer/Doctor fake payloads omit the SPA; fixture completeness will be corrected without weakening their success/failure assertions (disclosed to the user).
- Final integration authority and tests remain with the controller. Work occurs on `codex/product-readiness` in an isolated worktree.

## Completion record

Implementation and independent review are complete. See `docs/audit/2026-09-05-product-readiness.md` for final command results and exact host/browser coverage. Commercial distribution prerequisites and the remaining host/platform acceptance checklist are not claimed complete.
