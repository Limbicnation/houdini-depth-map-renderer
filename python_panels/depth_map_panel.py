"""Limbic Depth Map Renderer — Python Panel UI.
================================================
Mirrors the Blender Depth Map Generator v2.0 workflow:

  Depth pipeline:  Z → LOG MapRange → Brightness → Contrast → Scale → Grayscale → FileOut
  Mask pipeline:   IndexOB/Cryptomatte → IDMask → Grayscale/RGBA → FileOut

Both pipelines are independent — mask does NOT require depth to be set up first.
"""

import os
import json
import math
import sys

import hou

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

NODE_PREFIX  = "DM_"
HDA_CATEGORY = "Limic"

# ─────────────────────────────────────────────────────────────────────────────
# COP Backend Detection  (cop2 for H18-H20, cop for H21+)
# ─────────────────────────────────────────────────────────────────────────────

_COP_BACKEND = None


def _backend() -> str:
    """Return 'cop' for H21+ (copnet), 'cop2' for legacy (cop2net)."""
    global _COP_BACKEND
    if _COP_BACKEND is None:
        try:
            # Primary: check if /img accepts copnet as a child type
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
                # /img doesn't exist yet — fall back to version check
                _COP_BACKEND = "cop" if hou.applicationVersion()[0] >= 21 else "cop2"
        except Exception:
            _COP_BACKEND = "cop2"
    return _COP_BACKEND


# Semantic key → {backend: houdini_type_string}
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
    # H21+ mask pipeline additions
    "chromakey":    {"cop2": "cop2::chromakey",   "cop": "chromakey"},
    "sopimport":    {"cop2": "cop2::file",        "cop": "sopimport"},
    "rasterize":    {"cop2": "cop2::rasterize",   "cop": "rasterizegeo"},
}


def _create_node(parent: hou.Node, key: str, name: str) -> hou.Node:
    """Create a COP node using the correct backend type."""
    return parent.createNode(_NODE_MAP[key][_backend()], name)


def _set_label(node: hou.Node, label: str) -> None:
    """H21+ hou.CopNode dropped setLabel(); fall back to setComment().

    setLabel() exists on hou.Node but is NOT exposed on hou.CopNode in H21+.
    Using setComment() + DisplayComment flag preserves the label in the
    network editor and is functionally equivalent for pipeline readability.
    """
    if hasattr(node, "setLabel"):
        node.setLabel(label)
    else:
        node.setComment(label)
        node.setGenericFlag(hou.nodeFlag.DisplayComment, True)


def _container_type() -> str:
    """Return 'copnet' for H21+, 'cop2net' for legacy."""
    return "copnet" if _backend() == "cop" else "cop2net"


# ─────────────────────────────────────────────────────────────────────────────
# Default settings  (mirrors Blender's DepthMapSettings PropertyGroup v2.0)
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_SETTINGS = {
    # ── Setup tracking ──────────────────────────────────────────────────
    "setup_complete":    False,
    "mask_setup_complete": False,

    # ── Depth range ──────────────────────────────────────────────────────
    "use_custom_range":  False,
    "near":              0.1,
    "far":              1000.0,

    # ── Depth normalization (v2.0) ───────────────────────────────────────
    "normalization":     "LINEAR",   # LINEAR | LOGARITHMIC | RAW
    "scale_factor":       1.0,       # applied before normalization
    "invert":            True,       # far=0 (black), near=1 (white)

    # ── Depth adjustments (v2.0) ─────────────────────────────────────────
    "contrast":          0.2,        # gain = 1.0 + value
    "brightness":        0.0,        # added before contrast

    # ── Output ───────────────────────────────────────────────────────────
    "output_path":      "",           # "" → $HIP/depth_maps/
    "format":           "PNG",        # PNG | TIFF | EXR
    "bit_depth":        "16",         # "8" | "16"
    "preview":          False,        # add Viewer node alongside FileOut

    # ── Animation ────────────────────────────────────────────────────────
    "animation":         False,
    "use_scene_range":   True,
    "frame_start":       1,
    "frame_end":        250,

    # ── Mask export (v2.0 — mirrors Blender's mask pipeline) ─────────────
    "mask_enabled":      False,
    "mask_source":       "OBJECT_INDEX",   # OBJECT_INDEX | CRYPTOMATTE
    "mask_index":        1,                # Object Pass Index (1-32767)
    "mask_format":       "GRAYSCALE",       # GRAYSCALE | RGBA
    "mask_output_path":  "",                # "" → $HIP/mask_maps/
}


# ─────────────────────────────────────────────────────────────────────────────
# Settings helpers
# ─────────────────────────────────────────────────────────────────────────────

