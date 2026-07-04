---
date: 2026-07-03
topic: motor-qc-2
---

# Motor QC 2.0 — registro de checks, reglas por proyecto y baseline, vía modularización incremental

## Summary

Refactor incremental del plugin Sentinel hacia un paquete `sentinel/`, donde cada fase reduce el monolito y entrega una capacidad nueva: un registro declarativo de los 12 checks, reglas por proyecto en `sentinel_rules.json`, y un baseline por escena que silencia violaciones aceptadas con motivo. Las fixtures de regresión de la Fase 0 protegen cada paso: los 12 checks producen el mismo resultado antes y después de cada extracción.

---

## Problem Frame

Dos dolores reales y recurrentes en el equipo (2-5 artistas): las escenas heredadas de otras personas viven en rojo permanente — el panel deja de mirarse y los 12 checks pierden su valor a la vez — y `standard_fps` se guarda por máquina, así que dos artistas del mismo proyecto pueden validar contra reglas distintas.

Debajo hay un coste estructural probado: el commit `56b9461` existió solo para re-unificar la lista de checks en tres artefactos que habían derivado. El `.pyp` tiene hoy 11.067 líneas; el 57% es UI (con `YSPanel` concentrando 2.768 líneas) y el 35% es motor mayormente puro y extraíble. La auditoría de supervisor (2026-06-12) manda verificar antes de construir y consumir siempre la lista canónica de checks en todo artefacto.

Ningún tool del ecosistema C4D combina severidad formal + supresión por objeto + baseline de escena; los linters de código (RuboCop, SonarQube, ESLint) demuestran que ese trío es lo que hace adoptable un validador sobre material heredado.

---

## Key Decisions

- **Enfoque A — registro mínimo, valor primero.** Formalizar el proto-registro existente (`_CHECK_DISPLAY` + `ROW_KEYS` + `_build_qc_summary`) sin reescribir los checks por dentro, y construir ruleset y baseline encima. Descartados: plataforma completa de una vez (big-bang contrario a la auditoría) y config-sin-refactor (parche frágil que reintroduce la deriva).
- **Modularización incremental, no reescritura ni C++.** El conocimiento empírico de la API C4D 2026 incrustado en el código (ObjectData.Draw, transaction.Commit, diálogos async, DescIDs) es el activo; una reescritura lo tira y C++ multiplica el coste de build/distribución sin resolver ningún dolor real.
- **Paquete `sentinel/` con bootstrap en el `.pyp`.** Patrón oficial de Maxon: `sys.path.insert` con la carpeta del plugin, imports eager, llamadas `Register*` dentro del `.pyp`. `plugin/res/` no cambia. Política de recarga: reiniciar C4D (los módulos importados no se recargan con "Reload Python Plugins").
- **Severidad v1 = formalizar lo que existe.** Los tags FAIL/WARN de `_CHECK_DISPLAY` pasan a severidad de primera clase en el registro. La doble columna de contexto (trabajo vs. entrega) se difiere hasta que existan los gates.
- **Precedencia de reglas: proyecto > máquina > defaults.** El `sentinel_rules.json` junto a la escena gana sobre `sentinel_settings.json`; sin ficheros, el comportamiento actual.
- **Baseline abierto con registro.** Cualquier artista acepta violaciones; queda autor + motivo + fecha para revisión a posteriori. Identidad por `check_id` + ruta jerárquica del objeto: renombrar re-arma la excepción (debilidad asumida, estilo RuboCop).
- **Optimización oportunista acotada.** Al extraer un módulo se consolidan los near-duplicados ya identificados (clasificadores de rutas de texturas; hit-testing repetido en las user areas cuando toque la UI), solo con cobertura de fixtures y preservando comportamiento. Nada de reescrituras gratuitas.
- **Motor primero; UI al final.** `YSPanel` se adelgaza por goteo a medida que la lógica migra; el refactor de la UI y del singleton del overlay cierran la secuencia, no la abren.

---

## Requirements

**Modularización**

