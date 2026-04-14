"""Limbic Depth Map Renderer — HDA PythonModule.
================================================
Embedded in the limbic_depth_map_renderer HDA.  Provides the core
pipeline logic, settings helpers, and operator entry points.

This module is self-contained — it does NOT import from
python_panels.depth_map_panel at runtime.  The Python Panel UI
remains the primary interface; this module enables direct HDA
parameter-driven workflows (OnCreated, shelf tools, scripting).

Dual COP backend: cop2 (H18-H20) / cop (H21+).
"""

import os
import json
import math
import sys

import hou

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

NODE_PREFIX = "DM_"
HDA_CATEGORY = "Limic"

# ─────────────────────────────────────────────────────────────────────────────
# COP Backend Detection
# ─────────────────────────────────────────────────────────────────────────────

_COP_BACKEND = None


def backend() -> str:
    global _COP_BACKEND
    if _COP_BACKEND is None:
        try:
            img = hou.node("/img")
            if img is not None:
                child_types = img.childTypeCategory().nodeTypes()
                if "copnet" in child_types:
                    _COP_BACKEND = "cop"
                elif "cop2net" in child_types:
                    _COP_BACKEND = "cop2"
                else:
                    _COP_BACKEND = "cop" if hou.applicationVersion()[0] >= 21 else "cop2"
            else:
                _COP_BACKEND = "cop" if hou.applicationVersion()[0] >= 21 else "cop2"
        except Exception:
            _COP_BACKEND = "cop2"
    return _COP_BACKEND


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
    "threshold":    {"cop2": "cop2::function",    "cop": "function"},
    "invert_cop":   {"cop2": "cop2::invert",      "cop": "invert"},
}


def _create_node(parent, key, name):
    return parent.createNode(_NODE_MAP[key][backend()], name)


def _set_label(node, label):
    if hasattr(node, "setLabel"):
        node.setLabel(label)
    else:
        node.setComment(label)
        node.setGenericFlag(hou.nodeFlag.DisplayComment, True)


def _container_type():
    return "copnet" if backend() == "cop" else "cop2net"


# ─────────────────────────────────────────────────────────────────────────────
# Settings  (read from HDA parms, fall back to JSON dm_settings)
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_SETTINGS = {
    "setup_complete":      False,
    "mask_setup_complete": False,
    "use_custom_range":    False,
    "near":                0.1,
    "far":                1000.0,
    "normalization":       "LINEAR",
    "scale_factor":        1.0,
    "invert":              True,
    "contrast":            0.2,
    "brightness":          0.0,
    "output_path":         "",
    "format":              "PNG",
    "bit_depth":           "16",
    "preview":             False,
    "animation":           False,
    "use_scene_range":     True,
    "frame_start":         1,
    "frame_end":          250,
    "mask_enabled":        False,
    "mask_source":         "OBJECT_INDEX",
    "mask_index":          1,
    "mask_format":         "GRAYSCALE",
    "mask_output_path":    "",
}

# HDA parm name → settings key  (for explicit-parm HDA)
_PARM_MAP = {
    "usecustomrange": "use_custom_range",
    "near":           "near",
    "far":            "far",
    "normalization":  "normalization",
    "scalefactor":    "scale_factor",
    "invert":         "invert",
    "brightness":     "brightness",
    "contrast":       "contrast",
    "outputpath":     "output_path",
    "format":         "format",
    "bitdepth":       "bit_depth",
    "preview":        "preview",
    "animation":      "animation",
    "usescenerange":  "use_scene_range",
    "framestart":     "frame_start",
    "frameend":       "frame_end",
    "maskenabled":    "mask_enabled",
    "masksource":     "mask_source",
    "maskindex":      "mask_index",
    "maskformat":     "mask_format",
    "maskoutputpath": "mask_output_path",
}


def _has_explicit_parms(node):
    return node.parm("normalization") is not None


