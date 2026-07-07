# Codex Handoff Brief — Post-Render Validation Units U2, U3, U4 (Pure Engine Core)

> **Feature:** Post-Render Validation for the Sentinel Cinema 4D plugin.
> **This brief covers U2, U3, U4 ONLY** — the pure, C4D-free, pytest-able core.
> **Plan of record:** `docs/plans/2026-07-06-001-feat-post-render-validation-plan.md` (U1 gate already closed; see `scratchpad/u1_findings.md`). This brief is **self-contained** — you do not need to read the plan to implement U2–U4.
> **Work branch:** `feat/post-render-validation` (branch off `main`; do NOT commit on `main`). Commit scope: `feat(postrender):`.

---

## 1. Objective

Post-Render Validation is a safety net that audits rendered frames **on disk** after a render finishes, catching silent failures that waste a supervisor's time: missing frames in a sequence, hard-truncated (0-byte / header-only) frames, size-anomalous frames (black / denoiser-failed / crashed), and frames left over from a *previous* render version that partially overwrote the current one (false-green protection).

U2–U4 deliver the **pure engine core** and its test bed — everything that operates on plain filesystem paths and `{frame: (size, mtime)}` dictionaries, with **zero Cinema 4D dependency**, so the whole thing is unit-testable under vanilla `pytest` outside C4D:

- **U2** — deterministic dummy fixtures + the pytest harness that later units consume.
- **U3** — `expected_frames`, `detect_stale_cluster`, `scan_sequence`: enumerate the expected frame set, diff it against disk, detect gaps, hard truncation, and previous-session ("stale") frames via bimodal mtime clustering.
- **U4** — `size_outliers`: SPC (statistical process control) size-anomaly detector over an already-clean population.

All engine code lives in one new module, `plugin/sentinel/postrender.py`; all tests in one new file, `tests/test_postrender.py`.

---

## 2. Scope — IN vs OUT (hard boundary)

### IN (implement these, nothing more)

| Unit | Deliverable |
|---|---|
| **U2** | Dummy frame-sequence fixtures built **in-test** into `tmp_path` (a, b, c, f, g, h — see §5), plus `tests/test_postrender.py` scaffolding incl. the `_make_seq(...)` helper. |
| **U3** | In `plugin/sentinel/postrender.py`: `expected_frames(start, end, step)`, `detect_stale_cluster(mtimes_by_frame, gap_factor=6.0)`, `scan_sequence(folder, prefix, frame_set, ext)`. |
| **U4** | In `plugin/sentinel/postrender.py`: `size_outliers(sizes_by_frame, sigma=3.0)`. |

### OUT (do NOT touch, do NOT implement — these belong to U5/U6/U7)

- **NO `import c4d`** anywhere in `postrender.py` — not top-level, not lazy, not guarded. The module must import cleanly under plain CPython. (U5 is the only unit that touches C4D, and it will live in different functions / call sites.)
- **U5 (C4D scene params):** `build_expected_manifest(doc)`, `resolve_output_template(...)`, `audit_render_folder(doc, folder)`; reading `RDATA_*` params, range-by-mode, token expansion, AOV presence via Redshift, per-Take coverage, `REDSHIFT_AVAILABLE` guard, doc-level fallbacks. **The caller (U5/U6) is what pre-filters the SPC population — U4 itself must NOT filter.** The AOV / multi-Take fixtures (`missing_aov/`, `multi_take/`) belong to **U5** and are built in-test there — do **not** create them here (see §5 note).
- **U6 (report / persistence, pure but not yours):** `build_report(findings)`, `write_report_atomic(path, report)`, `append_render_history(...)`, `render_history_path(doc_path)`. **The cross-check dedup between `zero_byte`/`truncated` and `size_outliers`, and "stale not counted as found in the report", is assembled and *verified* in U6 — do not build a report or a dedup layer in U3/U4.**
- **U7 (thin UI):** the panel button `G.BTN_VALIDATE_RENDER`, dialog, `Command()` branch, `_validate_render_output(doc)`.
- **Do NOT** move the light-group helpers (`_is_lg_active_on_beauty` / `_scan_light_groups`) from `ui/panel.py` to `aovs.py` — that is U5's job.