- R1. Existe un paquete `sentinel/` junto a `plugin/sentinel_panel.pyp`; el `.pyp` queda como bootstrap: inserción de `sys.path`, imports eager de todos los submódulos y llamadas `Register*`.
- R2. La extracción va por fases motor-primero; al cierre de cada fase el plugin carga sin errores y los 12 checks producen resultado idéntico a v1.5.7 sobre las escenas fixture.
- R3. `plugin/res/` y el registro de los plugins ObjectData/TagData (overlay, Camera Frame) funcionan sin cambios tras cada fase.
- R4. El bootstrap purga los módulos `sentinel*` de `sys.modules` al recibir `C4DPL_RELOADPYTHONPLUGINS` como mitigación best-effort; la política soportada es reiniciar C4D.

**Registro de checks**

- R5. Cada check es una entrada declarativa en un registro único: id, etiqueta, severidad por defecto (FAIL/WARN), capacidad de fix y parámetros que consume.
- R6. Panel, QC Report, resumen de Save Version y preflight del Collector iteran el registro; añadir un check nuevo no requiere editar ningún consumidor.
- R7. El score y el orden del panel derivan del registro y reproducen el comportamiento actual con los defaults.

**Reglas por proyecto (`sentinel_rules.json`)**

- R8. Sentinel descubre `sentinel_rules.json` en la carpeta de la escena o su proyecto, con precedencia proyecto > settings de máquina > defaults embebidos.
- R9. Parámetros externalizados en v1: FPS estándar, frame inicial, presets de render aprobados, lista de nombres por defecto, insets de safe-area, severidad por check y checks activados/desactivados.
- R10. El header del panel muestra qué ruleset está activo y de dónde viene; sin fichero, muestra "defaults".
- R11. Un ruleset ilegible o inválido produce aviso y fallback a defaults; nunca un crash.

**Baseline por escena**

- R12. Desde el panel se acepta una violación concreta con motivo obligatorio; el sidecar `<base>_baseline.json` guarda check, identidad del ítem, autor, motivo y fecha, y se comparte entre versiones de la misma escena base (patrón del sidecar de notas).
- R13. El score y las filas del panel cuentan solo violaciones nuevas; las aceptadas se muestran colapsadas como recuento expandible.
- R14. La identidad de un ítem aceptado es `check_id` + ruta jerárquica del objeto; para checks sin objeto (FPS, presets, output) la identidad es el parámetro violado. Renombrar o mover el objeto re-arma la excepción.
- R15. QC Report, resumen de Save Version y manifiesto del Collector reportan tanto las violaciones nuevas como las aceptadas con sus motivos; ningún artefacto oculta ítems baselined.
- R16. Eliminar una aceptación re-arma el check en el siguiente refresco.

**Verificación y regresión**

- R17. Antes de la primera extracción existe la escalera de verificación: tests pytest para helpers puros, un par de escenas fixture (violadora + limpia) y un runner que compara los 12 checks contra JSON esperado. Es el criterio de cierre de cada fase.
- R18. Los helpers nuevos (registro, parseo/merge de ruleset, matching de baseline) nacen como Python puro con tests pytest ejecutables sin C4D.

**Optimización por el camino**

- R19. Cada extracción consolida los duplicados identificados en su módulo (p. ej. los tres clasificadores de rutas de texturas) cuando las fixtures cubren el comportamiento afectado; las consolidaciones sin cobertura se anotan y difieren.

---

## Acceptance Examples

