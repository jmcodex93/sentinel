# Redshift AOV Parameter IDs — Cinema 4D 2026

> **Why this file exists**: Maxon does NOT document these parameter IDs in their
> Python SDK reference. All values were discovered by probing `RSAOV` and RS
> `VideoPost` objects at runtime. Named constants were later found via `dir(c4d)`.
>
> These IDs may change between RS/C4D versions. If something breaks, re-probe
> using the Discovery Method at the bottom of this file.

---

## Named Constants (exist in c4d module)

### Per-AOV: Direct Output (`REDSHIFT_AOV_FILE_*`)
| Constant | ID | Purpose | Values |
|----------|-----|---------|--------|
| `REDSHIFT_AOV_FILE_ENABLED` | 5001 | Direct Output enable | 0=off, 1=on |
| `REDSHIFT_AOV_FILE_PATH` | 6000 | Output file path | str, default: `$filepath$filename_$pass` |
| `REDSHIFT_AOV_FILE_DATA_TYPE` | 6001 | Data type | See DATATYPE constants below |
| `REDSHIFT_AOV_FILE_FORMAT` | 6002 | File format | See FORMAT constants below |
| `REDSHIFT_AOV_FILE_BIT_DEPTH` | 6003 | Bit depth | See BIT_DEPTH constants below |
| `REDSHIFT_AOV_FILE_COMPRESSION` | 6004 | Compression | See COMPRESSION constants below |
| `REDSHIFT_AOV_FILE_STORAGE` | 6005 | Storage mode | 0=Scanline, 1=Tiled |
| `REDSHIFT_AOV_FILE_JPEG_QUALITY` | 6006 | JPEG quality | int (0-100) |
| `REDSHIFT_AOV_FILE_EXR_DWA_COMPRESSION` | 6007 | DWA compression level | float, default 45.0 |
| `REDSHIFT_AOV_FILE_EFFECTIVE_PATH` | 6008 | Resolved path (read-only) | str |

### Data Type Constants (`REDSHIFT_AOV_FILE_DATATYPE_*`)
| Constant | Value | Use |
|----------|-------|-----|
| `REDSHIFT_AOV_FILE_DATATYPE_RGB` | 0 | Utility passes (Depth, MV, Normals) |
| `REDSHIFT_AOV_FILE_DATATYPE_RGBA` | 1 | Beauty/color passes (alpha for transparency) |
| `REDSHIFT_AOV_FILE_DATATYPE_POINT` | 2 | Point data |
| `REDSHIFT_AOV_FILE_DATATYPE_SCALAR` | 3 | Single channel (Depth uses this automatically) |

### Format Constants (`REDSHIFT_AOV_FILE_FORMAT_*`)
| Constant | Value |
|----------|-------|
| `REDSHIFT_AOV_FILE_FORMAT_OPENEXR` | 0 |
| `REDSHIFT_AOV_FILE_FORMAT_TIFF` | 1 |
| `REDSHIFT_AOV_FILE_FORMAT_PNG` | 2 |
| `REDSHIFT_AOV_FILE_FORMAT_TGA` | 3 |
| `REDSHIFT_AOV_FILE_FORMAT_JPEG` | 4 |

### Bit Depth Constants (`REDSHIFT_AOV_FILE_BIT_DEPTH_*`)
| Constant | Value | Use |
|----------|-------|-----|
| `REDSHIFT_AOV_FILE_BIT_DEPTH_INT8` | 0 | 8-bit (not for compositing) |
| `REDSHIFT_AOV_FILE_BIT_DEPTH_INT16` | 1 | 16-bit integer |
| `REDSHIFT_AOV_FILE_BIT_DEPTH_INT32` | 2 | 32-bit integer |
| `REDSHIFT_AOV_FILE_BIT_DEPTH_FLOAT16` | 3 | 16-bit half float (beauty passes) |
| `REDSHIFT_AOV_FILE_BIT_DEPTH_FLOAT32` | 4 | 32-bit float (utility passes) |

