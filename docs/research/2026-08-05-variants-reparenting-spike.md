# Spike — reparentado: undo en un paso, BaseLinks y transformación (Sentinel Variants, v1.36)

**Fecha**: 2026-08-05 · **Entorno**: C4D 2026.303 vía MCP `exec_python`.
**Método**: documento throwaway **insertado** en la lista de documentos (sobre uno no insertado el undo devuelve `True` y no revierte — medido en el spike del Pin §2), cerrado con `KillDocument` en un `finally`. El undo se dispara con el comando del menú (`CallCommand(12105)`), nunca con `DoUndo()` desde script. **Toda lectura posterior a un undo re-busca el objeto en el documento por nombre**: C4D lo reemplaza al restaurar y el manejador anterior mide un huérfano.

Las tres preguntas venían del spec: cada una cambiaba el diseño si salía mal.

---

## 1. ¿Un reparentado se revierte con UN solo Cmd+Z, a la jerarquía exacta?

Montaje: `raiz → padre_a → [hermano, hijo → nieto]`, más un `padre_b` hermano. `hijo` se mueve a `padre_b` con `Remove()` + `InsertUnder()` dentro de un `StartUndo`/`EndUndo`. El índice entre hermanos de `hijo` bajo `padre_a` es **1**, no 0, a propósito: un undo que devuelve el objeto al padre correcto pero en otro orden no es "la jerarquía exacta".

Oráculo tras el undo: padre de `hijo`, su índice entre hermanos, que `nieto` siga colgando de él, y que siga siendo el mismo objeto.

```
inicial esperado: (padre_a, 1, True, True)
BASE   movido=(padre_b,0,True,True)  vuelve=False  pasos=>5
A      movido=(padre_b,0,True,True)  vuelve=True   pasos=1  final=(padre_a,1,True,True)
B      movido=(padre_b,0,True,True)  vuelve=True   pasos=1  final=(padre_a,1,True,True)
C      pasos=1  padre=padre_a  idx=1  nieto_ok=True
```

- **BASE** (sin ningún `AddUndo`): **no revierte** ni tras 5 pasos. Es el control que valida la sonda — sin él, un "vuelve=True" no probaría nada.
- **A** — `AddUndo(UNDOTYPE_CHANGE, hijo)` antes de mover: **1 paso, jerarquía exacta**.
- **B** — `AddUndo(UNDOTYPE_CHANGE, padre_a)` + `(..., padre_b)`: **1 paso, jerarquía exacta**.
- **C** — `AddUndo(UNDOTYPE_DELETEOBJ, hijo)` antes + `AddUndo(UNDOTYPE_NEWOBJ, hijo)` después: **1 paso, jerarquía exacta**.

**Veredicto: las tres funcionan.** Se adopta **A**: un solo `AddUndo` sobre el objeto que se mueve, antes de moverlo. Es la más simple y la que menos supone sobre la estructura (B necesita conocer ambos padres; C abre y cierra un par cuyo desbalanceo ya causó un bug real en matwire v1.32).

---

## 2. ¿Un enlace que apunta DENTRO de lo que se mueve sigue resolviendo?

Era el "requisito central" que el spec derivaba del spike de aislamiento: si aparcar rompe los enlaces, el mecanismo entero queda en cuestión.

Montaje: `hijo → objetivo`, y **fuera** del subárbol una cámara con un Target tag (`Ttargetexpression`, `TARGETEXPRESSIONTAG_LINK`) apuntando a `objetivo`. Cada lectura re-busca el tag por nombre.

```
base (antes de mover):          objetivo
tras mover a padre_b:           objetivo
tras aparcar en raiz:           objetivo
tras guardar+cargar APARCADO:   objetivo
```

**Veredicto: el enlace aguanta todo** — mover de padre, aparcar en la raíz con la visibilidad apagada, y guardar + cargar apuntando **dentro de un subárbol aparcado**, que es el caso que de verdad importa (la mitad de las opciones estarán aparcadas al guardar).

