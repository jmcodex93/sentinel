# Matwire polish — recursivo + ORM/ARM + sufijos por ruleset + leftover (v1.32.1)

**Fecha**: 2026-07-30
**Estado**: implementado en rama `feat/matwire-polish` (Tasks 1-5 completos, pytest 1056 + vitest 179 verdes, PLUGIN_VERSION 1.32.1) — **pendiente verificación live** (matriz corta de este doc + Cmd+Z del recipe imperativo del splitter + layout en columnas visto por primera vez) y merge a `main`.
**Contexto**: pulido de v1.32.0 (mergeado y live-verified) tras auditar el control que ofrece TexToMatO (capturas del usuario, plugin de su propiedad — estudiar-sí/copiar-no). Criterio Sentinel mantenido: **convención con opinión > knobs** — TexToMatO compensa con knobs lo que no tiene de preview; nosotros ya enseñamos el resultado antes de crear. Descartados explícitamente: toggle manual de Flip Y (nuestra auto-detección GL/DX lo cubre), toggle de case-sensitivity, Color Correct/Scale-Rot-Offset por defecto (bloat de grafo). Fases propias futuras (NO este release): OpenPBR, Triplanar/UV Context, Sprite opacity, import-from-base.

## Decisiones cerradas

1. **Escaneo recursivo** de la carpeta (los packs reales anidan: `Textures/4K/…`): `os.walk` con profundidad razonable (cap 5 niveles), los archivos entran con su ruta RELATIVA a la carpeta raíz (el writer une contra la raíz). La agrupación de sets NO cambia (por nombre de archivo, no por subcarpeta); `default_root` sigue siendo el basename de la carpeta elegida. Sin toggle: recursivo SIEMPRE (un pack plano da lo mismo; el knob de TexToMatO sobra con el preview delante).
2. **ORM/ARM cableado de verdad** (sustituye el `ignored packed_orm` de v1.32): un `rscolorsplitter` por textura empaquetada con el mapeo ESTÁNDAR FIJO **R=AO · G=Roughness · B=Metalness** (el orden ORM es la convención de la industria — sin dropdowns R/G/B como TexToMatO). Reglas: **los mapas dedicados GANAN** (si el set trae `_Roughness` dedicado, el canal G del splitter no se conecta a roughness); el AO del splitter sigue nuestra política AO (`outr` queda SIN conectar — visible); la textura ORM va en colorspace RAW. El canal del set pasa a llamarse `packed_orm` en `channels` (deja de ser ignored).
3. **Sufijos extensibles vía `sentinel_rules.json`** (mejor que las prefs por-máquina de TexToMatO: se comparte con el equipo, precedencia proyecto > defaults ya existente): clave nueva `matwire_suffixes` — dict `{channel: [sufijos extra]}` que se AÑADE a las tablas embebidas (nunca reemplaza; canales válidos = los canónicos del motor, claves desconocidas rechazadas por nombre como el resto del ruleset per-key). El motor puro recibe la tabla extra por parámetro (`scan_texture_sets(..., extra_suffixes=None)`); el op la resuelve del ruleset activo (`active_rules_for_doc`).
4. **Import leftover** (checkbox en la sub-vista, default OFF): los archivos `no_channel` se crean como texturesamplers SUELTOS (sin conectar, colorspace RAW, misma política que el AO) en el material de SU set si su raíz casa con uno, o en un material extra `<carpeta>_leftovers` si no casan con ninguno. `bad_extension` y variantes inferiores siguen fuera siempre.

## Diseño