### Compression Constants (`REDSHIFT_AOV_FILE_COMPRESSION_*`)
| Constant | Value | Type | Use |
|----------|-------|------|-----|
| `REDSHIFT_AOV_FILE_COMPRESSION_NONE` | 0 | Lossless | Largest files |
| `REDSHIFT_AOV_FILE_COMPRESSION_DEFAULT` | 1 | — | RS default |
| `REDSHIFT_AOV_FILE_COMPRESSION_TIFF_LZW` | 100 | Lossless | TIFF only |
| `REDSHIFT_AOV_FILE_COMPRESSION_EXR_RLE` | 200 | Lossless | Run-length |
| `REDSHIFT_AOV_FILE_COMPRESSION_EXR_ZIP` | 201 | Lossless | Good balance |
| `REDSHIFT_AOV_FILE_COMPRESSION_EXR_ZIPS` | 202 | Lossless | Single scanline |
| `REDSHIFT_AOV_FILE_COMPRESSION_EXR_PIZ` | 203 | Lossless | Good for utility/data passes |
| `REDSHIFT_AOV_FILE_COMPRESSION_EXR_PXR24` | 204 | Lossy | 24-bit precision |
| `REDSHIFT_AOV_FILE_COMPRESSION_EXR_B44` | 205 | Lossy | Fixed rate |
| `REDSHIFT_AOV_FILE_COMPRESSION_EXR_DWAA` | 206 | Lossy | Perceptually lossless at 45 |
| `REDSHIFT_AOV_FILE_COMPRESSION_EXR_DWAB` | 207 | Lossy | Block variant of DWAA |

### Per-AOV: Multi-Pass Output
| Constant | ID | Purpose | Values |
|----------|-----|---------|--------|
| `REDSHIFT_AOV_MULTIPASS_ENABLED` | 5000 | Multi-Pass enable | 0=off, 1=on |
| `REDSHIFT_AOV_MULTIPASS_BIT_DEPTH` | 1002 | Bit depth | 0=8, 1=16, 2=32 |

### Global AOV Settings (RS VideoPost)
| Constant | ID | Purpose | Values |
|----------|-----|---------|--------|
| `REDSHIFT_RENDERER_AOV_GLOBAL_MODE` | 3001 | AOV Mode | 0=Disable, 1=Enable, 2=Batch Only |
| `REDSHIFT_RENDERER_AOV_MULTIPART` | 3003 | Multi-Part EXR | bool |
| `REDSHIFT_RENDERER_AOV_FILE_BIT_DEPTH` | 3005 | Global bit depth | Same as per-AOV |
| `REDSHIFT_RENDERER_AOV_FILE_COMPRESSION` | 3006 | Global compression | Same as per-AOV |
| `REDSHIFT_RENDERER_AOV_FILE_EXR_DWA_COMPRESSION` | 3007 | Global DWA level | float |
| `REDSHIFT_RENDERER_AOV_FILE_STORAGE` | 3008 | Global storage | 0=Scanline, 1=Tiled |
| `REDSHIFT_RENDERER_AOV_MULTIPASS_COMPATIBILITY` | 3009 | Multi-Pass compat | bool |

---

## Per-AOV Option Params (ID range 1000-1029)

Discovered by probing. These control AOV-specific options like Depth mode and MV settings.

### General (all AOV types)
| ID | Name | Type | Default | Notes |
|----|------|------|---------|-------|
| 1000 | AOV Type (numeric) | int | varies | Mirrors `REDSHIFT_AOV_TYPE` |
| 1001 | AOV Name | str | varies | Mirrors `REDSHIFT_AOV_NAME` |
| 1002 | Multi-Pass Bit Depth | int | 2 | 0=8, 1=16, 2=32 |
| 1003 | (internal type flag) | int | varies | 1=Depth, 3=MV, 5=Diffuse etc. |
| 1004 | Depth: Filter Type | int | 0 | **0=Full, 1=Min, 2=Max, 3=Center Sample** |
| 1005 | (unknown) | Vector | (1,1,1) | |
| 1006 | Apply Color Processing | int | 1 | **Should be 0 for compositing (linear data)** |
| 1007 | (unknown) | int | 0 | |

### Motion Vectors specific
| ID | Name | Type | Default | Nuke | After Effects |
|----|------|------|---------|------|--------------|
| 1008 | Output Raw Vectors | int | 0 | **1 (ON)** | **0 (OFF)** |
| 1009 | No Clamp | int | 0 | **1 (ON)** | **0 (OFF)** |
| 1010 | Max Motion (pixels) | int | 8 | irrelevant | **64** (= RSMB MaxDisplace) |
| 1011 | Image Output Min | float | 0.0 | irrelevant | 0.0 |
| 1012 | Image Output Max | float | 1.0 | irrelevant | 1.0 |
| 1013 | Filtering | int | 1 | **0 (OFF)** | **0 (OFF)** |

### Depth specific
| ID | Name | Type | Default | Nuke | After Effects |
|----|------|------|---------|------|--------------|
| 1004 | Filter Type | int | 0 (Full) | **3 (Center Sample)** | **3 (Center Sample)** |
| 1019 | Depth Mode | int | 0 | **0 (Z raw)** | **2 (Z Normalized Inverted)** |
| 1020 | Use Camera Near/Far | int | 1 | **0 (OFF)** | **1 (ON)** |
| 1021 | Minimum Depth | float | 0.0 | 0.0 | 0.0 |
| 1022 | Maximum Depth | float | 10000.0 | 10000.0 | 10000.0 |
| 1024 | Env Rays to Black | int | 1 | 1 (ON) | 1 (ON) |

