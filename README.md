# Limbic Depth Map Renderer for Houdini

A **Blender Depth Map Generator v2.0** → **Houdini** port. Mirrors the Limbicnation Blender plugin's full feature set: depth pipeline with LINEAR / LOGARITHMIC / RAW normalization, independent mask export pipeline for ComfyUI, single-frame and animation rendering.

**Dual COP backend**: works on Houdini 18–20 (legacy COP2) and Houdini 21+ (new COP system) — auto-detected at runtime.

---

## What It Does

| Blender concept | Houdini equivalent |
|---|---|
| Depth compositor (Z → MapRange → Bright/Contrast → ColorRamp → FileOut) | COP network: DM_Source → DM_RangeMap/DM_LOG → DM_Brightness → DM_Contrast → DM_Scale → DM_Grayscale → DM_FileOut |
| Mask pipeline (IndexOB / Cryptomatte → IDMask → FileOut) | COP network: DM_MSource (IDToMask/Cryptomatte/SOP Import) → DM_MGrayscale/DM_MRGBA → DM_MaskFileOut |
| Sidebar N-panel | Python Panel in the Composite Desk |
| `scene.depth_map_settings` (PropertyGroup) | Explicit HDA parameters + `dm_settings` hidden parm |

---

## Project Structure

```
houdini-depth-map-renderer/
├── scripts/
│   ├── limbic_depth_map_core.py   # Shared core — all pipeline logic (no Qt)
│   ├── python_module.py           # Thin HDA PythonModule wrapper
│   └── on_created.py              # HDA OnCreated callback
├── python_panels/
│   └── depth_map_panel.py         # Thin Qt UI wrapper (Python Panel)
├── installer/
│   └── install.py                 # Legacy Houdini Textport installer
├── install_fixed.py               # Modern installer (H21+ compatible)
├── config/
│   └── shelf_actions.py           # Shelf tool registration
├── build.py                       # Build .otlc HDA archive
├── HDAs/                          # Generated HDA files
├── icons/
└── README.md
```

### Three-Layer Architecture

```
limbic_depth_map_core.py   (pure pipeline logic — no Qt, no UI)
├── python_module.py       (thin HDA PythonModule wrapper — for shelf/script use)
└── depth_map_panel.py     (thin Qt UI wrapper — for Python Panel)
```

All shared logic lives in `limbic_depth_map_core.py`. Both the HDA and the Python Panel import from it, eliminating code duplication.

---

## Installation

### Option A: HDA Install (Recommended)

```bash
python3 build.py --install
```

Then open Houdini → **File → Import → HDA File…** → select the `.otlc`.

### Option B: Package Install

```bash
python3 install_fixed.py
```

### Option C: Manual

Copy `python_panels/` → `~/houdiniXX.X/python_panels/`, restart Houdini.

Set the `LIMBIC_DEPTH_MAP` environment variable to the repository root so shelf tools and import paths resolve correctly.

---

## Usage

### Python Panel (UI)

1. Open the **Composite Desk** (or any pane)
2. **[+] New Pane Tab → Python Panel → Depth Map**
3. Configure depth settings, then **Setup Depth Network**
4. Optionally enable **Mask Export** and set Object Index + path
5. **Setup Mask Network** (independent of depth pipeline)
6. Render with **Render Depth Map** / **Render Mask**, or as animation

### HDA Node (Scripting)

1. Create a COP network (e.g., `/img/depth_map1`)
2. Drop the **Depth Map Renderer** HDA onto it
3. Set parameters on the HDA node directly
4. Use shelf tools or scripts to call Setup/Render/Reset

---

## Features

### Depth Pipeline

| Setting | Description | Default |
|---|---|---|
| Near / Far | Custom depth range | 0.1 / 1000.0 m |
| Normalization | LINEAR / LOGARITHMIC / RAW | LINEAR |
| Invert | Far=black (0), Near=white (1) | on |
| Scale Factor | Depth multiplier before normalization | 1.0 |
| Brightness | Additive offset before contrast | 0.0 |
| Contrast | Gain multiplier | 0.20 |
| Format | PNG / TIFF / EXR | PNG |
| Bit Depth | 8-bit / 16-bit | 16-bit |
| Preview | Add Viewer node alongside FileOut | off |

### Mask Export (ComfyUI)

| Setting | Description |
|---|---|
| Enable | Toggle mask pipeline |
| Source | OBJECT_INDEX (Pass Index) or CRYPTOMATTE |
| Object Index | Set on object: Properties → Relations → Pass Index |
| Format | GRAYSCALE (direct mask) or RGBA |
| Mask Path | Output directory |

**Mask integration with ComfyUI**: GRAYSCALE PNG outputs load directly as a mask node. Set Object Index on your character/prop, export mask, use it in ComfyUI ControlNet or as an alpha channel.

**H21+ Object Index masks**: On Houdini 21+, the mask pipeline uses SOP Import → Rasterize Geometry instead of IDToMask (which requires an Object ID render pass). Set the SOP path on the generated `DM_MaskInput` node to point to your geometry.

