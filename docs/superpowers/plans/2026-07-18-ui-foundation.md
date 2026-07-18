# UI Foundation (Fase 1 del rediseño) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sentinel Reports MVP — diálogo C4D dockeable con HTML embebido (Linear-adaptado) mostrando el Delivery Summary real, sobre servidor stdlib + cola main-thread propios, con `docs/design/DESIGN.md` como fuente de verdad.

**Architecture:** Spec: `docs/superpowers/specs/2026-07-18-ui-redesign-design.md` (leer PRIMERO). Patrón Overseer estudiado (NO copiar código): server `http.server` en 127.0.0.1 sirviendo estáticos + `/api/*`; cola de peticiones drenada por el `Timer` del diálogo host en el main thread de C4D. SPA Vite+React+TS+Tailwind en `web/` (fuente, no se sincroniza) con build a `plugin/web/` (se sincroniza con sync.sh). Bridge puro en `plugin/sentinel/webbridge.py` (stdlib, sin c4d, pytest); adaptador C4D en `plugin/sentinel/ui/reports.py`-adyacente.

**Tech Stack:** Python stdlib (http.server, queue, threading) · Vite + React 18 + TypeScript + Tailwind + Radix + Lucide · Inter woff2 local.

## Global Constraints

- `plugin/sentinel/webbridge.py` NUNCA importa c4d (patrón assets.py/manifest.py). Adaptador C4D en `plugin/sentinel/ui/` sí.
- Servidor SOLO en 127.0.0.1. Puertos: intentar 8347..8356; si todos ocupados → fallback navegador… no: sin puerto no hay navegador — reportar error claro en el diálogo.
- NO copiar código de Overseer (licencia): misma arquitectura, implementación propia.
- Tokens visuales EXACTOS del spec: canvas `#101113`, paneles `#17181b`, tinta `#f7f8f8`, muted `#6b6f76`, hairline `rgba(255,255,255,.06)`/`.08`, acento `#5e6ad2` (hover `#828fff`); semánticos: `#e0655f`/`#ffb74d`/`#68b06a`/`#8a8a8a`. Grid 8px, radius 8-10px, filas 32px, transiciones 100-150ms. Inter woff2 empaquetada en `web/` (descargar de Google Fonts/rsms, licencia OFL — incluirla).
- El build de la SPA (`plugin/web/`) SE COMMITEA (los artistas no tienen node). `web/node_modules` y artefactos intermedios → .gitignore.
- pytest completo verde tras cada tarea (baseline 404). Motores existentes intocables.
- Comentarios/UI en inglés. Commits estilo repo.
- Reload C4D = reiniciar; verificación live la hace el controller vía MCP exec_python.

---

### Task 1: `docs/design/DESIGN.md` — el sistema como spec consumible

**Files:** Create: `docs/design/DESIGN.md`

**Interfaces:** Produces: el documento que TODA tarea de UI posterior lee primero. Formato: el esquema de tokens de getdesign.md (hay un ejemplo real descargado en `/private/tmp/claude-501/-Users-javiermelgar-Library-CloudStorage-SynologyDrive-01-WORK-99---CODEX-10-YS-Guardian/1e8bf0fb-5db2-4706-8658-5af4030a4358/scratchpad/getdesign/DESIGN.md` — usar su ESTRUCTURA yaml de secciones description/colors/typography/spacing/components, con NUESTROS valores del spec).

- [ ] Escribir DESIGN.md: description (1 párrafo: Linear-adaptado para plugin C4D), colors (tokens exactos de Global Constraints, incluidos los 4 semánticos con su significado y la regla "el acento nunca marca estado"), typography (Inter, escala 11/12.5/13/15/18/20, pesos 400/500/600, tracking -0.01em en títulos), spacing (grid 8px, filas 32px, padding de sección 16-18px), rounded (sm 4, md 6-8, lg 10), components (report-page, kpi-card, table-row, badge, toast, strip, segmented-control — cada uno con sus tokens), rules (modal solo decisión; color solo semántica; hover .1-.15s).
- [ ] Añadir sección "For agents": léeme antes de tocar UI; sabor nativo ↔ HTML equivalencias (tabla del spec).
- [ ] Commit: `docs(design): DESIGN.md — Sentinel design system (Linear-adapted)`

### Task 2: Bridge puro `webbridge.py` + tests

**Files:** Create: `plugin/sentinel/webbridge.py`, `tests/test_webbridge.py`

**Interfaces:** Produces (contrato para T4):
- `class MainThreadQueue`: `submit(payload, timeout=30.0) -> dict` (bloquea el thread llamante hasta que el main thread procese; TimeoutError con mensaje "keep the Reports window open"), `drain(dispatch)` (llamado desde Timer; procesa TODO lo encolado; `dispatch(payload) -> dict`; excepción → `{"error": str, "traceback": str}`; nunca lanza).
- `create_server(web_root, api_handler, host="127.0.0.1", ports=range(8347, 8357)) -> (ThreadingHTTPServer, port)`: sirve estáticos de `web_root` (index.html fallback para rutas SPA, content-types básicos incl. woff2; path traversal bloqueado con normpath+startswith) y `POST/GET /api/<op>` → `api_handler(payload_dict) -> dict` como JSON. Sin CORS abierto (mismo origen siempre). OSError en todos los puertos → raise.
- `start_server_thread(server) -> Thread(daemon)` / `stop_server(server)`.

- [ ] TDD: tests primero — cola (submit desde thread + drain procesa y despierta; timeout; error en dispatch → dict error), server (estáticos: index, asset anidado, 404→index.html SPA, traversal `..` bloqueado; /api round-trip con handler eco; puerto ocupado → siguiente). Server tests con `http.client` contra server real en puerto efímero y un api_handler síncrono de stub (sin cola, sin c4d).
- [ ] Implementar. pytest completo verde (404 + nuevos).
- [ ] Commit: `feat(webui): pure stdlib bridge — main-thread queue + static/api server`

