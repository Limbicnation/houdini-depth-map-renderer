# CLAUDE.md — Limbic Depth Map Renderer

This file provides guidance to AI coding agents (Claude Code, Codex, etc.) when working in this repository.

## Project at a Glance

- **Type**: Houdini plugin (Python-only, no compiled C++)
- **What it does**: One-click depth-map pipeline (mirrors Blender Depth Map Generator)
- **Entry point**: `python_panels/depth_map_panel.py`
- **Min Houdini**: 18.0 (COP2 backend), 21.0 (new COP backend)

## Key Architecture Points

### Single Python module

Everything (HDA definition, operators, Python Panel UI, settings) lives in one file:

```
python_panels/depth_map_panel.py
├── _backend() / _NODE_MAP       # COP backend detection (cop2 vs cop)
├── _create_node()                # Backend-aware node creation
├── DEFAULT_SETTINGS              # dict — change here to add new settings
├── build_depth_network()         # Depth pipeline builder
├── build_mask_network()          # Mask pipeline builder
├── OpSetup / OpRender / OpReset  # Operators
├── DepthMapPanel                 # Python Panel UI (Qt)
└── _load() / _save()            # Settings persistence
```

### Dual COP backend

The plugin auto-detects the Houdini version at runtime:
- **H18-H20**: `cop2net` container + `cop2::*` node types (legacy COP2)
- **H21+**: `copnet` container + new COP node types (`bright`, `remap`, `mono`, etc.)

Node type mapping lives in `_NODE_MAP` dict. Backend detection in `_backend()`.

### Node prefix: `DM_`

Every COP node created by the plugin is prefixed with `DM_`. This is intentional — it:
- Makes the network easy to read
- Enables safe teardown on reset
- Mirrors Blender's `DM_` convention in its own compositor

### Settings on the node

The HDA stores settings as JSON in a hidden string parm called `dm_settings`. This means:
- Settings persist across sessions (saved with the `.hip` file)
- No external config files needed
- Mirrors Blender's `scene.depth_map_settings` property group

### Houdini COP vs Blender Compositor

| Blender | COP2 (H18-H20) | New COP (H21+) |
|---|---|---|
| `CompositorNodeRLayers` | `cop2::deep` | `file` |
| `CompositorNodeMapRange` | `cop2::range` | `remap` |
| `CompositorNodeBrightContrast` | `cop2::brightness` / `cop2::contrast` | `bright` / `contrast` |
| `CompositorNodeValToRGB` → BW | `cop2::convert` → `bw` | `mono` |
| `CompositorNodeFileOutput` | `cop2::file_output` | `rop_image` |

## Code Style

- **4-space indentation** (Houdini's Python API convention)
- **Type hints** where hou is not typed
- **F-strings** for all string formatting
- **No external dependencies** — only `hou`, `os`, `json`
- **PySide2** for Qt UI (Houdini 18.x), fallback PySide6 (Houdini 20+)

## Modifying the Pipeline

To add a new node to the depth pipeline, use the abstraction layer:

```python
# In build_depth_network() in depth_map_panel.py:

# Add to _NODE_MAP first:
#   "colormap": {"cop2": "cop2::colormap", "cop": "colorcorrect"},

# Then create using the abstraction:
new_node = _create_node(parent, "colormap", "DM_ColorMap")
new_node.setLabel("Custom Color Map")
new_node.setPosition(hou.Vector2(750, 0))

# Wire it in
new_node.setInput(0, rmap, 0)
gray.setInput(0, new_node, 0)

# Set parms (use backend conditional if names differ)
be = _backend()
if be == "cop":
    new_node.parm("new_cop_parm").set("viridis")
else:
    new_node.parm("colormap").set("viridis")
```

## Testing in Houdini

There is no headless test suite — the plugin requires a GUI. To test:

1. Open Houdini
2. Run `install_fixed.py` in Houdini Textport
3. Open Composite Desk → Depth Map panel
4. Click each button in order: Setup → Render → Reset
5. Test all normalization modes: LINEAR, LOGARITHMIC, RAW

## Files Quick-Reference

| File | Purpose |
|---|---|
| `python_panels/depth_map_panel.py` | **Main module** — everything here |
| `install_fixed.py` | Modern installer (H21+ compatible) |
| `installer/install.py` | Legacy installer |
| `build.py` | Generates the `.otlc` HDA archive |
| `config/shelf_actions.py` | Houdini shelf tool registration |
| `AGENTS.md` | General agent guidance |
| `CLAUDE.md` | This file |
| `README.md` | End-user docs |

## Environment Variables

| Variable | Used by | Meaning |
|---|---|---|
| `$HIP` | Houdini | Current Houdini scene directory |
| `$HFS` | build.py / installer | Houdini install root |
| `LIMBIC_DEPTH_MAP` | shelf_actions.py | Path to this repository |

## Adding a New Setting

1. `DEFAULT_SETTINGS` dict: add the key/value
2. `_load()` / `_save()`: already generic (JSON serialisation), no change needed
3. Qt panel `_build_ui()`: add a widget and wire it in `_collect()`
4. `build_depth_network()`: read from `settings` dict and apply to node parms
5. `README.md`: update the settings table

## FAQ

**Q: Why is the HDA `.otlc` just a tar archive?**
A: Real compiled HDAs contain compiled C++ libraries. Since this is Python-only, the `.otlc` is a lightweight tar containing the Python source + a manifest.

**Q: Can I use a pre-rendered EXR as depth input?**
A: On H21+ the source node is already a `file` node — set `filename` to the EXR path. On H18-H20, change the `"source"` entry in `_NODE_MAP` or replace `DM_Source` with `cop2::file`.

**Q: The Python Panel doesn't appear.**
A: Make sure the panel is installed via `install_fixed.py`. Check `hou.ui.curPaneTab()` — you must be in a Composite Desk for compositor panels to show.

**Q: How does the dual backend work?**
A: `_backend()` tries to create a `copnet` node. If it succeeds → H21+ (new COP). If it fails → H18-H20 (legacy COP2). The result is cached for the session. `_NODE_MAP` maps semantic keys to the correct node type strings per backend.