def load_settings(node):
    if _has_explicit_parms(node):
        settings = {**DEFAULT_SETTINGS}
        for parm_name, key in _PARM_MAP.items():
            p = node.parm(parm_name)
            if p is not None:
                val = p.eval()
                if isinstance(val, float) and key in (
                    "near", "far", "scale_factor", "contrast", "brightness",
                ):
                    settings[key] = val
                elif isinstance(val, int) and key in (
                    "mask_index", "frame_start", "frame_end",
                ):
                    settings[key] = val
                elif isinstance(val, bool) and key in (
                    "use_custom_range", "invert", "preview",
                    "animation", "use_scene_range", "mask_enabled",
                ):
                    settings[key] = val
                elif isinstance(val, str):
                    settings[key] = val
                else:
                    settings[key] = val
        json_p = node.parm("dm_settings")
        if json_p is not None:
            try:
                raw = json_p.eval()
                if raw:
                    saved = json.loads(raw)
                    settings["setup_complete"] = saved.get("setup_complete", False)
                    settings["mask_setup_complete"] = saved.get("mask_setup_complete", False)
            except Exception:
                pass
        return settings

    try:
        p = node.parm("dm_settings")
        if p is not None:
            raw = p.eval()
            if raw:
                return {**DEFAULT_SETTINGS, **json.loads(raw)}
    except Exception:
        pass
    return {**DEFAULT_SETTINGS}


def save_settings(node, settings):
    tracking = {
        "setup_complete": settings.get("setup_complete", False),
        "mask_setup_complete": settings.get("mask_setup_complete", False),
    }
    p = node.parm("dm_settings")
    if p is not None:
        p.set(json.dumps(tracking))

    if _has_explicit_parms(node):
        for parm_name, key in _PARM_MAP.items():
            p = node.parm(parm_name)
            if p is not None and key in settings:
                try:
                    p.set(settings[key])
                except Exception:
                    pass


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _dm_children(node):
    return [n for n in node.children() if n.name().startswith(NODE_PREFIX)]


def _output_dir(settings, key="output_path", fallback="depth_maps"):
    path = settings.get(key, "").strip()
    if not path:
        path = hou.expandString(f"$HIP/{fallback}/")
    os.makedirs(path, exist_ok=True)
    return path


def _filename(settings, prefix, frame=None):
    if frame is not None and settings.get("animation"):
        fname = f"{prefix}_{frame:05d}"
    else:
        fname = prefix
    ext = {"PNG": "png", "TIFF": "tiff", "EXR": "exr"}.get(
        settings.get("format", "PNG"), "png")
    return f"{fname}.{ext}"


def _frame_range(settings):
    if settings.get("use_scene_range", True):
        r = hou.playbar.playbackRange()
        return range(int(r[0]), int(r[1]) + 1)
    return range(settings.get("frame_start", 1), settings.get("frame_end", 250) + 1)


def _notify(node, severity, msg):
    try:
        hou.ui.setStatusMessage(msg, severity=severity)
    except Exception:
        print(f"[{severity.name}] {msg}", file=sys.stderr)


# ─────────────────────────────────────────────────────────────────────────────
# Path Normalization
# ─────────────────────────────────────────────────────────────────────────────

def resolve_script_path(relative_path):
    """Resolve a script path relative to $HIP or LIMBIC_DEPTH_MAP.

    Order of resolution:
      1. $HIP/<relative_path>   (scene-relative)
      2. $LIMBIC_DEPTH_MAP/<relative_path>  (plugin install root)
      3. <relative_path> as-is  (absolute or CWD)

    Always uses hou.expandString() so Houdini variables like $HIP
    are expanded at runtime.
    """
    hip_path = hou.expandString(f"$HIP/{relative_path}")
    if os.path.exists(hip_path):
        return hip_path

    limbic_root = os.environ.get("LIMBIC_DEPTH_MAP", "")
    if limbic_root:
        plugin_path = os.path.join(limbic_root, relative_path)
        if os.path.exists(plugin_path):
            return plugin_path

    expanded = hou.expandString(relative_path)
    if os.path.isabs(expanded) or os.path.exists(expanded):
        return expanded

    return hip_path