If a function needs a scene document, a render setting, an AOV, or a Redshift call — it is out of scope. U2–U4 receive **already-resolved** paths, prefixes, and numbers.

---

## 3. House rules (from project `CLAUDE.md` — obey verbatim)

- **EDIT, DON'T CREATE:** Modify existing files instead of creating new versions. *(Exception here: `postrender.py` and `test_postrender.py` legitimately do not exist yet — confirmed absent — so creating exactly those two is correct. Create no others.)*
- **NO HELPER SCRIPTS:** No installation/test/diagnostic scripts. No standalone runners, no `__main__` demo blocks.
- **KEEP IT SIMPLE / NO OVER-ENGINEERING:** Plain functions on dicts. No rolling-window SPC, no config objects, no class hierarchy.
- **MINIMAL DEPENDENCIES:** Standard library only. Allowed: `os`, `re`, `json`, `statistics` and/or `math`. **No numpy, no pandas, no third-party stats.**
- **FALLBACK GRACEFULLY:** A vanishing / permission-denied / empty / nonexistent folder must never raise — return empty / `missing` results (see §6.5).
- **NO FEATURE CREEP:** Exactly the four functions + fixtures. Nothing speculative.
- **Never modify a test to make it pass.** If a spec looks wrong, flag it — don't paper over it.
- **Padding convention:** format-spec (`f"{n:04d}"`) for *emitting*; `re` group parsing for *reading*. **Do NOT use `str.zfill()`** — the repo uses format-spec padding exclusively (`versioning.py:81` `:03d`, `versioning.py:20` regex parse).