_SETTINGS_STORE: dict[str, dict] = {}


def _settings_key(node: hou.Node) -> str:
    return node.path()


def _add_dm_settings_parm(node: hou.Node) -> bool:
    try:
        pg = node.parmTemplateGroup()
        pg.addParmTemplate(hou.StringParmTemplate(
            "dm_settings", "", 1,
            default_value=json.dumps(DEFAULT_SETTINGS), hide=True))
        node.setParmTemplateGroup(pg)
        if node.parm("dm_settings") is not None:
            return True
    except Exception as e:
        print(f"[Limbic Depth Map] Could not add dm_settings parm to "
              f"{node.path()}: {e}", file=sys.stderr)
    return False


def _load(node: hou.Node) -> dict:
    try:
        p = node.parm("dm_settings")
        if p is None:
            _add_dm_settings_parm(node)
            p = node.parm("dm_settings")
        if p is not None:
            raw = p.eval()
            if raw:
                return {**DEFAULT_SETTINGS, **json.loads(raw)}
    except Exception:
        pass
    key = _settings_key(node)
    if key in _SETTINGS_STORE:
        return {**DEFAULT_SETTINGS, **_SETTINGS_STORE[key]}
    return {**DEFAULT_SETTINGS}


def _save(node: hou.Node, settings: dict):
    p = node.parm("dm_settings")
    if p is None:
        _add_dm_settings_parm(node)
        p = node.parm("dm_settings")
    if p is not None:
        p.set(json.dumps(settings))
    else:
        _SETTINGS_STORE[_settings_key(node)] = settings


def _dm_children(node: hou.Node):
    return [n for n in node.children() if n.name().startswith(NODE_PREFIX)]


def _output_dir(settings: dict, key: str = "output_path",
                fallback: str = "depth_maps") -> str:
    path = settings.get(key, "").strip()
    if not path:
        path = hou.expandString(f"$HIP/{fallback}/")
    os.makedirs(path, exist_ok=True)
    return path


def _filename(settings: dict, prefix: str, frame: int | None = None) -> str:
    if frame is not None and settings.get("animation"):
        fname = f"{prefix}_{frame:05d}"
    else:
        fname = prefix
    ext = {"PNG": "png", "TIFF": "tiff", "EXR": "exr"}.get(settings.get("format", "PNG"), "png")
    return f"{fname}.{ext}"


def _frame_range(settings: dict):
    if settings.get("use_scene_range", True):
        r = hou.playbar.playbackRange()
        return range(int(r[0]), int(r[1]) + 1)
    return range(settings.get("frame_start", 1), settings.get("frame_end", 250) + 1)


def _notify(node: hou.Node, severity: hou.severityType, msg: str):
    try:
        hou.ui.setStatusMessage(msg, severity=severity)
    except Exception:
        print(f"[{severity.name}] {msg}", file=sys.stderr)


# ─────────────────────────────────────────────────────────────────────────────
# COP network builders  (dual backend: cop2 for H18-H20, cop for H21+)
# ─────────────────────────────────────────────────────────────────────────────

