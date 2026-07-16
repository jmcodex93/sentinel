---
title: El auto-fix del pre-flight destruye las violaciones del fixture que el test necesita
date: 2026-07-16
category: workflow-issues
module: testing
problem_type: workflow_issue
component: testing_framework
severity: medium
applies_when:
  - "Verificación en vivo de features de Collect/QC usando violating.c4d"
  - "Cualquier test manual cuyo sujeto sea una violación auto-fixable"
tags: [fixtures, violating-c4d, auto-fix, collect, test-procedure]
---

# El auto-fix del pre-flight destruye las violaciones del fixture que el test necesita

## Context
Verificando el re-scan de I4 con `tests/fixtures/violating.c4d`, el manifiesto salió con «0 assets». Causa: en un run anterior se pulsó **«Yes = Fix auto-fixable issues»** en el pre-flight del Collect — y el auto-fix de unused materials **borró** `missing_absolute_texture_mat`, el material que concentra dos violaciones del fixture (textura con ruta absoluta + material sin usar). El doc «arreglado» ya no podía demostrar nada sobre texturas.

## Guidance
Al verificar en vivo con `violating.c4d`:

1. **Pulsar siempre «No = Collect anyway»** en el pre-flight — «Yes» elimina 4 de las violaciones diseñadas (lights→group, camera shift→reset, unused mats→delete, y con el material borrado, la de texturas).
2. **Colectar a una carpeta nueva y vacía** en cada intento (evita además la rama de rename-refusal, ver doc relacionado).
3. **Leer el pre-flight como diagnóstico del estado del doc**: el fixture prístino muestra 12 tipos de issue; si faltan exactamente los auto-fixables, el doc ya fue mutado por un run anterior — reabrir el fixture original.

## Why This Matters
Un fixture es un oráculo: cada violación es un assert. El auto-fix es una feature legítima del producto que, aplicada al oráculo, lo convierte en una escena a medio limpiar que produce verificaciones falsamente tranquilizadoras («0 issues» que parece bug del escáner o, peor, pasa por bueno).

## When to Apply
- Cualquier peldaño en vivo del ladder de verificación que use `violating.c4d`/`clean.c4d`.
- Diseño de futuros fixtures: si una violación es auto-fixable, documentar en el propio test qué botón NO pulsar.

## Examples
Run contaminado: pre-flight con 8 tipos (sin lights/shift/unused/texturas) → re-scan «0 assets».
Run correcto (fixture prístino + «No»): pre-flight con 12 tipos → re-scan «1 assets — 1 missing» con `/__sentinel_fixture_missing__/missing_albedo.exr` y su procedencia.

## Related
- [[collect-rescan-stale-delivery-on-rename-refusal]] — el otro factor del mismo incidente