### Task 3: SPA `web/` — esqueleto + tokens + Delivery Summary

**Files:** Create: `web/` (fuente Vite), `plugin/web/` (build committeado), `.gitignore` entries

**Interfaces:**
- Consumes: `GET /api/report/delivery` → JSON `{scene, collected_at, artist, qc: {score}|null, summary: {total, collected, missing, external}, zip: {path, bytes}|null, assets: [{path, status, provenance}], pending_todos, manifest_path}` (T4 lo produce; para dev, `web/mock/` con fixture JSON y `npm run dev` con proxy o mock — decidir y documentar en web/README.md).
- Produces: `npm run build` → `plugin/web/` (index.html + assets con hash). Página `/` = Reports shell (sidebar mínima con "Delivery Summary"; más páginas en Fase 2) + página Delivery Summary: header (título + meta), 4 KPI cards, tabla de assets (hover, badges por estado con los colores semánticos, sticky header), footer con ruta del manifest. Estados: loading, error (servidor caído → mensaje con retry), manifest ausente → empty state con explicación.
- [ ] `npm create vite@latest` (react-ts) en `web/`; Tailwind + tokens del DESIGN.md como CSS vars + theme; Inter woff2 local (añadir licencia OFL junto a las fuentes); Radix + Lucide.
- [ ] Implementar shell + página con MOCK data primero (fixture = un manifest real anonimizado — hay uno en tests/fixtures? usar la estructura de manifest.py: leer sus tests para el shape exacto).
- [ ] Cablear fetch a `/api/report/delivery` con fallback a mock si `?mock=1`.
- [ ] `npm run build` → `plugin/web/`; commitear build + fuente; .gitignore: `web/node_modules/`, `web/dist/`.
- [ ] Commit: `feat(webui): Reports SPA skeleton — Linear-adapted tokens, Delivery Summary page`

### Task 4: Adaptador C4D — ReportsDialog + api ops + entrada en panel

**Files:** Create: `plugin/sentinel/ui/reports_dialog.py` · Modify: `plugin/sentinel/ui/panel.py` (entrada), `plugin/sentinel/ui/flows.py` si hace falta helper

**Interfaces:**
- `class ReportsDialog(gui.GeDialog)`: host del `CUSTOMGUI_HTMLVIEWER` a `http://127.0.0.1:<port>/`; `SetTimer(25)`; `Timer` → `queue.drain(dispatch)`; fallback: sin gadget → `webbrowser.open(url)` + StaticText aviso (patrón visto en Overseer/dialog.py — REESCRIBIR, no copiar). `DestroyWindow` → stop server. Server/queue perezosos y compartidos a nivel módulo (un solo server aunque se reabra el diálogo).
- `dispatch(payload)` — registro de ops: `{"op": "report/delivery"}` → localizar `sentinel_manifest.json`: (1) junto al doc activo si es un paquete colectado; (2) si no, `c4d.storage.LoadDialog(FILESELECT_DIRECTORY)`… NO: los diálogos en dispatch bloquean el Timer. En su lugar: op busca junto al doc y devuelve `{error: "no_manifest"}`; la SPA muestra empty-state con instrucción ("open a collected package or pass ?manifest=<path>"). Op alternativa `report/delivery?path=` acepta ruta explícita (query → payload).
- Panel: en la pestaña Versions, el botón condicional "Delivery Summary..." existente pasa a abrir ReportsDialog (localizar con grep; conservar el flujo viejo como fallback si el server no arranca). Mantener referencia `self._reports` (patrón _asset_hub).
- [ ] Implementar; adaptar el shape del JSON exactamente al contrato T3 leyendo manifest.py (claves reales del manifest v1.10: asset_summary, assets, scan_status, qc, etc. — mapear, no inventar).
- [ ] pytest verde (el adaptador no es testeable sin c4d; el mapeo manifest→payload SÍ: extraer `delivery_report_payload(manifest_dict) -> dict` PURO en webbridge.py o manifest-adyacente + tests).
- [ ] Commit: `feat(webui): Reports dialog host + /api/report/delivery + panel entry`

### Task 5: Verificación live + spikes + docs

**Files:** Modify: `CLAUDE.md` (What Works + entrada de versión) · `.superpowers/sdd/progress.md`

- [ ] Controller (no subagente): sync + restart C4D; abrir Reports sobre el paquete real de `/Users/javiermelgar/Desktop/Sentinel/CollectedHUB` (manifest real de la entrega v1.11); verificar render Linear-adaptado, KPIs correctos vs manifest, tabla, empty-state sin manifest.
- [ ] Spike Cmd+Z: con Reports abierto y enfocado, el usuario hace Cmd+Z en C4D → ¿llega el undo? Documentar veredicto en el spec (sección riesgos).
- [ ] Spike Windows: sin hardware ahora → documentar "pending hardware; fallback navegador operativo" en el spec.
- [ ] Docs: CLAUDE.md bullet + versión (v1.13.0: bump PLUGIN_VERSION + entrada historial). ROADMAP: fases 2-5 como pendientes.
- [ ] Commit final + merge según flujo de cierre de rama.

## Self-Review

Cobertura spec Fase 1 completa (DESIGN.md=T1, server/cola=T2, SPA+tokens=T3, host+api+entrada=T4, spikes+MVP live=T5). Sin TBDs: los contratos de cola/server/payload están definidos; el shape del manifest se ancla a manifest.py real en T4. Consistencia: web_root=plugin/web/ en T2/T3/T4 coincide; puertos 8347-8356 en T2/T4.
