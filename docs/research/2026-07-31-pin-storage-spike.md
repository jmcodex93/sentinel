# Spike — almacenamiento, undo y detección de geometría para Sentinel Pin (v1.35)

**Fecha**: 2026-07-31 · **Entorno**: C4D 2026.303 vía MCP `exec_python`.
**Método**: documentos throwaway creados e insertados solo cuando el undo lo exigía, y cerrados con `KillDocument` en un `finally`. Verificado al terminar: la escena activa del usuario intacta (8 objetos, 5 materiales), sin documentos de prueba abiertos.

---

## 1. ¿Un `BaseContainer` anidado dentro de un TAG sobrevive a guardar + recargar?

**Por qué bloqueaba**: el spec eligió "los pins viven en el tag, sin sidecar" apoyándose en que un contenedor anida dentro de otro **en memoria**. Nadie había comprobado que eso atraviese el `.c4d`. Un "no" obligaba a un sidecar y a otro spec.

Contenedor con string, float, vector, int, un sub-contenedor, un sub-sub-contenedor y una matriz, metido en el contenedor de un tag; guardar; cargar; leer todo.

```
string  : 'wide angle'          True
float   : 3.5                   True
vector  : Vector(10, 20, 30)    True
int     : 7                     True
subcont : ('ctrl', Vector(1,2,3))
nieto   : 'nieto'
matriz  : Vector(5, 6, 7)       True
```

**Veredicto: SÍ, a cualquier profundidad.** El diseño sin sidecar se sostiene.

**Regalo no previsto**: `SetMatrix`/`GetMatrix` funcionan en un contenedor y round-trippean. La transformación se guarda **entera**, sin descomponerla en vectores como habría hecho falta si no.

---

## 2. ¿Un solo bracket de undo cubre `SetData` + `SetMl` + `SetName` sobre varios objetos?

Esta es la restricción "un solo Cmd+Z" del spec, así que había que medirla.

**Tres intentos fallidos, y los tres eran mi prueba, no el undo.** Merece quedar escrito porque cada uno es una trampa reutilizable:

1. Documento **no insertado** en la lista de documentos → `DoUndo()` devuelve `True` y no revierte.
2. `DoUndo()` desde script → poco fiable; **ya estaba documentado en este proyecto** desde v1.5.7 y lo re-derivé por no leer mis propias notas.
3. `CallCommand(12105)` (el undo del menú) leyendo el estado en la misma llamada, y también en llamadas separadas → seguía "sin revertir".

La sonda que lo resolvió separó dos preguntas:

```
A) undo de inserción:            objetos 1 -> 0        FUNCIONA
B) leyendo MI handle tras undo:  radius = 999.0        "no revierte"
C) ¿mismo objeto en el doc?      False
   radius leído DEL DOCUMENTO:   10.0                  SÍ revirtió
```

**Veredicto: el undo funciona.** Al restaurar, **C4D reemplaza el objeto**: el handle que tenías queda desconectado del documento y sigue mostrando los valores mutados. Misma familia que `MoveToGroup` invalidando handles (v1.33).

**Consecuencia para quien verifique**: tras un undo hay que **volver a buscar el objeto en el documento**. Leer el handle anterior mide un huérfano y miente en la dirección más peligrosa — te hace creer que el undo está roto cuando funciona.

---

## 3. ¿Botones por fila dentro de un grupo multi-columna?

**No verificable en este harness.** Registrar un `TagData` en caliente desde `exec_python` falla con `OSError: cannot find pyp file` — el registro exige un plugin cargado desde disco, es decir `sync.sh` + reinicio.

Lo que sí hay: `frame_tag.py:1775-1781` fija `DESC_CUSTOMGUI = CUSTOMGUI_BUTTON` para `DTYPE_BUTTON`, con un comentario que dice que **sin eso el grupo de acciones sale vacío** — o sea que alguien observó ambos estados en este mismo código. Es evidencia real, más débil que una medición fresca.

