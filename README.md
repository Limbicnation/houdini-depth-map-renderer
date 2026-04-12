# Limbic Depth Map Renderer for Houdini

A **Blender Depth Map Generator v2.0** → **Houdini** port. Mirrors the Limbicnation Blender plugin's full feature set: depth pipeline with LINEAR / LOGARITHMIC / RAW normalization, independent mask export pipeline for ComfyUI, single-frame and animation rendering.

**Dual COP backend**: works on Houdini 18–20 (legacy COP2) and Houdini 21+ (new COP system) — auto-detected at runtime.

---

## What It Does

| Blender concept | Houdini equivalent |
|---|---|
| Depth compositor (Z → MapRange → Bright/Contrast → ColorRamp → FileOut) | COP network: DM_Source → DM_RangeMap/DM_LOG → DM_Brightness → DM_Contrast → DM_Scale → DM_Grayscale → DM_FileOut |
| Mask pipeline (IndexOB / Cryptomatte → IDMask → FileOut) | COP network: DM_MSource (IDToMask/Cryptomatte) → DM_MGrayscale/DM_MRGBA → DM_MaskFileOut |
| Sidebar N-panel | Python Panel in the Composite Desk |
| `scene.depth_map_settings` (PropertyGroup) | `dm_settings` parm (JSON on node) |
| `setup_complete` / `mask_setup_complete` flags | `node.userData()` + settings dict |

---

## Project Structure

```
houdini-depth-map-renderer/
├── python_panels/
│   └── depth_map_panel.py      # Main plugin (v2.1 — dual COP backend)
├── installer/
│   └── install.py              # Legacy Houdini Textport install
├── install_fixed.py            # Modern installer (H21+ compatible)
├── config/
│   └── shelf_actions.py        # Shelf tool registration
├── icons/
├── build.py
└── README.md
```

---

## Installation

### Recommended (H21+)

```bash
python3 install_fixed.py
```

Then restart Houdini. Or from the Houdini Python Shell:

```python
exec(open("/path/to/install_fixed.py").read())
```

### Manual

Copy `python_panels/depth_map_panel.py` → `~/houdini21.0/python_panels/`, restart Houdini.

---

## Usage

1. Open the **Composite Desk** (or any pane)
2. **[+] New Pane Tab → Python Panel → Depth Map**
3. Configure depth settings, then **Setup Depth Network**
4. Optionally enable **Mask Export** and set Object Index + path
5. **Setup Mask Network** (independent of depth pipeline)
6. Render with **Render Depth Map** / **Render Mask**, or as animation

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
| Source | OBJECT_INDEX (Pass Index) or CRYPTOMATTE (Cycles) |
| Object Index | Set on object: Properties → Relations → Pass Index |
| Format | GRAYSCALE (direct mask) or RGBA |
| Mask Path | Output directory |

**Mask integration with ComfyUI**: GRAYSCALE PNG outputs load directly as a mask node. Set Object Index on your character/prop, export mask, use it in ComfyUI ControlNet or as an alpha channel.

---

## COP Backend Compatibility

The plugin auto-detects the Houdini version and uses the correct node types:

| Semantic | COP2 (H18–H20) | New COP (H21+) |
|---|---|---|
| Depth source | `cop2::deep` | `file` |
| Range mapping | `cop2::range` | `remap` |
| Brightness | `cop2::brightness` | `bright` |
| Contrast | `cop2::contrast` | `contrast` |
| Scale | `cop2::multiply` | `function` |
| Grayscale | `cop2::convert` | `mono` |
| File output | `cop2::file_output` | `rop_image` |
| ID mask | `cop2::idtopmask` | `idtomask` |

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

### Mask Network (independent)
```
DM_MSource (IDToMask / Cryptomatte)
    → DM_MGrayscale  OR  DM_MRGBA_Convert (GRAYSCALE / RGBA)
    → DM_MaskFileOut
```

---

## Uninstall

```bash
rm ~/houdini21.0/python_panels/depth_map_panel.py
rm ~/houdini21.0/python_panels/depth_map_panel.pypanel
rm ~/houdini21.0/toolbar/limbic_depth_map_install.shelf
```
Restart Houdini.

---

## License

Apache 2.0

## Reference

- Blender Depth Map Generator: `github.com/limbicnation/blender-depth-map-generator`
- Houdini COP docs: `www.sidefx.com/docs/houdini/composite/`
- Houdini Python Panel API: `www.sidefx.com/docs/houdini/hom/ui.html#panels`
