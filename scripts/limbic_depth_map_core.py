"""Depth Map Renderer (gero::depth_map_renderer) — Shared Core.
=============================================================
Pure pipeline logic shared between the HDA PythonModule and the
Python Panel UI.  No Qt imports — only hou, os, json, math, sys.

Dual COP backend: COP2 (H18-H20) and Copernicus / new COP (H21+).
Backend is auto-detected from the Houdini version at runtime.

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
HDA_CATEGORY = "Limbicnation"
LAYOUT_STEP_X = 200
LAYOUT_MASK_Y = -300

# ─────────────────────────────────────────────────────────────────────────────
# COP Backend Detection
# ─────────────────────────────────────────────────────────────────────────────

# H21 removed the legacy COP2 network entirely (cop2net / cop2::* node types
# no longer exist), so on H21+ we must use the new Copernicus COP nodes.
_ENABLE_COP_BACKEND = True

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
# NOTE: Copernicus (H21 "cop") has no logarithm node and no identity
# "function", so "scale" multiplies via the Copernicus "bright" node
# (bright = multiplier, neutral 1.0).  LOG normalization degrades to LINEAR
# on the cop backend (see build_depth_network).
_NODE_MAP = {
    "source":       {"cop2": "cop2::file",        "cop": "file"},
    # "log" is COP2-only; on the cop backend LOG falls back to LINEAR before a
    # log node is ever created, so the "cop" value here is never used.
    "log":          {"cop2": "cop2::ln",           "cop": "function"},
    "range":        {"cop2": "cop2::range",       "cop": "remap"},
    "brightness":   {"cop2": "cop2::brightness",  "cop": "bright"},
    "contrast":     {"cop2": "cop2::contrast",    "cop": "contrast"},
    "scale":        {"cop2": "cop2::multiply",    "cop": "bright"},
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
    # Copernicus CopNode has no setLabel(); fall back to a comment.  Guard with
    # hasattr because accessing a missing bound method raises before _try_ok.
    if hasattr(node, "setLabel") and _try_ok(node.setLabel, label,
                                             where="set_label"):
        return
    if hasattr(node, "setComment"):
        _try_ok(node.setComment, label, where="set_label_comment")
        _try_ok(node.setGenericFlag, hou.nodeFlag.DisplayComment, True,
                where="set_label_flag")


def _container_type():
    return "copnet" if backend() == "cop" else "cop2net"


# The HDA is an Object subnet; its image pipeline lives in this inner COP
# network.  COP nodes therefore sit two levels below the HDA parms, so
# reactive channel references reach the HDA via "../../".
COP_CONTAINER = "depth_cop"


def cop_container(node, create=True):
    """Return the inner COP network that holds the DM_ pipeline.

    The HDA is an Object subnet, which cannot host COP nodes directly, so the
    pipeline lives in a child copnet/cop2net.  Returns None when absent and
    create is False.
    """
    c = node.node(COP_CONTAINER)
    if c is None and create:
        _ensure_editable(node)
        c = _try(node.createNode, _container_type(), COP_CONTAINER,
                 where="create_cop_container")
    return c


def _chref(parm_name: str) -> str:
    """Hscript channel reference from a pipeline COP node up to an HDA parm.

    COP nodes live in the inner copnet, one level below the HDA, hence ../../.
    """
    return f'ch("../../{parm_name}")'


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
    cop = cop_container(node, create=False)
    if cop is None:
        return []
    return [n for n in cop.children() if n.name().startswith(NODE_PREFIX)]


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
        # Global animation range (the whole timeline) — NOT playbackRange(),
        # which is only the in/out loop subset and would silently truncate the
        # render to the scrub region (e.g. 1-9).  To render an explicit
        # subrange, untick "Use Scene Frame Range" and set Start/End.
        r = hou.playbar.frameRange()
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

def _ensure_editable(node):
    """Unlock an HDA instance so its internal COP network can be (re)built.

    HDA instances are locked by default; creating/destroying child nodes
    raises PermissionError until editing of contents is allowed.
    """
    if hasattr(node, "allowEditingOfContents"):
        _try(node.allowEditingOfContents, where="allow_editing")


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


def _set_or_expr(parm, value, expr):
    """Set a parm to an Hscript expression (reactive) or a literal value.

    When ``expr`` is given the parm references an HDA parameter via ``ch()``
    so dragging the HDA slider updates the COP node live; otherwise the
    literal ``value`` is set.
    """
    import hou
    if expr is not None:
        parm.setExpression(expr, hou.exprLanguage.Hscript)
    else:
        parm.set(value)


def _set_range_parms(rmap, near, far, inv, be, min_expr=None, max_expr=None):
    if be == "cop":
        _set_or_expr(rmap.parm("inputmin"), near, min_expr)
        _set_or_expr(rmap.parm("inputmax"), far, max_expr)
        rmap.parm("outputmin").set(1.0 if inv else 0.0)
        rmap.parm("outputmax").set(0.0 if inv else 1.0)
    else:
        _set_or_expr(rmap.parm("from_min"), near, min_expr)
        _set_or_expr(rmap.parm("from_max"), far, max_expr)
        rmap.parm("to_min").set(1.0 if inv else 0.0)
        rmap.parm("to_max").set(0.0 if inv else 1.0)


def _set_scale_parms(scale_node, sf, be, expr=None):
    if be == "cop":
        # Copernicus "bright" node: bright = multiplier (neutral 1.0), shift = 0
        scale_node.parm("shift").set(0.0)
        _set_or_expr(scale_node.parm("bright"), sf, expr)
    else:
        _set_or_expr(scale_node.parm("scale1"), sf, expr)


def _prime_cop_source(cop, src_name):
    """Prepare a Copernicus file-reader source so the chain can cook.

    A Copernicus ``file`` node exposes NO output layers until its AOVs are
    populated from the image, so a freshly pointed source produces nothing and
    downstream nodes fail with "source is missing" / "Failed to cook layers".
    Reload the file and press "Add AOVs from File" to expose the layers.

    Returns False if no file path is set, True if primed, None if N/A.
    """
    if cop is None:
        return None
    src = cop.node(src_name)
    if src is None or src.parm("filename") is None:
        return None
    fn = src.parm("filename").evalAsString().strip()
    # "default.pic" is the file COP's placeholder default — treat as unset.
    if not fn or fn == "default.pic":
        return False
    # (Re)sync the AOV layer bindings to the CURRENT file.  Only re-adding when
    # the count is zero is not enough: a binding left over from a previously
    # loaded file (e.g. a multi-layer File-mode EXR, then switched to Auto's
    # single-channel _scene_depth.exr) keeps the AOV count non-zero while still
    # pointing at layers the new file lacks, so the downstream rop_image fails to
    # cook with "Failed to cook layers".  Clearing the count first, then
    # reloading and re-adding from the file, deterministically rebinds to
    # whatever the current file actually contains.  (Verified on H21: this heals
    # a stale 2-AOV binding down to the correct single AOV and the chain cooks;
    # "Add AOVs from File" is itself idempotent, so this never stacks AOVs.)
    aovs = src.parm("aovs")
    if aovs is not None:
        _try(aovs.set, 0, where="prime_clear_aovs")
    _try(src.parm("reload").pressButton, where="prime_reload")
    if src.parm("addaovs") is not None:
        _try(src.parm("addaovs").pressButton, where="prime_addaovs")
    return True


def _set_file_output_parms(fout, upstream, odir, fname, settings, be):
    if be == "cop":
        fout.parm("coppath").set(upstream.path())
        fout.parm("copoutput").set(os.path.join(odir, fname))
        # The Copernicus rop_image defaults (8-bit + OCIO transform) wreck a
        # depth map: 8-bit dithering of a narrow value band shows up as a
        # halftone, and the OCIO display transform brightens/bends the linear
        # depth.  Write the values straight at >=16-bit instead.
        fmt = settings.get("format", "PNG").upper()
        cc = fout.parm("colorconversion")
        if cc is not None:
            _try(cc.set, "raw", where="fout_colorconversion_raw")
        sp = fout.parm("setprecision")
        pr = fout.parm("precision")
        if sp is not None and pr is not None:
            _try(sp.set, 1, where="fout_setprecision")
            # 32-bit float for EXR; 16-bit for PNG/TIFF (8-bit would band).
            _try(pr.set, "b32" if fmt == "EXR" else "b16",
                 where="fout_precision")
    else:
        fout.parm("file").set(os.path.join(odir, fname))
        fout.parm("filetype").set(settings.get("format", "PNG").lower())
        fout.parm("bitdepth").set(settings.get("bit_depth", "16"))


def build_depth_network(node, settings: dict):
    import hou
    be = backend()
    _ensure_editable(node)
    cop = cop_container(node)
    if cop is None:
        raise RuntimeError(
            "Could not create COP container inside the HDA. "
            "Is the gero::depth_map_renderer HDA installed?")
    _ensure_editable(cop)
    _destroy_depth_nodes(node)

    norm = settings.get("normalization", "LINEAR")
    inv = settings.get("invert", True)
    near = settings.get("near", 0.1)
    far = settings.get("far", 1000.0)
    sf = settings.get("scale_factor", 1.0)
    STEP = LAYOUT_STEP_X

    # When the HDA exposes explicit parms, wire the COP nodes to them via
    # ch() expressions so sliders update the network live (no re-Setup).
    # Otherwise (legacy JSON-only nodes) fall back to literal values.
    reactive = has_explicit_parms(node)

    # Copernicus (H21) has no logarithm COP node, so LOG normalization
    # degrades to LINEAR there.  The legacy COP2 backend keeps full LOG.
    if norm == "LOGARITHMIC" and be == "cop":
        notify(node, hou.severityType.Warning,
               "Depth Map: LOG normalization is unavailable on Copernicus "
               "(H21); falling back to LINEAR.")
        norm = "LINEAR"

    src = _create_node(cop, "source", NODE_PREFIX + "Source")
    _set_label(src, "Z-Depth Source")
    src.setPosition(hou.Vector2(0, 0))
    # Read the depth EXR as raw data, not a colour image.  The Copernicus file
    # COP defaults to OCIO colour management ("ocio"), which would transform
    # the linear Z values; "raw" passes them through untouched.  (The parm is
    # named "colorspace" — there is no "rawchannel" parm on this node.)
    if be == "cop":
        cs = src.parm("colorspace")
        if cs is not None:
            _try(cs.set, "raw", where="src_colorspace_raw")
    # If auto-depth is on and a previous scene render exists, repoint the
    # source so the user isn't left with default.pic after a Reset+Setup.
    if settings.get("auto_depth", True):
        depth_exr = os.path.join(
            output_dir(settings, "output_path", "depth_maps"),
            "_scene_depth.exr")
        if os.path.exists(depth_exr):
            src.parm("filename").set(depth_exr)
    # If the source already points at a file (e.g. preserved instance after
    # definition update), reload AOVs so downstream nodes can cook.
    _prime_cop_source(cop, NODE_PREFIX + "Source")

    norm_steps = {"RAW": 0, "LINEAR": 1, "LOGARITHMIC": 2}
    norm_node_count = norm_steps.get(norm, 1)

    if norm == "RAW":
        normalize = src
    elif norm == "LOGARITHMIC":
        log_node = _create_node(cop, "log", NODE_PREFIX + "LOG")
        _set_label(log_node, "Log Normalize")
        log_node.setPosition(hou.Vector2(STEP, 0))
        _wire(log_node, src, be)
        if be == "cop":
            log_node.parm("func").set(1)
            log_node.parm("func_math").set(3)
        else:
            _try(log_node.parm("affectalpha").set, False,
                 where="log_affectalpha")

        rmap = _create_node(cop, "range", NODE_PREFIX + "RangeMap")
        _set_label(rmap, "Log Range Mapper")
        rmap.setPosition(hou.Vector2(STEP * 2, 0))
        log_min = math.log(max(near, 0.001))
        log_max = math.log(max(far, 0.001))
        min_expr = f'log(max({_chref("near")}, 0.001))' if reactive else None
        max_expr = f'log(max({_chref("far")}, 0.001))' if reactive else None
        _set_range_parms(rmap, log_min, log_max, inv, be,
                         min_expr=min_expr, max_expr=max_expr)
        _wire(rmap, log_node, be)
        normalize = rmap
    else:
        rmap = _create_node(cop, "range", NODE_PREFIX + "RangeMap")
        _set_label(rmap, "Depth Range Mapper")
        rmap.setPosition(hou.Vector2(STEP, 0))
        near_expr = _chref("near") if reactive else None
        far_expr = _chref("far") if reactive else None
        _set_range_parms(rmap, near, far, inv, be,
                         min_expr=near_expr, max_expr=far_expr)
        _wire(rmap, src, be)
        normalize = rmap

    x = (norm_node_count + 1) * STEP
    bright = _create_node(cop, "brightness", NODE_PREFIX + "Brightness")
    _set_label(bright, "Brightness")
    bright.setPosition(hou.Vector2(x, 0))
    # Brightness is additive (neutral 0).  On Copernicus the "bright" parm is a
    # multiplier (neutral 1.0), so additive brightness goes to "shift" instead.
    if be == "cop":
        bright.parm("bright").set(1.0)
        bright_parm = bright.parm("shift")
    else:
        bright_parm = bright.parm("brightness")
    _set_or_expr(bright_parm, settings.get("brightness", 0.0),
                 _chref("brightness") if reactive else None)
    _wire(bright, normalize, be)

    x += STEP
    ctr = _create_node(cop, "contrast", NODE_PREFIX + "Contrast")
    _set_label(ctr, "Depth Contrast")
    ctr.setPosition(hou.Vector2(x, 0))
    # Contrast parm is gain (1.0 + contrast); offset preserved in expression.
    _set_or_expr(ctr.parm("contrast" if be == "cop" else "gain"),
                 1.0 + settings.get("contrast", 0.2),
                 f'1 + {_chref("contrast")}' if reactive else None)
    _wire(ctr, bright, be)

    x += STEP
    scale = _create_node(cop, "scale", NODE_PREFIX + "Scale")
    _set_label(scale, "Depth Scale")
    scale.setPosition(hou.Vector2(x, 0))
    _set_scale_parms(scale, sf, be,
                     _chref("scalefactor") if reactive else None)
    _wire(scale, ctr, be)

    x += STEP
    gray = _create_node(cop, "grayscale", NODE_PREFIX + "Grayscale")
    _set_label(gray, "Grayscale Output")
    gray.setPosition(hou.Vector2(x, 0))
    if be == "cop2":
        gray.parm("copoutput").set("bw")
    _wire(gray, scale, be)

    x += STEP
    fout = _create_node(cop, "file_output", NODE_PREFIX + "FileOut")
    _set_label(fout, "Depth File Output")
    fout.setPosition(hou.Vector2(x, 0))
    odir = output_dir(settings, "output_path", "depth_maps")
    fname = filename(settings, "depth_map")
    _set_file_output_parms(fout, gray, odir, fname, settings, be)
    # Copernicus rop_image reads the COP at "coppath"; it has no image input.
    if be != "cop":
        _wire(fout, gray, be)

    if settings.get("preview", False):
        viewer = _create_node(cop, "viewer", NODE_PREFIX + "Viewer")
        _set_label(viewer, "Depth Preview")
        viewer.setPosition(hou.Vector2(x, 100))
        _wire(viewer, gray, be)

    display = gray if be == "cop" else fout
    _safe_set_display(cop, display)
    cop.layoutChildren()
    return fout


def build_mask_network(node, settings: dict):
    import hou
    be = backend()
    _ensure_editable(node)
    cop = cop_container(node)
    if cop is None:
        raise RuntimeError(
            "Could not create COP container inside the HDA. "
            "Is the gero::depth_map_renderer HDA installed?")
    _ensure_editable(cop)
    _destroy_mask_nodes(node)

    source = settings.get("mask_source", "OBJECT_INDEX")
    mfmt = settings.get("mask_format", "GRAYSCALE")
    midx = settings.get("mask_index", 1)
    reactive = has_explicit_parms(node)
    STEP = LAYOUT_STEP_X
    Y = LAYOUT_MASK_Y

    if source == "CRYPTOMATTE":
        mask_src = _create_node(cop, "cryptomatte", NODE_PREFIX + "MSource")
        _set_label(mask_src, "Cryptomatte Source")
        mask_src.setPosition(hou.Vector2(0, Y))
        if be == "cop":
            mask_input = _create_node(cop, "source", NODE_PREFIX + "MaskInput")
            _set_label(mask_input, "Cryptomatte EXR Source — set path")
            mask_input.setPosition(hou.Vector2(-200, Y))
            _wire(mask_src, mask_input, be)

    elif be == "cop" and source == "OBJECT_INDEX":
        mask_input = _create_node(cop, "sopimport", NODE_PREFIX + "MaskInput")
        _set_label(mask_input, "SOP Source (set path to your geo)")
        mask_input.setPosition(hou.Vector2(-200, Y))
        _try(mask_input.parm("soppath").set, "",
             where="set_soppath")

        mask_src = _create_node(cop, "rasterize", NODE_PREFIX + "MSource")
        _set_label(mask_src, "Rasterize Geo to Mask")
        mask_src.setPosition(hou.Vector2(0, Y))
        _wire(mask_src, mask_input, be)

    else:
        mask_src = _create_node(cop, "idtomask", NODE_PREFIX + "MSource")
        _set_label(mask_src, "Object Index Mask")
        mask_src.setPosition(hou.Vector2(0, Y))
        _try(_set_or_expr, mask_src.parm("object_id"), midx,
             _chref("maskindex") if reactive else None,
             where="set_object_id")

    x = 300
    if mfmt == "RGBA":
        convert_ = _create_node(cop, "convert_rgba",
                                NODE_PREFIX + "MRGBA_Convert")
        _set_label(convert_, "RGBA Convert")
        convert_.setPosition(hou.Vector2(x, Y))
        if be == "cop2":
            convert_.parm("copoutput").set("rgba")
        _wire(convert_, mask_src, be)
        mask_out = convert_
    else:
        mask_out = _create_node(cop, "grayscale", NODE_PREFIX + "MGrayscale")
        _set_label(mask_out, "Grayscale Mask")
        mask_out.setPosition(hou.Vector2(x, Y))
        if be == "cop2":
            mask_out.parm("copoutput").set("bw")
        _wire(mask_out, mask_src, be)

    x += STEP
    mfout = _create_node(cop, "file_output", NODE_PREFIX + "MaskFileOut")
    _set_label(mfout, "Mask File Output")
    mfout.setPosition(hou.Vector2(x, Y))

    odir = output_dir(settings, "mask_output_path", "mask_maps")
    fname = filename(settings, "mask_map")
    mask_settings = {**settings, "format": "PNG", "bit_depth": "16"}
    _set_file_output_parms(mfout, mask_out, odir, fname, mask_settings, be)
    if be != "cop":
        _wire(mfout, mask_out, be)

    display = mask_out if be == "cop" else mfout
    _safe_set_display(cop, display)
    cop.layoutChildren()
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


def _resolve_camera(node, settings):
    """Find the camera to render depth from: the Camera parm, else the first
    camera in /obj."""
    import hou
    cp = (settings.get("camera") or "").strip()
    if cp:
        c = node.node(cp) or hou.node(cp)
        if c is not None:
            return c
    obj = hou.node("/obj")
    if obj is not None:
        for n in obj.children():
            if n.type().name() == "cam":
                return n
    return None


def _auto_fit_depth_range(node, cam, settings):
    """Set Near/Far from the scene's actual camera-space depth.

    Mantra's Pz is positive camera-space distance (verified on H21).  We
    bracket every renderable /obj object by transforming its bounding-box
    corners into camera space and taking the min/max positive depth, then write
    the HDA ``near`` / ``far`` parms.  The Depth Range Mapper references those
    parms via ``ch()``, so the live network re-ranges automatically.

    No-op when the user enabled Custom Near/Far, when the parms are absent
    (legacy JSON-only nodes), or when no renderable geometry is found.
    """
    import hou
    if settings.get("use_custom_range", False):
        return
    near_p, far_p = node.parm("near"), node.parm("far")
    if near_p is None or far_p is None:
        return
    wt = _try(cam.worldTransform, where="autofit_cam_xform")
    if wt is None:
        return
    wtc = wt.inverted()

    dmin = dmax = None
    obj = hou.node("/obj")
    for n in (obj.children() if obj else []):
        if n == node or n == cam:
            continue
        if not hasattr(n, "renderNode"):
            continue
        rn = _try(n.renderNode, where="autofit_render_node")
        if rn is None:
            continue
        geo = _try(rn.geometry, where="autofit_geo")
        if geo is None:
            continue
        bb = _try(geo.boundingBox, where="autofit_bbox")
        if bb is None or not _try(bb.isValid, where="autofit_valid",
                                  default=False):
            continue
        otw = _try(n.worldTransform, where="autofit_obj_xform")
        if otw is None:
            continue
        mn, mx = bb.minvec(), bb.maxvec()
        for cx in (mn[0], mx[0]):
            for cy in (mn[1], mx[1]):
                for cz in (mn[2], mx[2]):
                    # local -> world -> camera; +depth is in front of camera.
                    pc = (hou.Vector3(cx, cy, cz) * otw) * wtc
                    depth = -pc[2]
                    if depth <= 0.0:
                        continue
                    dmin = depth if dmin is None else min(dmin, depth)
                    dmax = depth if dmax is None else max(dmax, depth)

    if dmin is None or dmax is None:
        return
    # Flat-depth scenes (a plane perpendicular to the camera) collapse to a
    # single distance; give them a tiny valid band instead of bailing to the
    # 0.1/1000 defaults.
    if dmax <= dmin:
        dmax = dmin + 0.01
    # Small padding so silhouette extremes don't clip to pure black/white.
    pad = max((dmax - dmin) * 0.02, 1e-4)
    near = max(dmin - pad, 1e-4)
    far = dmax + pad
    _try(near_p.set, near, where="autofit_set_near")
    _try(far_p.set, far, where="autofit_set_far")
    notify(node, hou.severityType.Message,
           f"Depth Map: auto-fitted Near={near:.2f} Far={far:.2f} "
           f"(enable Custom Near/Far to override)")


def render_scene_depth(node, settings):
    """Render the /obj scene's camera-space Z (Pz) to an EXR via Mantra and
    point DM_Source at it.  Renders the current frame.  Returns the EXR path,
    or None on failure.
    """
    import hou
    cam = _resolve_camera(node, settings)
    if cam is None:
        notify(node, hou.severityType.Error,
               "Depth Map: no camera found. Set the Camera parameter or add a "
               "camera to /obj.")
        return None

    import tempfile
    # The per-frame depth pass is a transient intermediate, not a deliverable.
    # Writing it into the user's output folder is unsafe when that folder is
    # watched by a file-sync client (QNAP Qsync, Dropbox, OneDrive, ...): the
    # client races the renderer to upload/dehydrate the file it just saw change,
    # which surfaces as an intermittent "Failed to cook layers" partway through
    # an animation (and leaves 0-byte / stub files behind).  Park both
    # transients in a private, per-node temp dir; only the final image lands in
    # the output folder.
    tmp = os.path.join(tempfile.gettempdir(), f"limbic_depth_{node.sessionId()}")
    if not os.path.isdir(tmp):
        _try(os.makedirs, tmp, where="mk_tmpdir", exist_ok=True)
    depth_exr = os.path.join(tmp, "_scene_depth.exr")
    # Mantra requires a main beauty output; it's unused, so park it in temp too.
    beauty = os.path.join(tmp, "_dm_scene_beauty.exr")

    out = hou.node("/out")
    rop = out.createNode("ifd", "_dm_scene_depth")
    try:
        rop.parm("camera").set(cam.path())
        rop.parm("vm_picture").set(beauty)
        # Camera-space Z depth as its own single-channel file.
        rop.parm("vm_numaux").set(1)
        rop.parm("vm_variable_plane1").set("Pz")
        rop.parm("vm_usefile_plane1").set(True)
        rop.parm("vm_filename_plane1").set(depth_exr)
        # Harden the Pz aux plane so the depth survives intact (verified on
        # H21 Mantra — the defaults bake it as a 3-channel half-float "color"
        # image in lin_rec709, which mangles the linear Z values):
        #   float vextype + float quantize  -> single-channel 32-bit, no
        #       half-float precision loss or inf overflow on large depths
        #   channel "C"                     -> lands on the default layer the
        #       Copernicus reader picks up (read as raw, see build_depth_network)
        #   dither 0 / gamma 1.0            -> depth is data, not a display image
        #   sfilter closest + pfilter       -> crisp silhouettes; no Gaussian
        #       "minmax min"                   averaging of depth across object
        #                                      edges (the edge-fringe artifact)
        for pname, pval in (
            ("vm_vextype_plane1", "float"),
            ("vm_channel_plane1", "C"),
            ("vm_quantize_plane1", "float"),
            ("vm_dither_plane1", 0),
            ("vm_gamma_plane1", 1.0),
            ("vm_sfilter_plane1", "closest"),
            ("vm_pfilter_plane1", "minmax min"),
        ):
            p = rop.parm(pname)
            if p is not None:
                _try(p.set, pval, where=f"set_{pname}")
        # Depth needs no anti-aliasing; keep it fast.
        _try(rop.parm("vm_samplesx").set, 1, where="samplesx")
        _try(rop.parm("vm_samplesy").set, 1, where="samplesy")
        # Pin the ROP explicitly to the current frame.  render() already honors
        # the ROP's trange (a fresh ifd defaults to trange=0 = "current frame"),
        # so this is defensive/clarifying rather than a fix — it guarantees the
        # per-frame loop drives the frame via hou.setFrame() and never inherits
        # a stale "render frame range" trange from elsewhere.
        cur = int(hou.frame())
        for pname, val in (("f1", cur), ("f2", cur), ("f3", 1)):
            p = rop.parm(pname)
            if p is not None:
                _try(p.set, val, where=f"set_{pname}")
        # Render Mantra in the FOREGROUND (blocking).  In an interactive GUI
        # session the ifd ROP otherwise dispatches mantra as a *background*
        # process and rop.render() returns in ~0.3 s — long before the EXR is
        # written.  DM_Source would then read an empty/partial file ("source is
        # missing"), or, across an animation, the loop races ahead of mantra and
        # every frame reads the same stale EXR (identical frames that stall).
        # Forcing foreground makes render() block until the depth EXR is
        # complete.  (hython already renders inline, so this is a no-op there.)
        p = rop.parm("soho_foreground")
        if p is not None:
            _try(p.set, 1, where="set_soho_foreground")
        rop.render(verbose=False)
    except Exception as e:
        notify(node, hou.severityType.Error, f"Depth Map: scene render failed: {e}")
        return None
    finally:
        _try(rop.destroy, where="destroy_scene_depth_rop")

    cop = cop_container(node)
    src = cop.node(NODE_PREFIX + "Source") if cop else None
    if src is not None and src.parm("filename") is not None:
        src.parm("filename").set(depth_exr)
    return depth_exr


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

        cop = cop_container(node, create=False)
        fout = cop.node(NODE_PREFIX + ("MaskFileOut" if mask else "FileOut")) \
            if cop else None
        if not fout:
            notify(node, hou.severityType.Error,
                   "Depth Map: output node not found - re-run Setup")
            return False

        frames = list(frame_range(settings)) if animation else [hou.frame()]
        if animation:
            notify(node, hou.severityType.ImportantMessage,
                   f"Depth Map: rendering {len(frames)} {prefix} frames...")

        be = backend()
        # Auto mode (Copernicus depth): render the /obj scene's depth per frame.
        auto = (be == "cop") and not mask and settings.get("auto_depth", True)
        # File mode on Copernicus: the source must already point at a depth EXR.
        if be == "cop" and not mask and not auto:
            if _prime_cop_source(cop, NODE_PREFIX + "Source") is False:
                notify(node, hou.severityType.Error,
                       "Depth Map: no Z-Depth source set. Either enable "
                       "Auto-Render Scene Depth, or open DM_Source and set its "
                       "file path to a rendered depth EXR.")
                return False

        # Auto-fit Near/Far ONCE per render (not per frame): the default
        # 0.1/1000 range crushes typical scene depth into the top few percent of
        # the remap (near-uniform white that dithers to a halftone).  Computing
        # it once gives a stable, flicker-free range across the whole sequence.
        # No-op when Custom Near/Far is on or no renderable geometry is found.
        if auto:
            cam = _resolve_camera(node, settings)
            if cam is not None:
                _auto_fit_depth_range(node, cam, settings)

        odir = output_dir(settings,
                          "mask_output_path" if mask else "output_path",
                          "mask_maps" if mask else "depth_maps")
        ok_count = 0
        for idx, frame in enumerate(frames):
            hou.setFrame(frame)
            if animation:
                notify(node, hou.severityType.Message,
                       f"Depth Map: {prefix} frame {int(frame)} "
                       f"({idx + 1}/{len(frames)})")
            if auto:
                if render_scene_depth(node, settings) is None:
                    notify(node, hou.severityType.Warning,
                           f"Depth Map: frame {int(frame)} depth render "
                           f"failed, skipping")
                    continue
                _prime_cop_source(cop, NODE_PREFIX + "Source")
            fname = filename(settings,
                             "mask_map" if mask else "depth_map",
                             frame=frame)
            if be == "cop":
                fout.parm("copoutput").set(os.path.join(odir, fname))
                # Pin rop_image explicitly to the current frame (defensive — the
                # loop already drives the frame via hou.setFrame()).
                cur = int(hou.frame())
                for pname, val in (("f1", cur), ("f2", cur), ("f3", 1)):
                    p = fout.parm(pname)
                    if p is not None:
                        _try(p.set, val, where=f"set_fout_{pname}")
                # Guard the output cook: a Copernicus "Failed to cook layers"
                # raise must skip this frame, not abort the whole sequence (the
                # render_scene_depth guard above does not cover this call).
                rendered = _try_ok(fout.render, where=f"fout_render_f{int(frame)}")
            else:
                fout.parm("file").set(os.path.join(odir, fname))
                rendered = _try_ok(fout.cook, force=True,
                                   where=f"fout_cook_f{int(frame)}")
            if not rendered:
                notify(node, hou.severityType.Warning,
                       f"Depth Map: frame {int(frame)} output cook failed, "
                       f"skipping")
                continue
            ok_count += 1

        if ok_count == 0:
            notify(node, hou.severityType.Error,
                   f"Depth Map: all {prefix} frames failed")
            return False
        notify(node, hou.severityType.ImportantMessage,
               f"Depth Map: rendered {ok_count}/{len(frames)} "
               f"{prefix} frame(s) -> {odir}")
        return True

    except Exception as e:
        notify(node, hou.severityType.Error, f"Render failed: {e}")
        return False


def reset_depth(node, mask_only=False) -> bool:
    import hou
    try:
        _ensure_editable(node)
        cop = cop_container(node, create=False)
        if cop is not None:
            _ensure_editable(cop)
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
