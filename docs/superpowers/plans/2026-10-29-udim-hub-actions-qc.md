# UDIM segunda entrega — plan de implementación

> Ejecución inline en la sesión que escribió el spec (aprobado por el usuario el 2026-10-29). Pasos `tarea → verificación`, como pide `CLAUDE.md`.

**Objetivo:** las cuatro acciones del Hub trabajan por tesela y el QC #14 avisa de las teselas sin textura.
**Spec:** `docs/superpowers/specs/2026-10-29-udim-hub-actions-qc-design.md`

## Restricciones globales

- Motor puro (sin `import c4d`) con pytest. El adaptador C4D es fino.
- Ninguna op del SPA abre un modal. Un `StartUndo`/`EndUndo` por gesto. El servidor re-deriva las teselas del disco.
- Los tests existentes no se tocan, salvo los cuatro de la negativa v1.42 que el usuario aprobó sustituir.
- Con cada cambio en el SPA se reconstruye `plugin/web/`.
- pytest: `PYTHONDONTWRITEBYTECODE=1 uv run --no-project --python 3.11 --with pytest==8.4.2 python -m pytest -q -p no:cacheprovider` (baseline: 1961 passed, 2 skipped).

## Tareas

1. **`udim.py`: `tile_of_uv`, `tiles_of_polygons`, `shrunk_pattern`.** → tests en `tests/test_udim.py` (fila 1011 = v ∈ [−1, 0], fuera de rango → None, triángulo, `poly_indices`, idempotencia de `shrunk_pattern`, nombre LOK con espacios).
2. **Shrink por tesela.** En `assets.shrink_plan` una fila UDIM pasa a ser `{"udim_tiles": [{"tile", "path", "target_path", "width", …, "copy_only"}]}`, con la meta por tesela, y en `hub_ops` (`_op_hub_shrink_start` re-deriva las teselas y lee la meta de cada una; `_run_shrink_for_job` hace todo o nada y relink al patrón). → test del plan (pytest puro) + test de op con `tmp_path`, el job ejecutado y el undo contado.
3. **Copy into project por tesela.** `assets.copy_plan` expande las teselas y `_op_hub_copy_into_project` aplica colisión por tesela y relink a `tex/<patrón>`. → tests puro + op.
4. **Switch resolution por tesela.** `assets.find_res_variants` pliega el listado a patrones y añade `tiles`; `_op_hub_switch_res` salta con `incomplete_tiles`; `hub/variants` saca el px de la base de su primera tesela. → tests puro + op.
5. **Collect + manifiesto.** Se quita la negativa. `manifest.build_asset_entries(…, source_tiles=None)` con `udim`/`missing_tiles`; `verify_package` por tesela; `flows.run_collect_pipeline` anota `source_tiles` antes de `SaveProject`. Se borran `_udim_refusal`/`_udim_files_in_scene` si ya nadie los usa. → tests de manifest + op de collect sin negativa.
6. **SPA.** Se quitan `udimRefusalMessage` y la rama de collect; toasts nuevos (maps/tiles, `incomplete_tiles`); tipos; build. → `npm test && npm run lint && npm run build`, y el bundle commiteado.
7. **QC #14.** `udim.py` puro (veredicto por objeto/material a partir de `{material: tiles usadas}` + `{material: [(fichero, tiles en disco)]}`), `udim_c4d.py` (material efectivo por polígono, lectura de UVs, caché por dirty), `checks/udim.py`, el registro, el tuple del oracle y el recongelado. → pytest con un fake de tags/selecciones/herencia + oracle en `c4dpy`.
8. **Live.** Los escenarios del spec en C4D 2026.304 por el MCP, con documentos desechables.
9. **Docs.** `docs/HISTORY.md`, `CLAUDE.md` (Current state, gotchas medidos), research (`SaveProject` + formato de UVs) y versión.
