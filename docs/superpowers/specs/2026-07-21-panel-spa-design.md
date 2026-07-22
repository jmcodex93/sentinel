# Fase 6 — Panel principal como SPA: arquitectura + rediseño UX (spec madre)

**Fecha**: 2026-07-21
**Estado**: aprobado en brainstorm (con companion visual — mockups en `.superpowers/brainstorm/75863-1784649095/content/`)
**Contexto**: última fase del rediseño UI (spec madre previa `2026-07-18-ui-redesign-design.md`, fases 1-5.3 entregadas en v1.13–v1.18). No es un port 1:1: es un **rediseño de usabilidad** del panel aprovechando la libertad del webview (tooltips, responsive, densidad, sin las limitaciones de layout de C4D 2026).

## Spike resuelto (2026-07-21, C4D 2026.302, en vivo)

- `HtmlViewerCustomGui` expone `PostWebMessage`/`SetWebMessageCallback`. El canal **JS→Python funciona** (`window.webkit.messageHandlers.webkitMessenger.postMessage` → callback con `(mensaje, bool)`; el host inyecta `window.testHandler <C4DWebKitDelegate>` y `window.webkitMessenger`).
- El canal **Python→JS (`PostWebMessage`) NO llega a la página** por ningún convenio descubrible (probados: `window.onmessage` directo, 11 nombres de función candidatos, eventos `message`/`webmessage` en window/document, `chrome.webview`, y `window.onerror` como trampa — nada dispara y no hay error JS). Los docs de Maxon (C++/Py) no documentan el lado JS receptor.
- **Decisión**: el refresco vivo del panel es **polling de stamp** (patrón Hub, probado en producción: `hub/state_stamp` 2s + re-anclaje desde mutaciones). PostWebMessage queda descartado; si Maxon lo documenta algún día, es una optimización drop-in.

## Decisiones cerradas (brainstorm)

1. **Migración total** del panel (header + QC/Render/Versions/Tools) a SPA — cierra el rediseño con una sola superficie visual.
2. **Panel nuevo en paralelo**: se registra un segundo panel dockeable ("Sentinel" nuevo); el nativo sigue intacto y operativo hasta la paridad, luego se jubila. Cero riesgo para el trabajo diario.
3. **IA = híbrido dashboard + rail adaptativo** (mockups aprobados):
   - **Home = dashboard "salud del shot"**: tarjetas de estado (QC con top-fails y fixes rápidos · Assets con missing/tamaño/VRAM · Render readiness · Versión/TODOs con Save/Deliver) — responde "¿cómo está mi shot?" en 2 segundos y pone las acciones frecuentes a un click.
   - **Navegación = rail adaptativo**: iconos con badges de estado (QC fails en rojo, missing en ámbar) cuando el panel está dockeado estrecho (~380px); se expande a sidebar etiquetada por breakpoint (≥~560px). Los badges son visibles desde cualquier sección — espíritu watchdog sin gastar ancho.
   - Secciones: Overview (home) · QC · Render · Deliver · Tools. ⌘K palette accesible desde el rail.
4. **Ventanas**: el panel **enlaza** — Hub y Reports siguen siendo ventanas grandes propias (superficies de trabajo); los formularios pequeños (Save Version, Notes, Settings) se **absorben como vistas del panel** (abrir ventana para 4 campos es fricción). Gate triage sigue como está (modal nativo en flujos síncronos; `form/gate` para triage suelto).

## Arquitectura

