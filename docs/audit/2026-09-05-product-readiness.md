# Sentinel product readiness — 2026-09-05

Baseline: v1.38.0, commit `9b4424e`. Stabilization branch: `codex/product-readiness`.
This record distinguishes existing functionality, engineering verification and release prerequisites. It does not declare a commercial release.

## Architecture and current product

Sentinel has a viable product structure: Python engines, C4D adapters, a bounded main-thread request queue and a dockable React SPA. The registry drives 13 QC checks, baseline acceptance and preflight; the delivery engine rescans collected scenes and persists a manifest. Frame, Pin, Variants, project standards, AOV management and render validation are already implemented. Material Graph v1.38 is merged. The native panel was retired in v1.25; old roadmap entries describing its migration are historical.

The stabilization concentrates on data persistence, document identity, truthful QC/Collect results, snapshot scheduling and a complete distributable. QC #14 (declared project assets), complexity thresholds and new commercial features are outside this pass.

## Engineering verification

Before changes: 1,705 Python tests passed; 238 web tests passed once the locked dependencies were installed. The frontend build succeeded but changed committed bundle files, exposing source/output drift. Four existing lint warnings were recorded.

Distribution/HTTP regressions reproduced seven failures before correction. The installer and Doctor now share validation of resources, scene assets, frontend entrypoint and local HTML/CSS dependencies. Invalid sources are rejected before touching an existing installation. Cache/development debris and C4D backups are excluded. Queue failures become generic HTTP errors; logged routes omit query strings. Focused suite: 217 tests passed, including a real queue→HTTP failure. Independent review found the timestamped C4D backup directory case; it was corrected and covered.

CI configuration runs Python tests on Linux/macOS/Windows and web tests, lint, typecheck/build plus committed-artifact parity on Linux. The remote matrix has not been run in this session. Pure tests do not certify C4D or Redshift compatibility.

Data/Collect: 265 focused tests passed after collision, missing-scene, rename-failure, manifest-failure and document-context regressions. Material QC: 161 focused tests passed; unreadable coverage remains outside baseline acceptance and inside the score denominator. Snapshot Watch: 184 focused tests passed, including host message→flow→worker integration, context changes, burst failures and cleanup.

Standalone `c4dpy` matched both frozen scene fixtures with the changed QC code and exited 0 when invoked without the runner's `SystemExit` wrapper. No oracle was changed. C4D emitted existing internal container diagnostics; this is evidence for the fixture checks, not a complete UI/platform certification. The additional acceptance results below exercise the current implementation in a fresh host process.

## Stabilization outcome

- Notes/history writes replace a completed temporary file; failed writes preserve the previous sidecar. Notes forms bind the draft to an opaque sidecar identity and a revision of the exact bytes read. Scene switches, unreadable files and intervening edits reject the submission while retaining the draft. Read/write encoding is explicit; legacy Windows locale sidecars are decoded before migrating on save. Standalone readers used by baseline/post-render/supervisor still work without importing the C4D package.
- Collect rejects an occupied output scene before SaveProject, preserves the effective filename through rescan and manifest, and fails explicitly on missing output, rename or manifest failure. Queued jobs validate the original document and preflight stamp. Actual host acceptance also exposed a missing `get_last_scan_meta` import that previously broke the collected-scene rescan; the production import and a regression now cover it.
- Material QC distinguishes observed violations from unreadable coverage. Baseline acceptance cannot hide a failed scan. Semantic Bump/Displacement inputs stop inference correctly, including generic texture names connected to Standard and OpenPBR materials.
- Panel reads pair their data and stamp in one main-thread dispatch. Independent view channels reject late responses and recover after errors. Hub metadata and resolution siblings refresh with each accepted inventory snapshot, including unchanged asset paths.
- Snapshot Watch runs from the existing MessageData pump. It waits for stable files, ignores initial backlog, captures output context on the main thread and limits conversion to one worker. Failures remain visible across later successful files. Source/destination changes do not redirect work already captured.
- Installer/Doctor share payload validation; the bundled frontend matches source. Third-party notices and the original license accompany the payload. No plugin IDs, tag schemas or commercial licensing behavior changed.

## Final verification and practical limits

