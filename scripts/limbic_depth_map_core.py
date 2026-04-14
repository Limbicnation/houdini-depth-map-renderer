"""Limbic Depth Map Renderer — Shared Core.
==========================================
Pure pipeline logic shared between the HDA PythonModule and the
Python Panel UI.  No Qt imports — only hou, os, json, math, sys.

Dual COP backend: cop2 (H18-H20) / cop (H21+).

Three-layer architecture:
    limbic_depth_map_core.py  (pure logic — this file)
    ├── python_module.py      (thin HDA PythonModule wrapper)
    └── depth_map_panel.py    (thin Qt UI wrapper)
"""

import os
import json
import math
import sys

from settings_model import (
    DepthMapSettings,
    generate_parm_defs,
    generate_parm_map,
    generate_default_settings,
    parm_name as _parm_name,
    _INTERNAL_FIELDS,
)

# NOTE: `import hou` is done LAZILY inside each function that needs it.
# This allows build.py (which runs in system Python3, outside Houdini) to
# import pure-data constants like PARM_DEFS, _NODE_MAP, DEFAULT_SETTINGS
# without triggering ModuleNotFoundError for the `hou` module.

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

NODE_PREFIX = "DM_"
HDA_CATEGORY = "Limic"
LAYOUT_STEP_X = 200
LAYOUT_MASK_Y = -300

# ─────────────────────────────────────────────────────────────────────────────
# COP Backend Detection
# ─────────────────────────────────────────────────────────────────────────────

_ENABLE_COP_BACKEND = False

_COP_BACKEND = None


def backend() -> str:
    global _COP_BACKEND
    if _COP_BACKEND is None:
        if _ENABLE_COP_BACKEND:
            import hou
            ver = hou.applicationVersion()
            _COP_BACKEND = "cop" if ver[0] >= 21 else "cop2"
        else:
            _COP_BACKEND = "cop2"
    return _COP_BACKEND


def reset_backend_cache():
    global _COP_BACKEND
    _COP_BACKEND = None


# Semantic key → {backend: houdini_type_string}
# NOTE: "scale" maps to cop2::multiply (has scale1 parm) and cop::function
# (uses func=0 for multiply, val1a for the multiplier).  The function COP
# does NOT have a "scale" parm — setting logic is handled in
# build_depth_network().
_NODE_MAP = {
    "source":       {"cop2": "cop2::file",        "cop": "file"},
    "log":          {"cop2": "cop2::function",    "cop": "function"},
    "range":        {"cop2": "cop2::range",       "cop": "remap"},
    "brightness":   {"cop2": "cop2::brightness",  "cop": "bright"},
    "contrast":     {"cop2": "cop2::contrast",    "cop": "contrast"},
    "scale":        {"cop2": "cop2::multiply",    "cop": "function"},
    "grayscale":    {"cop2": "cop2::convert",     "cop": "mono"},
    "file_output":  {"cop2": "cop2::file_output", "cop": "rop_image"},
    "viewer":       {"cop2": "cop2::viewer",      "cop": "output"},
    "idtomask":     {"cop2": "cop2::idtomask",    "cop": "idtomask"},
    "cryptomatte":  {"cop2": "cop2::cryptomatte", "cop": "cryptomatte"},
    "convert_rgba": {"cop2": "cop2::convert",     "cop": "monotorgba"},
    "sopimport":    {"cop2": "cop2::file",        "cop": "sopimport"},
    "rasterize":    {"cop2": "cop2::rasterize",   "cop": "rasterizegeo"},
}


def _create_node(parent, key, name):
    return parent.createNode(_NODE_MAP[key][backend()], name)


def _set_label(node, label):
    import hou
    if not _try_ok(node.setLabel, label, where="set_label"):
        _try_ok(node.setComment, label, where="set_label_comment")
        _try_ok(node.setGenericFlag, hou.nodeFlag.DisplayComment, True,
                where="set_label_flag")


def _container_type():
    return "copnet" if backend() == "cop" else "cop2net"


def _safe_set_display(node, display_node):
    if hasattr(node, "setDisplayNode"):
        _try(node.setDisplayNode, display_node, where="set_display")


_SENTINEL = object()