**Punto de verificación**: Tarea 3, paso 6 (tras `sync.sh` + reinicio). Si los botones no renderizan en un grupo de 5 columnas, el coste es rehacer el layout de la fila, no el diseño.

---

## 4. ¿Cómo se detecta geometría editable?

| Objeto | `isinstance(obj, c4d.PointObject)` | `GetPointCount()` |
|---|---|---|
| Cube paramétrico | `False` | — |
| Polygon object (vacío) | `True` | 0 |
| Polygon con puntos | `True` | 8 |
| Null | `False` | — |
| Camera | `False` | — |

**El test que usa el writer**: `isinstance(obj, c4d.PointObject)`. Distingue lo paramétrico (que sí capturamos entero) de lo que tiene puntos y polígonos fuera del contenedor. `GetPointCount()` no hace falta: un objeto poligonal vacío hoy puede no estarlo mañana, así que la advertencia debe salir igual.

---

## Constantes y reglas que consume la implementación

- Los pins caben en el contenedor del tag; **sin sidecar**.
- La matriz se guarda con `SetMatrix`, entera.
- `AddUndo(UNDOTYPE_CHANGE, obj)` antes de escribir, todo dentro de un `StartUndo`/`EndUndo`: un solo paso.
- **Al verificar un undo, re-buscar el objeto en el documento** — nunca leer el handle previo.
- Advertencia de geometría: `isinstance(obj, c4d.PointObject)`.

---

## 5. Iconos por instancia de tag (añadido 2026-07-31, tras comparar con la UI de Recall)

**Por qué**: elegimos *un tag por pin* con el argumento de que se ven los estados en el Object Manager sin abrir nada. Sin icono propio, varios pins son iconos idénticos y hay que pasar por encima para leer el nombre — el hueco ataca justo la razón del modelo. Recall dedica una sección entera a esto (color + número o letra).

| Pieza | Resultado |
|---|---|
| `c4d.MSG_GETCUSTOMICON` | existe (**1001090**) |
| `c4d.IconData` | existe; campos `bmp`, `x`, `y`, `w`, `h`, `flags` |
| `GeClipMap.Init(32,32,32)` | OK |
| `SetColor` + `FillRect` | OK — píxel central leído `[220,80,60]` |
| `GeClipMap.GetDefaultFont(GE_FONT_DEFAULT_SYSTEM)` | disponible |
| `SetFont` + `TextAt` | **dibuja de verdad**: 0 píxeles distintos del fondo antes, **95 después** |
| `GetBitmap()` | devuelve un `BaseBitmap` 32×32 usable |

**Veredicto: viable.** Se genera el icono en memoria (fondo del color elegido + carácter encima) y se entrega respondiendo a `MSG_GETCUSTOMICON` con un `IconData`.

**Lo que NO se pudo medir aquí**: que un `TagData` reciba efectivamente `MSG_GETCUSTOMICON`. `SetFont` exige un `BaseContainer` de descripción de fuente: pasar `None` lanza.

### RESULTADO NEGATIVO, medido después (2026-07-31)

**`MSG_GETCUSTOMICON` NO llega a un `TagData`** en C4D 2026.303. Implementado el handler, sincronizado y reiniciado: ningún pin muestra la letra y el desplegable de color no hace nada. Tampoco se puede simular desde script — `C4DAtom.Message` en Python exige un `dict`, así que un `IconData` no se puede pasar; solo C4D envía ese mensaje.

**Y sobraba de todos modos**: la pestaña **Basic** de cualquier tag ya trae un grupo `ICON` con `Icon File / ID`, casilla **`Icon Color`**, selector de color y presets. Marcar `Icon Color` tiñe el icono del tag en el Object Manager — exactamente lo que la tarea pretendía construir.

**Lección, segunda vez en esta misma feature** (la primera fue el campo de nombre): **antes de construir algo para un tag, mirar qué trae ya su pestaña Basic**. Nombre, icono y color están ahí. Duplicarlos crea dos controles compitiendo, y el nuestro pierde.

Todo el código del icono se retiró. Distinguir pins en el Object Manager se hace con el `Icon Color` nativo.
