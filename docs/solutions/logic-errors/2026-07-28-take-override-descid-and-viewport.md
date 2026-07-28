---
module: multiformat/frame_tag/frame_sync
tags: [takes, overrides, descid, viewport, updatescenenode, redshift, c4d-api]
problem_type: api-behavior
---

# Tres lecciones de la API de Takes/viewport cazadas en vivo (Frame v2, C4D 2026.303)

Las tres se manifestaron como "el crop/nudge no funciona" con síntomas distintos y raíces relacionadas. Verificadas en vivo con render real + medición en píxeles.

## 1. NUNCA uses un DescID construido a mano contra un override EXISTENTE

`BaseOverride.IsOverriddenParam(DescID(DescLevel(id)))` y `SetParameter`/`UpdateSceneNode` con un DescID construido a mano **fallan silenciosamente** contra un parámetro ya almacenado en el override (los niveles dtype/creator del DescID guardado no casan con `DescLevel(id)` ni `DescLevel(id, DTYPE_X, 0)`). Verificado: `IsOverriddenParam` devolvió False con AMBAS construcciones para un 7012 claramente presente.

**Regla**: resuelve siempre el DescID ALMACENADO del propio override y usa ESE:
```python
stored = {did[0].id: did for did in (ovr.GetAllOverrideDescID() or [])}
did = stored.get(param_id)          # None → el param no está overrideado
ovr.SetParameter(did, value, c4d.DESCFLAGS_SET_0)
```
`FindOrAddOverrideParam` con DescID de mano SÍ funciona para el ADD (fija el valor inicial); son los accesos POSTERIORES los que necesitan el stored DescID. Síntomas que causó: resets que nunca reseteaban (nudge→0 conservaba el pan viejo) y re-writes que nunca re-escribían ("los takes dejaron de cropear").

**Los fakes de test deben modelar esta rigidez**: un fake `IsOverriddenParam` que casa por id era el agujero que dejaba pasar el bug en verde (867 tests). Ahora devuelve False siempre y el fake expone `GetAllOverrideDescID`.

## 2. `UpdateSceneNode` empuja al estado de escena AUNQUE el take no sea el activo

Escribir overrides de N takes en cadena (el sync multi-formato) con `UpdateSceneNode` incondicional hace desfilar la cámara por los valores de cada formato — **el último escrito gana** y pisa el take que el usuario está viendo. Con 1 formato coincide de casualidad; con varios, desencuadre hasta que algo re-evalúa el take system (p.ej. un resize del viewport).

**Regla**: `UpdateSceneNode` SOLO si `takeData.GetCurrentTake() == take`. Los takes inactivos aplican sus overrides al activarse — ese es el contrato natural.

## 3. El viewport es PEREZOSO re-derivando la proyección al cambiar de take

Activar un take (RenderData + overrides de cámara nuevos) no siempre recomputa la proyección/letterbox del editor — se queda estampado hasta un resize del panel. Tras `SetCurrentTake`:
```python
c4d.EventAdd(c4d.EVENT_FORCEREDRAW)
c4d.DrawViews(c4d.DRAWFLAGS_ONLY_ACTIVE_VIEW | c4d.DRAWFLAGS_NO_THREAD | c4d.DRAWFLAGS_STATICBREAK)
```

## Bonus: overscan del viewport ≠ bug

El viewport muestra TODO el FOV y solo TINTA lo fuera del área de render (Render Safe). Con paneles anchos se ve contenido extra a los lados de un take 9:16 — comportamiento nativo; subir la opacidad del tinte al 100% en las opciones de vista lo vuelve negro. El RenderView de RS es siempre el preview exacto.

## Bonus 2: identidad de tags

`BaseTag` NO tiene `GetGUID()` (API de BaseObject). Identidad estable de un tag: `tag.FindUniqueID(c4d.MAXON_CREATOR_ID)` → `bytes(uid).hex()`. Un `str(tag.GetGUID())` envuelto en try/except desactivó el auto-sync entero en silencio.
