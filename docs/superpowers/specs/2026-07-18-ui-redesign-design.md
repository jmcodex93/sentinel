# Sentinel UI/UX Redesign — Design Spec

**Fecha:** 2026-07-18
**Estado:** Aprobado en brainstorming (secciones 1–4 validadas una a una)
**Contexto previo:** Asset Hub v1.11 + pulido v1.11.1 (los componentes nativos del Hub son la base del sabor nativo)

## Objetivo

Rediseño evolutivo de toda la UI de Sentinel para (por orden de dolor aprobado):
eliminar la inconsistencia visual, dar una respuesta única a "dónde vive X"
(arquitectura de información) y matar la lluvia de ~112 popups modales.
Audiencia: Javier como power-user + artistas de estudio sin manual.

**Criterio de éxito de la Fase 1 (verificable):** un diálogo C4D dockeable
("Sentinel Reports") renderiza el Delivery Summary real de un paquete colectado
con el design system Linear-adaptado, servido por un servidor stdlib local con
cola main-thread propia; los spikes de riesgo (Cmd+Z, Windows) tienen veredicto
documentado; `docs/design/DESIGN.md` existe y un agente puede construir UI
nueva leyéndolo.

## Decisiones cerradas (brainstorming)

| Tema | Decisión |
|---|---|
| Alcance | Evolución profunda (no revolución, no solo auditoría) |
| Audiencia | Javier + artistas de estudio |
| Dolores prioritarios | Inconsistencia visual · encontrar las cosas · popups |
| Estrategia técnica | **Híbrido por capas**: nativo GeDialog para interacción de escena; **HTML embebido** (`CUSTOMGUI_HTMLVIEWER`, verificado WebKit moderno en C4D 2026.302 con `SetWebMessageCallback`/`PostWebMessage` disponibles) para superficies ricas |
| Puente interactivo | **Patrón Overseer** (estudiado en /Users/javiermelgar/Downloads/Overseer, licencia estudiar-sí/copiar-no): servidor `http.server` stdlib en 127.0.0.1 + SPA `fetch('/api/<op>')` + cola drenada por `Timer` del diálogo en el main thread. Escrito por nosotros, cero código copiado |
| Informes read-only | Pueden servirse sin puente (mismo servidor, páginas de solo lectura) |
| Stack SPA | **Vite + React + TypeScript + Tailwind + Radix + Lucide** (node solo en dev; runtime = estáticos servidos por stdlib) |
| Sabor visual | **Linear adaptado**: base = DESIGN.md real de Linear (descargado vía getdesign.md), canvas elevado `#101113` (el `#010102` original haría agujero contra el gris de C4D), tinta `#f7f8f8`, paneles `#17181b`, hairlines `rgba(255,255,255,.06-.08)`, acento lavanda `#5e6ad2` (hover `#828fff`) SOLO en CTAs/focus/activo |
| Colores semánticos | Intocables y exclusivos de estado: missing/FAIL `#e0655f` · absolute/WARN `#ffb74d` · ok/PASS `#68b06a` · read-only/neutro `#8a8a8a`. El acento nunca compite con ellos |
| Formato del sistema | `docs/design/DESIGN.md` (esquema de tokens del formato getdesign.md) — fuente de verdad que todo agente lee antes de tocar UI |
| Tipografía | Inter (woff2 empaquetada local, patrón Overseer) en HTML; sistema en nativo |
| Anti-popup | Regla de oro: **modal solo para decisión bloqueante**; resultados → toast (4s, clicable a detalle) / caption / página de Reports |
| Command palette | ⌘K sobre todas las acciones del plugin (Fase 4) |

## Mapa de arquitectura de información (Sección 2, aprobado)

Principio: **panel = cockpit de esta escena** (estado + acciones) · **Settings =
solo máquina/estudio** (defaults, nunca acciones) · **Asset Hub = superficie
profunda de assets/entrega** · **Reports = superficie HTML de solo lectura**.

