# Sentinel Pin — estados por objeto a los que volver (v1.35)

**Fecha**: 2026-07-31
**Estado**: implementado y live-verified en rama feat/sentinel-pin (pytest 1195). **Modelo revisado 2026-07-31** tras ver la interfaz real de Recall: un tag = un pin, en vez de seis slots dentro de un tag. La Tarea 3 del plan (grid de seis filas) quedó obsoleta y se rehizo.
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

1. **Un tag = UN pin.** No una lista de slots dentro de un tag. Varios pins sobre un objeto son varios tags, cada uno con su nombre.

   *Corrección sobre la primera versión de este spec, tras ver la interfaz real de Recall (captura del usuario, 2026-07-31).* Su modelo es este —`Recall`/`Override` en singular, `Clear Current`, `Remove All Recall Tags` en plural, y toda una sección para personalizar el **icono del tag** con color, número o letra— y es mejor que el de seis slots por una razón que invalida mi propio argumento: defendí el tag frente al panel diciendo "ves que ese null tiene estados sin buscar nada", pero con seis slots **dentro** de un tag ves un tag, no los estados. Un tag por estado sí cumple esa promesa.

   Beneficio colateral: elimina el problema de layout en vez de maquillarlo. La primera implementación produjo un grid de seis filas donde el texto de estado se truncaba —ocultando precisamente la advertencia de geometría, que el spec declara obligatoria— porque las columnas del Attribute Manager reparten ancho entre campos que compiten. Un tag con una sola fila no tiene ese problema.

2. **Captura el objeto y toda su descendencia.** Un rig paramétrico casi nunca es un nodo: tocas el Cloner, el Effector y el falloff. Si hubiera que etiquetarlos uno a uno, la herramienta estorbaría más de lo que ayuda. Sin casillas para elegir alcance (Recall las tiene: Object / Hierarchy / Keyframes) — convención con opinión antes que knobs, como en matwire.

3. **La red de seguridad es un tag propio**, `↩ Antes de restaurar`, creado o actualizado por la herramienta en cada restauración y nunca por el artista. Es la decisión central del diseño (ver abajo) y es lo único que este diseño tiene y el de Recall no: en su interfaz no hay nada equivalente.

4. **Restaurar es el botón `Ir` del Attribute Manager, y además doble clic en el tag** desde el Object Manager (`MSG_EDIT`, id 21). El botón es el camino garantizado; el doble clic es el acelerador y se verifica en vivo — si no llegara el mensaje, se pierde el atajo, no la función.

5. **Sin confirmación al restaurar.** Es reversible por dos vías y un diálogo mataría lo único que hace útil esto: saltar rápido entre alternativas.

6. **El nombre del pin es el nombre del tag.** Así el Object Manager lo muestra al pasar por encima o seleccionarlo, sin abrir nada. **Sin iconos personalizados en v1** (Recall los tiene, con color y número o letra): generar bitmaps por color y carácter es trabajo real y no bloquea el uso. Queda anotado como el hueco visual frente a Recall — varios pins sobre un objeto se ven como iconos idénticos hasta que pasas por encima.

7. **Nombre "Pin"** elegido tras comprobar colisiones sobre los 427 tags/objetos registrados en el C4D del usuario: `Pose` (Pose Morph, PoseMixer), `State` (Initial State Tag), `Rest` (Octane Rest Position) y `Look` están ocupados; `Mark` y `Shot` los usa ya Sentinel para otra cosa.

## Diseño

### La red de seguridad, y por qué es lo más importante

El miedo real al restaurar no es perder el pin: es perder **lo que tienes ahora**, que no habías guardado porque ibas a probar un momento. Cmd+Z solo cubre eso si no haces nada más después, y siempre haces algo más después.

Cada vez que se restaura un pin, la herramienta **captura primero el estado actual** en un tag `↩ Antes de restaurar` sobre el mismo objeto — creándolo si no existe, sobrescribiéndolo si ya está. Saltar pasa a ser gratis: si no era eso, vuelves. Cuesta exactamente lo mismo que ya cuesta guardar un pin.

Restaurar DESDE ese tag no lo sobrescribe: si lo hiciera, destruiría la única copia del estado del que estás volviendo.

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

### La interfaz del tag

Una sola fila, porque el tag es un solo pin:

```
Nombre   [ wide angle                    ]
Estado     12 obj · hace 2 h · geometría no incluida · 8 pistas · 2 pistas no incluidas
           [ Pin ]   [ Ir ]
```

*(Actualizado tras la Tarea 6, que capturó y restauró las pistas
CTRACK_CATEGORY_VALUE de verdad — ver más abajo. "pistas" es lo capturado
y restaurable; "pistas no incluidas" es lo que sigue sin poder capturarse,
nunca lo que había en el diseño original de este spec.)*

El **estado es texto estático**, no un campo: es dato de solo lectura y meterlo en una caja editable invita a escribir en ella y además le roba ancho al nombre — que fue exactamente el fallo de la primera implementación.

El **contador de objetos no es decoración**: dice de un vistazo si el pin cubre el rig entero o solo el nodo que tocaste, y es la primera señal de que la jerarquía cambió.

