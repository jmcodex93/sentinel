# Sentinel Pin — estados por objeto a los que volver (v1.35)

**Fecha**: 2026-07-31
**Estado**: aprobado en brainstorm, pendiente de plan.
**Contexto**: primera de las dos capas del arco "puntos de retorno", que cierra la expansión de Tools (v1.30 quick-wins → v1.31 Batch Rename → v1.32-v1.34 matwire → **v1.35 este spec** → v1.36 red automática).

Nace de un plugin que el usuario compró y **ya no puede ejecutar**: Rocket Lasso Recall (binario C++, última build R25; C4D 2026 está cuatro versiones mayores por delante). No es competir con una herramienta en uso — es recuperar una capacidad perdida. Su EULA prohíbe descompilar, así que **no se examinó el binario**: lo que se estudió son su documentación pública, sus recursos en texto plano y la API de C4D medida directamente.

## Hechos medidos antes de diseñar

Todo leído del C4D vivo (2026.303, 2026-07-31):

| Hecho | Consecuencia de diseño |
|---|---|
| `GetData()`/`SetData()` devuelven y reponen **los parámetros propios** del objeto, sin saber qué significan (un Alembic Generator de terceros da 23 entradas) | La captura es **genérica**: funciona con X-Particles, Forester o cualquier plugin |
| La **transformación NO está** en ese contenedor — vive en la matriz (`GetMl`/`SetMl`) | Se capturan por separado; asumirlo habría restaurado un rig con los parámetros bien y en el sitio equivocado |
| El **nombre** tampoco está | Se captura aparte |
| Un `BaseContainer` **anida** dentro del de un tag | Los pins caben en el tag y viajan con el `.c4d`, sin sidecar |
| **Ningún id nativo sobrevive a guardar+cargar**: `GetGUID()` y `FindUniqueID(MAXON_CREATOR_ID)` se regeneran | El emparejamiento al restaurar es **por ubicación**, nunca por id. Ver [[reference_c4d_object_identity]]; este mismo hecho causó el bug del baseline corregido en v1.34.1 |
| La geometría editable (puntos/polígonos) y los grafos maxon (materiales RS) **no están** en el contenedor | Fuera de alcance, y **dicho en la UI**, no en la documentación |

## Decisiones cerradas

1. **Un tag por objeto** (`Sentinel Pin`), no una lista en el panel: la visibilidad en el Object Manager es la mitad del valor — ves que ese null tiene estados sin buscarlos. Un listado en el panel puede añadirse después leyendo lo que el tag ya guarda, sin rehacer nada.
2. **Captura el objeto y toda su descendencia.** Un rig paramétrico casi nunca es un nodo: tocas el Cloner, el Effector y el falloff. Si hubiera que etiquetarlos uno a uno, la herramienta estorbaría más de lo que ayuda.
3. **Seis slots fijos, más uno reservado.** Seis cubre el caso más exigente (un set de cámaras: wide/mid/close/top/side/hero) y a partir de ahí dejas de recordar qué guardaste. Un número fijo obliga a decidir qué sobrescribes, lo cual es sano frente a acumular estados sin nombre.
4. **El séptimo slot es "Antes de restaurar"**, escrito por la herramienta en cada salto. Es la decisión central del diseño (ver abajo).
5. **Sin colores.** Con nombre editable y contador de objetos, el color solo añade ruido.
6. **Sin confirmación al restaurar.** Es reversible por dos vías y un diálogo mataría lo único que hace útil esto: saltar rápido entre alternativas.
7. **Nombre "Pin"** elegido tras comprobar colisiones sobre los 427 tags/objetos registrados en el C4D del usuario: `Pose` (Pose Morph, PoseMixer), `State` (Initial State Tag), `Rest` (Octane Rest Position) y `Look` están ocupados; `Mark` y `Shot` los usa ya Sentinel para otra cosa.

## Diseño

### El slot reservado, y por qué es lo más importante

El miedo real al restaurar no es perder el pin: es perder **lo que tienes ahora**, que no habías guardado porque ibas a probar un momento. Cmd+Z solo cubre eso si no haces nada más después, y siempre haces algo más después.

Cada vez que se restaura un pin, la herramienta **captura primero el estado actual** en el slot reservado. Saltar pasa a ser gratis: si no era eso, vuelves. Cuesta exactamente lo mismo que ya cuesta guardar un pin, y es la diferencia entre una herramienta que usas y una que te da respeto.

### Qué guarda un pin

Por cada objeto cubierto (el del tag y toda su descendencia, en recorrido determinista):