---

## RS VideoPost — Caustics Parameters (ID range 9013-9022)

| ID | Name | Type | Values | Verified |
|----|------|------|--------|----------|
| 9013 | **Enabled** | int | 0=off, 1=on | Yes — toggled, confirmed |
| 9014 | Caustics Engine | int | 2=Brute Force | Read from probe |
| 9015 | Global Caustics | int | 0=off, 1=on | Read from probe |
| 9016 | Reflection Caustics | int | 0=off, 1=on | Read from probe |
| 9017 | Refraction Caustics | int | 0=off, 1=on | Read from probe |
| 9018 | Light Casts Caustics | int | 0=off, 1=on | Read from probe |
| 9019 | Disable Intensity Clamp | int | 0=off, 1=on | Read from probe |
| 9020 | Brute Force Rays | int | 256 | Read from probe |
| 9021 | Indirect Caustics | int | 0=off, 1=on | Read from probe |

---

## AOV Type Constants (`c4d.REDSHIFT_AOV_TYPE_*`)

| AOV | Constant | ID |
|-----|----------|-----|
| Beauty | `REDSHIFT_AOV_TYPE_BEAUTY` or `REDSHIFT_AOV_TYPE_MAIN` | — |
| Depth | `REDSHIFT_AOV_TYPE_DEPTH` | 1 |
| Object-Space Position | `REDSHIFT_AOV_TYPE_OBJECT_SPACE_POSITION` | 2 |
| Motion Vectors | `REDSHIFT_AOV_TYPE_MOTION_VECTORS` | 3 |
| Diffuse Lighting | `REDSHIFT_AOV_TYPE_DIFFUSE_LIGHTING` | 5 |
| World Position | `REDSHIFT_AOV_TYPE_WORLD_POSITION` | 8 |
| Reflections | `REDSHIFT_AOV_TYPE_REFLECTIONS` | 11 |
| Normals | `REDSHIFT_AOV_TYPE_NORMALS` | 24 |
| Cryptomatte | `REDSHIFT_AOV_TYPE_CRYPTOMATTE` | 42 |
| GI | `REDSHIFT_AOV_TYPE_GLOBAL_ILLUMINATION` | — |
| Specular Lighting | `REDSHIFT_AOV_TYPE_SPECULAR_LIGHTING` | — |
| Emission | `REDSHIFT_AOV_TYPE_EMISSION` | — |
| SSS | `REDSHIFT_AOV_TYPE_SUB_SURFACE_SCATTER` | — |
| Refractions | `REDSHIFT_AOV_TYPE_REFRACTIONS` | — |
| Ambient Occlusion | `REDSHIFT_AOV_TYPE_AMBIENT_OCCLUSION` | — |
| Diffuse Filter | `REDSHIFT_AOV_TYPE_DIFFUSE_FILTER` | — |
| Reflection Filter | `REDSHIFT_AOV_TYPE_REFLECTION_FILTER` | — |
| Diffuse Lighting Raw | `REDSHIFT_AOV_TYPE_DIFFUSE_LIGHTING_RAW` | — |
| Volume Lighting | `REDSHIFT_AOV_TYPE_VOLUME_LIGHTING` | — |
| Volume Fog Tint | `REDSHIFT_AOV_TYPE_VOLUME_FOG_TINT` | — |
| Volume Fog Emission | `REDSHIFT_AOV_TYPE_VOLUME_FOG_EMISSION` | — |
| Shadows | `REDSHIFT_AOV_TYPE_SHADOWS` | — |
| Caustics | `REDSHIFT_AOV_TYPE_CAUSTICS` | — |
| Bump Normals | `REDSHIFT_AOV_TYPE_BUMP_NORMALS` | — |

### Constants that DO NOT exist
- `REDSHIFT_AOV_DIRECT_ENABLED` → use `REDSHIFT_AOV_FILE_ENABLED`
- `REDSHIFT_AOV_TYPE_GI` → use `REDSHIFT_AOV_TYPE_GLOBAL_ILLUMINATION`
- `REDSHIFT_AOV_TYPE_SSS` → use `REDSHIFT_AOV_TYPE_SUB_SURFACE_SCATTER`

---

## RS Object Plugin IDs (Scene Detection)

