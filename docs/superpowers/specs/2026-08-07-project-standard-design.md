# El estándar del proyecto — publicar desde un shot bueno, arrancar shots desde él (v1.37)

**Fecha**: 2026-08-07 · **Estado**: diseño aprobado en brainstorm, pendiente de plan.

**Contexto**: nace de dos huecos encontrados al cerrar la v1.36.10 (la escena plantilla del estudio, apuntada desde el ruleset). El primero: `sentinel_rules.json` **solo se lee, nunca se escribe** — no hay una sola ruta en el plugin que lo cree. Para que un estudio tenga su ruleset, alguien escribe JSON a mano, y a partir de la v1.36 ese archivo gobierna trece claves. El segundo: la plantilla y el ruleset describen el mismo estándar desde dos lados y **pueden discrepar**, que es el fallo que ya mordió con Reset All.

---

## El problema real, en palabras del artista

**Cómo empieza un shot hoy**: duplicando el shot anterior. Es el patrón más común en estudios de motion, y el que arrastra los errores del shot viejo al nuevo.

**Qué hay que limpiar al duplicar**: las cuatro categorías, siempre —
1. la geometría y el look del shot viejo,
2. las rutas de salida y los nombres,
3. el rango de frames y la cámara,
4. el historial, las notas y las versiones.

Cuatro limpiezas manuales por shot, y la que se escapa —las rutas— **renderiza encima de la entrega anterior**.

Así que el valor de esta feature no es "dame un archivo de inicio". Es **"dame un archivo sin los restos del shot anterior"**.

## Principio rector

**Derivar de una escena real en vez de preguntar.** Si algo se puede comprobar mirando una escena, no se pregunta: un JSON puede *afirmar* que el fps es 25; una escena a 25 fps no miente.

Corolario de reparto:

| | |
|---|---|
| **Derivable de una escena** — fps, frame inicial, presets aprobados y requeridos, ruta de la plantilla, patrón de carpetas | se publica desde el shot bendecido, **nunca se teclea** |
| **Sin representación en una escena** — severidad por check, checks on/off, gates, insets de safe area, sufijos de matwire | siguen en el JSON, con sus defaults |

## El estándar es el denominador común, no una escena completa

**Decisión central, y la que evita reproducir el problema que la feature viene a resolver.** El artista lo planteó con dos proyectos reales:

- **Coche de cliente**: el mismo coche en todos los shots, su shading evoluciona. Es **común** — viaja al estándar, y las actualizaciones propagan por el proxy.
- **Simulación de pétalos**: cada shot lleva la suya. Es **del shot** — no viaja.

Si el estándar fuese "un shot bendecido con todo dentro", en el segundo proyecto cada shot nuevo heredaría la simulación de otro: exactamente el problema de duplicar.

**Sentinel no adivina qué es común.** Muestra qué va a viajar y el supervisor cura, con una vista previa antes de publicar:

```
Viajará al estándar
  jerarquía  Cameras · Lights · Geometry · Environment
  presets    previz · pre_render · render · stills
  rango      1001, 25 fps
  proxies    coche_v4.rs
  luces      key · fill · rim
  patrón     shots/{shot}/{shot}_v001.c4d      (derivado de dónde vive este shot)

No viajará
  historial de versiones, notas y TODOs
  el número de versión del archivo
```

Mismo patrón que matwire y Batch Rename, donde el preview manda y el servidor re-deriva al aplicar.

### Las cuatro categorías de limpieza, y quién se ocupa de cada una

El artista las nombró todas como "siempre hay que limpiarlo". No las limpia la misma mano:

