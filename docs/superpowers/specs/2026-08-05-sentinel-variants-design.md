# Sentinel Variants — opciones que conviven, una activa (v1.36)

**Fecha**: 2026-08-05 · **Estado**: diseño aprobado, pendiente de spike bloqueante.

**Contexto**: sustituye a la "capa automática" que la v1.35 había anotado como v1.36. Esa idea se **descartó en este mismo brainstorm** y la razón queda registrada abajo, para que nadie la re-derive.

---

## Por qué NO se construye la capa automática

El spec del Pin (v1.35) anotó como v1.36 una capa que guardara un snapshot del documento antes de cada operación destructiva de Sentinel. Al abrir el brainstorm, la primera pregunta fue en qué momento real le había faltado ese punto de retorno al artista. La respuesta: **nunca — era prevención**.

No hay incidente detrás. Construir un subsistema entero (qué lo dispara, dónde viven los archivos, cuántos se conservan, cuándo se purgan, qué significa "volver" cuando volver es abrir un archivo y perder lo hecho después) para un problema que no se ha tenido contradice las reglas del proyecto: *no diseñes para requisitos hipotéticos*. Además compite con algo que el artista ya usa y entiende — Smart Save Version.

El arco "dos capas" (manual + automática) no salió de una necesidad: se escribió como delimitación de alcance en el spec de la v1.35 y se convirtió en hoja de ruta sin que nadie comprobara que hacía falta.

**Deuda separada, sin versión propia**: auditar en C4D vivo que cada operación destructiva de Sentinel se revierte con un solo Cmd+Z. Tiene evidencia real (el contrato estuvo roto en matwire con más de un material, lo encontró el usuario en uso normal; el ledger de la v1.35 anota una rama del pin que escribe fuera del bloque de undo). Se hace como tarea de fondo — es higiene de ingeniería, invisible para el artista, y no merece una versión.

---

## El problema real

En una semana normal el artista itera **opciones**: variantes de modelado (subdivisiones, deformadores), pruebas de curvas de animación, intensidades de lighting. Las tres pesan por igual.

**Lo que hace hoy**: duplica el objeto y aparca la copia en un null llamado `backup`.

Ese método funciona —por eso lo usa— y su ventaja sobre el Pin es que se lleva la jerarquía entera: si la opción B tiene un Bend y la A no, la copia lo conserva. Sus costes son concretos: la escena engorda, el null se vuelve un cajón desastre, se pierde qué diferencia a cada copia, volver a una implica mover y renombrar a mano.

**Sentinel Variants formaliza ese método, no lo sustituye.**

### Verbo distinto al del Pin

| | |
|---|---|
| **Pin** (v1.35) | volver a un estado anterior **de los mismos objetos** |
| **Variants** (v1.36) | elegir entre **alternativas que coexisten** |

Ambos se quedan. El Pin no puede cubrir esto: nunca crea ni borra objetos, así que "con Bend / sin Bend" queda fuera de su alcance por diseño.

---

## El modelo

La unidad es un **anclaje**: el sitio de la escena cuyo contenido varía.

- Crear un conjunto **envuelve la selección en un null de anclaje** — el mismo gesto que el artista hace a mano. El null nace en **identidad** (sin posición, rotación ni escala) para que lo envuelto conserve su transformación en el mundo. Reparentar no invalida los `BaseLink`, así que lo que apuntara a esos objetos los sigue apuntando.
- Lo que había pasa a ser **Opción A**, sin tocar nada más.
- Una opción es un **subárbol completo**, por eso un solo mecanismo cubre las tres áreas: se lleva jerarquía, parámetros, pistas de animación con sus claves y tags de material.
- **Una sola opción está activa**; las demás quedan guardadas y fuera de en medio.
- El conjunto vive en un **tag sobre el null de anclaje** — visible en el Object Manager sin abrir nada, la promesa que justificó usar un tag en el Pin.

### Spike BLOQUEANTE: qué significa "guardada"

Dos caminos posibles, y cuál es correcto **se mide, no se razona**:

