# AGENTS.md — Houdini Depth Map Renderer (v2.0)

## Project Overview

Limbic Depth Map Renderer ports Blender Depth Map Generator v2.0 to Houdini. Two independent COP2 pipelines (depth compositor + ComfyUI mask exporter) accessed via a Python Panel UI.

- **Version**: 2.0.0 | **License**: Apache 2.0 | **Min Houdini**: 18.0 | **Language**: Python 3.9+

## Build / Lint / Test Commands

### Build
```bash
python3 build.py                          # build .otlc to ./HDAs/
python3 build.py --out ./HDAs/custom.otlc # custom output path
python3 build.py --install                # build + copy to ~/houdini18.0/otls/
python3 build.py --verbose                # build with archive contents listing
```

### Lint
No linter is configured. Use standard Python tooling:
```bash
python3 -m py_compile python_panels/depth_map_panel.py  # syntax check
python3 -m py_compile build.py
python3 -m py_compile installer/install.py
python3 -m py_compile config/shelf_actions.py
```

### Test
There is **no headless test suite** — the plugin requires Houdini's GUI and `hou` module. Manual testing checklist:

1. Open Houdini → import HDA: `File → Import → HDA File…` → select `HDAs/limbic_depth_map_renderer.otlc`
2. Create COP2 network: right-click → `Material → Compose`
3. Drop HDA onto network → open Composite Desk → Depth Map panel
4. Test each pipeline independently:
   - **Depth**: Setup → Render → verify output files → Reset
   - **Mask**: Setup Mask → Render Mask → verify output files → Reset Mask
5. Test all normalization modes: LINEAR, LOGARITHMIC, RAW
6. Test animation rendering, GRAYSCALE vs RGBA mask format

### Single test scenario (manual)
```
1. Setup depth with LINEAR → verify DM_RangeMap node params (from_min/from_max/to_min/to_max)
2. Setup depth with LOGARITHMIC → verify DM_LOG + DM_RangeMap chain exists
3. Setup depth with RAW → verify no range node in network
4. Brightness=0.5 → verify DM_Brightness brightness parm = 0.5
5. Contrast=0.3 → verify DM_Contrast gain parm = 1.30
6. Scale=2.0 → verify DM_Scale scale1 parm = 2.0
```

## Code Style Guidelines

### Imports
```python
import os
import json
import math

import hou
```
- Standard library first (alphabetical), then a blank line, then third-party (`hou`)
- No external dependencies beyond `hou`, `os`, `json`, `math`, `sys`
- PySide2 import with PySide6 fallback:
  ```python
  try:
      from PySide2 import QtWidgets, QtCore, QtGui
  except ImportError:
      try:
          from PySide6 import QtWidgets, QtCore, QtGui
      except ImportError:
          from PySide2 import QtWidgets, QtCore, QtGui
  ```

### Formatting
- **4-space indentation** (no tabs) — Houdini Python convention
- **Line width**: ~100 chars soft limit
- **Trailing commas** in multi-line dicts/lists (follow existing patterns)
- **Section dividers**: use `# ── Section Name ───────────` style with 72-char rule
- **No blank line** after function docstring closing `"""`

### Type Annotations
- Use type hints for function signatures where `hou` types are involved:
  ```python
  def build_depth_network(node: hou.COP2Node, settings: dict):
  def _save(node: hou.Node, settings: dict):
  def _output_dir(settings: dict, key: str = "output_path",
                  fallback: str = "depth_maps") -> str:
  ```
- `dict` for settings (not TypedDict — keep it simple)
- Return types where non-obvious; omit for `-> None` defaults

### Naming Conventions
| Item | Convention | Example |
|---|---|---|
| Module-level constants | `UPPER_SNAKE` | `NODE_PREFIX`, `HDA_CATEGORY`, `DEFAULT_SETTINGS` |
| Private module functions | `_lower_snake` | `_load()`, `_save()`, `_dm_children()` |
| Operator classes | `Op{Name}` (PascalCase with Op prefix) | `OpSetup`, `OpRender`, `OpReset` |
| Operator methods | `@staticmethod` named `execute` | `OpSetup.execute(node, mask_only=False)` |
| COP2 node names | `DM_` prefix + PascalCase | `DM_Source`, `DM_RangeMap`, `DM_FileOut` |
| Mask pipeline nodes | `DM_M` prefix | `DM_MSource`, `DM_MGrayscale`, `DM_MaskFileOut` |
| Settings keys | `lower_snake` | `"normalization"`, `"scale_factor"`, `"mask_enabled"` |
| Qt widget variables | `lower_snake` with type hint | `combo_norm`, `spin_near`, `btn_setup` |
| HDA category | `"Limic"` (typo preserved for compat) | `HDA_CATEGORY = "Limic"` |