def build_depth_network(node: hou.Node, settings: dict):
    """
    Build the depth-map compositing pipeline.
    Mirrors Blender's depth compositor exactly.

    Pipeline (matches Blender v2.0):
        DM_Source (Z from deep raster / file)
            → DM_LOG (log normalize — optional)
            → DM_RangeMap (range mapping — optional)
            → DM_Brightness (additive brightness)
            → DM_Contrast   (multiplicative gain)
            → DM_Scale     (depth scale factor)
            → DM_Grayscale (RGBA → BW)
            → DM_FileOut / DM_Viewer (output + optional preview)

    Supports both COP2 (H18-H20) and new COP (H21+) backends.
    """
    be = _backend()

    for n in list(_dm_children(node)):  # list() — avoid mutating during iteration
        if n.name().startswith(NODE_PREFIX + "M"):  # keep mask nodes
            continue
        n.destroy()

    norm = settings.get("normalization", "LINEAR")
    inv  = settings.get("invert", True)
    near = settings.get("near", 0.1)
    far  = settings.get("far",  1000.0)
    sf   = settings.get("scale_factor", 1.0)

    # ── 1. Z-Depth Source ─────────────────────────────────────────────────
    src = _create_node(node, "source", NODE_PREFIX + "Source")
    _set_label(src, "Z-Depth Source")
    src.setPosition(hou.Vector2(0, 0))

    # ── 2. Depth Normalization ────────────────────────────────────────────
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

    # ── 3. Brightness (v2.0) ─────────────────────────────────────────────
    x = (norm_node_count + 1) * STEP
    bright = _create_node(node, "brightness", NODE_PREFIX + "Brightness")
    _set_label(bright, "Brightness")
    bright.setPosition(hou.Vector2(x, 0))
    bright.parm("bright" if be == "cop" else "brightness").set(
        settings.get("brightness", 0.0))
    bright.setInput(0, normalize, 0)

    # ── 4. Contrast (v2.0 — separate from brightness) ───────────────────
    x += STEP
    ctr = _create_node(node, "contrast", NODE_PREFIX + "Contrast")
    _set_label(ctr, "Depth Contrast")
    ctr.setPosition(hou.Vector2(x, 0))
    ctr.parm("contrast" if be == "cop" else "gain").set(
        1.0 + settings.get("contrast", 0.2))
    ctr.setInput(0, bright, 0)

    # ── 5. Scale Factor (v2.0) ────────────────────────────────────────────
    x += STEP
    scale = _create_node(node, "scale", NODE_PREFIX + "Scale")
    _set_label(scale, "Depth Scale")
    scale.setPosition(hou.Vector2(x, 0))
    scale.parm("scale" if be == "cop" else "scale1").set(sf)
    scale.setInput(0, ctr, 0)

    # ── 6. Grayscale ──────────────────────────────────────────────────────
    x += STEP
    gray = _create_node(node, "grayscale", NODE_PREFIX + "Grayscale")
    _set_label(gray, "Grayscale Output")
    gray.setPosition(hou.Vector2(x, 0))
    if be == "cop2":
        gray.parm("copoutput").set("bw")
    gray.setInput(0, scale, 0)

    # ── 7a. File Output ──────────────────────────────────────────────────
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

    # ── 7b. Viewer node (optional preview — v2.0) ────────────────────────
    if settings.get("preview", False):
        viewer = _create_node(node, "viewer", NODE_PREFIX + "Viewer")
        _set_label(viewer, "Depth Preview")
        viewer.setPosition(hou.Vector2(x, 100))
        if be == "cop2":
            viewer.setInput(0, gray, 0)

    display = gray if be == "cop" else fout
    if hasattr(node, "setDisplayNode"):  # only available when copnet is in /img context
        node.setDisplayNode(display)
    node.layoutChildren()
    return fout


def build_mask_network(node: hou.Node, settings: dict):
    """
    Build the mask export compositing pipeline.
    Independent of depth — can run without depth being set up.

    Pipeline (matches Blender v2.0):
        DM_MSource (IndexOB / Cryptomatte)
            → DM_MRGBA_Convert or DM_MGrayscale
            → DM_MaskFileOut

    Supports both COP2 (H18-H20) and new COP (H21+) backends.
    """
    be = _backend()

    for n in list(_dm_children(node)):  # list() — avoid mutating during iteration
        if n.name().startswith(NODE_PREFIX + "M"):
            n.destroy()

    source = settings.get("mask_source", "OBJECT_INDEX")
    mfmt   = settings.get("mask_format", "GRAYSCALE")
    midx   = settings.get("mask_index", 1)

    # ── 1. Mask Source ────────────────────────────────────────────────────
    # H21+ new COP: idtomask requires an 'id' render plane (Karma/Mantra EXR only).
    # For H21+ we use chromakey on the rendered depth image instead — practical
    # for ComfyUI mask generation without a dedicated ID pass.
    # cop2 backend retains idtomask for full Mantra/render-pass pipelines.

    if source == "CRYPTOMATTE":
        # Always: cryptomatte node handles its own input via path parm
        mask_src = _create_node(node, "cryptomatte", NODE_PREFIX + "MSource")
        _set_label(mask_src, "Cryptomatte Source")
        mask_src.setPosition(hou.Vector2(0, -300))

    elif be == "cop" and source == "OBJECT_INDEX":
        # H21+ new COP: sopimport → rasterizegeo pipeline.
        # Reads SOP geometry directly — no pre-rendered image required.
        # The user sets the sopimport path to their scene object (e.g. /obj/geo1).
        # rasterizegeo rasterizes it against the camera to produce a clean mask.
        mask_input = _create_node(node, "sopimport", NODE_PREFIX + "MaskInput")
        _set_label(mask_input, "SOP Source (set path to your geo)")
        mask_input.setPosition(hou.Vector2(-200, -300))
        # Leave soppath for user to set — no default that won't exist
        try:
            mask_input.parm("soppath").set("")
        except Exception:
            pass

        mask_src = _create_node(node, "rasterize", NODE_PREFIX + "MSource")
        _set_label(mask_src, "Rasterize Geo to Mask")
        mask_src.setPosition(hou.Vector2(0, -300))
        mask_src.setInput(0, mask_input, 0)

    else:
        # cop2 backend: idtomask works with Mantra Object Index render pass
        mask_src = _create_node(node, "idtomask", NODE_PREFIX + "MSource")
        _set_label(mask_src, "Object Index Mask")
        mask_src.parm("object_id").set(midx)
        mask_src.setPosition(hou.Vector2(0, -300))

    # ── 2. Output format ──────────────────────────────────────────────────
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

    # ── 3. File Output ────────────────────────────────────────────────────
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
    if hasattr(node, "setDisplayNode"):  # only available when copnet is in /img context
        node.setDisplayNode(display)
    node.layoutChildren()
    return mfout


