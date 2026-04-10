# Limbic Depth Map Renderer for Houdini

A **Blender Depth Map Generator v2.0** → **Houdini** port. Mirrors the Limbicnation Blender plugin's full feature set: depth pipeline with LINEAR / LOGARITHMIC / RAW normalization, independent mask export pipeline for ComfyUI, single-frame and animation rendering.

---

## What It Does

| Blender concept | Houdini equivalent |
|---|---|
| Depth compositor (Z → MapRange → Bright/Contrast → ColorRamp → FileOut) | COP2 network: DM_Source → DM_RangeMap/DM_LOG → DM_Brightness → DM_Contrast → DM_Scale → DM_Grayscale → DM_FileOut |
| Mask pipeline (IndexOB / Cryptomatte → IDMask → FileOut) | COP2 network: DM_MSource (IDTopMask/Cryptomatte) → DM_MGrayscale/DM_MRGBA → DM_MaskFileOut |
| Sidebar N-panel | Python Panel in the Composite Desk |
| `scene.depth_map_settings` (PropertyGroup) | `dm_settings` parm (JSON on node) |
| `setup_complete` / `mask_setup_complete` flags | `node.userData()` + settings dict |

---

## Project Structure

```
houdini-depth-map-renderer/
├── python_panels/
│   └── depth_map_panel.py      # Main plugin (v2.0 — depth + mask pipelines)
├── HDAs/
│   └── limbic_depth_map_renderer.otlc
├── cop2_filters/
├── installer/
│   └── install.py             # Houdini Textport install
├── config/
│   └── shelf_actions.py       # Shelf tool registration
├── build.py
└── README.md
```

---

## Installation

```python
# Run in Houdini Textport:
>>> exec(open("/path/to/installer/install.py").read())
```

Or manually: copy `HDAs/*.otlc` → `~/houdini18.0/otls/`, `python_panels/*.py` → `~/houdini18.0/python_panels/`, restart Houdini.

---

## Usage

1. Create a **COP2 network** (right-click → Material → Compose)
2. Drop the **Depth Map Renderer HDA** onto the network
3. Open the **Composite Desk** — the Depth Map panel appears in the sidebar
4. Configure depth settings, then **Setup Depth Network**
5. Optionally enable **Mask Export** and set Object Index + path
6. **Setup Mask Network** (independent of depth pipeline)
7. Render with **Render Depth Map** / **Render Mask**, or as animation

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
| Preview | Add COP2 Viewer node alongside FileOut | off |

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

## COP2 Pipelines

### Depth Network
```
DM_Source (Z from Mantra deep raster)
    → DM_RangeMap (LINEAR: near→far → 1→0)  OR  DM_LOG → DM_RangeMap (LOG)
    → DM_Brightness (brightness offset)
    → DM_Contrast (gain boost)
    → DM_Scale (scale_factor multiply)
    → DM_Grayscale (RGBA → BW)
    → DM_FileOut (+ optional DM_Viewer)
```

### Mask Network (independent)
```
DM_MSource (IDTopMask OBJECT_INDEX  OR  cop2::cryptomatte)
    → DM_MGrayscale  OR  DM_MRGBA_Convert (GRAYSCALE / RGBA)
    → DM_MaskFileOut
```

---

## Uninstall

```bash
rm ~/houdini18.0/otls/limbic_depth_map_renderer.otlc
rm ~/houdini18.0/python_panels/depth_map_panel.py
rm ~/houdini18.0/packages/limbic_depth_map.json
rm -rf ~/houdini18.0/cop2_filters/limbic_depth_map*
```
Restart Houdini.

---

## License

Apache 2.0

## Reference

- Blender Depth Map Generator: `github.com/limbicnation/blender-depth-map-generator`
- Houdini COP2 docs: `www.sidefx.com/docs/houdini/cop2/`
- Houdini Python Panel API: `www.sidefx.com/docs/houdini/hom/ui.html#panels`