> **Fixture-location note (this brief intentionally supersedes the plan's Output Structure):** the plan's "Output Structure" sketches committed `tests/fixtures/postrender/` subfolders. The **real house convention** (verified: `test_baseline.py`, `test_rules.py`, `test_texture_path_helpers.py` all build filesystem trees in pytest's `tmp_path`; `grep tempfile tests/*.py` → none; the only committed fixtures are c4dpy-built `.c4d` oracles) is **in-test construction into `tmp_path`**. Follow the house convention: **do not commit anything under `tests/fixtures/`**; build every dummy sequence in-test. Ignore the untracked `tests/fixtures/backup/` dir entirely.

---

## 4. Setup — imports, running, fixtures

### 4.1 How the test imports the module (Idiom A — pure single-module load)

`postrender.py` is import-time pure, so `tests/test_postrender.py` loads that ONE file directly, exactly like `tests/test_framing.py` / `tests/test_gate.py` do. Use this scaffold verbatim (adapted names):

```python
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POSTRENDER_PATH = ROOT / "plugin" / "sentinel" / "postrender.py"

spec = importlib.util.spec_from_file_location(
    "sentinel_postrender_under_test", POSTRENDER_PATH
)
postrender = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = postrender
spec.loader.exec_module(postrender)
```

- `tests/conftest.py` already inserts `plugin/` onto `sys.path`, but the load above targets the file by absolute path and does not rely on it.
- **Do NOT** use the `sentinel_module` fake-c4d fixture (Idiom B). It exists only for modules that `import c4d`; using it here would mask an accidental `import c4d`. Staying on Idiom A is itself a purity guard.
- **Purity assertion — copy the exact two-line guard from `tests/test_framing.py:30-32` verbatim** (adapted to the postrender module var). Do **not** write a naive `assert "c4d" not in sys.modules` — it FAILS in the full-suite run: `sentinel_module` is `scope="session"` (`conftest.py:222`), installs `sys.modules["c4d"] = _PermissiveModule` (`conftest.py:213`), and an earlier test (`test_baseline_artifacts.py`, alphabetically before `test_postrender.py`) requests it, leaving a fake `c4d` resident that is never removed. The correct guard:

  ```python
  def test_postrender_module_is_pure_python():
      assert "c4d" not in sys.modules or getattr(sys.modules["c4d"], "__name__", "") == "c4d"
      assert not any(name == "c4d" for name in postrender.__dict__)
  ```

### 4.2 Running the tests

- **Canonical command (from the plan):**
  ```
  python3 -m pytest tests/test_postrender.py -q
  ```
- Full-suite sanity (the only form `tests/README.md` documents): `python3 -m pytest tests` — must stay green (no regressions).
- Environment: **Python 3.12.4**, **pytest 9.1.1**. No `pytest.ini` / `pyproject.toml` / CI yaml exists; `tests/conftest.py` is the only config.

### 4.3 Fixtures

- Built **in-test** into pytest's `tmp_path` via a local `_make_seq(...)` helper (see §5). Never write under `tests/fixtures/`.
- Do not add a shared `tests/helpers.py` — the house style is copy-doubles-inline.
- The heavy `.c4d` oracles under `tests/fixtures/` are irrelevant to U2–U4; do not read or produce them.

---

## 5. U2 — Fixtures + harness

**Goal:** dummy folders that exercise every U3/U4 criterion without C4D.
**Requirements satisfied:** R9 (disk logic is pure and pytest-able).
**Test expectation for U2 itself:** none — U2 is infrastructure; its correctness is proven by U3/U4 consuming it.

> **Note:** the plan's fixtures `missing_aov/` (d) and `multi_take/` (e) are **NOT built here** — they exercise AOV-coverage / per-Take logic owned by U5/U6, which build their own `tmp_path` fixtures in their own session. Building them now would produce dead, torn-down folders (they cannot be "shared" across sessions when they live in `tmp_path`), violating KEEP IT SIMPLE / NO FEATURE CREEP. U2 builds only what U3/U4 assert on: **a, b, c, f, g, h**.

### 5.1 The `_make_seq` helper

Define inline in `tests/test_postrender.py`:

```python
def _make_seq(folder, start, end, size_fn, mtime_fn, ext, prefix="beauty", sep="_",
              skip=()):
    """Create a dummy frame sequence on disk.

    folder   : pathlib.Path (created if missing)
    start,end : inclusive frame range (both endpoints written)
    size_fn  : callable(frame:int) -> int  bytes to write for that frame (0 => 0-byte)
    mtime_fn : callable(frame:int) -> float  epoch seconds; set via os.utime
    ext      : extension WITHOUT dot, e.g. "exr"
    prefix   : filename stem before the frame number, e.g. "beauty"
    sep      : separator between prefix and 4-digit frame: "_" (beauty_1001) or "." (beauty.1001)
    skip     : frames NOT to write (to punch a gap)
    Returns the list of written file paths.
    """
```

Behavior it must implement:
- `folder.mkdir(parents=True, exist_ok=True)`.
- For each `frame` in `range(start, end + 1)` and not in `skip`: filename = `f"{prefix}{sep}{frame:04d}.{ext}"`; write `size_fn(frame)` bytes (e.g. `b"\0" * n`); then `os.utime(path, (m, m))` with `m = mtime_fn(frame)`.
- **Padding = 4-digit zero-padded** via `f"{frame:04d}"` (matches U1's `$frame` → 4-digit contract). Fixtures MUST exercise **both** separator styles so the scanner is proven on both: `sep="_"` (`beauty_1001.exr`) and `sep="."` (`beauty.1001.exr`).
- Also drop at least one non-matching file (e.g. a `.txt`) into one fixture folder to prove the scanner ignores foreign extensions.

### 5.2 Fixture subfolders — exact contents

Frame range is **1001–1100 inclusive (100 frames)** unless noted. "median size" ≈ a fixed nominal, e.g. `5_000_000` bytes with small ±noise (deterministic, e.g. `5_000_000 + (frame % 7) * 1000`).

> **Session-mtime rule (mandatory — the anti-false-green tests depend on it):** each mtime *cluster* MUST use **monotonic NONZERO intra-cluster spacing**. Flat/identical timestamps within a cluster make the median inter-frame delta 0, which `detect_stale_cluster` treats as a degenerate single-mtime case (§6.3 step 4) and would **silently defeat** the stale detection. Use e.g. `base + i*60` (60 s/frame) within a cluster.

| # | Folder | Contents |
|---|---|---|
| **a** | `single_complete/` | 1001–1100, all present, sizes ~uniform (small ±noise), **one session**: `mtime = BASE + i*60` (monotonic, 60 s spacing). Style: `sep="_"`. Expected: `missing==[]`, `zero_byte==[]`, `truncated==[]`, `stale==[]`, `size_outliers==[]`. |
| **b** | `gap_truncated/` | 1001–1100 with **frame 1043 absent** (gap, via `skip=(1043,)`), **frame 1050 at 0 bytes**, and **frame 1075 at 512 bytes** (sub-FLOOR → truncated). Single session (`BASE + i*60`). Style: `sep="."` (proves dot-parsing). Also drop a `notes.txt`. Expected: `missing==[1043]`, `zero_byte==[1050]`, `truncated==[1075]`. |
| **c** | `black_frame/` | 1001–1100 all present, uniform sizes **except frame 1057 at <10% of the median** (e.g. median 5_000_000 → 1057 at ~200_000). Single session. Expected: `1057` in `size_outliers`. |
| **f** | `stale_overwrite/` | 1001–1100 all present, **bimodal mtimes**: recent cluster 1001–1049 at `BASE + i*60`; old cluster 1050–1100 at `BASE - 100_000 + i*60` (≈27 h earlier). Nonzero 60 s intra-cluster spacing in BOTH clusters; the ~100_000 s inter-cluster gap ≫ 6× the 60 s median. Expected: `1050..1100` flagged as `stale` and NOT in `found`. |
| **g** | `long_render_spread/` | 1001–1100 all present, mtimes strictly monotonic `BASE + i*300` (5 min/frame ≈ 8 h span), **no gap** > 6× median. One legitimate long render. Expected: `stale == []` (crying-wolf boundary). |
| **h** | `stale_plus_black/` | Old overwrite cluster like (f) (e.g. 1050–1100 old-mtime, and give those a *different* size band, e.g. ~3_000_000, to model different settings) **plus one genuinely black frame from the current session** (e.g. frame 1020 in the recent cluster at ~200_000). Expected downstream: after excluding the stale cluster from the SPC population, the current-session black frame (1020) is STILL caught by `size_outliers`. |

---

## 6. U3 — sequence scan + integrity + session awareness

**Requirements:** R2 (sequence gaps + session-suspect frames), R3 (hard truncation), R9 (pure), KTD8 (cluster-based session detection).
**Depends on:** U2.
**File:** `plugin/sentinel/postrender.py` (create), `tests/test_postrender.py`.

### 6.1 Exact signatures + return shapes

```python
def expected_frames(start, end, step):
    """Canonical expected frame list == list(range(start, end + 1, step))  # end inclusive
    Examples: (1001,1100,1) -> 100 frames; step 2 -> 50; (F,F,1) -> [F].
    """
    # returns: list[int]


def detect_stale_cluster(mtimes_by_frame, gap_factor=6.0):
    """Bimodal-mtime session detector (KTD8).

    mtimes_by_frame : {frame:int -> mtime:float}  (present frames only)
    gap_factor      : a gap larger than gap_factor * median_inter_delta splits sessions.
    Returns the frames belonging ONLY to the OLDEST cluster (stale / previous session),
    sorted ascending. No qualifying gap (uniform / monotonic long render) -> [].
    """
    # returns: list[int]


def scan_sequence(folder, prefix, frame_set, ext):
    """Enumerate frame_set on disk and classify.

    folder    : path to the render folder (str/Path)
    prefix    : filename stem before the frame number (e.g. "beauty"); see 6.4
    frame_set : iterable[int] expected frames (from expected_frames)
    ext       : extension without dot, e.g. "exr"
    Returns dict with EXACTLY these keys, each a sorted list[int]:
      {"found": [...],      # present, real-size, current-session
       "missing": [...],    # in frame_set, no file on disk
       "zero_byte": [...],  # file exists, getsize == 0
       "truncated": [...],  # file exists, 0 < getsize < FLOOR
       "stale": [...]}      # present but in the older mtime cluster
    """
```

### 6.2 Classification rules (precise)

- **Missing:** frame in `frame_set` with no matching file on disk → `missing`.
- **zero_byte:** file exists AND `os.path.getsize(path) == 0` → `zero_byte`. (A 0-byte file is NOT `found`, NOT `missing`, NOT `truncated`.)
- **truncated:** file exists AND `0 < getsize < FLOOR` → `truncated`. `FLOOR` is a module-level constant — a conservative minimum-viable header size. Use `MIN_VIABLE_BYTES = 1024` (document the choice in a comment). This is U3's domain (absolute signal), distinct from U4's relative anomalies. Boundary is strict `<` (a file of exactly `FLOOR` bytes is `found`).
- **stale:** among frames that pass existence + size (i.e. would otherwise be `found`), collect their mtimes and run `detect_stale_cluster`. Frames in the older cluster go to `stale`. **A `stale` frame is removed from `found`.** Encode (comment) that mtime is unreliable on synced/copied folders (Synology conflicted-copy), so stale is a WARN-level signal — U3 only reports the list; severity labeling happens later (U6/U7).
- **found:** exists, `getsize >= FLOOR`, and not in the stale cluster.

### 6.3 `detect_stale_cluster` algorithm (KTD8 — the anti-false-green core)

1. If fewer than 3 present frames → return `[]` (nothing to cluster).
2. Sort the (frame, mtime) pairs by mtime ascending.
3. Compute consecutive deltas between sorted mtimes; take the **median** inter-frame delta.
4. If the median delta is 0 → **all present frames share one identical mtime** (degenerate single-mtime case, not a legitimate bimodal split) → return `[]`. *(This is why §5.2 mandates nonzero monotonic intra-cluster spacing: with real cadence, `median_delta` reflects the intra-session spacing and this branch never eats a true bimodal fixture.)*
5. Find the **largest** gap between consecutive sorted mtimes. If that gap `> gap_factor * median_delta`, it is a session cut: everything **before** the cut is the older cluster → return those frames (sorted ascending). Otherwise → `[]`.
6. Detect only **one** cut in v1 (the single largest qualifying gap); flag only the **oldest** cluster. A uniformly increasing spread yields no qualifying gap → `[]`.
7. **Do NOT** add a `session_mtime` / external-anchor argument — it is dead in v1; detection is self-contained over the set.

### 6.4 Filename parsing (both separator styles)

- `os.listdir(folder)`; case-insensitive extension filter: `name.lower().endswith("." + ext.lower())`.
- Case-insensitively require the stem to start with `prefix`.
- **Extract the frame number as the LAST digit run before the extension** (NOT the first): strip the extension, then `m = re.findall(r"\d+", stem)` → `int(m[-1])`. This tolerates digits inside the prefix (e.g. `shot_010_beauty_1001.exr` → `1001`, not `010`) and handles both `beauty_1001.exr` and `beauty.1001.exr` regardless of the `_`/`.` separator. Skip files with no digit run.
- Map parsed frame → path, then diff against `frame_set`.
- Example call agreeing with `_make_seq`: `scan_sequence(folder, "beauty", expected_frames(1001, 1100, 1), "exr")` matches both separator styles.
- **No `str.zfill()`**; emit padding (if ever needed) with `f"{n:04d}"`.

### 6.5 R10 graceful fallback

- Nonexistent / empty / unreadable folder → every expected frame lands in `missing`; `zero_byte`/`truncated`/`stale`/`found` all `[]`; **no exception**. Guard `os.listdir` and per-file `getsize` in try/except (mirror `collect_scene`'s guard shape at `panel.py:1495`).

### 6.6 Reuse anchors (verified current line numbers — copy the *shape*, not blindly)

- **Folder scan + mtime read:** `plugin/sentinel/ui/panel.py:1602` `_find_latest_exr` — case-insensitive `.lower().endswith('.exr')`, `(path, os.path.getmtime(path))` tuples, never raises. **Caveat:** it picks latest-by-mtime and does **no** frame parsing — add your own.
- **Existence + size guard:** the loop at `plugin/sentinel/ui/panel.py:1495` (`getsize` at `:1499`), inside `collect_scene` (def `:1241`) — `if filepath and os.path.exists(filepath): total_size += os.path.getsize(filepath)` wrapped in `try/except`. **Caveat:** it does NOT detect 0-byte files (a 0-byte file passes `exists()` and adds 0). Your zero-byte / FLOOR checks are new logic; reuse only the `exists()`→`getsize()`-in-try/except shape.
- **Inclusive frame count:** `plugin/sentinel/checks/render.py:443` — `frame_length = frame_end - frame_start + 1`. Your `expected_frames` MUST use `end + 1` to stay consistent with QC #11 (guards there: invalid range at `:407`, a `> 1000` sanity ceiling at `:444`).
- **Padding convention:** `plugin/sentinel/versioning.py:81` uses `:03d` format-spec; `:20` uses `re.compile(r'_v(\d+)...', re.IGNORECASE)`; folder-scan idiom at `versioning.py:149-150`. Format-spec for emit, regex `\d+` for parse.

### 6.7 U3 test scenarios (write every one)

- **(a)** `single_complete/` → `missing==[]`, `zero_byte==[]`, `truncated==[]`, `stale==[]`.
- **(b)** `gap_truncated/` → `missing==[1043]`, `zero_byte==[1050]`, `truncated==[1075]`.
- **Session / overwrite (KTD8):** `stale_overwrite/` → frames `1050..1100` appear in `stale` and NOT in `found`. Anti-false-green proof.
- **Session / long-render boundary (KTD8):** `long_render_spread/` → `stale == []` (monotonic multi-hour spread, no gap → one session).
- **`expected_frames` arithmetic:** `(1001,1100,1)` → length 100; `(1001,1100,2)` → length 50; single-frame `(F,F,1)` → `[F]`.
- **Padding / separator parse:** both `beauty_1001.exr` and `beauty.1001.exr` recognized; a `.txt` file ignored; a name with digits in the prefix parses the trailing run.
- **R10 no-crash:** empty folder and nonexistent folder → all expected frames in `missing`, no exception.
- **`detect_stale_cluster` unit tests (directly, not only via scan):** a bimodal `{frame: mtime}` (nonzero intra-cluster spacing) returns the older cluster; a monotonic uniform one returns `[]`; identical mtimes return `[]`; <3 frames return `[]`.

---

## 7. U4 — SPC size-outlier detector

**Requirements:** R4 (relative size anomalies via control chart), R9 (pure).
**Depends on:** U2 (parallel to U3).
**File:** `plugin/sentinel/postrender.py`, `tests/test_postrender.py`.

### 7.1 Exact signature + return

```python
def size_outliers(sizes_by_frame, sigma=3.0):
    """Flag frames whose size deviates > sigma robust-deviations from the median.

    sizes_by_frame : {frame:int -> size:int}  ALREADY pre-filtered clean population
    sigma          : threshold in robust-deviation units (default 3.0)
    Returns: sorted list[int] of frames flagged as size anomalies.
    """
```

### 7.2 The critical population rule (do NOT violate)

- `size_outliers` receives a **clean dict**: the caller (U5/U6 — NOT U4) has already excluded any frame classified `stale`, `zero_byte`, or `truncated` **before** computing statistics. **U4 does no filtering itself.** Rationale: a stale frame from another version may have a legitimately different size (different settings/resolution) and would contaminate the median/deviation, masking a real black frame or fabricating false outliers.
- Hard truncation is **U3's** domain. U4 owns **relative** anomalies only. Do not re-detect 0-byte / header-only here.

### 7.3 Statistic

- **median** of the sizes; a **robust deviation** — MAD (median absolute deviation) preferred, or population σ (`statistics.pstdev`) acceptable. Stdlib only (`statistics.median`, `statistics.pstdev`, or hand-rolled MAD). If using MAD, scale ×1.4826 so the `sigma` threshold reads as σ-comparable (document the choice).
- Flag frame `f` if `abs(size_f - median) > sigma * deviation`.
- Return flagged frames sorted ascending.

### 7.4 Edge cases (must not crash, must not false-positive)

- **≤ 2 samples** → `[]` (insufficient sample).
- **deviation == 0** (all-equal sizes) → `[]` (guard explicitly; no threshold blow-up).
- **Uniform ± small noise** → `[]` (no false positives).
- Neighborhood = the whole sequence in v1 (rolling window deferred; do not implement it).

### 7.5 U4 test scenarios (write every one)

- **(c)** A frame at <10% of the median (`black_frame/` frame 1057) appears in `size_outliers` with its frame number.
- Uniform sequence (± small noise) → `[]` (assert on `single_complete/` sizes).
- A frame at ~5σ **above** the median → flagged.
- 1–2 frame sequence → `[]` (no crash).
- All-equal sizes (deviation == 0) → `[]` (no division by zero).
- **Clean population (`stale_plus_black/`):** build `sizes_by_frame` with the stale cluster's (differently-sized) frames **excluded**; assert the current-session black frame (1020) IS flagged. Then, as a contrast assert, include the stale frames and show the result **changes** (the black frame is no longer flagged, or the flagged set differs) — proving why pre-filtering matters. (U4 receives whichever dict the test passes; the test itself does the exclusion, standing in for the U5/U6 caller.)
- **Dedup note:** the guarantee that a 0-byte frame does not appear simultaneously in `size_outliers` after report assembly is verified in **U6**, not here. In U4 you simply never receive `zero_byte`/`truncated`/`stale` frames because the caller stripped them.

---

## 8. Acceptance criteria checklist (U2–U4 subset)

- [ ] **(a)** `single_complete/`: `scan_sequence` → `missing==[]`, `zero_byte==[]`, `truncated==[]`, `stale==[]`; `size_outliers` → `[]`.
- [ ] **(b)** `gap_truncated/`: `missing==[1043]`, `zero_byte==[1050]`, `truncated==[1075]`.
- [ ] **(c)** `black_frame/`: `size_outliers` contains `1057`.
- [ ] **(f) session/overwrite:** `stale_overwrite/`: `1050..1100` in `stale`, absent from `found`.
- [ ] **(g) long-render boundary:** `long_render_spread/`: `stale == []`.
- [ ] **(h) clean population:** `stale_plus_black/`: current-session black frame (1020) flagged when stale excluded; result changes (not flagged) when included.
- [ ] `expected_frames` arithmetic: 100 / 50 / 1 for the three cases.
- [ ] Padding/separator: both `beauty_1001.exr` and `beauty.1001.exr` parsed; trailing-digit run used; `.txt` ignored.
- [ ] R10: empty & nonexistent folder → all `missing`, no crash.
- [ ] Edge: ≤2 samples and deviation==0 → `size_outliers == []`, no exception.
- [ ] `postrender.py` contains **no `import c4d`** (module loads via the Idiom-A loader; purity test from `test_framing.py:30-32` passes).

---

## 9. Verification

Run:

```
python3 -m pytest tests/test_postrender.py -q
```

Expected: **all green**; also confirm `python3 -m pytest tests` stays green (no regression). Environment: Python 3.12.4, pytest 9.1.1.

The load-bearing proof is **`stale_overwrite/`**: a partial overwrite (old frames filling the tail of the range) is **not** read as a complete render — the false-green the whole feature exists to prevent. **`long_render_spread/`** is its counterweight, proving the detector doesn't cry wolf on a legitimate long render.

Report the actual pytest output (pass counts) as evidence of done. Never edit a test to force a pass; if a spec seems wrong, flag it.

---

## 10. Review checkpoint (what will be adversarially verified before acceptance)

The reviewer will check, and reject if any fails:

1. **Purity:** `grep -n "import c4d" plugin/sentinel/postrender.py` returns nothing; module loads via Idiom-A with no fake-`c4d` installed; the `test_framing.py:30-32`-style purity test is present and passes in the full suite.
2. **Bimodal correctness:** `long_render_spread/` yields `stale == []` while `stale_overwrite/` isolates only the **older** cluster; `gap_factor` used as `gap > gap_factor * median_delta`; no "older-than-newest-frame" heuristic; fixtures use nonzero monotonic intra-cluster spacing.
3. **Stale ≠ found:** stale frames excluded from `found`.
4. **Clean SPC population:** `size_outliers` does no internal filtering; `stale_plus_black/` proves both the catch (clean population) and the change-on-contamination.
5. **Truncated bucket covered:** a sub-FLOOR frame (1075 @ 512 B) lands in `truncated`, distinct from `zero_byte`; `<` boundary correct.
6. **Dedup deferred:** no report/dedup layer in U3/U4 (that's U6).
7. **Parser:** trailing-digit run; both `_`/`.` separators; foreign extensions ignored; `re` + format-spec, no `str.zfill()`.
8. **No scope leak:** no manifest builder, no atomic writer, no sidecar, no panel button, no `aovs.py` edits, no C4D reads, no `missing_aov/`/`multi_take/` fixtures.
9. **Graceful fallback:** empty/missing/unreadable folder never raises.
10. **Stdlib only:** imports limited to `os`, `re`, `json`, `statistics`/`math`.
11. **Only two files created:** `plugin/sentinel/postrender.py` and `tests/test_postrender.py`; nothing else touched.