- **Host**: `SentinelPanelSPA` — GeDialog dockeable registrado como plugin de comando propio, con un único `CUSTOMGUI_HTMLVIEWER` a pantalla completa (`?page=panel`). Su `Timer(25ms)` asume los tres deberes: `_queue.drain(_dispatch)`, `pump_jobs()`, y (al jubilar el nativo) el snapshot watchfolder. Retención anti-GC como los demás hosts.
- **Incógnita del host a verificar en 6.0** (única que quedaba): comportamiento del gadget HTML **dockeado** (los hosts actuales son ventanas async): foco, Cmd+Z passthrough, resize con el layout de C4D. **Estado: spike de dock VERDE (verificado en vivo)** — dockea como panel nativo, el breakpoint del rail (560px) responde al resize, Cmd+Z atraviesa al documento con el panel dockeado con foco, el polling refresca el dashboard; probado con escena real de producción (SHOT_18: overview correcto, QC 6/12 + 39 assets, coincidiendo con Reports/Hub). El fallback a ventana flotante persistente queda descartado — no hizo falta.
- **Refresco**: polling de un `panel/state_stamp` (generaliza el del Hub: documento + dirty de materiales + contadores de escena) mientras la página está visible; mutaciones devuelven stamp (re-anclaje). El dashboard re-computa sus tarjetas al cambiar el stamp; el QC score usa la caché existente (`check_cache`) — el polling no dispara re-checks, los lee.
- **Ops**: capa fina nueva `panel_ops.py` sobre los motores existentes (`qc/score`, `fixes`, `versioning`, `flows`, `aovs`, `postrender`...) — cero lógica duplicada, patrón de las 5 fases previas. Los helpers de payload compartidos de fase 2 se reutilizan (el dashboard QC = mismo scoring que Reports).
- **SPA**: la misma app (`web/`), rutas `?page=panel` (+ subrutas cliente por sección). El design system DESIGN.md manda; los formularios existentes (`form/*` pages) se remontan como vistas internas del panel donde aplique.

## Descomposición en sub-fases (cada una: spec+plan propios, subagentes, live, merge)

- **6.0 — Host + shell + Overview**: registrar `SentinelPanelSPA`, spike de dock en vivo, rail adaptativo + header + dashboard con las 4 tarjetas (read-only + deep-links a Hub/Reports + fixes rápidos vía ops palette existentes). Entregable usable desde el día 1.
- **6.1 — Sección QC**: los 12 checks con Select/Fix/Info/Accept inline (sin popups: detalles expandibles, baseline con autor+razón como formulario inline), agrupación por severidad, fix-all.
- **6.2 — Sección Render**: presets + resolución, Multi-Format/Sentinel Frame, AOVs (Essentials/Production/Light Groups), snapshots (dir efectivo + watchfolder toggle), post-render validation (deep-link a Reports).
- **6.3 — Sección Deliver**: Save Version (vista absorbida), Recent versions, Notes/TODOs (vista absorbida), acceso Hub/Supervisor/Delivery Summary.
- **6.4 — Sección Tools + jubilación**: los scene tools + marking; Settings como vista; retirar el panel nativo (el comando viejo abre el nuevo), migración de menús/atajos, limpieza de código retirado ("kept one release": `collect_scene`, `TextureRepathingDialog`).

Cada sub-fase rediseña su sección (no portar 1:1): p. ej. QC pierde los 3 botones por fila a favor de fila expandible con acciones contextuales; Tools agrupa los 8 botones por intención con descripciones. El detalle se decide en el brainstorm de cada sub-fase (companion visual disponible).

## Principios transversales

- Lógica de negocio SOLO en motores; ops = adaptadores finos; nativo como fallback hasta jubilación.
- Errores inline y toasts; popups nativos solo para decisiones bloqueantes síncronas.
- Tokens de DESIGN.md; acento nunca estado; nuevas cromas solo derivadas y documentadas.
- Todo lo persistente (layout del rail, orden de tarjetas si se hace configurable) vía `hub_spa_ui`-style keys en `sentinel_settings.json`.
- Windows queda pendiente de hardware (fallback navegador operativo, patrón fases previas).

## Fuera de alcance (fase madre)

- Rediseñar el detalle interno de cada sección aquí (va en cada sub-fase).
- PostWebMessage push (descartado por spike; anotado como optimización futura si Maxon lo documenta).
- Tocar Hub/Reports/palette (ya entregados; solo se enlazan).
- Branding nuevo.

## Verificación (por sub-fase, escalera habitual)

pytest de ops/payloads puros · vitest de lógica TS · build committeado · live C4D con escena real + eyeball · review final por incremento. 6.0 incluye además el spike de dock documentado (resultado → CLAUDE.md limitaciones o capacidades).