| Función | Destino |
|---|---|
| Snapshot dir | Auto-detect de `redshift_rv.cfg`; fallback editable SOLO en Settings; panel muestra efectivo + origen; Browse del panel se elimina; campo de Settings deshabilitado con caption "auto-detected from RenderView" cuando la detección funciona (patrón FPS/ruleset v1.6.0) |
| Multi-Part EXR | Default de estudio en Settings; estado + switch de escena SOLO en Render |
| Versiones/Notes/Collect | Pestaña Versions → **Deliver**: Save Version, Recent, Notes, Hub como única puerta de entrega |
| QC Report / Delivery Summary / Doctor / Supervisor / resúmenes | **Sentinel Reports** (HTML unificado) |
| GitHub / Report Bug | Menú burger; footer queda Settings + Doctor |
| ~112 popups | Triage: informativos → toast/caption/Reports; decisiones → modal se queda |

## Design system (Sección 3, aprobado)

Dos sabores del mismo sistema:
- **Nativo (existe)**: `AssetHubHeaderArea` (cabecera bicolor 2 lados),
  `PreflightStripArea` (franja verde/ámbar), QuickTab, `AssetListArea`
  (tabla sort/drag/divisores), captions de resultado. Tokens = los 5 colores
  semánticos como `c4d.Vector`, espaciado 6px.
- **HTML (nuevo, Linear-adaptado)**: tokens arriba; componentes: página de
  informe (header + meta + KPI cards + tabla hover 32px + badges), toast,
  segmented control, command palette (Fase 4). Grid 8px, radius 8-10px,
  transiciones 100-150ms.

## Fases (Sección 4, aprobado)

1. **Fundación**: `docs/design/DESIGN.md`; esqueleto `web/` (stack A) con
   tokens; servidor stdlib + cola main-thread + diálogo host
   `CUSTOMGUI_HTMLVIEWER` dockeable con fallback a navegador externo; spikes
   Cmd+Z-con-foco-webview y Windows (veredicto documentado); **Sentinel
   Reports MVP** = Delivery Summary real leyendo `sentinel_manifest.json`.
2. **Reports completo**: QC Report, Doctor, Supervisor, resúmenes de
   collect/validate-render; triage de popups informativos.
3. **Consolidación IA nativa**: snapshots (según mapa), Multi-Part EXR,
   Deliver, footer/burger.
4. **Formularios a SPA** *(condicionada a spikes verdes)*: Save Version,
   Settings, Notes, Gate Triage; toasts; command palette ⌘K.
5. **Hub en SPA**: evaluar con datos (tabla virtualizada para miles de assets).

## Manejo de errores / riesgos

- Servidor: solo 127.0.0.1, puerto configurable, arranque perezoso (al abrir
  la primera superficie HTML), apagado en `DestroyWindow`; si el puerto está
  ocupado, probar N+1..N+10 y luego fallback navegador con aviso.
- Cola main-thread: timeout por petición (30s), errores → JSON `{error}` con
  traceback a consola; el Timer nunca lanza.
- Fallback: sin gadget HTML o fallo de render → `webbrowser.open` de la misma
  URL (paridad Overseer).
- Cmd+Z: **SPIKE VERDE (2026-07-19, C4D 2026.302 macOS)** — con la ventana de
  Reports enfocada, Cmd+Z atraviesa el webview y deshace en la escena
  (verificado por el usuario: mover objeto → foco Reports → Cmd+Z → el objeto
  vuelve). Fase 4 desbloqueada para HTML embebido.
- Windows: **pendiente de hardware** — el fallback a navegador externo está
  operativo (verificado el camino de código); verificar el motor del gadget
  cuando haya una máquina Windows antes de dar Fase 4 por cross-platform.

## Testing

- Motor puro (cola, registro de ops, helpers de manifest→informe): pytest.
- Servidor: tests de integración con `http.client` contra un server efímero
  (sin C4D — la cola se stubbed).
- SPA: build reproducible (`npm ci && npm run build` → estáticos committeados);
  tests de componentes (vitest) opcionales desde Fase 2.
- Live C4D: ladder habitual (fixtures + escena real + eyeball con captura).

## Fuera de alcance

- Copiar código de Overseer (solo arquitectura).
- Migrar el Hub (Fase 5, decisión futura).
- Tocar motores existentes (manifest, gate, assets, postrender).
- Branding nuevo (logo/nombre) — solo sistema visual.
