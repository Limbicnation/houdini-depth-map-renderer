# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project at a Glance

- **Type**: Houdini digital asset (Python-only, no compiled C++)
- **What it does**: One-click depth-map pipeline (Z-pass → Range → Brightness → Contrast → Scale → Grayscale → PNG/TIFF/EXR), plus an independent ComfyUI mask exporter. Mirrors the Blender Depth Map Generator.
- **HDA type**: `gero::depth_map_renderer` — an **Object subnet** that lives in `/obj`
- **Min Houdini**: 18.0 (legacy COP2 backend), 21.0 (Copernicus / new COP backend)

## Architecture (read this first)

The plugin was refactored from a single file into **three layers**. The old single-file design described by `AGENTS.md` (and prior CLAUDE.md) is obsolete.

```
scripts/settings_model.py          ← single source of truth: DepthMapSettings dataclass
        │  generates PARM_DEFS, _PARM_MAP, DEFAULT_SETTINGS
        ▼
scripts/limbic_depth_map_core.py   ← ALL pipeline logic (pure; no Qt). Edit features HERE.
        ├── scripts/python_module.py   ← thin HDA PythonModule wrapper (button callbacks, init_node)
        ├── scripts/on_created.py      ← HDA OnCreated event → calls python_module.init_node()
        └── python_panels/depth_map_panel.py  ← DEPRECATED Qt UI (kept for back-compat only)
```

**Where to make changes:** almost everything lives in `scripts/limbic_depth_map_core.py`. The HDA now exposes all parameters directly on the node interface — **the Python Panel is deprecated** and should not gain new features.

### The HDA is an Object subnet, not a COP node

An Object subnet cannot host COP nodes directly, so the image pipeline lives in an **inner copnet named `depth_cop`** (`COP_CONTAINER` in core). This two-level nesting matters:

- COP pipeline nodes sit **two levels below** the HDA parameters (HDA → `depth_cop` copnet → `DM_*` nodes).
- Reactive channel references therefore reach HDA parms via **`../../parm`** (see `_chref()`). This is what makes dragging a Near/Far/Brightness slider update the live network without re-running Setup.
- HDA instances are **locked** by default; `_ensure_editable()` calls `allowEditingOfContents()` on the HDA node before any node create/destroy.

### Dual COP backend

Backend is version-detected in `backend()`: Houdini ≥ 21 → `"cop"` (Copernicus), else → `"cop2"` (legacy COP2). H21 removed COP2 entirely. The `_NODE_MAP` dict maps semantic keys (`"source"`, `"range"`, `"brightness"`, …) to the correct node-type string per backend; create nodes via `_create_node(parent, key, name)`, never by hardcoding a type string.

Copernicus-specific gotchas already handled in core (preserve these when editing):
- No logarithm node → **LOG normalization degrades to LINEAR** on `cop`.
- `bright` parm is a **multiplier** (neutral 1.0); additive brightness goes to `shift`.
- A `file` reader exposes **no output layers** until AOVs are populated — `_prime_cop_source()` presses `reload` + `addaovs`. A freshly created source defaults to the placeholder `"default.pic"`, treated as "no source set".
- `rop_image` reads its COP via the `coppath` parm — there is **no image input wire**.
- `CopNode` has no `setLabel()` — `_set_label()` falls back to `setComment()`.

### Two render modes (Auto vs File)

Controlled by the **Auto-Render Scene Depth** toggle (`auto_depth`, default ON):
- **Auto**: `render_scene_depth()` renders the `/obj` scene's camera-space Z (Mantra `ifd` ROP, `Pz` aux plane → temp EXR), points `DM_Source` at it, then processes. Camera comes from the `camera` parm, else the first `/obj` cam.
- **File**: source must already point at a user-provided depth EXR.

### Self-contained bootstrap

The HDA must work for end users with no env var and no repo checkout. `_bootstrap_core()` in `python_module.py`:
1. **Dev mode**: if `$LIMBIC_DEPTH_MAP/scripts/limbic_depth_map_core.py` exists, import from disk (live edits, no rebuild).
2. **Self-contained**: otherwise extract the embedded `settings_model` + `limbic_depth_map_core` HDA sections to a temp dir (`tempfile.mkdtemp`) and import from there.

`hou` is imported **lazily inside functions**, never at module top, so `build.py` can import pure-data constants (`PARM_DEFS`, `_NODE_MAP`, `DEFAULT_SETTINGS`) from system Python outside Houdini.

### Node prefix `DM_`

Every pipeline COP node is prefixed `DM_`; mask nodes additionally start with `DM_M`. This enables selective teardown (`_destroy_depth_nodes` skips `DM_M*`; `_destroy_mask_nodes` keeps only `DM_M*`). The depth and mask pipelines are fully independent.