- AE1. **Covers R8, R10.** Given un `sentinel_rules.json` con `fps: 24` junto a la escena, when se abre la escena, then QC #11 valida contra 24 fps y el header muestra el ruleset activo; al borrar el fichero, vuelve a 25 (default) sin reiniciar.
- AE2. **Covers R12, R13.** Given una escena heredada con 5 violaciones, when se aceptan las 5 con motivo, then el score cuenta 0 nuevas y el panel muestra "5 aceptadas"; una violación nueva sube el contador a 1.
- AE3. **Covers R14, R16.** Given un objeto con violación aceptada, when se renombra, then la violación reaparece como nueva; al borrar la aceptación desde el panel, el check se re-arma en el siguiente refresco.
- AE4. **Covers R15.** Given una escena con violaciones aceptadas, when se exporta el QC Report o se ejecuta Collect Scene, then el artefacto lista las aceptadas con autor y motivo junto a las nuevas.
- AE5. **Covers R2, R17.** Given la fase 1 de extracción completada, when corre el runner de fixtures, then los 12 checks devuelven exactamente el JSON esperado registrado con v1.5.7.
- AE6. **Covers R11.** Given un `sentinel_rules.json` corrupto, when se abre la escena, then el panel funciona con defaults y muestra un aviso no bloqueante.

---

## Scope Boundaries

**Deferred for later**

- Quality gates en Save FINAL / Collect (I3 del roadmap): consumirán la severidad del registro, pero son el ciclo siguiente.
- Severidad de doble contexto (trabajo vs. entrega): se añade cuando existan los gates que la necesitan.
- Refactor profundo de `YSPanel` y extracción del singleton `_overlay_state`: fase de cierre, no bloquea ruleset ni baseline.
- Caducidad opcional de aceptaciones del baseline (re-armar por fecha/versión): valorar tras uso real.
- Ediciones/versionado formal del ruleset ("adopted editions"): innecesario para un equipo de 2-5.

**Outside this product's identity**

- Reescritura desde cero o migración a C++: descartada tras evaluación; solo se reconsideraría un componente C++ aislado ante un cuello de botella medido.
- Cualquier dependencia de servidor: el filesystem compartido es la infraestructura.
- Adopción por terceros como driver de diseño del contrato del ruleset en v1.

---

## Dependencies / Assumptions

- La Fase 0 (higiene de ramas: congelar el WIP de v1.5.8/v1.6.0 fuera de `main`; escalera de verificación) precede a la primera extracción — mandato de la auditoría.
- El equipo dispone de carpeta compartida por proyecto donde puede vivir `sentinel_rules.json`.
- Los tests pytest cubren solo lógica pura (sin `import c4d`); la validación en vivo usa las escenas fixture dentro de C4D.
- El patrón de paquete está verificado contra la documentación oficial de Maxon 2026 (Python Libraries Manual); el desarrollo asume reinicio de C4D para recargar.

---

## Outstanding Questions

**Deferred to Planning**

- Granularidad exacta de módulos del paquete (el mapa estructural propone `checks`, `textures`, `versioning`, `multiformat`, `safe_areas`, `notes`, `aovs`, `settings`, `utils`, `ui/`): decidir por fase durante el plan.
- Regla de descubrimiento del ruleset (solo carpeta de la escena vs. búsqueda ascendente acotada) y formato del campo de identidad del ruleset mostrado en el header.
- Esquema exacto del sidecar `<base>_baseline.json` y migración si cambia.
- Orden de fases de extracción y qué consolidaciones de R19 entran en cada una.

---

## Sources

- `docs/audit/2026-06-12_supervisor_audit.md` — mandato de verificación, prioridades reordenadas, anti-patrón "confianza falsa".
- `docs/ideation/2026-07-03-sentinel-10x-ideation.html` — idea origen (I2 Motor QC 2.0), basis y prior art (Deadline, glTF-Validator, RuboCop/SonarQube).
- `plugin/sentinel_panel.pyp:7228` — `_CHECK_DISPLAY` (proto-registro con FAIL/WARN); `plugin/sentinel_panel.pyp:2817` — `_build_qc_summary` (consumidor unificado).
- Mapa estructural del `.pyp` (sesión 2026-07-03): 11.067 líneas; 35% motor / 57% UI / 8% plumbing; `YSPanel` 2.768 líneas; hotspots de acoplamiento (`_overlay_state`, `YSPanel.Command()`).
- Maxon Python Libraries Manual (C4D 2026): patrón `sys.path.insert` + paquete; recarga de módulos importados no soportada por "Reload Python Plugins".