1. **Apagar la visibilidad** (editor y render) dejando la opción donde está. Limpio: nada se mueve, ningún enlace se rompe, el cambio es trivialmente un paso de undo.
2. **Sacarla de la jerarquía** a un contenedor gestionado — lo que el artista hace hoy. Más invasivo, neutraliza de forma inequívoca.

**La pregunta a medir**: ¿un objeto con la visibilidad apagada sigue *contando* para lo que lo rodea? Un Cloner que reparte entre sus hijos, un Boole, un deformador que afecta a lo que cuelga. Si un hijo oculto sigue contando, apagar la visibilidad no aísla la opción y hay que sacarla.

**Esta medición decide las dos mitades del diseño** — el mecanismo de cambio y si la salida a Takes es viable (ver abajo).

---

## El flujo

Cuatro gestos:

- **Crear opciones** sobre lo seleccionado (un objeto o varios a la vez, así que un setup de luces entero es un conjunto). Lo actual pasa a ser *A*.
- **Duplicar como nueva opción**: copia la activa, la nombra *B*, deja al artista trabajando sobre ella. Es el Cmd+C + arrastrar al backup de hoy.
- **Cambiar de opción** desde la lista del tag, en **un solo paso de deshacer**.
- **Renombrar y borrar** opciones — "Opción B" no dice nada en tres días; "sin bend, subdiv 3" sí.

**Cuál está puesta se ve siempre**, en la fila del tag y en el propio Object Manager.

---

## La salida a Takes

**Publicar opciones como Takes** genera un take por opción, cada uno configurado para que su opción sea la activa: se renderizan las tres sin montaje manual.

**Depende del spike**: los Takes sobrescriben *parámetros*, no jerarquía.
- Si basta apagar la visibilidad → publicar es casi gratis (un override de visibilidad por take, mecanismo nativo).
- Si hay que sacar de la jerarquía → los Takes no pueden expresarlo, y la salida pasa a ser un "renderiza todas las opciones" que cambia y lanza, una por una.

**Choque con Sentinel Frame**: si la escena tiene un Frame ya hay takes por formato. Formatos × opciones es una matriz que crece rápido, así que **no se genera el producto cruzado automáticamente** — se avisa y decide el artista.

---

## Límites honestos, dichos en la UI

Misma regla que el Pin: los límites se muestran en la fila del tag, no solo aquí.

- **La escena pesa lo mismo que hoy.** Las copias son reales — es justo lo que hace que funcione donde el Pin no llega. Con geometría editable y subdivisiones, tres opciones ocupan tres veces. Sin magia.
- **Los materiales NO se duplican**: al copiar un subárbol se duplican los *tags* de material, que siguen apuntando a los mismos materiales. El Material Manager no engorda.
- **Borrar una opción borra su contenido**, revertible con un Cmd+Z como todo lo demás.

---

## Fuera de alcance

- **Comparación lado a lado** (ver A y B a la vez): es otro mecanismo — dos subárboles visibles simultáneamente, con su propio problema de posición y de render.
- **Opciones anidadas** (opciones dentro de opciones): una matriz que nadie sabe leer.
- **Takes nativos como eje del sistema**: evaluados y descartados. Son el mecanismo de variantes de la casa y renderizan gratis, pero el artista no los usa, su interfaz es pesada para tres pruebas rápidas de intensidad, y chocan con los takes por formato del Frame. Se conservan como *salida*, no como base.
- **Aligerar el peso de las copias** (instancias, proxies, descarga a disco): optimización sin problema medido detrás.

---

## Criterio de terminado

- Crear un conjunto sobre un objeto y sobre varios a la vez, conservando las transformaciones en el mundo y sin romper enlaces que apunten dentro.
- Duplicar, renombrar, borrar y cambiar de opción, **cada acción un solo paso de deshacer**, verificado en C4D vivo (no en el harness de tests: los fakes de este repo han dado verde sobre código roto siete veces).
- Una variante de cada área real: estructura (con y sin deformador), valores (intensidades de luz), y curvas (dos timings distintos del mismo objeto).
- Publicar como Takes y renderizar cada opción sin montaje manual — o, si el spike lo impide, el camino alternativo funcionando.
- Los límites visibles en la fila del tag.
