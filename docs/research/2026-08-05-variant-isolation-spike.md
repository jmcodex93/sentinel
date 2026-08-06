# Spike — cómo se aísla de verdad una rama de la escena (Sentinel Variants, v1.36)

**Fecha**: 2026-08-05 · **Entorno**: C4D 2026.303 vía MCP `exec_python`.
**Método**: documento throwaway insertado en la lista de documentos, cerrado con `KillDocument` en un `finally`. Oráculo: *Current State to Object* (`MCOMMAND_CURRENTSTATETOOBJECT`) tras `ExecutePasses`, contando polígonos del resultado — es decir, lo que el generador **construye de verdad**, no lo que dicen sus parámetros.

---

## La pregunta

El diseño de Variants necesita que, con la opción A activa, la escena se comporte **exactamente como si B no existiera**. Había dos candidatos para "guardar" una opción inactiva, y el barato era claramente preferible si funcionaba:

1. **Apagar la visibilidad** (editor + render), dejando la rama donde está. Nada se mueve → ningún `BaseLink` en riesgo, cambio trivialmente deshacible en un paso.
2. **Sacarla de la jerarquía** a un contenedor gestionado — lo que el artista ya hace a mano con su null `backup`.

La pregunta medible: **¿una rama oculta sigue contando para lo que la rodea?** (un Cloner que reparte entre sus hijos, un Subdivision Surface, un deformador).

---

## Resultado

Cloner con dos hijos (`Ocube` + `Osphere`), control reproducido en dos sondas independientes:

```
control: ambos hijos = 2584 polys
  B oculto      = 2584   NO AISLA
  B desactivado =   24   aísla
  B fuera       =   54   aísla
  desactivar == sacar ?  NO
```

Subdivision Surface con un hijo: visible = 96 polys, oculto = **96** (no aísla), desactivado = 0.

**Dos conclusiones, y la segunda es la que decide:**

1. **Ocultar NO aísla.** El generador sigue consumiendo la rama invisible. El camino barato queda descartado.
2. **Desactivar tampoco sirve**, aunque a primera vista "aísle": produce un resultado **distinto** al de sacar la rama (24 vs 54). El Cloner sigue contando al hijo desactivado como un hueco en su reparto. Como la promesa del sistema es equivalencia exacta con "la opción no existe", solo **sacar de la jerarquía** la cumple.

El método manual del artista era el correcto desde el principio.

---

## Consecuencias de diseño

- **El cambio de opción mueve subárboles.** Preservar los `BaseLink` que apunten dentro pasa de riesgo marginal a requisito central.
- **La salida a Takes cae.** Los Takes sobrescriben parámetros, no jerarquía, así que no pueden expresar "esta opción está dentro y las otras fuera". Enseñar opciones se resuelve con un "renderiza todas las opciones" que cambia y lanza, una por una.

---

## Límite honesto de este spike

~~**El caso del deformador no está medido.**~~ **MEDIDO Y CERRADO (2026-08-06).**

Lo que este spike dio por "no medible" era un **error de la sonda, no un límite de C4D**: el objeto que insertaba con el id `1019221` **no es un Bend, es un Spline Wrap** — sin spline no deforma nada, de ahí el control nulo de 0 puntos movidos. Repetido con `c4d.Obend`:

```
CONTROL: el Bend mueve 169 de 218 puntos  -> la sonda MIDE algo
  ocultando    -> NO AISLA (sigue deformando)
  desactivando -> AISLA
  sacandolo    -> AISLA
```

**El deformador se comporta como los generadores**: ocultarlo NO lo neutraliza — el cubo sigue deformado con el Bend invisible. Refuerza la conclusión del spike en vez de matizarla.

Lección de método, la segunda de este mismo documento: **un control a cero no dice "aquí no hay efecto", dice "esta sonda no está midiendo"**. La primera vez fue tocar de paso los parámetros del Cloner; ésta, un id equivocado que produce un objeto plausible con otro nombre. En ambos casos el síntoma es idéntico y engañoso: números que parecen respuestas.

**Trampa de método, registrada porque me costó tres sondas**: al añadir casos toqué de paso los parámetros del Cloner (`ID_MG_MOTIONGENERATOR_MODE`, `MG_LINEAR_COUNT`) y el tamaño del cubo, y rompí los casos base sin darme cuenta — el oráculo devolvía 0 para todo y "desactivar == sacar" salía `SI` por vacuidad. La sonda que resolvió fue volver al montaje exacto que ya daba 2584 y cambiar **una sola variable**. Es la misma guarda que el diseño exige del arnés de undo: **comprobar que el caso base hace algo antes de creerse el resultado**.