### String Formatting
- **Always use f-strings** — never `%` formatting or `.format()`
- F-strings for notification messages, file paths, node labels:
  ```python
  f"Depth Map: {mode} network created"
  f"Setup failed: {e}"
  os.path.join(odir, fname)
  ```

### Error Handling
- Use `_notify()` helper for user-facing messages (sets Houdini status bar):
  ```python
  _notify(node, hou.severityType.Important, f"Depth Map: {mode} network created")
  _notify(node, hou.severityType.Error, f"Setup failed: {e}")
  ```
- Settings load: fail silently to defaults (`_load()` returns `DEFAULT_SETTINGS` on error)
- Node destruction: iterate `_dm_children()` and `destroyChild()` — no orphan check needed
- Shelf actions: catch `ImportError` and display Houdini message dialog
- Operator `execute()` methods: catch all exceptions, notify error, return `False`

### Architecture Patterns

#### Two Independent Pipelines
Depth and Mask pipelines are fully independent. Mask nodes use `DM_M` prefix to allow selective teardown:
```python
# Reset depth only — preserve mask nodes
for n in _dm_children(node):
    if n.name().startswith(NODE_PREFIX + "M"):  # skip mask nodes
        continue
    node.destroyChild(n)

# Reset mask only — preserve depth nodes
for n in _dm_children(node):
    if not n.name().startswith(NODE_PREFIX + "M"):  # skip depth nodes
        continue
    node.destroyChild(n)
```

#### Settings Persistence
Settings stored as JSON on node's `dm_settings` hidden string parm. Always use `_load()`/`_save()`:
```python
settings = _load(node)        # merge with DEFAULT_SETTINGS
settings["contrast"] = 0.3    # modify
_save(node, settings)         # write back
```

#### Adding a New Normalization Mode
1. Add mode string to `DEFAULT_SETTINGS["normalization"]` options
2. In `build_depth_network()`, add a branch with `NODE_PREFIX + "ModeName"`
3. Update the QComboBox in `_build_ui()`
4. Update README

#### Adding a New Setting
1. Add key/value to `DEFAULT_SETTINGS` dict
2. `_load()`/`_save()` already handle arbitrary JSON — no change needed
3. Add widget in `_build_ui()` and wire into `_collect()` / `_load()`
4. Read from `settings` dict in `build_depth_network()` / `build_mask_network()`
5. Update README settings table

## Key Files

| File | Purpose |
|---|---|
| `python_panels/depth_map_panel.py` | Main module — depth + mask pipelines, Qt UI, operators |
| `build.py` | `.otlc` HDA archive generator (tar + xz) |
| `installer/install.py` | Houdini Textport install script |
| `config/shelf_actions.py` | Shelf tool registration |
| `README.md` | End-user documentation |
| `CLAUDE.md` | Claude Code specific guidance |

## COP2 Node Reference

| Node Type | Role |
|---|---|
| `cop2::deep` | Read Z from Mantra deep raster |
| `cop2::range` | Linear depth normalization (MapRange) |
| `cop2::ln` | Natural log (LOGARITHMIC mode preprocessor) |
| `cop2::brightness` | Additive brightness offset |
| `cop2::contrast` | Multiplicative gain (contrast) |
| `cop2::multiply` | Scale factor |
| `cop2::convert` | RGBA ↔ BW conversion |
| `cop2::file_output` | PNG/TIFF/EXR writer |
| `cop2::viewer` | Interactive preview |
| `cop2::idtopmask` | Object Index → BW mask |
| `cop2::cryptomatte` | Cryptomatte AOV reader |
| `cop2::constant` | Solid color constant (RGBA mask white fill) |

## Environment Variables

| Variable | Used By | Meaning |
|---|---|---|
| `$HIP` | Houdini | Current scene directory (output default) |
| `$HFS` | build.py, installer | Houdini install root |
| `LIMBIC_DEPTH_MAP` | shelf_actions.py | Path to this repository |