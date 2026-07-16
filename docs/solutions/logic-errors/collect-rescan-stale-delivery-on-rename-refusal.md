---
title: Collect re-scan auditaba la entrega vieja cuando el rename a nombre limpio se rehusaba
date: 2026-07-16
category: logic-errors
module: scene_collector
problem_type: logic_error
component: tooling
symptoms:
  - "Package re-scan: 0 assets tras un collect que SaveProject reporta con assets"
  - "El manifiesto refleja el contenido de una entrega anterior, no la recién colectada"
root_cause: logic_error
resolution_type: code_fix
severity: high
tags: [collect, manifest, rename, stale-file, i4]
---

# Collect re-scan auditaba la entrega vieja cuando el rename a nombre limpio se rehusaba

## Problem
En `collect_scene` (I4, Collect Confiable), al re-colectar sobre una carpeta destino que ya contenía una entrega previa con el mismo nombre limpio, el re-scan post-copia auditaba el archivo **viejo** en vez del recién escrito por SaveProject — el manifiesto certificaba la entrega equivocada.

## Symptoms
- Diálogo de éxito con «Package re-scan: 0 assets» en una escena con texturas.
- Detectado en el primer run en vivo con `violating.c4d` (segunda ejecución sobre la misma carpeta).

## What Didn't Work
- Sospechar del escáner de texturas o del `SCENEFILTER` del `LoadDocument`: ambos eran correctos; el input era el archivo equivocado.

## Solution
`plugin/sentinel/ui/flows.py` (commit `593ec90`). La Phase 2.5 rehúsa el rename si `desired_at` ya existe (defensa anti-overwrite), dejando `saved_at` (el output fresco de SaveProject) en disco. La selección estaba invertida:

```python
# ANTES — con rename rehusado, desired_at es la entrega VIEJA:
delivered_c4d = desired_at if os.path.exists(desired_at) else saved_at

# DESPUÉS — saved_at solo sobrevive cuando el rename no ocurrió;
# en ese caso es el output fresco y debe ganar:
delivered_c4d = saved_at if os.path.exists(saved_at) else desired_at
```

## Why This Works
Tras un rename exitoso, `saved_at` deja de existir y `desired_at` es el archivo fresco. Tras un rename rehusado, ambos existen pero solo `saved_at` es de esta ejecución. Preferir `saved_at` cubre ambos casos sin estado adicional.

## Prevention
- En flujos «escribe → renombra → consume», el consumidor debe seleccionar por *frescura garantizada* (el path que solo existe en la rama tomada), nunca por preferencia de nombre.
- Peldaño de datos reales obligatorio antes de merge para features de filesystem — este bug pasó pytest 305/305 y una revisión final de rama; lo cazó el segundo run en vivo (tercera vez que el patrón se confirma en este repo, ver `docs/audit/`).

## Related Issues
- PR #13 (Collect Confiable I4) · `docs/audit/2026-07-16_i4_sdd_ledger.md`