# ─────────────────────────────────────────────────────────────────────────────
# COP Network Builders
# ─────────────────────────────────────────────────────────────────────────────

def build_depth_network(node, settings):
    be = backend()

    for n in list(_dm_children(node)):
        if n.name().startswith(NODE_PREFIX + "M"):
            continue
        n.destroy()

    norm = settings.get("normalization", "LINEAR")
    inv  = settings.get("invert", True)
    near = settings.get("near", 0.1)
    far  = settings.get("far", 1000.0)
    sf   = settings.get("scale_factor", 1.0)

    src = _create_node(node, "source", NODE_PREFIX + "Source")
    _set_label(src, "Z-Depth Source")
    src.setPosition(hou.Vector2(0, 0))

    norm_steps = {"RAW": 0, "LINEAR": 1, "LOGARITHMIC": 2}
    norm_node_count = norm_steps.get(norm, 1)
    STEP = 200

    if norm == "RAW":
        normalize = src
    elif norm == "LOGARITHMIC":
        log_node = _create_node(node, "log", NODE_PREFIX + "LOG")
        _set_label(log_node, "Log Normalize")
        log_node.setPosition(hou.Vector2(STEP, 0))
        log_node.setInput(0, src, 0)
        log_node.parm("func").set(1)
        log_node.parm("func_math").set(3)

        rmap = _create_node(node, "range", NODE_PREFIX + "RangeMap")
        _set_label(rmap, "Log Range Mapper")
        rmap.setPosition(hou.Vector2(STEP * 2, 0))
        log_min = 0.0
        log_max = math.log(max(far, 0.001))
        if be == "cop":
            rmap.parm("inputmin").set(log_min)
            rmap.parm("inputmax").set(log_max)
            rmap.parm("outputmin").set(1.0 if inv else 0.0)
            rmap.parm("outputmax").set(0.0 if inv else 1.0)
        else:
            rmap.parm("from_min").set(log_min)
            rmap.parm("from_max").set(log_max)
            rmap.parm("to_min").set(1.0 if inv else 0.0)
            rmap.parm("to_max").set(0.0 if inv else 1.0)
        normalize = rmap
        rmap.setInput(0, log_node, 0)
    else:
        rmap = _create_node(node, "range", NODE_PREFIX + "RangeMap")
        _set_label(rmap, "Depth Range Mapper")
        rmap.setPosition(hou.Vector2(STEP, 0))
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
        normalize = rmap

    x = (norm_node_count + 1) * STEP
    bright = _create_node(node, "brightness", NODE_PREFIX + "Brightness")
    _set_label(bright, "Brightness")
    bright.setPosition(hou.Vector2(x, 0))
    bright.parm("bright" if be == "cop" else "brightness").set(
        settings.get("brightness", 0.0))
    bright.setInput(0, normalize, 0)

    x += STEP
    ctr = _create_node(node, "contrast", NODE_PREFIX + "Contrast")
    _set_label(ctr, "Depth Contrast")
    ctr.setPosition(hou.Vector2(x, 0))
    ctr.parm("contrast" if be == "cop" else "gain").set(
        1.0 + settings.get("contrast", 0.2))
    ctr.setInput(0, bright, 0)

    x += STEP
    scale = _create_node(node, "scale", NODE_PREFIX + "Scale")
    _set_label(scale, "Depth Scale")
    scale.setPosition(hou.Vector2(x, 0))
    scale.parm("scale" if be == "cop" else "scale1").set(sf)
    scale.setInput(0, ctr, 0)

    x += STEP
    gray = _create_node(node, "grayscale", NODE_PREFIX + "Grayscale")
    _set_label(gray, "Grayscale Output")
    gray.setPosition(hou.Vector2(x, 0))
    if be == "cop2":
        gray.parm("copoutput").set("bw")
    gray.setInput(0, scale, 0)

    x += STEP
    fout = _create_node(node, "file_output", NODE_PREFIX + "FileOut")
    _set_label(fout, "Depth File Output")
    fout.setPosition(hou.Vector2(x, 0))
    odir  = _output_dir(settings, "output_path", "depth_maps")
    fname = _filename(settings, "depth_map")
    if be == "cop":
        fout.parm("coppath").set(gray.path())
        fout.parm("copoutput").set(os.path.join(odir, fname))
    else:
        fout.parm("file").set(os.path.join(odir, fname))
        fout.parm("filetype").set(settings.get("format", "PNG").lower())
        fout.parm("bitdepth").set(settings.get("bit_depth", "16"))
        fout.setInput(0, gray, 0)

    if settings.get("preview", False):
        viewer = _create_node(node, "viewer", NODE_PREFIX + "Viewer")
        _set_label(viewer, "Depth Preview")
        viewer.setPosition(hou.Vector2(x, 100))
        if be == "cop2":
            viewer.setInput(0, gray, 0)

    display = gray if be == "cop" else fout
    if hasattr(node, "setDisplayNode"):
        try:
            node.setDisplayNode(display)
        except Exception:
            pass
    node.layoutChildren()
    return fout