# ─────────────────────────────────────────────────────────────────────────────
# Operators
# ─────────────────────────────────────────────────────────────────────────────

class OpSetup:
    script_label = "limbic.setup_depth_map"

    @staticmethod
    def execute(node: hou.Node, mask_only: bool = False) -> bool:
        settings = _load(node)
        try:
            if mask_only:
                build_mask_network(node, settings)
                settings["mask_setup_complete"] = True
            else:
                build_depth_network(node, settings)
                settings["setup_complete"] = True
            _save(node, settings)
            mode = "Mask" if mask_only else "Depth"
            _notify(node, hou.severityType.Important,
                    f"Depth Map: {mode} network created")
            return True
        except Exception as e:
            _notify(node, hou.severityType.Error,
                    f"Setup failed: {e}")
            return False


class OpRender:
    script_label = "limbic.render_depth_map"

    @staticmethod
    def execute(node: hou.Node, animation: bool = False,
               mask: bool = False) -> bool:
        try:
            settings = _load(node)
            settings["animation"] = animation
            _save(node, settings)

            prefix = "Mask" if mask else "depth"
            complete_key = "mask_setup_complete" if mask else "setup_complete"

            if not settings.get(complete_key, False):
                if not OpSetup.execute(node, mask_only=mask):
                    return False

            fout = node.node(NODE_PREFIX +
                             ("MaskFileOut" if mask else "FileOut"))
            if not fout:
                _notify(node, hou.severityType.Error,
                        f"Depth Map: output node not found — re-run Setup")
                return False

            frames = list(_frame_range(settings)) if animation else [hou.frame()]
            if animation:
                _notify(node, hou.severityType.Important,
                        f"Depth Map: rendering {len(frames)} {prefix} frames…")

            be = _backend()
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
                    f"Depth Map: rendered {len(frames)} {prefix} frame(s) → {odir}")
            return True

        except Exception as e:
            _notify(node, hou.severityType.Error,
                    f"Render failed: {e}")
            return False


class OpReset:
    script_label = "limbic.reset_depth_map"

    @staticmethod
    def execute(node: hou.Node, mask_only: bool = False) -> bool:
        try:
            for n in list(_dm_children(node)):  # list() snapshot
                if mask_only and not n.name().startswith(NODE_PREFIX + "M"):
                    continue
                n.destroy()

            settings = _load(node)
            if mask_only:
                settings["mask_setup_complete"] = False
            else:
                settings["setup_complete"] = False
            _save(node, settings)

            _notify(node, hou.severityType.Important,
                    "Depth Map: network reset")
            return True
        except Exception as e:
            _notify(node, hou.severityType.Error,
                    f"Reset failed: {e}")
            return False


# ─────────────────────────────────────────────────────────────────────────────
# Python Panel Interface (Qt UI — mirrors Blender's sidebar)
# ─────────────────────────────────────────────────────────────────────────────