### Decir la verdad sobre lo que no captura

Un artista va a pinchar un objeto poligonal esperando recuperar el modelado, y no va a volver. Si algún objeto cubierto tiene geometría editable, **la fila lo dice** — *"geometría no incluida"* — en el momento de guardar, no en un manual. Misma regla que ya rige el preview de matwire: una fila no promete un cableado que el writer no va a hacer.

**Y lo mismo con los keyframes, que era peor porque era silencioso — hasta la Tarea 6, ejecutada dentro de este mismo release.** Recall los captura (casilla `Keyframes` en su interfaz); la primera versión de este spec dejaba a Sentinel Pin solo avisando. Consecuencia concreta que motivó la Tarea 6: si un parámetro está **animado**, restaurar solo su valor estático no hace nada visible — la pista lo sobrescribe en el siguiente cambio de frame. El pin sería un no-op justo en los rigs animados, que es media razón de ser de la herramienta. Así que **las pistas `CTRACK_CATEGORY_VALUE` (claves escalares simples) se capturan y se restauran de verdad** — la fila lo dice con *"N pistas"* — y solo lo que queda genuinamente fuera de alcance (categoría `CTRACK_CATEGORY_DATA`/`_PLUGIN`: PLA, morphs, sonido, terceros — estructura distinta, sin ruta de serialización desde Python) se avisa como *"N pistas no incluidas"*, nunca en silencio. Ver `docs/research/2026-07-31-pin-storage-spike.md` §6 para lo medido.

### Identificadores de plugin

El tag usa **`2099078`**. Ocupados hoy en el rango `2099xxx`: `2099069` (plugin), `2099073` (Sentinel Frame tag), `2099075` (palette), `2099077` (frame sync MessageData); `2099072` retirado y no reutilizable. `2099078` está libre — verificado por grep sobre `plugin/`, el mismo método con el que se eligieron los anteriores, y queda registrado en el comentario del `.pyp` junto a ellos.

## Errores

- Objeto del pin borrado, o tag sin objeto: el tag no puede existir sin su host, así que el caso no se da; si el host se renombra, los pins siguen (la ubicación del host es su propia ruta).
- Jerarquía cambiada: se restaura lo reconocido y se reporta lo demás (arriba).
- Un pin guardado con una versión anterior del esquema: se ignora con un aviso en la fila, nunca se aplica a medias.
- Restaurar sin nada que restaurar (todos los objetos desaparecieron): no se toca la escena y se dice.

## Verificación

- **pytest** sobre el motor puro: recorrido determinista de la jerarquía, construcción de la clave de ubicación, plan de restauración con objetos ausentes y sobrantes.
- **Live en C4D**, que es donde esto se demuestra:
  - Pinchar un rig paramétrico (Cloner + Effector + falloff), destrozar los tres, restaurar, y comprobar **parámetros y transformaciones** de los tres — no solo que "se ve bien".
  - Un objeto de plugin de terceros dentro de la jerarquía, para probar que la captura es genérica.
  - Restaurar tras borrar un objeto y añadir otro: conteo correcto y reporte honesto.
  - **Un solo Cmd+Z** revierte una restauración completa.
  - El tag `↩ Antes de restaurar` aparece tras el primer salto y permite volver al estado previo; restaurar desde él NO lo sobrescribe.
  - Varios pins sobre un mismo objeto conviven y cada uno restaura el suyo.
  - Doble clic en el tag desde el Object Manager restaura (o, si `MSG_EDIT` no llega a un tag, queda anotado como atajo no disponible y el botón `Ir` es el camino).
  - Guardar la escena, reabrirla, y comprobar que los pins siguen ahí y **siguen restaurando** — el caso que el bug del baseline demostró que hay que probar explícitamente.

## Fuera de alcance

- **La capa automática** (snapshot de documento antes de operaciones destructivas de Sentinel): es v1.36, mecanismo distinto y palabra distinta — ahí sí es un punto de retorno, no una alternativa.
- **Geometría editable y grafos de nodos**: no están en el contenedor. Capturarlos exigiría clonar y reemplazar el objeto, lo que rompe los `BaseLink` que le apunten (constraints, XPresso, un Sentinel Frame apuntando a esa cámara) — y fallaría en silencio. Si algún día se aborda, va con su spike.
- **Iconos personalizados por pin**: se intentó y se retiró. `MSG_GETCUSTOMICON` **no llega a un `TagData`** (medido en C4D 2026.303), y además sobraba: la pestaña **Basic** de todo tag ya trae `Icon Color` con selector y presets, que tiñe el icono en el Object Manager. Distinguir pins se hace con ese control nativo. Lo que sigue sin haber es el **carácter** sobre el icono (Recall sí lo tiene).
- **Pistas fuera de la categoría VALUE** (ver arriba: `CTRACK_CATEGORY_DATA`/`_PLUGIN` — PLA, morphs, sonido, terceros — hoy se avisan, no se capturan; las pistas `VALUE` SÍ se capturan y restauran desde la Tarea 6) y **listado de pins en el panel**.