**Consecuencia**: no hay límite que declarar en la fila del tag por este motivo. El riesgo que el spec marcaba como central **no se materializa** con `BaseLink`. Nota de alcance: medido con un Target tag; otros tags con enlaces (Constraint, XPresso) no se probaron uno a uno — comparten el mecanismo `BaseLink`, pero eso es un argumento, no una medición.

---

## 3. ¿Reparentar conserva la transformación en el mundo?

El spec lo **afirmaba**. Medido con una matriz global no trivial —posición, rotación **y** escala no uniformes, porque el caso fácil (solo posición) es justo el que no distingue nada— comparando `GetMg()` componente a componente con tolerancia `1e-6`.

```
caso base: matriz global no trivial = SI
1 null en IDENTIDAD   -> CONSERVA
2 null TRANSFORMADO   -> NO conserva (esperado)
3 ida y vuelta        -> CONSERVA  (aparcado conserva: True)
4 claves de animacion -> antes=[0.0, 250.0] despues=[0.0, 250.0]  INTACTAS
```

**Veredicto: el spec acertaba, y ahora está medido.** Un null en identidad conserva la transformación exacta; uno transformado no, lo que convierte "**el anclaje nace en identidad**" en un requisito con consecuencia medida, no en una preferencia de estilo. La ida y vuelta anclaje → aparcado → anclaje —que es literalmente un cambio de A a B y vuelta a A— devuelve la matriz de partida. Y las claves de animación **no se recomponen** al reparentar.

**Consecuencia**: la creación del conjunto **no** necesita recomponer matrices con `SetMg`. Se ahorra un paso que el plan tenía previsto como posible requisito de la Tarea 3.

---

## Resumen para la implementación

| Pregunta | Respuesta | Efecto |
|---|---|---|
| Undo de un reparentado | 1 paso con `AddUndo(UNDOTYPE_CHANGE, obj)` antes de mover | Se adopta la variante A |
| Enlaces al contenido movido | Sobreviven a mover, aparcar y guardar+cargar | Sin límite que declarar; el riesgo "central" no se materializa |
| Transformación en el mundo | La conserva si el nuevo padre está en identidad | El anclaje nace en identidad **por necesidad medida**; sin recomposición de matriz |
| Claves de animación | Intactas al reparentar | Sin trabajo extra |

---

## 4. ¿Cómo se lanza un render desde el plugin? (sonda de la Tarea 5)

**Por qué bloqueaba**: el spec sustituyó la salida a Takes por "renderizar todas las opciones", y **no hay ni un solo `RenderDocument` en todo el plugin** — sin patrón de casa que copiar, no se podía diseñar a ciegas.

Medido con el motor real de trabajo, **Redshift** (`RDATA_RENDERENGINE = 1036219`), a 160×120:

```
vacía    result=0 (RENDERRESULT_OK)  suma_pixeles=0      1.45s
con cubo result=0                    suma_pixeles=8058   1.03s
CASO BASE (difieren): True
Save -> 1   existe=True   bytes=1664
3 seguidos: [0, 0, 0] en 1.25s
```

**Veredicto: la vía síncrona funciona.** `documents.RenderDocument(doc, rd.GetDataInstance(), bmp, c4d.RENDERFLAGS_EXTERNAL)` devuelve `RENDERRESULT_OK` con Redshift, el bitmap trae píxeles reales, `bmp.Save(path, c4d.FILTER_PNG, None, c4d.SAVEBIT_0)` escribe el archivo, y tres llamadas seguidas no cuelgan C4D.

**El caso base era obligatorio**: una escena vacía renderiza un bitmap negro con `result=OK`, exactamente el resultado nulo que parece una respuesta. Solo comparando contra una escena con contenido (0 vs 8058) la medición dice algo.

**Consecuencia**: se implementa la vía 1 (bucle de opciones → `RenderDocument` → `Save`). La segunda vía —ruta de salida por opción + render nativo asíncrono esperando con el predicado de `renderwatch.py`— **no hace falta** y no se explora.