class DepthMapPanel:

    def __init__(self):
        self.node = None
        try:
            self.node = self._resolve_node()
            if self.node is not None:
                self._ensure_parm()
        except Exception:
            self.node = None

    def _resolve_node(self):
        try:
            pane = hou.ui.curPaneTab()
            if pane and pane.type() == hou.paneTabType.CompositorViewer:
                n = pane.pwd() if hasattr(pane, "pwd") else None
                if n is not None:
                    return n
        except Exception:
            pass
        return self._find_hda()

    def onCreate(self):
        self.node = self._resolve_node()
        self._ensure_parm()

    def onRevive(self):
        self.node = self._resolve_node()
        self._ensure_parm()

    def onActiveNodeChanged(self, kwargs):
        self.node = kwargs.get("active_node", None)
        self._ensure_parm()

    def _find_hda(self):
        container_types = {"copnet", "cop2net"}
        for root in [hou.node("/obj"), hou.node("/img")]:
            if root is None:
                continue
            for n in root.allSubChildren():
                try:
                    tname = n.type().name()
                    if tname == "limbic_depth_map_renderer":
                        return n
                    if tname in container_types and (
                            n.parm("dm_settings") is not None
                            or _settings_key(n) in _SETTINGS_STORE):
                        return n
                except Exception:
                    pass
        return None

    def _ensure_node(self):
        if self.node is not None:
            return True
        self.node = self._find_hda()
        if self.node is not None:
            self._ensure_parm()
            return True
        try:
            img = hou.node("/img")
            if img is None:
                img = hou.node("/obj").createNode("img", "img")
            ctype = _container_type()
            net = img.createNode(ctype, "depth_map1")
            net.moveToGoodPosition()
            self.node = net
            self._ensure_parm()
            return True
        except Exception as e:
            be = _backend()
            ctype = _container_type()
            ver = hou.applicationVersionString()
            hou.ui.displayMessage(
                f"Could not create Depth Map network:\n{e}\n\n"
                f"Debug: backend={be}, container={ctype}, houdini={ver}",
                severity=hou.severityType.Error)
            return False

    def _ensure_parm(self):
        if self.node is None:
            return
        if self.node.parm("dm_settings") is None:
            _add_dm_settings_parm(self.node)

    def _current_settings(self) -> dict:
        return _load(self.node) if self.node else {**DEFAULT_SETTINGS}

    def _refresh_node(self):
        try:
            resolved = self._resolve_node()
            if resolved is not None:
                self.node = resolved
                self._ensure_parm()
        except Exception:
            pass

    def _save(self, settings: dict):
        if self.node:
            _save(self.node, settings)

    def buildUI(self, parent_widget):
        from hutil.Qt import QtWidgets, QtCore
        _build_ui(self, parent_widget, QtWidgets, QtCore)


