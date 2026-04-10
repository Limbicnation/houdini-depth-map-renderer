# CLAUDE.md — Limbic Depth Map Renderer

This file provides guidance to AI coding agents (Claude Code, Codex, etc.) when working in this repository.

## Project at a Glance

- **Type**: Houdini plugin (Python-only, no compiled C++)
- **What it does**: One-click COP2 depth-map pipeline (mirrors Blender Depth Map Generator)
- **Entry point**: `python_panels/depth_map_panel.py`
- **Min Houdini**: 18.0

## Key Architecture Points

### Single Python module

Everything (HDA definition, operators, Python Panel UI, settings) lives in one file:

```
python_panels/depth_map_panel.py
├── DEFAULT_SETTINGS          # dict — change here to add new settings
├── LimbicDepthMapPanelInterface  # Python Panel UI (Qt)
├── LIMBIC_OT_setup_depth_map     # Creates COP2 network
├── LIMBIC_OT_render_depth_map    # Executes render
├── LIMBIC_OT_reset_depth_map     # Tears down network
├── _build_cop2_network()         # Core pipeline builder
└── _load_settings() / _save_settings()
```

### Node prefix: `DM_`

Every COP2 node created by the plugin is prefixed with `DM_`. This is intentional — it:
- Makes the network easy to read
- Enables safe teardown on reset
- Mirrors Blender's `DM_` convention in its own compositor

### Settings on the node

The HDA stores settings as JSON in a hidden string parm called `dm_settings`. This means:
- Settings persist across sessions (saved with the `.hip` file)
- No external config files needed
- Mirrors Blender's `scene.depth_map_settings` property group

### COP2 vs Blender Compositor

The Houdini COP2 pipeline is conceptually identical to Blender's compositor:

| Blender | Houdini COP2 |
|---|---|
| `CompositorNodeRLayers` | `cop2::deep` (reads Mantra Z) |
| `CompositorNodeMapRange` | `cop2::range` |
| `CompositorNodeBrightContrast` | `cop2::contrast` |
| `CompositorNodeValToRGB` → BW | `cop2::convert` → `bw` |
| `CompositorNodeFileOutput` | `cop2::file_output` |

## Code Style

- **4-space indentation** (Houdini's Python API convention)
- **Type hints** where hou is not typed
- **F-strings** for all string formatting
- **No external dependencies** — only `hou`, `os`, `json`
- **PySide2** for Qt UI (Houdini 18.x), fallback PySide6 (Houdini 20+)

## Modifying the COP2 Network

To change the pipeline (e.g. add a new node):

```python
# In _build_cop2_network() in depth_map_panel.py:

# Create the new node
new_node = parent.createNode("cop2::colormap", "DM_ColorMap")
new_node.setLabel("Custom Color Map")
new_node.setPosition(hou.Vector2(750, 0))

# Wire it in (insert between contrast and grayscale)
new_node.setInput(0, rmap, 0)   # upstream
gray.setInput(0, new_node, 0)   # downstream

# Set parms
new_node.parm("colormap").set("viridis")
```

## Testing in Houdini

There is no headless test suite — the plugin requires a GUI. To test:

1. Open Houdini
2. `File → Import → HDA File…` → select `HDAs/limbic_depth_map_renderer.otlc`
3. Create a COP2 network: right-click → `Material → Compose`
4. Drop the HDA onto the network
5. Open Composite Desk → Depth Map panel
6. Click each button in order: Setup → Render → Reset

## Files Quick-Reference

| File | Purpose |
|---|---|
| `python_panels/depth_map_panel.py` | **Main module** — everything here |
| `installer/install.py` | One-click install (run in Houdini Textport) |
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
2. `_load_settings()` / `_save_settings()`: already generic (JSON serialisation), no change needed
3. Qt panel `buildNormal UI_()`: add a widget and wire it in `_collect_settings_from_ui()`
4. `_build_cop2_network()`: read from `settings` dict and apply to node parms
5. `README.md`: update the settings table

## FAQ

**Q: Why is the HDA `.otlc` just a tar archive?**
A: Real compiled HDAs contain compiled C++ libraries. Since this is Python-only, the `.otlc` is a lightweight tar containing the Python source + a manifest. Houdini can import it as a package reference.

**Q: Can I use a pre-rendered EXR as depth input?**
A: Yes — replace `DM_Source` (`cop2::deep`) with `cop2::file` pointing to the EXR. The code is structured so you only need to change the node creation line in `_build_cop2_network()`.

**Q: The Python Panel doesn't appear.**
A: Make sure the HDA has `python: true` in its definition and the class name matches what Houdini expects. Check `hou.ui.curPaneTab()` — you must be in a Composite Desk for COP2 panels to show.
