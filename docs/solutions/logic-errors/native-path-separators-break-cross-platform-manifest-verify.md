---
title: Separadores de path nativos en el manifiesto rompen el verify cross-platform
date: 2026-07-16
category: logic-errors
module: scene_collector
problem_type: logic_error
component: tooling
symptoms:
  - "Verify en macOS reporta LOST todos los assets de un paquete colectado en Windows"
root_cause: logic_error
resolution_type: code_fix
severity: high
tags: [cross-platform, path-separators, manifest, verify, windows, macos, i4]
---

# Separadores de path nativos en el manifiesto rompen el verify cross-platform

## Problem
El manifiesto de entrega guardaba las rutas relativas de assets con `os.path.relpath` (separadores nativos). Un paquete colectado en Windows escribe `"tex\\wood.jpg"` en el JSON; el «Verify Delivery» en macOS busca ese literal, no existe, y reporta **todos** los assets como LOST — falsa alarma sistemática en el escenario exacto (handoff entre máquinas) que la feature protege.

## Symptoms
- VERIFY lista como LOST assets que están físicamente en el paquete, siempre que emisor y receptor usan OS distinto.

## What Didn't Work
- El plan original ni lo contempló: su propio test tenía una aserción ambigua (`== x or == y`) sobre el separador en vez de mandatar la normalización — el bug estaba en el plan, no solo en el código. Lo cazó la revisión final de rama (Critical), no pytest (que corre en un solo OS).

## Solution
Commit `59e3748` en `plugin/sentinel/manifest.py`: normalizar a `/` al escribir y unir tolerante al leer.

```python
# escritura (build_asset_entries):
path = os.path.relpath(real, root).replace(os.sep, "/")

# lectura (verify_package):
candidate = os.path.join(package_root, *path.replace("\\", "/").split("/"))
```

Más un test que serializa el manifiesto y afirma `"\\" not in json.dumps(m["assets"])`.

## Why This Works
El JSON se vuelve un formato de transporte con separador canónico (`/`), y el consumo re-materializa al separador local vía `os.path.join(*parts)`. Ninguno de los dos lados depende del OS del otro.

## Prevention
- Todo path que se serialice a un sidecar/manifiesto que viaja entre máquinas se normaliza a `/` en la escritura; el consumo hace split + join local. Sin excepciones.
- Test estándar para cualquier serializador nuevo de rutas: «el JSON no contiene backslashes».
- En review, una aserción con `or` sobre valores esperados es un smell: el test no sabe qué contrato exige.

## Related Issues
- PR #13 · revisión final de rama (Critical #1)