def _build_ui(panel: DepthMapPanel, parent, QtWidgets, QtCore):

    outer = QtWidgets.QVBoxLayout(parent)
    outer.setContentsMargins(8, 8, 8, 8)
    outer.setSpacing(4)

    # ═══════════════════════════════════════════════════════════════════
    # SECTION 1 — Depth Range
    # ═══════════════════════════════════════════════════════════════════
    depth_grp = QtWidgets.QGroupBox("Depth Range")
    depth_layout = QtWidgets.QFormLayout(depth_grp)
    depth_layout.setSpacing(4)

    cb_custom = QtWidgets.QCheckBox("Custom Near/Far Range")
    depth_layout.addRow(cb_custom)

    spin_near = QtWidgets.QDoubleSpinBox()
    spin_near.setRange(0.001, 99999); spin_near.setDecimals(3); spin_near.setSuffix(" m")
    depth_layout.addRow("Near:", spin_near)

    spin_far = QtWidgets.QDoubleSpinBox()
    spin_far.setRange(0.001, 99999); spin_far.setDecimals(3); spin_far.setSuffix(" m")
    depth_layout.addRow("Far:", spin_far)

    combo_norm = QtWidgets.QComboBox()
    combo_norm.addItems(["LINEAR", "LOGARITHMIC", "RAW"])
    depth_layout.addRow("Normalization:", combo_norm)

    cb_inv = QtWidgets.QCheckBox("Invert (near = white, far = black)")
    cb_inv.setChecked(True)
    depth_layout.addRow(cb_inv)

    spin_scale = QtWidgets.QDoubleSpinBox()
    spin_scale.setRange(0.001, 1000); spin_scale.setDecimals(4); spin_scale.setValue(1.0)
    depth_layout.addRow("Scale Factor:", spin_scale)

    outer.addWidget(depth_grp)

    # ═══════════════════════════════════════════════════════════════════
    # SECTION 2 — Depth Adjustments (v2.0)
    # ═══════════════════════════════════════════════════════════════════
    adj_grp = QtWidgets.QGroupBox("Depth Adjustments")
    adj_layout = QtWidgets.QFormLayout(adj_grp)
    adj_layout.setSpacing(4)

    slider_bright = QtWidgets.QSlider(QtCore.Qt.Horizontal)
    slider_bright.setRange(-100, 100); slider_bright.setValue(0)
    lbl_bright = QtWidgets.QLabel("0.00")
    bright_row = QtWidgets.QHBoxLayout()
    bright_row.addWidget(slider_bright); bright_row.addWidget(lbl_bright)
    slider_bright.valueChanged.connect(
        lambda v: lbl_bright.setText(f"{v/100.0:.2f}"))
    adj_layout.addRow("Brightness:", bright_row)

    slider_ctr = QtWidgets.QSlider(QtCore.Qt.Horizontal)
    slider_ctr.setRange(0, 200); slider_ctr.setValue(20)
    lbl_ctr = QtWidgets.QLabel("0.20")
    ctr_row = QtWidgets.QHBoxLayout()
    ctr_row.addWidget(slider_ctr); ctr_row.addWidget(lbl_ctr)
    slider_ctr.valueChanged.connect(
        lambda v: lbl_ctr.setText(f"{v/100.0:.2f}"))
    adj_layout.addRow("Contrast:", ctr_row)

    outer.addWidget(adj_grp)

    # ═══════════════════════════════════════════════════════════════════
    # SECTION 3 — Output
    # ═══════════════════════════════════════════════════════════════════
    out_grp = QtWidgets.QGroupBox("Output")
    out_layout = QtWidgets.QFormLayout(out_grp)
    out_layout.setSpacing(4)

    edit_path = QtWidgets.QLineEdit()
    edit_path.setPlaceholderText("$HIP/depth_maps/")
    out_layout.addRow("Path:", edit_path)

    combo_fmt = QtWidgets.QComboBox()
    combo_fmt.addItems(["PNG", "TIFF", "EXR"])
    out_layout.addRow("Format:", combo_fmt)

    combo_bits = QtWidgets.QComboBox()
    combo_bits.addItems(["8-bit", "16-bit"])
    out_layout.addRow("Bit Depth:", combo_bits)

    cb_preview = QtWidgets.QCheckBox("Add Viewer node (preview in compositor)")
    out_layout.addRow(cb_preview)

    outer.addWidget(out_grp)

    # ═══════════════════════════════════════════════════════════════════
    # SECTION 4 — Animation
    # ═══════════════════════════════════════════════════════════════════
    anim_grp = QtWidgets.QGroupBox("Animation")
    anim_layout = QtWidgets.QFormLayout(anim_grp)
    anim_layout.setSpacing(4)

    cb_anim = QtWidgets.QCheckBox("Render as animation sequence")
    anim_layout.addRow(cb_anim)

    cb_scene = QtWidgets.QCheckBox("Use scene frame range")
    cb_scene.setChecked(True)
    anim_layout.addRow(cb_scene)

    spin_start = QtWidgets.QSpinBox()
    spin_start.setRange(0, 99999); spin_start.setValue(1)
    spin_end = QtWidgets.QSpinBox()
    spin_end.setRange(0, 99999); spin_end.setValue(250)
    frow = QtWidgets.QHBoxLayout()
    frow.addWidget(spin_start); frow.addWidget(QtWidgets.QLabel(" → "))
    frow.addWidget(spin_end)
    anim_layout.addRow("Frames:", frow)

    outer.addWidget(anim_grp)

    # ═══════════════════════════════════════════════════════════════════
    # SECTION 5 — Mask Export (v2.0 — independent pipeline)
    # ═══════════════════════════════════════════════════════════════════
    mask_grp = QtWidgets.QGroupBox("Mask Export (ComfyUI)")
    mask_layout = QtWidgets.QFormLayout(mask_grp)
    mask_layout.setSpacing(4)

    cb_mask_on = QtWidgets.QCheckBox("Enable mask export")
    mask_layout.addRow(cb_mask_on)

    combo_mask_src = QtWidgets.QComboBox()
    combo_mask_src.addItems(["OBJECT_INDEX", "CRYPTOMATTE"])
    mask_layout.addRow("Source:", combo_mask_src)

    spin_midx = QtWidgets.QSpinBox()
    spin_midx.setRange(1, 32767); spin_midx.setValue(1)
    lbl_midx = QtWidgets.QLabel("Set Object → Relations → Pass Index")
    lbl_midx.setStyleSheet("color: gray; font-size: 10px")
    midx_row = QtWidgets.QHBoxLayout()
    midx_row.addWidget(spin_midx)
    mask_layout.addRow("Object Index:", midx_row)
    mask_layout.addRow("", lbl_midx)

    combo_mask_fmt = QtWidgets.QComboBox()
    combo_mask_fmt.addItems(["GRAYSCALE", "RGBA"])
    mask_layout.addRow("Format:", combo_mask_fmt)

    edit_mask_path = QtWidgets.QLineEdit()
    edit_mask_path.setPlaceholderText("$HIP/mask_maps/")
    mask_layout.addRow("Mask Path:", edit_mask_path)

    outer.addWidget(mask_grp)

    # ═══════════════════════════════════════════════════════════════════
    # ACTION BUTTONS
    # ═══════════════════════════════════════════════════════════════════
    btn_setup   = QtWidgets.QPushButton("⚙  Setup Depth Network")
    btn_render  = QtWidgets.QPushButton("▶  Render Depth Map")
    btn_anim    = QtWidgets.QPushButton("▶▶  Render Depth Animation")
    btn_reset   = QtWidgets.QPushButton("✕  Reset All")

    sep = QtWidgets.QLabel("<hr>")
    sep.setStyleSheet("color: #555")

    mask_btn_setup  = QtWidgets.QPushButton("⚙  Setup Mask Network")
    mask_btn_render = QtWidgets.QPushButton("▶  Render Mask")
    mask_btn_anim   = QtWidgets.QPushButton("▶▶  Render Mask Animation")
    mask_btn_reset  = QtWidgets.QPushButton("✕  Reset Mask")

    btn_layout = QtWidgets.QHBoxLayout()
    btn_layout.addWidget(btn_setup)
    btn_layout.addWidget(btn_render)
    outer.addLayout(btn_layout)
    outer.addWidget(btn_anim)
    outer.addWidget(btn_reset)
    outer.addWidget(sep)

    mask_btn_layout = QtWidgets.QHBoxLayout()
    mask_btn_layout.addWidget(mask_btn_setup)
    mask_btn_layout.addWidget(mask_btn_render)
    outer.addLayout(mask_btn_layout)
    outer.addWidget(mask_btn_anim)
    outer.addWidget(mask_btn_reset)

    outer.addStretch(1)

    # ── Wire signals ────────────────────────────────────────────────────────

    def _collect() -> dict:
        return {
            "use_custom_range":  cb_custom.isChecked(),
            "near":              spin_near.value(),
            "far":               spin_far.value(),
            "normalization":     combo_norm.currentText(),
            "invert":            cb_inv.isChecked(),
            "scale_factor":      spin_scale.value(),
            "brightness":        slider_bright.value() / 100.0,
            "contrast":         slider_ctr.value() / 100.0,
            "output_path":       edit_path.text().strip(),
            "format":            combo_fmt.currentText(),
            "bit_depth":        "16" if combo_bits.currentText() == "16-bit" else "8",
            "preview":           cb_preview.isChecked(),
            "animation":         cb_anim.isChecked(),
            "use_scene_range":   cb_scene.isChecked(),
            "frame_start":       spin_start.value(),
            "frame_end":         spin_end.value(),
            "mask_enabled":       cb_mask_on.isChecked(),
            "mask_source":       combo_mask_src.currentText(),
            "mask_index":        spin_midx.value(),
            "mask_format":       combo_mask_fmt.currentText(),
            "mask_output_path":  edit_mask_path.text().strip(),
        }

    def _load_ui():
        s = panel._current_settings()
        cb_custom.setChecked(s.get("use_custom_range", False))
        spin_near.setValue(s.get("near", 0.1))
        spin_far.setValue(s.get("far", 1000.0))
        combo_norm.setCurrentText(s.get("normalization", "LINEAR"))
        cb_inv.setChecked(s.get("invert", True))
        spin_scale.setValue(s.get("scale_factor", 1.0))
        slider_bright.setValue(int(s.get("brightness", 0.0) * 100))
        lbl_bright.setText(f"{s.get('brightness', 0.0):.2f}")
        slider_ctr.setValue(int(s.get("contrast", 0.2) * 100))
        lbl_ctr.setText(f"{s.get('contrast', 0.2):.2f}")
        edit_path.setText(s.get("output_path", ""))
        combo_fmt.setCurrentText(s.get("format", "PNG"))
        combo_bits.setCurrentText(
            "16-bit" if s.get("bit_depth") == "16" else "8-bit")
        cb_preview.setChecked(s.get("preview", False))
        cb_anim.setChecked(s.get("animation", False))
        cb_scene.setChecked(s.get("use_scene_range", True))
        spin_start.setValue(s.get("frame_start", 1))
        spin_end.setValue(s.get("frame_end", 250))
        cb_mask_on.setChecked(s.get("mask_enabled", False))
        combo_mask_src.setCurrentText(s.get("mask_source", "OBJECT_INDEX"))
        spin_midx.setValue(s.get("mask_index", 1))
        combo_mask_fmt.setCurrentText(s.get("mask_format", "GRAYSCALE"))
        edit_mask_path.setText(s.get("mask_output_path", ""))

    def _on_setup():
        try:
            s = _collect()
            panel._refresh_node()
            if panel._ensure_node():
                panel._save(s)
                OpSetup.execute(panel.node, mask_only=False)
            else:
                hou.ui.displayMessage(
                    "No COP network found. Open a Compositor pane and try again.",
                    title="Depth Map", severity=hou.severityType.Warning)
        except Exception as e:
            hou.ui.displayMessage(f"Setup failed:\n{e}", title="Depth Map Error",
                                  severity=hou.severityType.Error)

    def _on_render():
        try:
            s = _collect()
            s["animation"] = False
            panel._refresh_node()
            if panel._ensure_node():
                panel._save(s)
                OpRender.execute(panel.node, animation=False, mask=False)
            else:
                hou.ui.displayMessage(
                    "No COP network found. Run Setup first.",
                    title="Depth Map", severity=hou.severityType.Warning)
        except Exception as e:
            hou.ui.displayMessage(f"Render failed:\n{e}", title="Depth Map Error",
                                  severity=hou.severityType.Error)

    def _on_anim():
        try:
            s = _collect()
            s["animation"] = True
            panel._refresh_node()
            if panel._ensure_node():
                panel._save(s)
                OpRender.execute(panel.node, animation=True, mask=False)
            else:
                hou.ui.displayMessage(
                    "No COP network found. Run Setup first.",
                    title="Depth Map", severity=hou.severityType.Warning)
        except Exception as e:
            hou.ui.displayMessage(f"Animation render failed:\n{e}",
                                  title="Depth Map Error",
                                  severity=hou.severityType.Error)

    def _on_reset():
        try:
            panel._refresh_node()
            if panel._ensure_node():
                OpReset.execute(panel.node, mask_only=False)
            else:
                hou.ui.displayMessage(
                    "No COP network to reset.", title="Depth Map",
                    severity=hou.severityType.Warning)
        except Exception as e:
            hou.ui.displayMessage(f"Reset failed:\n{e}", title="Depth Map Error",
                                  severity=hou.severityType.Error)

    def _on_mask_setup():
        try:
            s = _collect()
            panel._refresh_node()
            if panel._ensure_node():
                panel._save(s)
                OpSetup.execute(panel.node, mask_only=True)
            else:
                hou.ui.displayMessage(
                    "No COP network found. Open a Compositor pane and try again.",
                    title="Depth Map", severity=hou.severityType.Warning)
        except Exception as e:
            hou.ui.displayMessage(f"Mask setup failed:\n{e}",
                                  title="Depth Map Error",
                                  severity=hou.severityType.Error)

    def _on_mask_render():
        try:
            s = _collect()
            s["animation"] = False
            panel._refresh_node()
            if panel._ensure_node():
                panel._save(s)
                OpRender.execute(panel.node, animation=False, mask=True)
            else:
                hou.ui.displayMessage(
                    "No COP network found. Run Mask Setup first.",
                    title="Depth Map", severity=hou.severityType.Warning)
        except Exception as e:
            hou.ui.displayMessage(f"Mask render failed:\n{e}",
                                  title="Depth Map Error",
                                  severity=hou.severityType.Error)

    def _on_mask_anim():
        try:
            s = _collect()
            s["animation"] = True
            panel._refresh_node()
            if panel._ensure_node():
                panel._save(s)
                OpRender.execute(panel.node, animation=True, mask=True)
            else:
                hou.ui.displayMessage(
                    "No COP network found. Run Mask Setup first.",
                    title="Depth Map", severity=hou.severityType.Warning)
        except Exception as e:
            hou.ui.displayMessage(f"Mask animation failed:\n{e}",
                                  title="Depth Map Error",
                                  severity=hou.severityType.Error)

    def _on_mask_reset():
        try:
            panel._refresh_node()
            if panel._ensure_node():
                OpReset.execute(panel.node, mask_only=True)
            else:
                hou.ui.displayMessage(
                    "No COP network to reset.", title="Depth Map",
                    severity=hou.severityType.Warning)
        except Exception as e:
            hou.ui.displayMessage(f"Mask reset failed:\n{e}",
                                  title="Depth Map Error",
                                  severity=hou.severityType.Error)

    btn_setup.clicked.connect(_on_setup)
    btn_render.clicked.connect(_on_render)
    btn_anim.clicked.connect(_on_anim)
    btn_reset.clicked.connect(_on_reset)
    mask_btn_setup.clicked.connect(_on_mask_setup)
    mask_btn_render.clicked.connect(_on_mask_render)
    mask_btn_anim.clicked.connect(_on_mask_anim)
    mask_btn_reset.clicked.connect(_on_mask_reset)

    _load_ui()


# ─────────────────────────────────────────────────────────────────────────────
# Module registration
# ─────────────────────────────────────────────────────────────────────────────

def register_operators():
    pass


def unregister_operators():
    pass


def createInterface():
    from hutil.Qt import QtWidgets
    root = QtWidgets.QWidget()
    panel = DepthMapPanel()
    panel.buildUI(root)
    root._depth_map_panel = panel
    return root