def _depth_node_exists(node):
    for n in node.children():
        if n.name() == NODE_PREFIX + "Grayscale":
            return n
    return None


def build_mask_network(node, settings):
    be = backend()

    for n in list(_dm_children(node)):
        if n.name().startswith(NODE_PREFIX + "M"):
            n.destroy()

    source = settings.get("mask_source", "OBJECT_INDEX")
    mfmt   = settings.get("mask_format", "GRAYSCALE")
    midx   = settings.get("mask_index", 1)

    # ── H21+ depth-threshold mask ──────────────────────────────────────────
    # In H21+ new COP, idtomask requires a rendered EXR with an Object ID
    # plane.  OpenGL renders and default.pic don't carry this pass, so the
    # COP kernel fails with "Not enough sources specified" / "src is missing".
    # Fallback: derive the mask from the depth pipeline output via threshold.
    if be == "cop" and source == "OBJECT_INDEX":
        depth_gray = _depth_node_exists(node)
        if depth_gray is None:
            _notify(node, hou.severityType.Warning,
                    "Depth Map: no depth pipeline found — building one first")
            build_depth_network(node, settings)
            depth_gray = _depth_node_exists(node)

        if depth_gray is not None:
            mask_src = _create_node(node, "threshold", NODE_PREFIX + "MThreshold")
            _set_label(mask_src, f"Depth Threshold (object cut at idx {midx})")
            mask_src.setPosition(hou.Vector2(0, -300))
            mask_src.setInput(0, depth_gray, 0)
            mask_src.parm("func").set(1)
            mask_src.parm("func_math").set(3)
            threshold_val = 1.0 / max(midx, 1)
            mask_src.parm("val1a").set(threshold_val)
        else:
            mask_src = _create_node(node, "source", NODE_PREFIX + "MSource")
            _set_label(mask_src, "Mask Source (set EXR with Object ID plane)")
            mask_src.setPosition(hou.Vector2(0, -300))
    elif source == "CRYPTOMATTE":
        mask_src = _create_node(node, "cryptomatte", NODE_PREFIX + "MSource")
        _set_label(mask_src, "Cryptomatte Source")
        mask_src.setPosition(hou.Vector2(0, -300))
        if be == "cop":
            mask_input = _create_node(node, "source", NODE_PREFIX + "MaskInput")
            _set_label(mask_input, "Cryptomatte EXR Source — set path")
            mask_input.setPosition(hou.Vector2(-200, -300))
            mask_src.setInput(0, mask_input, 0)
    else:
        # COP2 path — idtomask reads from ambient stream
        mask_src = _create_node(node, "idtomask", NODE_PREFIX + "MSource")
        _set_label(mask_src, "Object Index Mask")
        mask_src.parm("object_id").set(midx)
        mask_src.setPosition(hou.Vector2(0, -300))

    if mfmt == "RGBA":
        convert_ = _create_node(node, "convert_rgba", NODE_PREFIX + "MRGBA_Convert")
        _set_label(convert_, "RGBA Convert")
        convert_.setPosition(hou.Vector2(300, -300))
        if be == "cop2":
            convert_.parm("copoutput").set("rgba")
        convert_.setInput(0, mask_src, 0)
        mask_out = convert_
    else:
        mask_out = _create_node(node, "grayscale", NODE_PREFIX + "MGrayscale")
        _set_label(mask_out, "Grayscale Mask")
        mask_out.setPosition(hou.Vector2(300, -300))
        if be == "cop2":
            mask_out.parm("copoutput").set("bw")
        mask_out.setInput(0, mask_src, 0)

    mfout = _create_node(node, "file_output", NODE_PREFIX + "MaskFileOut")
    _set_label(mfout, "Mask File Output")
    mfout.setPosition(hou.Vector2(600, -300))

    odir  = _output_dir(settings, "mask_output_path", "mask_maps")
    fname = _filename(settings, "mask_map")
    if be == "cop":
        mfout.parm("coppath").set(mask_out.path())
        mfout.parm("copoutput").set(os.path.join(odir, fname))
    else:
        mfout.parm("file").set(os.path.join(odir, fname))
        mfout.parm("filetype").set("png")
        mfout.parm("bitdepth").set(settings.get("bit_depth", "16"))
        mfout.setInput(0, mask_out, 0)

    display = mask_out if be == "cop" else mfout
    if hasattr(node, "setDisplayNode"):
        try:
            node.setDisplayNode(display)
        except Exception:
            pass
    node.layoutChildren()
    return mfout


