---
module: Asset Hub (bridge/hub.py payload, web HubPage + lib/hubTable + lib/hubOwner)
tags: [hub, selection, undo, redo, identity, spa]
problem_type: logic-error
---

# Hub clicks right after an Undo/Redo lost the selection (R4/R5, Windows round 8)

**Symptom (Windows 11 + C4D 2026.4.0, v1.43.3).** Right after Ctrl+Z / Ctrl+Y of a Copy into project:
- quick row clicks gave "That asset is no longer in the scene." for an asset still in the scene, and one "The scene is still updating" toast per click;
- Shift+click and Ctrl+click were ignored ("1 selected") for about 5 s.

**Cause.** A Hub row's `key` is its canonical path (`assets.merge_inventories`), and Undo/Redo of a relink rewrites the path of every row. The clicks were made on the list the refresh then replaced:
- `selectOwner` refreshed on `scene_changed` and retried with the **old** key, so the server answered `unknown key`;
- the Shift anchor and the selection kept the old keys, so `applySelection` fell back to a single row, and "N selected" counted keys no row showed.

Reproduced on macOS + C4D 2026.304 with 1.43.3 by opening the Hub in a browser (Shift and Cmd clicks work there; background clicks on the C4D panel carry no modifiers). After an Undo, Shift+click gave "1 selected" instead of 4. A click on the old list went `scene_changed` → refresh → `unknown key` → toast.

**What stays the same across Undo/Redo** (measured, 2 materials × 4 UDIM maps; Copy into project → Undo → Redo → Undo):
- the key: changes at every step (`lib/…` ↔ `tex/…`);
- the owners: identical for every sampler of a material (`Moss · material · path`), so they don't tell rows apart;
- the scan order of `scan_all_texture_paths`: identical in all 5 states. It is not creation order (Metalness before BaseColor), but it doesn't change between reads.

**Fix (branch `fix/hub-clicks-after-undo`).**
- The payload carries `slot` = `tex:<tex_idxs>`.
- On every refresh the SPA maps old keys to new ones by slot (`carriedKeys`), but only when every slot keeps its owners. A material added or removed shifts the scan positions, and then nothing is carried, so a selection never moves to another row.
- The selection, the Shift anchor and an alias table (for clicks that left from the old list) follow the moved keys; keys no longer present are dropped.
- "The scene is still updating" shows once per 5 s window (`noticeGate`).

Verified live with the new build: after the Undo the selection stayed on its row, Shift+click gave 4 and Cmd+click 5, and a click on the old list retried with the carried key and selected the material with no toast.

**Found on the way, not fixed:** selecting a **different** material with `doc.SetActiveMaterial` between an Undo and a Redo empties the Redo stack. A Hub row click (`hub/select_owner`) does exactly that. Scanning, `EventAdd`, re-selecting the active material and `SetActiveObject(None)` don't.
