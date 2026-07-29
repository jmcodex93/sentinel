# Batch Rename — objetos + materiales con tokens y preview (v1.31)

**Fecha**: 2026-07-29
**Estado**: implementado en rama `feat/batch-rename` (motor + ops + sub-vista SPA, pytest 976 + vitest 158 verdes), **PENDIENTE verificación live** (matriz al pie de este documento)
**Contexto**: segunda fase del arco "expansión de Tools" (v1.30 quick-wins ✅ → **v1.31 este spec** → v1.32 RS auto-wire → v1.33 Recall/template). La investigación (`docs/research/2026-07-28-c4d-community-tools.md`) señala naming como la categoría más reinventada del mercado (4+ renamers independientes, Plus Renamer a $399/año). Motivo propio de Sentinel: QC #8 (default names) y el naming de takes del Frame dependen de nombres sanos — el renamer cierra el ciclo detectar→arreglar. Base: main con v1.30.0 mergeado y live-verified.

## Decisiones cerradas

1. **Alcance v1**: **objetos** (selección del Object Manager) y **materiales** (selección del Material Manager). Layers fuera (poca demanda relativa); **Takes fuera a propósito** — los takes del Sentinel Frame se auto-nombran y renombrarlos a mano pelearía con el auto-sync.
2. **Pipeline de operaciones, orden FIJO y documentado**: (1) **Patrón** — si no está vacío reemplaza el nombre entero, con tokens; (2) **Find/Replace** literal con toggle Match case; (3) **Prefijo/Sufijo**. Tokens del patrón: `$n` (contador con start + padding configurables), `$name` (nombre actual), `$parent` (nombre del padre; vacío para raíces/materiales), `$type` (nombre de tipo: Cube, Light, Material…).
3. **`$n` numera en ORDEN DE SELECCIÓN** (`GETACTIVEOBJECTFLAGS_SELECTIONORDER`) — control explícito del artista; el preview muestra ese orden tal cual. Materiales: orden del Material Manager (`GetActiveMaterials()`).
4. **UI = sub-vista del panel** (Tools → "Batch Rename →", sub-router local patrón Render→Frame), con **preview en vivo** old→new y Apply primary.
5. **Colisiones** (dos nombres finales iguales en el lote) se AVISAN en el preview (ámbar) pero no bloquean — C4D permite duplicados; Sentinel avisa, el artista decide.
6. Sin presets persistidos en v1 (YAGNI; el patrón last-5 del repathing existe si el uso lo pide).

## Diseño

### Motor (`renaming.py`, módulo nuevo PURO)

- Sin `import c4d`; pytest directo. **La misma función alimenta preview y apply — WYSIWYG por construcción.**
- `rename_plan(items, ops) -> list[{"old", "new", "collision"}]`:
  - `items` = `[{"name": str, "parent": str, "type_name": str}]` en el orden YA resuelto por el adapter (selección u orden de manager).
  - `ops` = `{"pattern": str, "find": str, "replace": str, "match_case": bool, "prefix": str, "suffix": str, "num_start": int, "num_padding": int}` — todos opcionales con defaults neutros (`num_start` 1, `num_padding` 3).
  - Expansión de tokens sobre el patrón por item (índice del contador = posición en `items`); find/replace case-insensitive por defecto (mismo idioma que el repathing: `re.sub` con literal escapado y lambda); prefijo/sufijo al final.
  - `collision=True` en toda fila cuyo nombre final se repita dentro del lote.
  - Config neutra (todo vacío) → plan vacío de cambios (`old == new` en todas) — el caller lo detecta como no-op.
- `ops_is_noop(ops) -> bool` — guard puro para el `nothing_to_do`.

### Ops (`panel_tools_ops.py`)

- `panel/tools/rename_preview` (read-only): payload `{"source": "objects"|"materials", "ops": {...}}` → `{"rows": [{"old","new","collision"}], "truncated": bool}` capado a 500 filas. Fuentes: objetos `doc.GetActiveObjects(GETACTIVEOBJECTFLAGS_SELECTIONORDER)`; materiales `doc.GetActiveMaterials()`. Sin selección → `{"ok": False, "error": "no_selection"}`.
- `panel/tools/rename_apply`: MISMO payload; re-deriva el plan server-side (nunca confía en filas del cliente) y aplica los `old != new` en **UN undo** (`StartUndo`/`AddUndo(CHANGE, node)`/`SetName`); devuelve `{"ok": True, "renamed": N, "collisions": M}`. Config neutra → `{"ok": False, "error": "nothing_to_do"}`. Dialog-free (`_forbid_dialog`).
- `$parent` para objetos = `GetUp().GetName()` (vacío si raíz); `$type` = `GetTypeName()` si existe, fallback vacío.

### UI (sub-vista del panel)

- `ToolsSection` gana **"Batch Rename →"** (sub-router local `toolsView: "main"|"rename"` en la sección, espejo del patrón Render→Frame).
- Sub-vista `RenameSubview`: toggle **Objects/Materials**; campos Pattern (con hint de tokens: `$n · $name · $parent · $type`), Find + Replace + Match case, Prefix, Suffix, Start # + Padding; **tabla preview** old→new (debounce ~300ms al teclear; re-fetch cuando cambia el stamp del poll — cambiar la selección en C4D refresca el preview; filas `collision` en ámbar con nota "duplicate result"); **Apply** primary → toast "Renamed N object(s)/material(s)" (+ aviso de colisiones si M>0); `← Tools` vuelve.
- Lógica pura del cliente en `panelRename.ts` (shape de payload, copys de toast) con vitest; el preview NUNCA se calcula en el cliente — siempre `rename_preview` (una sola fuente de verdad, el motor Python).
- Estado `busyTool` compartido; un Cmd+Z revierte el lote (webview: recordar la lección `restoreFocus` si la sub-vista desmonta algo con foco).

## Errores / no-regresión

- Cero cambios en QC/registry; las herramientas existentes de Tools intactas; el sub-router no altera la vista main de Tools.
- Takes/layers jamás tocados; los nombres de cámara que alimentan el naming de takes del Frame pueden cambiar — eso ya lo cubre el rename-safe BaseLink resolver del Frame (v1.8), verificar en la matriz live.
- Apply re-deriva server-side: un preview stale (selección cambiada entre preview y apply) nunca aplica nombres desalineados.

## Verificación

- pytest: pipeline puro (orden patrón→find/replace→prefijo/sufijo, tokens con padding/start, `$parent`/`$type`, case toggle, colisiones, config neutra no-op), contratos de ops (`_forbid_dialog`, no_selection, nothing_to_do, cap 500, re-derivación en apply).
- vitest: payload shape + copys.
- Live (matriz): renombrar 10 cubos con `luz_$n` start 5 padding 2 → luz_05..luz_14 en orden de clic; find/replace con y sin case; `$parent`/`$type` reales; materiales; colisión avisada; renombrar la CÁMARA host de un Sentinel Frame → el auto-sync re-nombra sus takes sin duplicarlos (rename-safety BaseLink); un Cmd+Z; preview siguiendo cambios de selección.

## Fuera de alcance

- Layers y Takes; presets persistidos; regex en find/replace (literal only v1); case transforms (UPPER/lower/Title) — candidatos a v1.31.x si el uso los pide.
