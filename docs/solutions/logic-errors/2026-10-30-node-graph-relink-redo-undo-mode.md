---
module: textures (apply_texture_path_change), hub_ops relinks
tags: [undo, redo, maxon, node-graph, redshift, transaction, c4d-api]
problem_type: api-behavior
---

# Redo restored only one map of a Hub relink (W8, Windows round 7)

**Symptom.** Copy into project relinked 18 maps in 2 materials in one gesture. One Cmd+Z restored all 18, but Redo restored **1**, and a second Redo did nothing. Reproduced on macOS with 3 maps in one material: Redo restored 1/3.

**Cause, measured in C4D 2026.304.** `apply_texture_path_change` writes each RS/Arnold port in its own `graph.BeginTransaction(user_data)` with `UndoMode = UNDO_MODE.ADD`, inside the caller's `StartUndo`/`EndUndo`. With `ADD`, each transaction adds its own entry to the step: Undo reverts them all, but **Redo replays only the first**. The per-sampler `AddUndo(UNDOTYPE_CHANGE, material)` was not the cause: with or without it, `ADD` gave the same result.

| Transaction mode (6 maps, 2 materials, one bracket) | Undo | Redo |
|---|---|---|
| `ADD`, with or without `AddUndo` per map or per material | correct | 1/6 per port; 3/6 when grouped per material |
| default (no user data) | only the last write | — |
| `START` | 2 steps | — |
| **`NONE` + `AddUndo(UNDOTYPE_CHANGE, material)` before each write** | correct, one step | **6/6** |
| `NONE` without `AddUndo` | — | 3/6 (the snapshot is what carries redo) |

**Fix.** `UNDO_MODE.NONE` in the relink transaction. The material snapshot, which includes its node graph, carries undo and redo; the batch stays one Cmd+Z.

**Tests.**
- `tests/test_texture_relink_undo.py` pins the order: `AddUndo(CHANGE, host)` → transaction with `NONE` → `SetPortValue` → `Commit`. Mutation to `ADD` makes it fail.
- `tests/c4d_runner/run_udim_checks.py::copy_redo_many_maps` covers 6 maps in 2 materials: Cmd+Z, Redo, Cmd+Z. It fails on v1.43.2 and passes with the fix.

**Open.** `matgraph_c4d._undo_join_user_data` (Material Graph fixes) still uses `ADD` across several transactions per batch, so the same Redo loss is likely there. Not measured yet.