## Build & Test

There is no headless unit-test suite — but the HDA **can** be built and exercised headlessly via `hython`.

```bash
# 1. Regenerate the Houdini build script (runs in system Python3, outside Houdini)
python3 build.py                              # → HDAs/build_hda.py

# 2. Build + install the .hda inside Houdini
/opt/hfs21.0.512/bin/hython HDAs/build_hda.py
```

- **hython path**: `/opt/hfs21.0.512/bin/hython` (Houdini 21.0.512). `/opt/hfs20.5` has **no** hython, so only H21 building is possible locally.
- **`HDAs/build_hda.py` and `*.hda`/`*.otlc` are gitignored build artifacts** — never commit them.
- Set **`LIMBIC_DEPTH_MAP=<repo root>`** before testing so the runtime imports core from disk and picks up your edits to `scripts/`.
- Syntax check without Houdini: `python3 -m py_compile scripts/*.py build.py`

`build.py` reads the five script files, embeds them as HDA sections, builds an Object subnet → `createDigitalAsset` (Object table) → inner copnet/cop2net → default COP nodes. Build order is load-bearing: build contents → `updateFromNode` → `setParmTemplateGroup` → `addSection` → `setExtraFileOption("OnCreated/IsPython", True)` → `copyToHDAFile`.

## Adding or Changing a Setting

The dataclass is the single source of truth — **do not** maintain parallel dicts.

1. Add a field (with default + type) to `DepthMapSettings` in `scripts/settings_model.py`.
2. If it's a menu, add it to `_MENU_ITEMS`; for a custom label, add to `_PARM_LABELS`; for a non-default parm name, add to `_PARM_NAME_MAP`. `PARM_DEFS`, `_PARM_MAP`, and `DEFAULT_SETTINGS` regenerate automatically.
3. Add the matching `hou.*ParmTemplate` to the relevant folder in `build.py` (the build script defines the actual HDA interface).
4. Read `settings.get("your_key")` in `build_depth_network()` / `build_mask_network()` and apply it to node parms (use a `_chref(...)` expression for live/reactive sliders).
5. Rebuild the HDA (`python3 build.py` → hython) and update `README.md`.

## Adding a Node to the Pipeline

Use the abstraction layer — add a semantic key to `_NODE_MAP` (with both `cop2` and `cop` type strings), then `_create_node(cop, "yourkey", NODE_PREFIX + "YourNode")`, set position, `_wire(node, upstream, be)`, and set parms with a backend conditional on `backend()` where parm names differ.

## Code Style

- 4-space indent, f-strings only, line ~100 chars, trailing commas in multi-line literals.
- No external deps beyond `hou`, `os`, `json`, `math`, `sys`, `tempfile`. Import `hou` lazily inside functions.
- Wrap fallible Houdini API calls in `_try()` / `_try_ok()` (log to stderr, return default) rather than bare try/except. User-facing messages go through `notify(node, severity, msg)`.
- A repo security hook false-positives on the Python dynamic-code builtins. Avoid those tokens in source — load embedded code via temp-file extraction plus a normal `import`, and read parm values with `parm.evalAsString()` / `parm.evalAsInt()` (the Houdini API forms the hook won't flag).

## Commit Convention

Do **not** add `Co-Authored-By: Claude` or other AI attribution to commit messages in this repo.

## Files Quick-Reference

| File | Purpose |
|---|---|
| `scripts/limbic_depth_map_core.py` | **Main module** — all pipeline logic |
| `scripts/settings_model.py` | `DepthMapSettings` dataclass + parm generators (single source of truth) |
| `scripts/python_module.py` | HDA PythonModule wrapper + bootstrap + button callbacks |
| `scripts/on_created.py` | HDA OnCreated script → `init_node()` |
| `python_panels/depth_map_panel.py` | **Deprecated** Qt panel (back-compat only) |
| `build.py` | Generates `HDAs/build_hda.py` (run inside hython to build the `.hda`) |
| `config/shelf_actions.py` | Houdini shelf tool registration |
| `installer/install.py` / `install_fixed.py` | Installers |
| `AGENTS.md` | Older agent guidance — **partially stale** (describes the pre-refactor single-file design) |
| `README.md` | End-user docs |

## Environment Variables

| Variable | Used by | Meaning |
|---|---|---|
| `$HIP` | Houdini | Current scene directory (default output root) |
| `$HFS` | build.py / installer | Houdini install root |
| `LIMBIC_DEPTH_MAP` | bootstrap / shelf_actions | Path to this repo (enables dev-mode import from disk) |