| Object | Plugin ID | Triggers |
|--------|-----------|----------|
| RS Environment | 1036757 | Volume AOVs (global fog) |
| RS Volume | 1038655 | Volume AOVs (smoke/fire) |
| RS Light | 1036751 | + types: 1036754, 1038653, 1036950, 1034355, 1036753 |
| RS Camera | 1057516 | |
| RS Texture Sampler (legacy) | 1036227 | |
| Alembic Generator | 1028083 | Asset path checks |
| Alembic Tag | 1028081 | Asset path checks |

---

## RS Node Material Access

| Item | Value |
|------|-------|
| Node Space ID | `com.redshift3d.redshift4c4d.class.nodespace` |
| Render Engine ID | 1036219 |
| Graph access | `mat.GetNodeMaterialReference().GetGraph(RS_NODESPACE)` |
| Root node | `graph.GetViewRoot()` (NOT `GetRoot()` — deprecated since 2025) |
| Port values | `port.GetPortValue()` (NOT `GetDefaultValue()` — deprecated since 2024.4) |
| Texture paths | Nested sub-ports of TextureSampler nodes. Recursive scan required. |
| maxon.Url → path | `val.GetSystemPath()` or `val.ToString()` |

---

## Sentinel AOV Configuration

### Global Settings (applied to RS VideoPost)
| Setting | Constant | Value |
|---------|----------|-------|
| AOV Mode | `REDSHIFT_RENDERER_AOV_GLOBAL_MODE` | `ENABLE` (1) |
| Multi-Part EXR | `REDSHIFT_RENDERER_AOV_MULTIPART` | True |

### Per-AOV Settings

| Setting | Beauty AOVs | Utility AOVs |
|---------|-------------|--------------|
| Direct Output | ON | ON |
| Multi-Pass | OFF | OFF |
| Data Type | RGBA | RGB |
| Bit Depth | EXR Half Float (16-bit) | EXR Float (32-bit)* |
| Compression | DWAB (45) | PIZ |

*Exception: Normals, Bump Normals → 16-bit half float

### Compositor-Specific Configuration

**Nuke:**
| AOV | Settings |
|-----|----------|
| Depth | Mode=Z (raw world units), Filter=Center Sample, Camera Near/Far=OFF |
| Motion Vectors | Raw Vectors=ON, No Clamp=ON, Filtering=OFF |

**After Effects (Frischluft + RSMB Pro):**
| AOV | Settings |
|-----|----------|
| Depth | Mode=Z Normalized Inverted (white=near), Filter=Center Sample, Camera Near/Far=ON |
| Motion Vectors | Raw Vectors=OFF (normalized 0-1), No Clamp=OFF, Max Motion=64px, Filtering=OFF |

### AOV Tiers

**Essentials (11 AOVs):**
Beauty, Diffuse Lighting, GI, Specular Lighting, Reflections, SSS,
Refractions, Emission, Depth, Motion Vectors, Cryptomatte

**Production (17+ AOVs = Essentials + 6):**
\+ Diffuse Filter, World Position, Normals, Ambient Occlusion,
Reflection Filter, Refractions Raw

**Conditional AOVs (auto-detected):**
- **Caustics** — added when RS Caustics Enabled (VP param 9013=1)
- **Volume Lighting/Fog Tint/Fog Emission** — added when RS Environment or RS Volume objects exist in scene

### Beauty Rebuild Equation
```
Beauty = (Diffuse + GI + Specular + Reflections + SSS + Refractions
         + Emission + Caustics) × Volume Fog Tint
         + Volume Lighting + Volume Fog Emission
```

---

## Discovery Method

To find unknown parameter IDs:

1. Create/select an AOV in the AOV Manager
2. Add probe code:
```python
# For RSAOV params:
for pid in range(START, END):
    try:
        val = aov.GetParameter(pid)
        if val is not None:
            print(f"id={pid} val={val} type={type(val).__name__}")
    except:
        pass

# For VideoPost params:
for pid in range(START, END):
    try:
        val = vprs[pid]
        if val is not None:
            print(f"id={pid} val={val} type={type(val).__name__}")
    except:
        pass

# Find named constants:
for attr in dir(c4d):
    if "REDSHIFT" in attr and "KEYWORD" in attr:
        print(f"{attr} = {getattr(c4d, attr)}")
```
3. Note current values, change setting manually in UI, probe again
4. The changed ID is your target

**Known ID ranges:**
- 1000-1029: Per-AOV options (type, name, depth mode, MV settings)
- 3001-3010: RS VideoPost global AOV settings
- 5000-5001: Per-AOV output enables (Multi-Pass, Direct)
- 6000-6008: Per-AOV Direct Output config
- 9013-9022: RS VideoPost Caustics tab

**Pro tip**: Always try `dir(c4d)` with a keyword filter first — many constants
exist but aren't documented. Only fall back to brute-force probing when no
named constant exists.
