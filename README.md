# Limbic Depth Map Renderer for Houdini

A **Blender Depth Map Generator v2.0** → **Houdini** port. One-click depth map pipeline with LINEAR / LOGARITHMIC / RAW normalization, independent mask export for ComfyUI, and single-frame + animation rendering.

Dual COP backend: Houdini 18-20 (legacy COP2) and Houdini 21+ (new COP) — auto-detected at runtime.

---

## Quick Start

### Install

```bash
python3 build.py --install
```

Then in Houdini: **File → Import → HDA File** → select the `.hda`.

### Use via Python Panel

1. Open **Composite Desk** (or any pane)
2. **[+] New Pane Tab → Python Panel → Depth Map**
3. Configure settings → **Setup Depth Network**
4. Optionally enable **Mask Export** → **Setup Mask Network**
5. **Render Depth Map** / **Render Mask** (or animation)

### Use via HDA Node

1. In `/img`, create a **Depth Map Renderer** HDA
2. Set parameters on the node
3. Use shelf tools or scripts to Setup/Render/Reset

---

## Project Structure

```
houdini-depth-map-renderer/
├── scripts/
│   ├── settings_model.py         # DepthMapSettings dataclass — single source of truth
│   ├── limbic_depth_map_core.py  # Core pipeline logic (no Qt)
│   ├── python_module.py          # HDA PythonModule wrapper
│   └── on_created.py             # HDA OnCreated callback
├── python_panels/
│   └── depth_map_panel.py        # Qt UI (Python Panel) — DEPRECATED, use HDA
├── build.py                      # Generate HDA build script
├── HDAs/                         # Generated HDA files
├── icons/
└── config/shelf_actions.py       # Shelf tool registration
```

### Architecture

```
settings_model.py        (dataclass — all settings defined once)
├── limbic_depth_map_core.py  (pipeline logic — no Qt, no UI)
│   ├── python_module.py       (HDA wrapper — for shelf/script use)
│   └── depth_map_panel.py     (Qt panel — for Python Panel UI)
```

---

## Depth Pipeline

```
DM_Source (Z-depth input)
  → DM_Invert (optional)
  → DM_RangeMap (LINEAR) or DM_LOG → DM_RangeMap (LOGARITHMIC)
  → DM_Brightness → DM_Contrast → DM_Scale
  → DM_Grayscale → DM_FileOut (+ optional DM_Viewer)
```

## Mask Pipeline (independent — does NOT require depth)

```
DM_MSource → DM_MIdToMask → DM_MGrayscale / DM_MRGBA → DM_MaskFileOut
```

### Settings

| Setting | Default | Description |
|---|---|---|
| Near / Far | 0.1 / 1000.0 | Custom depth range |
| Normalization | LINEAR | LINEAR, LOGARITHMIC, or RAW |
| Invert | on | Far=black, Near=white |
| Scale Factor | 1.0 | Depth multiplier |
| Brightness | 0.0 | Additive offset |
| Contrast | 0.2 | Gain multiplier |
| Exposure | 0.0 | Exposure adjustment |
| Gamma | 1.0 | Gamma correction |
| Black / White Point | 0.0 / 1.0 | Level adjustment |
| Clip Enable | off | Near/far clipping |
| Format | PNG | PNG, TIFF, or EXR |
| Bit Depth | 16 | 8-bit or 16-bit |
| Animation | off | Render frame range |
| Mask Source | OBJECT_INDEX | OBJECT_INDEX or CRYPTOMATTE |
| Mask Format | GRAYSCALE | GRAYSCALE or RGBA |

---

## COP Node Reference

| Semantic | COP2 (H18-20) | New COP (H21+) |
|---|---|---|
| Depth source | `cop2::deep` | `file` |
| Range mapping | `cop2::range` | `remap` |
| Log normalize | `cop2::ln` | `function` |
| Brightness | `cop2::brightness` | `bright` |
| Contrast | `cop2::contrast` | `contrast` |
| Scale | `cop2::multiply` | `function` |
| Grayscale | `cop2::convert` | `mono` |
| File output | `cop2::file_output` | `rop_image` |
| Viewer | `cop2::viewer` | `output` |
| ID mask | `cop2::idtomask` | `idtomask` |
| RGBA convert | `cop2::convert` | `monotorgba` |

---

## Build

```bash
python3 build.py                          # build to ./HDAs/
python3 build.py --install                # build + copy to ~/houdiniXX.X/otls/
```

---

## Environment Variables

| Variable | Used by | Meaning |
|---|---|---|
| `$HIP` | Houdini | Current scene directory |
| `$HFS` | build.py | Houdini install root |
| `LIMBIC_DEPTH_MAP` | shelf_actions.py | Path to this repo |

---

## Uninstall

```bash
rm ~/houdiniXX.X/python_panels/depth_map_panel.py
rm ~/houdiniXX.X/python_panels/depth_map_panel.pypanel
rm ~/houdiniXX.X/otls/gero_depth_map_renderer.hda
rm ~/houdiniXX.X/packages/limbic_depth_map.json
```
Restart Houdini.

## License

Apache 2.0
