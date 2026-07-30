# Spike live — OpenPBR en Redshift (v1.34)

**Fecha**: 2026-07-30 · **Entorno**: C4D 2026.303, Redshift, vía MCP `exec_python`.
**Método**: materiales construidos sobre un `BaseDocument()` throwaway (nunca insertado en C4D), renders 100×100 con la RenderData del doc activo clonada, `RENDERFLAGS_EXTERNAL`, píxeles leídos con `GetPixel`. Cero residuo en la escena del usuario (verificado: 0 materiales filtrados).

Las cuatro preguntas que el spec dejó abiertas, respondidas con medidas.

---

## 1. `geometry_normal` — ¿acepta el nodo `bumpmap`? (riesgo alto)

**Por qué importaba**: en Standard el nodo `bumpmap` entra en `bump_input`. El puerto de OpenPBR se llama *normal*, no *bump*. Si esperase otra cosa, el material se vería igualmente y solo el **relieve** estaría mal — un fallo silencioso. Por eso se verifica renderizando, no leyendo parámetros.

Normal map generado con relieve real (ondas seno en X e Y, tangent-space), no el plano `(128,128,255)`.

| Comparación | Píxeles distintos | Max diff |
|---|---|---|
| OpenPBR **con** normal vs **sin** normal | **2957/10000** | 253 |
| OpenPBR con normal vs Standard con normal | 1579/10000 | 38 |

**Veredicto: ACEPTA.** El mapa hace algo grande y evidente (2957 px, max 253). Frente a Standard la diferencia es pequeña y del orden esperado de dos BRDF distintos con el mismo relieve — no de un relieve ausente o invertido.

**Consecuencia para el writer**: la rama de normal/bump no cambia; solo el id del puerto destino.

---

## 2. `emission_luminance` — qué valor escribir

**Por qué importaba**: nace a **0**, igual que el `emission_weight` de Standard — la trampa que v1.32 documentó (los tres plugins del mercado entregan emisión invisible). Pero *luminance* no es un peso 0-1, así que el 1.0 de Standard no se hereda.

Barrido con el mismo mapa de emisión, media global de píxel (media sobre TODOS los píxeles; una primera medición promediando solo píxeles "encendidos" salió no-monótona porque al subir la emisión entran más píxeles al denominador — métrica descartada):

| `emission_luminance` | media global | ratio vs Standard |
|---|---|---|
| 1 | 2.36 | 0.10× |
| 10 | 2.61 | 0.11× |
| 100 | 5.49 | 0.23× |
| 200 | 8.74 | 0.37× |
| 300 | 11.99 | 0.51× |
| 500 | 18.42 | 0.78× |
| 1000 | 34.50 | 1.46× |

Referencia: Standard con `emission_weight = 1.0` → media global **23.63**. Con emisión ~0 la media es 2.36 (solo el base color).

Por encima de 100 la respuesta es **lineal**: ~3.22 de media global por cada 100 de luminancia.

**HALLAZGO que cambia la pregunta**: la equivalencia **no es independiente de la escena**. El `emission_weight` de Standard escala una textura; el `emission_luminance` de OpenPBR es una magnitud absoluta en nits. El valor que iguala a Standard *en esta escena y con esta exposición* es ≈ **660** (interpolando entre 500 y 1000), y sería otro con otra iluminación. Perseguir esa igualdad sería fijar en el writer un número atado a mi escena de prueba.

**Decisión: `1000`.** Es la referencia estándar de blanco HDR en nits — un número redondo y justificable en vez de un ajuste a mi test — y renderiza 1.46× la referencia de Standard, es decir **claramente visible**, que es el objetivo real heredado de v1.32. Es una constante de una línea: si en producción se ve fuerte, se baja sin tocar arquitectura.

```python
BRDF_EMISSION_AMOUNT = {"standard": 1.0, "openpbr": 1000.0}
```

---

## 3. `rsmathinv` — puertos y que invierta de verdad

Disponibilidad: `rsmathinv` ✅ · `rsmathinvcolor` ✅ · `rscolorinvert` ❌ (no existe).

| Nodo | Entradas | Salida |
|---|---|---|
| `rsmathinv` | `input` (Float64), `math_op` (Int64) | `out` |
| `rsmathinvcolor` | `input` (ColorA64), `applytoalpha`, `math_op` | `outcolor` |

**Trampa detectada**: ambos llevan un puerto **`math_op`**, que nace en **20**. Misma clase que el `uv_tiling = 1` de v1.33, que resultó ser *hex tiling* y no "tiling normal": un enum sin documentar del que no se puede asumir el significado.

Verificado con oráculo de render — gloss pasado por `rsmathinv` con `math_op` por defecto, contra un mapa de roughness que es el complemento exacto (`255 − v`):

| Comparación | Píxeles distintos | Max diff |
|---|---|---|
| `gloss → rsmathinv` vs `roughness = 1 − gloss` | **1/10000** | **1** |
| `gloss → rsmathinv` vs `gloss sin invertir` (control) | 2770/10000 | 106 |

**Veredicto: `math_op = 20` ES `1 − x`.** Un píxel difiriendo en 1/255 es ruido de cuantización, no señal; y el control demuestra que el oráculo discrimina con holgura.

Se usa **`rsmathinv`** (escalar): el destino `specular_roughness` es escalar, y RS ya convierte la salida del sampler igual que hace hoy en Standard.

**El writer escribe `math_op = 20` EXPLÍCITAMENTE**, aunque sea el default. Es la regla de la casa que ya rige colorspaces, `flipy` y `uv_tiling`: el grafo no descansa sobre un default de nodo que una versión futura podría cambiar en silencio. (No aplica la excepción del `rscolorcorrection`, donde no se escribe nada porque el estado por defecto *es* la identidad medida y escribir constantes sería adivinar; aquí 20 es una operación medida y nombrada de la que dependemos.)

```python
_RS_INVERT = _RS_CORE + "rsmathinv"
_RS_INVERT_INPUT = _RS_INVERT + ".input"
_RS_INVERT_MATH_OP = _RS_INVERT + ".math_op"
_RS_INVERT_OP_INVERT = 20          # medido: 1 - x
```

---

## 4. Displacement sobre OpenPBR

Grafo `output.surface = openpbrmaterial` + `output.displacement = displacement(texmap=sampler)`:

```
nodos: ['displacement', 'openpbrmaterial', 'output', 'texturesampler']
output.surface       conexiones=1
output.displacement  conexiones=1
```

**Veredicto: sin cambios.** El displacement cuelga del nodo de salida, no del BRDF, así que la rama existente vale tal cual.

---

## Constantes que consume el writer

```python
BRDF_EMISSION_AMOUNT = {"standard": 1.0, "openpbr": 1000.0}

_RS_INVERT = _RS_CORE + "rsmathinv"
_RS_INVERT_INPUT = _RS_INVERT + ".input"
_RS_INVERT_MATH_OP = _RS_INVERT + ".math_op"
_RS_INVERT_OP_INVERT = 20          # medido: 1 - x (default, escrito explícito)
```

## Lo que NO se probó

- Los canales exclusivos de OpenPBR (coat, fuzz, subsurface, thin-film): fuera de alcance por spec, ningún pack PBR estándar los entrega sueltos.
- `rsmathinvcolor`: existe y podría servir, pero no se necesita — no se eligió a ciegas, se descartó porque el destino es escalar.
- La equivalencia de emisión en escenas con otra exposición: por definición no es transferible (ver §2).
