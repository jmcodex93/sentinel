---
title: Tipos nativos de Maxon (IDs >= 1M) contaminan el inventario de "requires plugins"
date: 2026-07-16
category: logic-errors
module: scene_collector
problem_type: logic_error
component: tooling
symptoms:
  - "Delivery Summary lista XPresso, Subdivision Surface, Cloner, Data Tag o Bevel como plugins requeridos"
root_cause: wrong_api
resolution_type: code_fix
severity: medium
tags: [plugin-ids, maxon, manifest, required-plugins, heuristica, i4]
---

# Tipos nativos de Maxon (IDs >= 1M) contaminan el inventario de "requires plugins"

## Problem
El inventario de plugins requeridos del manifiesto de entrega usaba la heurística «`GetType() >= 1_000_000` = plugin de terceros». Falsa: Maxon registra features **nativas** en ese mismo rango, así que toda escena con MoGraph o un deformador moderno listaba «requiere Cloner/XPresso/Bevel» — ruido que entierra la señal real (Redshift, Octane).

## Symptoms
- Primer collect de producción real: `required_plugins` = XPresso (1001149), Subdivision Surface (1007455), Cloner (1018544), Data Tag (1018625), Bevel (431000028) junto a los RS legítimos.

## What Didn't Work
- No hay API limpia para «is builtin»: `c4d.plugins.FindPlugin` encuentra nativos y de terceros por igual, y filtrar por ruta del módulo (dentro del bundle de C4D) también descartaría Redshift, que es justo lo que hay que reportar.

## Solution
Denylist curada en el motor puro (`plugin/sentinel/manifest.py`, commit `79d8dab`), testeable con pytest:

```python
NATIVE_PLUGIN_IDS = frozenset({
    1001149,    # XPresso tag
    1007455,    # Subdivision Surface
    1018544,    # Cloner (MoGraph)
    1018625,    # Data Tag (MoGraph)
    431000028,  # Bevel deformer
})

def filter_native_plugins(plugins):
    return [p for p in plugins or []
            if p.get("plugin_id") not in NATIVE_PLUGIN_IDS]
```

El adaptador (`flows.py::_rescan_collected_package`) filtra antes de escribir el manifiesto. IDs de renderer **nunca** entran en la denylist: un receptor sin Redshift es exactamente lo que el inventario existe para avisar.

## Why This Works
La lista es finita, verificada en vivo (cada ID comprobado en C4D 2026.301), y crece por evidencia: cada nativo nuevo que aparezca en un collect real se añade con su comentario. Falso negativo (nativo sin filtrar) = ruido menor; falso positivo (tercero filtrado) = imposible mientras la denylist solo contenga IDs verificados como nativos.

## Prevention
- Nunca asumir que el rango de plugin-ID (>= 1M) implica terceros — Maxon lo usa para módulos propios desde hace años.
- Nuevos IDs a la denylist solo con verificación en vivo (`obj.GetType()` + `GetTypeName()` en C4D), nunca de memoria.

## Related Issues
- PR #13 · [[collect-rescan-stale-delivery-on-rename-refusal]] (mismo ciclo de verificación en producción)