---

## COP Backend Compatibility

The plugin auto-detects the Houdini version and uses the correct node types:

| Semantic | COP2 (H18–H20) | New COP (H21+) | Notes |
|---|---|---|---|
| Depth source | `cop2::file` | `file` | Set path to Z-depth EXR |
| Range mapping | `cop2::range` | `remap` | Linear normalization |
| Log normalize | `cop2::function` | `function` | LOGARITHMIC mode |
| Brightness | `cop2::brightness` | `bright` | Additive offset |
| Contrast | `cop2::contrast` | `contrast` | Gain (1 + contrast) |
| Scale | `cop2::multiply` | `function` | Multiply mode, val1a parm |
| Grayscale | `cop2::convert` | `mono` | RGBA → BW |
| File output | `cop2::file_output` | `rop_image` | PNG/TIFF/EXR writer |
| Viewer | `cop2::viewer` | `output` | Display marker |
| ID mask | `cop2::idtomask` | `idtomask` | Object Index (COP2 only) |
| Cryptomatte | `cop2::cryptomatte` | `cryptomatte` | Cryptomatte AOV reader |
| RGBA convert | `cop2::convert` | `monotorgba` | Mono → RGBA |
| SOP import | `cop2::file` | `sopimport` | H21+ mask source |
| Rasterize | `cop2::rasterize` | `rasterizegeo` | H21+ mask from geometry |

### Depth Network
```
DM_Source (Z-depth input)
    → DM_RangeMap (LINEAR: near→far → 1→0)  OR  DM_LOG → DM_RangeMap (LOG)
    → DM_Brightness (brightness offset)
    → DM_Contrast (gain boost)
    → DM_Scale (scale_factor multiply)
    → DM_Grayscale (→ BW)
    → DM_FileOut (+ optional DM_Viewer)
```

### Mask Network (independent — does NOT require depth)

**COP2 (H18–H20):**
```
DM_MSource (IDToMask — set object_id parm)
    → DM_MGrayscale / DM_MRGBA_Convert
    → DM_MaskFileOut
```

**New COP (H21+) — OBJECT_INDEX:**
```
DM_MaskInput (SOP Import — set soppath)
    → DM_MSource (Rasterize Geometry)
    → DM_MGrayscale / DM_MRGBA_Convert
    → DM_MaskFileOut
```

**Both backends — CRYPTOMATTE:**
```
DM_MSource (Cryptomatte — requires EXR with Crypto AOV)
    → DM_MGrayscale / DM_MRGBA_Convert
    → DM_MaskFileOut
```

---

## HDA Parameters

The HDA exposes explicit parameters matching the Python Panel settings. These are also available for scripting via `hou.Node.parm()`:

| Parm Name | Type | Settings Key |
|---|---|---|
| `usecustomrange` | Toggle | `use_custom_range` |
| `near` | Float | `near` |
| `far` | Float | `far` |
| `normalization` | String (menu) | `normalization` |
| `scalefactor` | Float | `scale_factor` |
| `invert` | Toggle | `invert` |
| `brightness` | Float | `brightness` |
| `contrast` | Float | `contrast` |
| `outputpath` | String | `output_path` |
| `format` | String (menu) | `format` |
| `bitdepth` | String (menu) | `bit_depth` |
| `preview` | Toggle | `preview` |
| `animation` | Toggle | `animation` |
| `usescenerange` | Toggle | `use_scene_range` |
| `framestart` | Integer | `frame_start` |
| `frameend` | Integer | `frame_end` |
| `maskenabled` | Toggle | `mask_enabled` |
| `masksource` | String (menu) | `mask_source` |
| `maskindex` | Integer | `mask_index` |
| `maskformat` | String (menu) | `mask_format` |
| `maskoutputpath` | String | `mask_output_path` |
| `dm_settings` | String (hidden) | JSON tracking state |
| `cop_backend` | String (hidden) | Auto-detected COP backend |

---

## Build

```bash
python3 build.py                          # build .otlc to ./HDAs/
python3 build.py --out ./HDAs/custom.otlc # custom output path
python3 build.py --install                # build + copy to ~/houdiniXX.X/otls/
python3 build.py --verbose                # build with archive contents listing
```

---

## Uninstall

```bash
rm ~/houdiniXX.X/python_panels/depth_map_panel.py
rm ~/houdiniXX.X/python_panels/depth_map_panel.pypanel
rm ~/houdiniXX.X/otls/limbic_depth_map_renderer.otlc
rm ~/houdiniXX.X/packages/limbic_depth_map.json
```
Restart Houdini.

---

## License

Apache 2.0

## Reference

- Blender Depth Map Generator: `github.com/limbicnation/blender-depth-map-generator`
- Houdini COP docs: `www.sidefx.com/docs/houdini/composite/`
- Houdini Python Panel API: `www.sidefx.com/docs/houdini/hom/ui.html#panels`
