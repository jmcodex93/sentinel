# Workflow Codex ⇄ Fable — Log de implementación y revisión

**Proceso establecido (12-13 jun 2026):** Codex (plugin `codex@openai-codex`, GPT-5.5) implementa tareas con especificación verificable; Fable (Claude) revisa el diff completo y **verifica cada afirmación del informe de Codex con lecturas/greps directos del código antes de aceptarla**. Codex lee `AGENTS.md` (puntero puro a `CLAUDE.md`, sin contenido duplicado — decisión deliberada para evitar drift entre ambos ficheros).

## Rondas ejecutadas

### Ronda 1 — Limpieza documental (12 jun)
- Codex: README 11→12 checks (respetando changelog histórico), rebrand del instalador (`INSTALL_YS_GUARDIAN.bat` → `INSTALL_SENTINEL.bat`), `TEST_PYTHON_SETUP.bat`, `INSTALLATION_README.md`, `LICENSE` nuevo, line-count de CLAUDE.md.
- **Review de Fable cazó un bug que Codex no vio**: el instalador verificaba/copiaba 3 ficheros que viven en `plugin/legacy/` desde v1.4.0 (habría abortado la instalación), y no copiaba `plugin/res/` (obligatorio desde v1.5.6) ni `abc_retime/`.

### Ronda 2 — Fix del instalador (12 jun)
- Codex corrigió el set de copia para que sea equivalente a lo que `sync.sh` sincroniza en macOS (menos `legacy/`). Verificado línea a línea.
- Imprecisión menor detectada en su informe (contenido de `plugin/icons/`), sin impacto funcional.

### Ronda 3 — Auditoría de supervisor (12 jun)
- Goal delegado a Codex: auditoría completa read-only → `docs/audit/2026-06-12_supervisor_audit.md`.
- **Codex encontró 3 bugs reales de código** que ni la auditoría de Fable ni 7 versiones de testing manual habían detectado. Los 3 verificados por Fable contra el código antes de aceptarlos:
  1. `_build_qc_summary` calculaba el score de Save Version sobre 11 checks (sin `cross_aspect`).
  2. El Export QC Report no incluía `_cross_aspect_bad` → el JSON omitía QC #12.
  3. El preflight de Scene Collector solo corría ~8 de los 12 checks.
- Discrepancias de Fable con el informe: el veredicto "KILL" a Scene Tools se rebaja a "congelar" (coste de mantenimiento casi nulo, valor diario real); la afirmación sobre CoreMessage ("polling throttled") queda como hipótesis no verificada.
- Drift adicional confirmado: "10 QC checks" en README:136 / CLAUDE.md:55, referencia a `RUN_INSTALLER.bat` inexistente, instalador hardcodeado a C4D 2024.

### Ronda 4 — Unificación de los 12 checks (13 jun)
- Codex implementó la lista canónica de 12 checks en los tres artefactos divergentes:
  - `_build_qc_summary` → añade `cross_aspect` (estrategia `current_frame`), score automático /12.
  - Export QC Report → `cross_aspect_bad` en el handler + sección `checks.cross_aspect` en el JSON (status/count/items, cap 30).
  - Scene Collector preflight → añadidos `check_keys`, `check_camera_shift`, `check_render_conflicts`, `check_fps_range`, `check_cross_aspect_safe_area`.
- Docs: README:136 y CLAUDE.md:55 → 12; `RUN_INSTALLER.bat` sustituido por consejo válido. ROADMAP:486 intacto (histórico).
- `py_compile` OK. **Verificado por Fable**: firma `sample_strategy` correcta, los 12 checks presentes en preflight, clave pasada en el handler (línea 9596), diff del .pyp limitado a las funciones especificadas (+48 líneas; el WIP v1.5.8/v1.6.0 intacto).

## Estado / pendientes

- [x] Limpieza documental + rebrand instalador (Rondas 1-2)
- [x] Auditoría supervisor (Ronda 3)
- [x] Unificación 12 checks + drift "10 checks" (Ronda 4)
- [x] **Verificación en C4D vivo** de la Ronda 4 (13 jun, C4D 2026.3, escena fixture vía MCP: cubo marcado Safe Area Subject en x=280 + takes 9x16/1x1): panel `QC 7/12` con fila Safe Area WARN (2 violaciones); history JSON de Save Version con `qc_score: "7/12"` y `cross_aspect: 2`; QC report con `summary.score: "7/12"` y sección `checks.cross_aspect` (items `HeroSubject [9x16] sides=right frames=1001`); manifest del Collector con `pre_flight_issues` incluyendo presets, FPS/range y "2 cross-aspect violations". Los tres artefactos consistentes entre sí y con el panel.
  - Gotcha operativo descubierto: **"Reload Python Plugins" (id 1026375) mata el bridge MCP de cinema4d y no se re-registra** — para recargar Sentinel con el bridge en uso, reiniciar C4D entero.
- [ ] Commit de todo lo anterior (el .pyp mezcla estos fixes con el WIP v1.5.8/v1.6.0 → commitear por hunks o separar el WIP antes).
- [ ] Separar WIP v1.5.8 (Preserve Vertical + HUD + dim mask) y v1.6.0 (Camera Frame tag) en commits/rama + documentarlos en ROADMAP.md.

## Lecciones del workflow

- Codex ejecuta rápido y limpio lo **bien especificado**; falla exactamente en las instrucciones vagas ("verify the script copies the right files" se la saltó en Ronda 1).
- El valor está en el **doble loop**: cada dirección del contraste ha cazado errores reales del otro lado.
- La verificación final de features de plugin sigue requiriendo C4D abierto — el loop Codex+Fable cubre implementación y consistencia, no comportamiento en viewport.