def _try(fn, *args, where: str = "", default=None, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception as e:
        print(f"[limbic_depth_map] {where}: {type(e).__name__}: {e}",
              file=sys.stderr)
        return default


def _try_ok(fn, *args, where: str = "", **kwargs) -> bool:
    try:
        fn(*args, **kwargs)
        return True
    except Exception as e:
        print(f"[limbic_depth_map] {where}: {type(e).__name__}: {e}",
              file=sys.stderr)
        return False


def _wire(node, upstream, be, input_name='source', input_idx=0,
          output_idx=0):
    """Connect upstream → node.  Dispatches by COP backend.

    H21+ ``cop`` nodes expose named inputs (e.g. 'source') so
    setNamedInput is preferred.  cop2 nodes use positional
    setInput(index, …).  Falls back gracefully so a single code
    path works across both backends.
    """
    if be == "cop":
        if _try_ok(node.setNamedInput, input_name, upstream, output_idx,
                   where=f"wire_named:{node.name()}"):
            return
    _try_ok(node.setInput, input_idx, upstream, output_idx,
            where=f"wire:{node.name()}")


# ─────────────────────────────────────────────────────────────────────────────
# Default Settings
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_SETTINGS = generate_default_settings()

# ─────────────────────────────────────────────────────────────────────────────
# HDA Explicit Parameter Interface
# ─────────────────────────────────────────────────────────────────────────────

_PARM_MAP = generate_parm_map()

PARM_DEFS = generate_parm_defs()


def has_explicit_parms(node) -> bool:
    return node.parm("normalization") is not None


def load_settings(node) -> dict:
    if has_explicit_parms(node):
        settings = {**DEFAULT_SETTINGS}
        for parm_name, key in _PARM_MAP.items():
            p = node.parm(parm_name)
            if p is not None:
                val = _try(p.eval, where=f"load_parm:{parm_name}",
                           default=_SENTINEL)
                if val is not _SENTINEL:
                    settings[key] = val
        json_p = node.parm("dm_settings")
        if json_p is not None:
            raw = _try(json_p.eval, where="load_json_parm")
            if raw:
                saved = _try(json.loads, raw, where="parse_json_settings",
                             default={})
                if saved:
                    settings["setup_complete"] = saved.get(
                        "setup_complete", False)
                    settings["mask_setup_complete"] = saved.get(
                        "mask_setup_complete", False)
        return settings

    p = node.parm("dm_settings")
    if p is not None:
        raw = _try(p.eval, where="load_json_parm")
        if raw:
            saved = _try(json.loads, raw, where="parse_json_settings",
                         default={})
            if saved:
                return {**DEFAULT_SETTINGS, **saved}
    return {**DEFAULT_SETTINGS}


def save_settings(node, settings: dict):
    tracking = {
        "setup_complete": settings.get("setup_complete", False),
        "mask_setup_complete": settings.get("mask_setup_complete", False),
    }
    p = node.parm("dm_settings")
    if p is not None:
        _try(p.set, json.dumps(tracking), where="save_json_parm")

    if has_explicit_parms(node):
        for parm_name, key in _PARM_MAP.items():
            p = node.parm(parm_name)
            if p is not None and key in settings:
                _try(p.set, settings[key], where=f"save_parm:{parm_name}")


def add_dm_settings_parm(node) -> bool:
    import hou
    if node.parm("dm_settings") is not None:
        return True
    try:
        pg = node.parmTemplateGroup()
        # Note: 'hide' kwarg is invalid in H21+ — call .hide(True) on the template
        pt = hou.StringParmTemplate(
            "dm_settings", "DM Settings", 1,
            default_value=[json.dumps(DEFAULT_SETTINGS)])
        pt.hide(True)
        pg.addParmTemplate(pt)
        node.setParmTemplateGroup(pg)
        return node.parm("dm_settings") is not None
    except Exception as e:
        print(f"[Limbic Depth Map] Could not add dm_settings parm to "
              f"{node.path()}: {e}", file=sys.stderr)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def dm_children(node):
    return [n for n in node.children() if n.name().startswith(NODE_PREFIX)]


def output_dir(settings: dict, key: str = "output_path",
               fallback: str = "depth_maps") -> str:
    """Return the output directory, creating it if needed.

    Handles both directory paths ("$HIP/depth_maps/") and
    file paths ("$HIP/Render/Temp/Depth.jpg") gracefully —
    the latter's parent directory is used.
    """
    import hou
    path = settings.get(key, "").strip()
    if not path:
        path = hou.expandString(f"$HIP/{fallback}/")
    path = hou.expandString(path)
    # If path looks like a file (has extension), use its parent dir
    _, ext = os.path.splitext(path)
    if ext:
        path = os.path.dirname(path)
    os.makedirs(path, exist_ok=True)
    return path if path.endswith(os.sep) else path + os.sep


def filename(settings: dict, prefix: str, frame=None) -> str:
    if frame is not None and settings.get("animation"):
        fname = f"{prefix}_{frame:05d}"
    else:
        fname = prefix
    ext = {"PNG": "png", "TIFF": "tiff", "EXR": "exr"}.get(
        settings.get("format", "PNG"), "png")
    return f"{fname}.{ext}"


def frame_range(settings: dict):
    import hou
    if settings.get("use_scene_range", True):
        r = hou.playbar.playbackRange()
        return range(int(r[0]), int(r[1]) + 1)
    return range(settings.get("frame_start", 1), settings.get("frame_end", 250) + 1)


def notify(node, severity, msg: str):
    import hou
    try:
        hou.ui.setStatusMessage(msg, severity=severity)
    except Exception:
        print(f"[{severity.name}] {msg}", file=sys.stderr)


# ─────────────────────────────────────────────────────────────────────────────
# Path Normalization
# ─────────────────────────────────────────────────────────────────────────────

def resolve_script_path(relative_path: str) -> str:
    import hou
    hip_path = hou.expandString(f"$HIP/{relative_path}")
    if os.path.exists(hip_path):
        return hip_path

    limbic_root = os.environ.get("LIMBIC_DEPTH_MAP", "")
    if limbic_root:
        plugin_path = os.path.join(limbic_root, relative_path)
        if os.path.exists(plugin_path):
            return plugin_path

    for hp in hou.expandString("$HOUDINI_PATH").split(os.pathsep):
        candidate = os.path.join(hp, relative_path)
        if os.path.exists(candidate):
            return candidate

    expanded = hou.expandString(relative_path)
    if os.path.isabs(expanded) or os.path.exists(expanded):
        return expanded

    return hip_path



# ─────────────────────────────────────────────────────────────────────────────
# COP Network Builders
# ─────────────────────────────────────────────────────────────────────────────

def _destroy_depth_nodes(node):
    for n in list(dm_children(node)):
        if n.name().startswith(NODE_PREFIX + "M"):
            continue
        _try(n.destroy, where=f"destroy_depth:{n.name()}")


def _destroy_mask_nodes(node):
    for n in list(dm_children(node)):
        if not n.name().startswith(NODE_PREFIX + "M"):
            continue
        _try(n.destroy, where=f"destroy_mask:{n.name()}")


def _set_range_parms(rmap, near, far, inv, be):
    if be == "cop":
        rmap.parm("inputmin").set(near)
        rmap.parm("inputmax").set(far)
        rmap.parm("outputmin").set(1.0 if inv else 0.0)
        rmap.parm("outputmax").set(0.0 if inv else 1.0)
    else:
        rmap.parm("from_min").set(near)
        rmap.parm("from_max").set(far)
        rmap.parm("to_min").set(1.0 if inv else 0.0)
        rmap.parm("to_max").set(0.0 if inv else 1.0)


def _set_scale_parms(scale_node, sf, be):
    if be == "cop":
        # H21 function COP: func=0 (multiply), parm name is "scale" not "val1a"
        scale_node.parm("func").set(0)
        scale_node.parm("scale").set(sf)
    else:
        scale_node.parm("scale1").set(sf)


def _set_file_output_parms(fout, upstream, odir, fname, settings, be):
    if be == "cop":
        fout.parm("coppath").set(upstream.path())
        fout.parm("copoutput").set(os.path.join(odir, fname))
    else:
        fout.parm("file").set(os.path.join(odir, fname))
        fout.parm("filetype").set(settings.get("format", "PNG").lower())
        fout.parm("bitdepth").set(settings.get("bit_depth", "16"))


def build_depth_network(node, settings: dict):
    import hou
    be = backend()
    _destroy_depth_nodes(node)

    norm = settings.get("normalization", "LINEAR")
    inv = settings.get("invert", True)
    near = settings.get("near", 0.1)
    far = settings.get("far", 1000.0)
    sf = settings.get("scale_factor", 1.0)
    STEP = LAYOUT_STEP_X

    src = _create_node(node, "source", NODE_PREFIX + "Source")
    _set_label(src, "Z-Depth Source")
    src.setPosition(hou.Vector2(0, 0))

    norm_steps = {"RAW": 0, "LINEAR": 1, "LOGARITHMIC": 2}
    norm_node_count = norm_steps.get(norm, 1)

    if norm == "RAW":
        normalize = src
    elif norm == "LOGARITHMIC":
        log_node = _create_node(node, "log", NODE_PREFIX + "LOG")
        _set_label(log_node, "Log Normalize")
        log_node.setPosition(hou.Vector2(STEP, 0))
        _wire(log_node, src, be)
        log_node.parm("func").set(1)
        log_node.parm("func_math").set(3)

        rmap = _create_node(node, "range", NODE_PREFIX + "RangeMap")
        _set_label(rmap, "Log Range Mapper")
        rmap.setPosition(hou.Vector2(STEP * 2, 0))
        log_min = 0.0
        log_max = math.log(max(far, 0.001))
        _set_range_parms(rmap, log_min, log_max, inv, be)
        _wire(rmap, log_node, be)
        normalize = rmap
    else:
        rmap = _create_node(node, "range", NODE_PREFIX + "RangeMap")
        _set_label(rmap, "Depth Range Mapper")
        rmap.setPosition(hou.Vector2(STEP, 0))
        _set_range_parms(rmap, near, far, inv, be)
        _wire(rmap, src, be)
        normalize = rmap

    x = (norm_node_count + 1) * STEP
    bright = _create_node(node, "brightness", NODE_PREFIX + "Brightness")
    _set_label(bright, "Brightness")
    bright.setPosition(hou.Vector2(x, 0))
    bright.parm("bright" if be == "cop" else "brightness").set(
        settings.get("brightness", 0.0))
    _wire(bright, normalize, be)

    x += STEP
    ctr = _create_node(node, "contrast", NODE_PREFIX + "Contrast")
    _set_label(ctr, "Depth Contrast")
    ctr.setPosition(hou.Vector2(x, 0))
    ctr.parm("contrast" if be == "cop" else "gain").set(
        1.0 + settings.get("contrast", 0.2))
    _wire(ctr, bright, be)

    x += STEP
    scale = _create_node(node, "scale", NODE_PREFIX + "Scale")
    _set_label(scale, "Depth Scale")
    scale.setPosition(hou.Vector2(x, 0))
    _set_scale_parms(scale, sf, be)
    _wire(scale, ctr, be)

    x += STEP
    gray = _create_node(node, "grayscale", NODE_PREFIX + "Grayscale")
    _set_label(gray, "Grayscale Output")
    gray.setPosition(hou.Vector2(x, 0))
    if be == "cop2":
        gray.parm("copoutput").set("bw")
    _wire(gray, scale, be)

    x += STEP
    fout = _create_node(node, "file_output", NODE_PREFIX + "FileOut")
    _set_label(fout, "Depth File Output")
    fout.setPosition(hou.Vector2(x, 0))
    odir = output_dir(settings, "output_path", "depth_maps")
    fname = filename(settings, "depth_map")
    _set_file_output_parms(fout, gray, odir, fname, settings, be)
    _wire(fout, gray, be)

    if settings.get("preview", False):
        viewer = _create_node(node, "viewer", NODE_PREFIX + "Viewer")
        _set_label(viewer, "Depth Preview")
        viewer.setPosition(hou.Vector2(x, 100))
        _wire(viewer, gray, be)

    display = gray if be == "cop" else fout
    _safe_set_display(node, display)
    node.layoutChildren()
    return fout


def build_mask_network(node, settings: dict):
    import hou
    be = backend()
    _destroy_mask_nodes(node)

    source = settings.get("mask_source", "OBJECT_INDEX")
    mfmt = settings.get("mask_format", "GRAYSCALE")
    midx = settings.get("mask_index", 1)
    STEP = LAYOUT_STEP_X
    Y = LAYOUT_MASK_Y

    if source == "CRYPTOMATTE":
        mask_src = _create_node(node, "cryptomatte", NODE_PREFIX + "MSource")
        _set_label(mask_src, "Cryptomatte Source")
        mask_src.setPosition(hou.Vector2(0, Y))
        if be == "cop":
            mask_input = _create_node(node, "source", NODE_PREFIX + "MaskInput")
            _set_label(mask_input, "Cryptomatte EXR Source — set path")
            mask_input.setPosition(hou.Vector2(-200, Y))
            _wire(mask_src, mask_input, be)

    elif be == "cop" and source == "OBJECT_INDEX":
        mask_input = _create_node(node, "sopimport", NODE_PREFIX + "MaskInput")
        _set_label(mask_input, "SOP Source (set path to your geo)")
        mask_input.setPosition(hou.Vector2(-200, Y))
        _try(mask_input.parm("soppath").set, "",
             where="set_soppath")

        mask_src = _create_node(node, "rasterize", NODE_PREFIX + "MSource")
        _set_label(mask_src, "Rasterize Geo to Mask")
        mask_src.setPosition(hou.Vector2(0, Y))
        _wire(mask_src, mask_input, be)

    else:
        mask_src = _create_node(node, "idtomask", NODE_PREFIX + "MSource")
        _set_label(mask_src, "Object Index Mask")
        mask_src.setPosition(hou.Vector2(0, Y))
        _try(mask_src.parm("object_id").set, midx,
             where="set_object_id")

    x = 300
    if mfmt == "RGBA":
        convert_ = _create_node(node, "convert_rgba",
                                NODE_PREFIX + "MRGBA_Convert")
        _set_label(convert_, "RGBA Convert")
        convert_.setPosition(hou.Vector2(x, Y))
        if be == "cop2":
            convert_.parm("copoutput").set("rgba")
        _wire(convert_, mask_src, be)
        mask_out = convert_
    else:
        mask_out = _create_node(node, "grayscale", NODE_PREFIX + "MGrayscale")
        _set_label(mask_out, "Grayscale Mask")
        mask_out.setPosition(hou.Vector2(x, Y))
        if be == "cop2":
            mask_out.parm("copoutput").set("bw")
        _wire(mask_out, mask_src, be)

    x += STEP
    mfout = _create_node(node, "file_output", NODE_PREFIX + "MaskFileOut")
    _set_label(mfout, "Mask File Output")
    mfout.setPosition(hou.Vector2(x, Y))

    odir = output_dir(settings, "mask_output_path", "mask_maps")
    fname = filename(settings, "mask_map")
    mask_settings = {**settings, "format": "PNG", "bit_depth": "16"}
    _set_file_output_parms(mfout, mask_out, odir, fname, mask_settings, be)
    _wire(mfout, mask_out, be)

    display = mask_out if be == "cop" else mfout
    _safe_set_display(node, display)
    node.layoutChildren()
    return mfout


# ─────────────────────────────────────────────────────────────────────────────
# Operators
# ─────────────────────────────────────────────────────────────────────────────

def setup_depth(node, mask_only=False) -> bool:
    import hou
    settings = load_settings(node)
    try:
        if mask_only:
            build_mask_network(node, settings)
            settings["mask_setup_complete"] = True
        else:
            build_depth_network(node, settings)
            settings["setup_complete"] = True
        save_settings(node, settings)
        mode = "Mask" if mask_only else "Depth"
        notify(node, hou.severityType.ImportantMessage,
               f"Depth Map: {mode} network created")
        return True
    except Exception as e:
        notify(node, hou.severityType.Error, f"Setup failed: {e}")
        return False


def render_depth(node, animation=False, mask=False) -> bool:
    import hou
    try:
        settings = load_settings(node)
        settings["animation"] = animation
        save_settings(node, settings)

        prefix = "Mask" if mask else "depth"
        complete_key = "mask_setup_complete" if mask else "setup_complete"

        if not settings.get(complete_key, False):
            if not setup_depth(node, mask_only=mask):
                return False

        fout = node.node(NODE_PREFIX + ("MaskFileOut" if mask else "FileOut"))
        if not fout:
            notify(node, hou.severityType.Error,
                   "Depth Map: output node not found - re-run Setup")
            return False

        frames = list(frame_range(settings)) if animation else [hou.frame()]
        if animation:
            notify(node, hou.severityType.ImportantMessage,
                   f"Depth Map: rendering {len(frames)} {prefix} frames...")

        be = backend()
        odir = output_dir(settings,
                          "mask_output_path" if mask else "output_path",
                          "mask_maps" if mask else "depth_maps")
        for frame in frames:
            hou.setFrame(frame)
            fname = filename(settings,
                             "mask_map" if mask else "depth_map",
                             frame=frame)
            if be == "cop":
                fout.parm("copoutput").set(os.path.join(odir, fname))
                fout.render()
            else:
                fout.parm("file").set(os.path.join(odir, fname))
                fout.cook(force=True)

        notify(node, hou.severityType.ImportantMessage,
               f"Depth Map: rendered {len(frames)} {prefix} frame(s) -> {odir}")
        return True

    except Exception as e:
        notify(node, hou.severityType.Error, f"Render failed: {e}")
        return False


def reset_depth(node, mask_only=False) -> bool:
    import hou
    try:
        children = list(dm_children(node))
        for n in children:
            if mask_only and not n.name().startswith(NODE_PREFIX + "M"):
                continue
            _try(n.destroy, where=f"reset:{n.name()}")

        settings = load_settings(node)
        if mask_only:
            settings["mask_setup_complete"] = False
        else:
            settings["setup_complete"] = False
        save_settings(node, settings)

        notify(node, hou.severityType.ImportantMessage,
               "Depth Map: network reset")
        return True
    except Exception as e:
        notify(node, hou.severityType.Error, f"Reset failed: {e}")
        return False