- **`matwire.py`**: `scan_texture_sets(filenames, default_root, extra_suffixes=None)` — la tabla de canales se construye por llamada cuando hay extras (los compilados default se cachean a módulo); validación pura `validate_extra_suffixes(raw)` (dict str→list[str], canales canónicos only, sufijos normalizados lowercase, devuelve (valid, rejected_keys) — el op reporta rejected como warning igual que el ruleset per-key). `no_channel` gana metadato de raíz probable (`root_hint`) para el leftover-por-set. Reglas ORM: el canal `packed_orm` entra en `channels` (una por set; segunda ORM del mismo set → `duplicate_channel`).
- **`matwire_c4d.py`**: `build_description` gana la rama `packed_orm` → nodo `rscolorsplitter` (`.input` ← sampler RAW; `.outg` → `refl_roughness` SOLO si el set no trae roughness dedicado; `.outb` → `metalness` SOLO sin metalness dedicado; `.outr` sin conectar — política AO). El id `rscolorsplitter` y sus puertos vienen del catálogo del research (confirmados en TexToMatO); **mini-spike live** al inicio de la tarea del writer para wire-testearlo (patrón v1.32: nada extrapolado en el writer sin evidencia). Leftover: samplers sueltos añadidos al segundo ApplyDescription (patrón AO) del material correspondiente; material `_leftovers` = material sin standardmaterial? NO — un Standard vacío + samplers sueltos (mismo path de creación, cero casos especiales).
- **Ops**: `matwire_preview` lista recursivo, resuelve `matwire_suffixes` del ruleset (con `suffix_warnings` en la respuesta si hubo claves rechazadas) y devuelve además `leftovers: [{file, set|null}]`; `matwire_create` gana `{"import_leftovers": bool}` en el payload (default false). Paths relativos con subcarpetas viajan tal cual en `channels` (el writer une con la raíz — verificar separadores en el join).
- **SPA**: `MatwireSubview` gana el checkbox **Import unrecognized files** (default off) + contador; los leftovers listados (plegados) con su set destino; el aviso de sufijos rechazados del ruleset como nota inline. Fila de canal `packed_orm` con label "ORM/ARM (packed)" y nota de qué canales aporta en este set (según dedicados presentes).

## Errores / no-regresión

- Carpeta plana + sin ruleset + sin leftover ⇒ byte-idéntico a v1.32 (mismo scan, mismos sets, mismo writer) SALVO que los ORM pasan de ignored a canal — cambio deseado y visible en preview.
- Recursión: symlinks no seguidos; cap de profundidad 5; carpetas ocultas (`.`) saltadas.
- El ruleset sigue el contrato per-key existente: una clave mala en `matwire_suffixes` se rechaza por nombre, el resto aplica.

## Verificación

- pytest: recursión (rutas relativas, cap, ocultas), extra_suffixes (añade, no reemplaza; validación per-key), ORM en channels con reglas dedicado-gana (puro) y rama splitter en build_description (dict pinned), leftovers con root_hint y material extra, contratos de ops.
- vitest: checkbox + labels + leftovers plegados + warning de sufijos.
- Live (matriz corta): pack real anidado recursivo; carpeta con `x_ORM.png` + roughness dedicado → splitter con G sin conectar a roughness (dedicado gana) y B a metalness; ruleset con sufijo custom (`col_especial`) reconocido; leftover ON crea samplers sueltos; un Cmd+Z.

## Fuera de alcance

- OpenPBR, Triplanar/UV Context, Sprite opacity, import-from-base, mapeo R/G/B configurable, Color Correct/transform nodes.
- **`suffix_warnings` solo en el preview** (juicio fijado, review M2): `matwire_create` no repite el aviso de claves `matwire_suffixes` rechazadas — el artista lo tiene delante en la misma pantalla desde la que crea, y duplicarlo en el toast del create sería ruido, no información nueva.
- **`assign_leftovers` ignora la subcarpeta** (juicio fijado, review M5): la asignación de leftovers casa por STEM del archivo (prefijo-más-largo contra los nombres de set), así que `4K/notas.png` se asigna igual que `notas.png` en la raíz. Con el escaneo recursivo la carpeta podría desempatar, pero el nombre es la señal que el artista controla y la que ya gobierna la agrupación de sets — desempatar por carpeta introduciría una segunda regla de identidad para el mismo problema.

## Ajustes del review final de rama (v1.32.1)

- **I1 — ranking de resolución por directorio**: el escaneo recursivo × agrupación por basename hacía que un pack multi-res anidado (`1K/albedo.png` + `4K/albedo.png`, exactamente el layout que motiva la feature) colapsara en un set cuyo ganador lo decidía `sorted()` (arbitrario). Cuando el NOMBRE del archivo no trae token de resolución, el rank sale ahora de los segmentos de DIRECTORIO de su ruta relativa (`_dir_px`; gana el segmento más profundo con token). El token del nombre mantiene prioridad y una carpeta plana se comporta byte-idéntico.
- **I2 — la fila ORM dice qué aporta**: `orm_contributions` (motor puro) es la ÚNICA fuente de la regla dedicado-gana; la consumen tanto el preview (campo `contributes` en la fila `packed_orm` → `→ roughness + metalness` / `→ metalness` / `→ unconnected (dedicated maps win)`) como los connects del writer, así que la fila no puede prometer un cableado que el writer no hará.