# ─────────────────────────────────────────────────────────────────────────────
# Operators  (callable from HDA buttons, shelf tools, and Python Panel)
# ─────────────────────────────────────────────────────────────────────────────

def setup_depth(node, mask_only=False):
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
        _notify(node, hou.severityType.Important,
                f"Depth Map: {mode} network created")
        return True
    except Exception as e:
        _notify(node, hou.severityType.Error, f"Setup failed: {e}")
        return False


def render_depth(node, animation=False, mask=False):
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
            _notify(node, hou.severityType.Error,
                    "Depth Map: output node not found - re-run Setup")
            return False

        frames = list(_frame_range(settings)) if animation else [hou.frame()]
        if animation:
            _notify(node, hou.severityType.Important,
                    f"Depth Map: rendering {len(frames)} {prefix} frames...")

        be = backend()
        odir = _output_dir(settings,
                           "mask_output_path" if mask else "output_path",
                           "mask_maps" if mask else "depth_maps")
        for frame in frames:
            hou.setFrame(frame)
            fname = _filename(settings,
                              "mask_map" if mask else "depth_map",
                              frame=frame)
            if be == "cop":
                fout.parm("copoutput").set(os.path.join(odir, fname))
                fout.render()
            else:
                fout.parm("file").set(os.path.join(odir, fname))
                fout.cook(force=True)

        _notify(node, hou.severityType.Important,
                f"Depth Map: rendered {len(frames)} {prefix} frame(s) -> {odir}")
        return True

    except Exception as e:
        _notify(node, hou.severityType.Error, f"Render failed: {e}")
        return False


def reset_depth(node, mask_only=False):
    try:
        for n in list(_dm_children(node)):
            if mask_only and not n.name().startswith(NODE_PREFIX + "M"):
                continue
            n.destroy()

        settings = load_settings(node)
        if mask_only:
            settings["mask_setup_complete"] = False
        else:
            settings["setup_complete"] = False
        save_settings(node, settings)

        _notify(node, hou.severityType.Important,
                "Depth Map: network reset")
        return True
    except Exception as e:
        _notify(node, hou.severityType.Error, f"Reset failed: {e}")
        return False