- el `BaseContainer` propio del objeto,
- su matriz local,
- su nombre,
- su **ubicación**, que es la clave de reemparejamiento: la ruta de nombres desde el objeto del tag hasta él, más el índice entre los hermanos que comparten nombre. Se define **dentro del subárbol del pin**, no desde la raíz de la escena, para que mover el rig entero a otro sitio no invalide sus pins.

  Hereda la debilidad que ya está documentada para el baseline ([[reference_c4d_object_identity]]): renombrar un objeto lo desemparejará, y renumerar hermanos homónimos puede emparejar el equivocado. Se acepta con los ojos abiertos — no existe id estable en C4D — y por eso el resultado de cada restauración **se reporta** en vez de darse por bueno.

Más, por pin: nombre editable, fecha, y el número de objetos cubiertos.

### Restaurar

En **un solo paso de deshacer**. Cada objeto reencontrado por ubicación recupera su contenedor, su matriz y su nombre. Nada se crea ni se borra: un pin no reconstruye objetos que ya no existen ni elimina los que aparecieron después.

El resultado se reporta siempre: *"9 de 12 restaurados · 3 no encontrados"*, con la lista de los que faltan. Nunca falla en silencio ni deja el rig a medias sin decirlo.

### La fila de un slot

```
● wide angle          12 obj · hace 2 h        [ Ir ]  [ Re-pin ]  [ ✕ ]
● falloff v2           3 obj · ayer 18:40      [ Ir ]  [ Re-pin ]  [ ✕ ]
○ vacío                                        [ Pin aquí ]
○ vacío                                        [ Pin aquí ]
○ vacío                                        [ Pin aquí ]
○ vacío                                        [ Pin aquí ]
─────────────────────────────────────────────────────────────
↩ Antes de restaurar   12 obj · hace 1 min     [ Ir ]
```

El **contador de objetos no es decoración**: dice de un vistazo si el pin cubre el rig entero o solo el nodo que tocaste, y es la primera señal de que la jerarquía cambió.

### Decir la verdad sobre lo que no captura

Un artista va a pinchar un objeto poligonal esperando recuperar el modelado, y no va a volver. Si algún objeto cubierto tiene geometría editable, **la fila lo dice** — *"geometría no incluida"* — en el momento de guardar, no en un manual. Misma regla que ya rige el preview de matwire: una fila no promete un cableado que el writer no va a hacer.

### Identificadores de plugin

El tag usa **`2099078`**. Ocupados hoy en el rango `2099xxx`: `2099069` (plugin), `2099073` (Sentinel Frame tag), `2099075` (palette), `2099077` (frame sync MessageData); `2099072` retirado y no reutilizable. `2099078` está libre — verificado por grep sobre `plugin/`, el mismo método con el que se eligieron los anteriores, y queda registrado en el comentario del `.pyp` junto a ellos.

## Errores

- Objeto del pin borrado, o tag sin objeto: el tag no puede existir sin su host, así que el caso no se da; si el host se renombra, los pins siguen (la ubicación del host es su propia ruta).
- Jerarquía cambiada: se restaura lo reconocido y se reporta lo demás (arriba).
- Un pin guardado con una versión anterior del esquema: se ignora con un aviso en la fila, nunca se aplica a medias.
- Restaurar sin nada que restaurar (todos los objetos desaparecieron): no se toca la escena y se dice.

## Verificación

- **pytest** sobre el motor puro: recorrido determinista de la jerarquía, construcción de la clave de ubicación, plan de restauración con objetos ausentes y sobrantes, y el pin automático al slot reservado.
- **Live en C4D**, que es donde esto se demuestra:
  - Pinchar un rig paramétrico (Cloner + Effector + falloff), destrozar los tres, restaurar, y comprobar **parámetros y transformaciones** de los tres — no solo que "se ve bien".
  - Un objeto de plugin de terceros dentro de la jerarquía, para probar que la captura es genérica.
  - Restaurar tras borrar un objeto y añadir otro: conteo correcto y reporte honesto.
  - **Un solo Cmd+Z** revierte una restauración completa.
  - El slot "Antes de restaurar" permite volver al estado previo a un salto.
  - Guardar la escena, reabrirla, y comprobar que los pins siguen ahí y **siguen restaurando** — el caso que el bug del baseline demostró que hay que probar explícitamente.

## Fuera de alcance

- **La capa automática** (snapshot de documento antes de operaciones destructivas de Sentinel): es v1.36, mecanismo distinto y palabra distinta — ahí sí es un punto de retorno, no una alternativa.
- **Geometría editable y grafos de nodos**: no están en el contenedor. Capturarlos exigiría clonar y reemplazar el objeto, lo que rompe los `BaseLink` que le apunten (constraints, XPresso, un Sentinel Frame apuntando a esa cámara) — y fallaría en silencio. Si algún día se aborda, va con su spike.
- **Listado de pins en el panel** y colores por slot.
