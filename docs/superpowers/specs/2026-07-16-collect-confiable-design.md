# Collect Confiable (I4) — Design

**Fecha:** 2026-07-16
**Origen:** brainstorming (superpowers) sobre la revisión crítica de Sentinel; idea I4 del ranking de ideación (`docs/ideation/2026-07-16-sentinel-critical-review-ideation.html`, idea 3), redimensionada por las respuestas del usuario.

## Contexto y decisiones de encuadre

- **Éxito del ciclo (usuario):** pipeline cubierto de punta a punta — el tramo escena→entrega es el último sin protección (QC cubre la escena; I1 cubre post-render; la entrega no tiene garantía).
- **Dolor nº1 (usuario):** paquete de entrega incompleto descubierto en destino. Save-with-Assets nativo es poco fiable y omite referencias (RS Proxy documentado).
- **Receptor principal (usuario):** otro estudio/freelance **con C4D** — handoff de escena viva, no cliente final.
- **Consecuencias de diseño:** sin `verify.py` standalone en v1 y sin hashes SHA-256 (escenario adversarial no aplica; campo `hash` reservado en el schema). La verificación en destino la hace Sentinel mismo si el receptor lo tiene. Render mixto (local + granja/servicio según proyecto): la validación de granja queda explícitamente fuera de este diseño.

## Objetivo

El Scene Collector deja de «copiar y confiar» y pasa a **empaquetar con prueba**: un manifiesto de dependencias generado por re-scan del paquete ya colectado, con clasificación honesta por asset, sellado con el estado QC, y verificable en destino.

## Arquitectura

Patrón asentado del plugin: motor puro + adaptador C4D fino + sidecar por concern.

### 1. `plugin/sentinel/manifest.py` (nuevo — motor puro, stdlib-only, sin `import c4d`)

- Entrada: inventario de dependencias (lista de `{path, tipo, origen}`) + raíz del paquete.
- Clasifica cada asset: `copiado` (resuelve relativo al paquete) / `faltante` (referenciado, no está) / `externo` (resuelve, pero fuera del paquete o ruta absoluta).
- Soporta secuencias/tokens (`$frame`, UDIM): verifica el patrón (≥1 fichero del set), anota `tipo: secuencia` + conteo.
- Serializa/parsea el schema JSON del manifiesto. Pytest-able con árboles de carpetas dummy (mismo enfoque que `postrender.py`).

### 2. Adaptador en el flujo de Collect (`ui/flows.py`)

Tras el `SaveProject()` + renombrado limpio actuales (sin cambios):

1. Reabrir el `.c4d` colectado en documento temporal (`LoadDocument` sin UI).
2. Escanear dependencias **sobre esa copia** — el paso donde Save-with-Assets miente — con `scan_all_texture_paths` + inventario ampliado (alcance v1 abajo).
3. Clasificar contra la raíz del paquete con el motor; cerrar el temporal.
4. Escribir `<base>_manifest.json` (atomic tmp+rename, quinto sidecar).
5. Diálogo de éxito ampliado: «N assets: X en paquete · Y faltantes · Z externos» + lista expandible de problemas. **Con faltantes no se bloquea ni se borra el collect: se marca en rojo y el manifiesto registra la verdad** (informar con dientes, no secuestrar — coherente con la filosofía de gates).

### 3. Recepción (`ui/panel.py` — ligero)

- Al abrir una escena con `_manifest.json` adyacente y artista de history ≠ artista local: el header ofrece «Ver resumen de entrega» — QC score sellado, baseline con autor+razón, TODOs pendientes.
- Botón «Verificar entrega»: re-corre el motor contra el disco del receptor (detecta pérdidas de transferencia/sync).
- Sin manifiesto adyacente → no aparece nada (cero ruido).

## Alcance del escáner — v1

**Entra:**
- Todo lo ya cubierto por `scan_all_texture_paths` v1.5.7 (node-graphs RS/Arnold, Xbitmap clásico, Octane legacy image shaders, BaseContainer params, RS Dome HDR, cachés Alembic, tag shaders).
- **RS Proxy** (el hueco documentado que motivó I4).
- **VDB** (volúmenes).
- **XRefs.**
- **Inventario de plugins de terceros requeridos**: enumerar tipos de objeto/tag no nativos y nombrarlos en el manifiesto (no se copian; se avisa: «esta escena necesita ABC Retime»).

**Deferido (campo reservado en schema):** IES, fuentes (MoText), OCIO (C4D 2026 lo embebe por escena), audio, Substance. Hashes (`hash: null` en v1).

## Schema del manifiesto (v1)

```json
{
  "schema": 1,
  "generado": "<ISO-8601>",
  "escena_origen": {"filename": "...", "version": "v012", "status": "FINAL", "artista": "..."},
  "qc": {"passed": 11, "total": 12, "new": 1, "accepted": 2, "ruleset": "<nombre>"},
  "cobertura": "completa | parcial (<motivo, p.ej. Octane container-only>)",
  "estado_scan": "ok | fallido",
  "plugins_requeridos": [{"nombre": "ABC Retime", "plugin_id": 123456}],
  "assets": [
    {"path": "tex/madera.jpg", "tipo": "textura", "origen": "rs_nodegraph",
     "estado": "copiado | faltante | externo", "hash": null}
  ]
}
```

## Manejo de errores

- `LoadDocument` del colectado falla → manifiesto con `estado_scan: "fallido"` + aviso visible. **Nunca un manifiesto silenciosamente vacío** (anti falsa-confianza).
- Renderer con cobertura parcial del escáner (p. ej. Octane node-graph sin introspección) → `cobertura: "parcial (...)"` declarada en manifiesto y diálogo; no se finge completitud.
- Secuencia con huecos → asset marcado con conteo esperado/encontrado.
- Sidecars de Sentinel (baseline, notes, rules) ya viajan con el Collect actual; el manifiesto verifica su presencia como assets más.

## Testing y verificación (escalera obligada)

1. **pytest** sobre `manifest.py` con árboles dummy: paquete completo / faltante / externo / secuencia con hueco / scan fallido / cobertura parcial (~15-20 tests, sin C4D).
2. **Fixtures C4D:** colectar `tests/fixtures/violating.c4d` con una textura movida a propósito → el manifiesto lista exactamente esa como `faltante`; `clean.c4d` colectada → 0 issues.
3. **Peldaño de producción real (innegociable — lección I1):** colectar una entrega real reciente y verificar el manifiesto contra el contenido conocido, **antes de merge**. La lección: pytest + review adversarial dejaron pasar 2 falsos positivos en postrender que solo el run real cazó.
4. **Recepción:** abrir el paquete en segunda máquina/usuario → resumen de handoff correcto + «Verificar entrega» detecta un fichero borrado a propósito.

## Fuera de alcance (explícito)

- Validación de granja / pre-flight de submission (dolor secundario declarado; candidato a ciclo posterior).
- Hashes y certificado attestation (escenario adversarial no aplica al receptor real).
- `verify.py` standalone para receptores sin C4D.
- Cambios en el pre-flight QC del Collect existente.
