---
module: multiformat/framing/frame_tag
tags: [redshift, camera, takes, overrides, crop, orscamera, spike]
problem_type: api-behavior
---

# RS camera (ORSCAMERA) + Take overrides — spike live C4D 2026.303 (Frame v2, Task 1)

Spike medido con render real (cubo 200 en origen relativo, cámara a −600, RD 640×360 RS; medición en píxeles con predicción exacta antes de cada test). Escena: doc del usuario con env-light RS; geometría de test aislada en y=10000; todo limpiado al terminar.

## Matriz definitiva (FindOrAddOverrideParam POR PARÁMETRO sobre cámara PRÍSTINA)

| Palanca (override por Take) | Ocamera | ORSCAMERA (1057516) | Evidencia |
|---|---|---|---|
| focal — id **500** (REAL) | (v1.8.0 verificado) | ✅ EXACTO | 500=70 → 498px predicho/medido |
| aperture/sensor — **1006** (REAL) / **7002** (Vector) | ✅ EXACTO | ✅ EXACTO (Vector entero) | 1006=18 → 498px; 7002=(18,12) → 498px |
| film offset / shift — 1118/1119 / **7012** (Vector) | (v1.8.0 verificado) | ✅ EXACTO | 7012=(0.25,0) → desplazamiento 160px = 0.25×640, tamaño intacto |

## Modelo de la ORSCAMERA (descubierto por predicción exacta)

- **El render deriva FOV = 2·atan(sensor_7002.x/2 ÷ focal_500)**. El id **500** ("Focal Length" compat-C4D) es el que lee el RENDERER. Verificado: cámara fresca trae 500=35 y 7003=36 → el baseline midió atan(18/**35**), no 18/36.
- **7003 ("Focal Length (mm)" del AM) es un conveniente de UI**: escribirlo re-deriva el SENSOR para preservar el ángulo de visión (escribir 7003=72 escaló sensor 36→72). No es el focal del render.
- **4601 (Vector, oculto) = AOV almacenado** (horizontal, vertical) — estado derivado interno.
- Sensor Y se re-deriva del film aspect con Fit=Horizontal (7005=1, default): Y = X / aspect.
- **Shift 7012**: unidades = **fracción del ancho de frame** (gate-relativo); +X desplaza el contenido a la izquierda. Misma semántica que el film offset de Ocamera, empaquetada en Vector. Vector entero overrideable.
- Fit (7005): 0=Fill-Crop 1=Horizontal 2=Vertical 3=Overscan 4=Square. Tests hechos con el default Horizontal. Preset 7001=127 (Full Frame 36×24).
- 7013 "Mode" es modo ESTÉREO (Side by Side/Top Bottom/L/R), no proyección.

## Hallazgo crítico de seguridad: NUNCA escribir params base de la ORSCAMERA en crudo

Escribir 7002/7003/500 directamente en el nodo base desincroniza el estado acoplado (4601/7003/sensor se re-derivan parcialmente) → la cámara queda en estado híbrido irreproducible (medimos bases contaminadas de 293×272 px no-cuadradas). **Los overrides por Take sobre cámara prístina son exactos; los writes en base son veneno.** El invariante de Sentinel ("la cámara master nunca se muta") no es solo UX — es requisito de corrección.

## Otros hallazgos

- El `take_override` del MCP (OverrideNode) hace snapshot de TODO el nodo (199 descids, incluido el AOV 4601 congelado) → resultados incoherentes. El mecanismo correcto es el de Sentinel: `FindOrAddOverrideParam` por parámetro (deja exactamente 1 descid).
- **Re-explicación de v1.8.0**: "RS ignora aperture" = escribir el id 1006 de Ocamera sobre ORSCAMERA (inerte, el id no existe ahí). "Focal funciona" = el id 500 existe en ambos nodos y el renderer RS lo lee. **El bug del nudge WYSIWYG**: FILM_OFFSET_X/Y (1118/1119, Ocamera) son inertes en ORSCAMERA → el nudge se veía en guías pero no en el render. Fix: 7012.

## DECISIÓN para el writer (Task 2)

- `ORSCAMERA_TYPE = 1057516`; `RS_SENSOR_SIZE = 7002` (Vector, mm); `RS_SENSOR_SHIFT = 7012` (Vector, fracción de frame); focal compat = 500.
- **Ocamera** → crop por `CAMERAOBJECT_APERTURE` (1006) × factor + `FILM_OFFSET_X/Y`.
- **ORSCAMERA** → crop por `7002 = Vector(x×factor, y×factor, 0)` + nudge por `7012 = Vector(nx, ny, 0)` (mismos valores gate-relativos que el film offset).
- Ambos preservan focal → DOF y animación de focal intactos en Ocamera. **Edge diferido a la matriz final**: focal ANIMADA en ORSCAMERA (¿la animación va por 7003 re-derivando sensor y pelearía con el override de 7002?) — verificar en la matriz live; si pelea, fallback focal-500 para cámaras RS con focal animada.
- No testeado (bajo riesgo/no usado por el estudio): Ocamera+tag RS legacy; Fit≠Horizontal (leer 7005 y si ≠1, avisar o normalizar).
- Conversión estándar→RS con Takes viejos: los overrides Ocamera viejos quedan inertes (no rompen); el auto-sync debe detectar el cambio de tipo (GetType en la firma) y regenerar limpio.