| Categoría | Quién |
|---|---|
| **Rutas de salida y nombres** | **Se limpian solas.** El QC #9 exige tokens, así que un shot conforme ya las tiene tokenizadas y resuelven al nombre del shot nuevo. |
| **Historial, notas y versión** | **Sentinel.** Son sidecars y metadatos del archivo, sin ambigüedad sobre si son restos. |
| **Geometría y look** | **El supervisor**, en la vista previa. Es la línea coche-vs-pétalos: Sentinel no puede saber cuál es cuál. |
| **Rango y cámara** | **Ninguno de los dos, y es deliberado.** El **frame inicial** es del estándar (1001, validado por QC #11). La **duración** viaja como valor de partida y el artista la ajusta a su pieza: Sentinel no puede inventar cuánto dura un shot que aún no existe, y ponerlo a cero sería peor que dejar uno razonable. La **cámara** viaja como parte del andamiaje (con su Sentinel Frame si lo tiene) y el artista replantea. |

Que dos de las cuatro no las limpie la herramienta **no es una carencia**: es que no tiene la información para hacerlo, y fingir que sí la convertiría en un generador de shots mal dimensionados.

### Sobre proxies y XRef: no se construye nada

El estudio ya usa proxies de Redshift/Octane/Arnold, o XRef. **Un proxy es un archivo en disco: cambiarlo cambia todos los shots que apuntan a él.** Esa ES la propagación. Sentinel ya clasifica `.rs`, `.rsproxy` y `.ass` como `proxy` y `.c4d` como `xref` (`assets.py:13-25`), así que el Asset Hub ya los inventaría.

No se introduce ningún mecanismo de referencia: si el shot bendecido lleva el proxy, la copia lo lleva apuntando al mismo archivo, y las actualizaciones propagan como ya lo hacen. Meter XRefs donde funcionan los proxies sería cambiarle el pipeline al estudio, no darle una herramienta.

## Solo se publica desde un shot que pasa el QC

El QC #9 ya **exige** que las rutas de salida lleven `$prj` o `$take` (`checks/render.py`). Un shot que pasa el QC tiene por tanto las rutas **tokenizadas**, y esas se resuelven solas en cada shot nuevo — o sea que la categoría de limpieza más peligrosa **se limpia sola** si el estándar es un shot conforme.

De ahí el criterio: **no se publica un estándar desde un shot que no pasa 12/12**. Un fallo dentro del estándar se multiplica por todos los shots del proyecto.

---

## Los dos gestos

### A. Publicar el estándar (supervisor, una vez por proyecto)

1. Abre el shot que quiere como base.
2. Sentinel comprueba el QC. Si no pasa, se niega y dice qué falla.
3. Vista previa de lo que viajará y lo que no. El supervisor cura.
4. Elige la carpeta del proyecto.
5. Sentinel escribe ahí `sentinel_rules.json` (claves derivadas + defaults para el resto) y la **escena estándar ya limpia**.

**Con procedencia**: quién publicó y cuándo. Hay **un supervisor por proyecto y puede no ser el mismo**; cuando un shot empiece a fallar, esa línea es la que lo explica.

**Republicar avisa de qué cambia** antes de sobrescribir (*"el fps pasa de 25 a 24, se añade el preset `cliente_9x16`, la plantilla se reemplaza"*). Un estándar que cambia en silencio rompe shots que ayer estaban bien.

### B. Nuevo shot desde el estándar (artista, cada día)

1. Elige dónde y escribe el nombre.
2. Sentinel lee el estándar, copia la escena estándar, la nombra según la convención de versiones existente (`versioning.build_versioned_filename` → `nombre_v001.c4d`), la coloca según el **patrón declarado** y la abre.

Nada más: sin restos de nadie, con las rutas tokenizadas resolviéndose solas.

**El patrón de carpetas se deriva** de dónde vivía el shot bendecido respecto a la raíz del proyecto (`<proyecto>/shots/SH010/SH010_v012.c4d` → `shots/{shot}/{shot}_v001.c4d`), aparece en la vista previa y el supervisor lo corrige ahí si no es lo que quiere. Un campo menos que rellenar.

**El artista nunca ve el ruleset.** No tiene que aprender qué es: le llegan escenas correctas.

### El día 1 de un proyecto: la master la monta el supervisor

"Shot bendecido" no significa shot de producción: **es cualquier escena que tengas abierta y pase el QC**. El día 1 de un proyecto el supervisor monta su master —de cero, o copiando a mano la de otro proyecto— la abre y la publica. A partir de ahí `template_scene` apunta a ella y el `new.c4d` del plugin deja de intervenir **para ese proyecto**.

**Descartado en el brainstorm** (decisión del artista, para que nadie lo re-derive): heredar el estándar de otro proyecto con un gesto, y una biblioteca de masters del estudio por tipo de pieza. Ambas son plausibles y ninguna tiene demanda todavía; de dónde sale la master el día 1 es asunto del supervisor, no de la herramienta.

**Reparto de la caída al `new.c4d` del plugin**, que es deliberadamente asimétrico: *Reset All* cae a él en silencio cuando el ruleset no dice nada (normalizar unos presets con el default es razonable); *nuevo shot* **se niega** (arrancar un shot entero del estándar equivocado, no).

## Errores — negarse claro antes que seguir a medias

- **No hay estándar en esa carpeta** → se dice, con la ruta donde buscó.
- **El estándar apunta a una escena que no existe** → se niega y nombra el archivo. **No** cae a la plantilla del plugin: para un shot nuevo, arrancar del estándar equivocado es peor que no arrancar.
- **El nombre de shot ya existe** → no sobrescribe.

## Fuera de alcance

- **QC #13 — los assets que el proyecto declara.** Es la tercera pieza del análisis y tiene su propio spec: un check con su identidad, baseline y fontanería de informe, que aporta valor **incluso sin B** (un shot que ya existe también puede haber perdido un proxy, o apuntar a `coche_v3.rs` cuando el proyecto declara el v4).
- **Editar el ruleset a mano desde el panel.** Las claves derivables se publican desde una escena; las demás siguen en el JSON. Si el uso pide un formulario, se hace cuando duela.
- **Versionado del estándar.** Se sobrescribe con aviso de qué cambia; sin historial.
- **Inventar estructura de carpetas** más allá del patrón derivado.

## Verificación

- **Motor puro** (derivación de claves desde una escena, patrón de carpetas, plan de limpieza, textos de la vista previa): pytest directo, sin `import c4d`.
- **En C4D vivo**: publicar desde un shot real y volver a abrirlo; crear un shot y comprobar que no arrastra nada; el ciclo completo publicar → nuevo shot → QC 12/12.
- **Trampa medida y obligatoria**: `SaveDocument` escribe el archivo pero **no ata el documento en memoria a esa ruta** (`GetDocumentPath()` queda vacío y el ruleset no tiene desde dónde buscar, `reason='unsaved'`). Todo lo que verifique descubrimiento de ruleset **guarda y recarga**. Me mordió dos veces en la v1.36.10.
- **El arnés miente hasta que se demuestre lo contrario** (diez recurrencias esta semana): verificación por mutación de cada test, y lo que no sea ejercitable bajo el fake se declara en vez de fingirse.

## Criterio de terminado

- Publicar desde un shot que pasa el QC deja `sentinel_rules.json` y la escena estándar en la carpeta del proyecto, con procedencia.
- Publicar desde un shot que NO pasa se niega y dice qué falla.
- La vista previa lista lo que viaja y lo que no, y el supervisor puede quitar contenido del shot antes de publicar.
- Un shot nuevo sale con la estructura, presets, rango y assets comunes — y **sin** historial, notas, versión ni contenido del shot bendecido que el supervisor haya retirado.
- Las rutas de salida del shot nuevo resuelven a su propio nombre sin tocarlas.
- Republicar avisa de qué cambia antes de sobrescribir.