| Evidence from this session | Result |
|---|---|
| Full Python suite, system Python 3.12/macOS | 1,759 passed in 18.57s (baseline: 1,705) |
| Web Vitest | 247 passed across 15 files |
| Web lint, TypeScript and Vite build | Passed; previous four lint warnings removed; generated bundle included |
| Frozen C4D fixture oracles | Both matched text and structured JSON; no oracle changes |
| Fresh C4D 2026 `c4dpy` acceptance | Generic normal detection, RAW fix and one-step Undo under Standard/OpenPBR; real SaveProject/rescan/manifest and negative paths; Notes context/revision guards; Watch with real document context — passed |
| Mounted browser UI, mock data | Panel/Render navigation, Hub search and refresh, Notes edit/save passed; no browser warning/error logs |
| Clean temporary installation of the actual payload | Passed shared verifier, license parity and cache/backup exclusion |
| Independent review | Durability, QC, SPA, scheduler and distribution reviewed; reproduced findings corrected with regression coverage |

Reproduce host acceptance with `c4dpy -g_console=true` and the **absolute** path to `tests/c4d_runner/run_product_checks.py`. Use a fresh process. It intentionally refuses to run as a GUI Script Manager action and cleans up its disposable documents/files.

Final local web tools used Node 25.3; CI pins Node 24 and its remote run is still pending. The browser smoke used mocks; it does not certify the embedded C4D webview. Existing GUI documents and the installed plugin were left untouched. Manual webview/document-switch testing after a full restart, Frame/Pin/Variants/AOV regression smoke, real EXR converter integration, network shares, and the Windows/older-C4D matrix remain release acceptance work. Current tests cover converter scheduling and failures but the host Watch acceptance copies a PNG. Notes revision checks are optimistic conflict detection, not a distributed lock between multiple processes. Atomic sidecar replacement protects failed writes, not a guaranteed power-loss transaction.

## Before distributing a commercial product

| Area | Repository evidence | Required evidence before launch |
|---|---|---|
| Ownership and distribution terms | Root LICENSE names Javier Melgar / Yambo Studio, permits use, and restricts redistribution/resale without written permission | Confirm rights for the original code and intended distribution; settle the product license with the relevant owners |
| Bundled abc_retime | AXISFX copyright/author attribution; no redistribution grant found in its bundled files | Record applicable permission/license or remove the dependency from the commercial package |
| Web dependencies and Inter | Locked dependency notices now ship in `plugin/THIRD_PARTY_NOTICES.txt`; Inter OFL is bundled | Recheck the actual compiled bundle at each dependency update; preserve notices |
| Scene rigs and icons | Binary `.c4d` assets and icons are bundled; README credits contributors | Record source/permission for each redistributed asset |
| Plugin IDs | Stable IDs exist for panel, palette, Frame, Pin, Variants and MessageData | Confirm allocation/uniqueness with the relevant registration records; repository checks alone cannot establish it |
| Host support | Historical live tests mainly document C4D 2026/macOS | Verify a named C4D/Redshift/OS matrix, including Windows and any claimed older C4D release |
| Updates and rollback | Source validation prevents an incomplete source replacing an install; copy remains a mirror operation | Test clean install, update, interrupted copy and rollback with closed C4D; retain the previous payload before release updates |
| Support | Doctor and structured local diagnostics exist | Provide a support template with versions, reproducible scene and redacted logs; avoid sharing private project assets |

These are evidence gaps to resolve with the owners, not conclusions about permissions held outside this repository. This pass does not change licenses, add activation, accounts, payment or telemetry.

## Host acceptance checklist

Use disposable scenes, preserve existing open documents, and fully restart C4D after package/class changes. No Reload Python Plugins.

- Notes: open A, edit draft, switch to B, save; B must remain intact and the draft recoverable. Verify same-base version changes and concurrent sidecar edits.
- Collect: valid delivery, occupied scene path, manifest-write failure and document switch/edit while queued; no false completion or wrong scene identity.
- QC: generic-name sRGB texture through Bump into Standard/OpenPBR; unreadable graph must visibly remain unverified and cannot be accepted into clean status.
- Snapshot Watch: backlog ignored, new file settles, converted once, no main-thread conversion freeze, off/directory changes bounded, failures visible.
- Panel/Hub: opening without a document, transient read error, rapid document switching, asset replaced at the same path and newly created resolution sibling.
- Regression smoke: Frame/Pin/Variants, AOV mutation and one-step undo/redo on the changed graph operations.

## Active backlog after stabilization

QC #14 and scene-complexity budgets need their own specifications. Keep the integral undo audit, heavy-material-graph performance measurements, Pin nested-parameter coverage / Display Color / X-Ray / RS shutter offset, and Variants output collisions for identically named anchors visible. These were not all reproduced or resolved by the current pass.

## Delivery of this change

Branch: `codex/product-readiness`. Worktree: `.worktrees/product-readiness`. The original `main` checkout and the running GUI installation remain unchanged. The branch contains the rebuilt plugin payload, regression coverage, CI configuration and this evidence record. No release was published.
