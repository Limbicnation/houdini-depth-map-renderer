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

1. In `/obj`, create a **Depth Map Renderer** HDA (it sits alongside your geometry)
2. Set parameters on the node
3. Use the node's **Actions** buttons (or shelf tools / scripts) to Setup/Render/Reset

---

## Rendering

### Depth source: auto-render or file

The HDA has two modes, controlled by the **Auto-Render Scene Depth** toggle:

- **Auto (default)** — on Render, the HDA renders the `/obj` scene's camera-space
  Z depth (Mantra `Pz`) from the chosen **Camera** to a temp EXR, then processes
  it. One-click depth straight from your scene geometry; no pre-render needed.
  If the **Camera** parm is empty, the first camera in `/obj` is used.
- **File** — turn the toggle off and point `DM_Source` (inside the inner
  `depth_cop` network) at your own pre-rendered depth **EXR**.

### Single frame via Python

```python
# Create the HDA in /obj (Object-level node, alongside your scene geometry)
dmr = hou.node("/obj").createNode("gero::depth_map_renderer", "depth_renderer")

# Auto-render scene depth from a camera (the default)
dmr.parm("autodepth").set(True)
dmr.parm("camera").set("/obj/cam1")        # or leave empty to auto-pick

# Set output directory (defaults to $HIP/depth_maps/ if empty)
dmr.parm("outputpath").set("$HIP/render/depth_output")

# Configure
dmr.parm("near").set(1.0); dmr.parm("far").set(50.0)  # scene depth range
dmr.parm("normalization").set("LINEAR")   # LINEAR, LOGARITHMIC, or RAW
dmr.parm("invert").set(True)              # near=white, far=black
dmr.parm("format").set("PNG")             # PNG, TIFF, or EXR
dmr.parm("bitdepth").set("16")            # 8 or 16 bit

# Render (Setup runs automatically on create; sliders are already live)
dmr.hm().render_depth(dmr)
```

> `hm()` is shorthand for `hou.Node.hdaModule()` — it returns the HDA's embedded
> Python module. It only works on an installed HDA instance; calling it on a
> plain (non-HDA) node raises `AttributeError`.

Output: `$HIP/render/depth_output/depth_map_0001.png`

### Animation

```python
dmr.parm("animation").set(True)
dmr.parm("usescenerange").set(True)       # uses scene frame range
# Or set manually:
dmr.parm("framestart").set(1)
dmr.parm("frameend").set(250)

dmr.hm().render_depth(dmr, animation=True)
```

### Mask export

Independent from depth — export object masks for ComfyUI:

```python
dmr.parm("maskenabled").set(True)
dmr.parm("maskindex").set(1)              # Object Pass Index
dmr.parm("maskformat").set("GRAYSCALE")   # GRAYSCALE or RGBA
dmr.parm("maskoutputpath").set("$HIP/mask_maps/")

dmr.hm().setup_depth(dmr, mask_only=True)
dmr.hm().render_depth(dmr, mask=True)
```

Set the Object Pass Index on your geometry: **Properties → Relations → Pass Index**.

### What happens internally

The HDA is an **Object subnet** (lives in `/obj`). Its image pipeline lives in an
inner COP network named `depth_cop`. `render_depth()` builds this chain there:

```
/obj/<hda>/depth_cop/
  DM_Source (reads your Z-depth EXR)
  → DM_RangeMap (maps near/far to 0–1)
  → DM_Brightness → DM_Contrast → DM_Scale
  → DM_Grayscale
  → DM_FileOut (writes PNG/TIFF/EXR)
```

Then it cooks `DM_FileOut` per frame with the output path set.

### Live (reactive) parameters

The depth network is built automatically when you create the HDA, so the
**Near**, **Far**, **Brightness**, **Contrast**, **Scale Factor**, and
**Object Index** parameters are wired to the COP nodes with `ch()` expressions
and are **live immediately** — dragging a slider updates the network without
clicking Setup. Structural changes (Normalization, Format, Mask Source) change
the node graph, so they still require a **Setup** click to rebuild.

The HDA is **self-contained**: its Python core is embedded in the asset, so it
works with no `LIMBIC_DEPTH_MAP` env var and no external files. (Setting
`LIMBIC_DEPTH_MAP` is only useful for live development of the core scripts.)

### Houdini 21 (Copernicus) notes

- The HDA is an **Object asset in `/obj`** on all versions. On H21+ its inner
  `depth_cop` network uses **Copernicus** COP nodes; on H18-H20 it uses legacy
  COP2 nodes — auto-detected at runtime.
- **LOGARITHMIC** normalization is unavailable on Copernicus (it has no logarithm
  COP node) and falls back to LINEAR with a warning. The H18-H20 COP2 backend
  keeps full LOG support.
- On COP2, LOG now maps the range from `log(near)`..`log(far)` (previously the
  minimum was hardcoded to `0`), so **`near` affects LOG mode** — re-Setup an
  existing LOG scene to pick up the corrected mapping.

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
