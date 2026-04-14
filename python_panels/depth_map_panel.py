"""Limbic Depth Map Renderer — Python Panel UI.
===============================================
Thin Qt UI wrapper around the shared core module.
Provides the user-facing panel; all pipeline logic lives in
limbic_depth_map_core.py.

Both pipelines are independent — mask does NOT require depth.
"""

import json
import os
import sys


def _find_core_dir() -> str:
    """Locate the scripts/ directory containing limbic_depth_map_core.py.

    Works in all execution contexts:
      - Normal file import (__file__ is defined)
      - Houdini .pypanel CDATA (__file__ is NOT defined)
      - HDA PythonModule embedded script
    """
    # 1. Try __file__-based resolution (works for normal imports)
    try:
        this_dir = os.path.dirname(os.path.abspath(__file__))
        candidate = os.path.join(this_dir, "..", "scripts")
        if os.path.exists(os.path.join(candidate, "limbic_depth_map_core.py")):
            return os.path.normpath(candidate)
    except NameError:
        pass

    # 2. Try LIMBIC_DEPTH_MAP environment variable
    limbic_root = os.environ.get("LIMBIC_DEPTH_MAP", "")
    if limbic_root:
        scripts_dir = os.path.join(limbic_root, "scripts")
        if os.path.exists(os.path.join(scripts_dir, "limbic_depth_map_core.py")):
            return scripts_dir

    # 3. Try HOUDINI_PATH scan (requires hou, but we're in Houdini)
    try:
        import hou
        for hp in hou.expandString("$HOUDINI_PATH").split(os.pathsep):
            candidate = os.path.join(hp, "scripts")
            if os.path.exists(os.path.join(candidate, "limbic_depth_map_core.py")):
                return candidate
    except Exception:
        pass

    # 4. Last resort: relative to CWD
    candidate = os.path.join(os.getcwd(), "scripts")
    if os.path.exists(os.path.join(candidate, "limbic_depth_map_core.py")):
        return candidate

    return os.path.normpath(os.path.join(os.getcwd(), "scripts"))


_core_dir = _find_core_dir()
if _core_dir not in sys.path:
    sys.path.insert(0, _core_dir)

import hou

from limbic_depth_map_core import (  # noqa: E402
    NODE_PREFIX,
    HDA_CATEGORY,
    DEFAULT_SETTINGS,
    backend,
    _container_type,
    load_settings,
    save_settings,
    add_dm_settings_parm,
    dm_children,
    output_dir,
    filename,
    frame_range,
    notify,
    build_depth_network,
    build_mask_network,
    setup_depth,
    render_depth,
    reset_depth,
    reset_backend_cache,
)
from settings_model import DepthMapSettings  # noqa: E402

# ── Houdini 21.0 UI Bug Workaround ─────────────────────────────────────────
# H21+ new COP node types don't expose outputNames() the same way COP2 did.
# This causes IndexError in nodegraphutils.py line 1281 when hovering wires:
#   output_names[wire.outputIndex()] -> IndexError (empty tuple)
# We monkey-patch getPromptWithNoHandler to catch and suppress this.
# SideFX bug, cosmetic only — does not affect node functionality.
def _patch_h21_wire_hover_bug():
    try:
        import hou
        if hou.applicationVersion()[0] < 21:
            return
    except Exception:
        pass
    try:
        from nodegraphutils import getPromptWithNoHandler as _orig
        import nodegraphutils as _ngu
        def _safe_get_prompt(uievent):
            try:
                return _orig(uievent)
            except IndexError:
                return ""
        _ngu.getPromptWithNoHandler = _safe_get_prompt
    except Exception:
        pass

_patch_h21_wire_hover_bug()

_SETTINGS_STORE: dict[int, dict] = {}


def _settings_key(node: hou.Node) -> int:
    try:
        return node.sessionId()
    except Exception:
        return hash(node.path())


def _load(node: hou.Node) -> dict:
    """Load settings — delegates to core load_settings(), falls back to store."""
    try:
        return load_settings(node)
    except Exception:
        pass
    key = _settings_key(node)
    if key in _SETTINGS_STORE:
        return {**DEFAULT_SETTINGS, **_SETTINGS_STORE[key]}
    return {**DEFAULT_SETTINGS}


def _save(node: hou.Node, settings: dict):
    """Save settings — delegates to core save_settings(), falls back to store."""
    try:
        save_settings(node, settings)
        return
    except Exception:
        pass
    _SETTINGS_STORE[_settings_key(node)] = settings


class OpSetup:
    script_label = "limbic.setup_depth_map"

    @staticmethod
    def execute(node: hou.Node, mask_only: bool = False) -> bool:
        return setup_depth(node, mask_only=mask_only)


class OpRender:
    script_label = "limbic.render_depth_map"

    @staticmethod
    def execute(node: hou.Node, animation: bool = False,
                mask: bool = False) -> bool:
        return render_depth(node, animation=animation, mask=mask)


class OpReset:
    script_label = "limbic.reset_depth_map"

    @staticmethod
    def execute(node: hou.Node, mask_only: bool = False) -> bool:
        return reset_depth(node, mask_only=mask_only)



# ─────────────────────────────────────────────────────────────────────────────
# HDA Spawner
# ─────────────────────────────────────────────────────────────────────────────

def spawn_hda(node_name: str = "depth_map") -> "hou.Node | None":
    """Create a limbic_depth_map_renderer COP network instance in /img.

    - No hardcoded paths — uses hou.getenv() / hou.expandString().
    - Auto-creates /img container if missing.
    - Auto-increments name on collision (depth_map1, depth_map2, ...).
    - Wrapped in undo group.
    - Returns the created hou.Node, or None on failure.
    """
    img = hou.node("/img")
    if img is None:
        try:
            img = hou.node("/obj").createNode("img", "img")
            img.moveToGoodPosition()
        except Exception as e:
            print(f"[Limbic Depth Map] Could not create /img context: {e}",
                  file=sys.stderr)
            try:
                hou.ui.displayMessage(
                    f"Could not create /img context:\n{e}",
                    title="Depth Map Spawner",
                    severity=hou.severityType.Error,
                )
            except Exception:
                pass
            return None

    base = node_name
    if base[-1:].isdigit():
        while base and base[-1].isdigit():
            base = base[:-1]
        base = base or "depth_map"
    counter = 1
    while img.node(f"{base}{counter}") is not None:
        counter += 1
    final_name = f"{base}{counter}"

    try:
        with hou.undos.group("Spawn Depth Map HDA"):
            hda_type = hou.nodeType("Driver/cop/gero::depth_map_renderer")
            if hda_type is not None:
                node = img.createNode(
                    "gero::depth_map_renderer", final_name)
            else:
                node = img.createNode(_container_type(), final_name)
                add_dm_settings_parm(node)
                p = node.parm("dm_settings")
                if p is not None:
                    p.set(json.dumps({
                        "setup_complete": False,
                        "mask_setup_complete": False,
                    }))
            node.moveToGoodPosition()
            node.setSelected(True, clear_all_selected=True)
        hou.ui.setStatusMessage(
            f"Depth Map: spawned '{final_name}' in /img",
            severity=hou.severityType.ImportantMessage,
        )
        return node
    except Exception as e:
        import traceback
        traceback.print_exc(file=sys.stderr)
        try:
            hou.ui.displayMessage(
                f"Spawn failed:\n{e}",
                title="Depth Map Spawner",
                severity=hou.severityType.Error,
            )
        except Exception:
            pass
        return None

class DepthMapPanel:

    def __init__(self):
        self.node = None
        try:
            self.node = self._resolve_node()
            if self.node is not None:
                self._ensure_parm()
        except Exception:
            self.node = None

    def __del__(self):
        """Clean up _SETTINGS_STORE entries when panel is destroyed."""
        try:
            if self.node is not None:
                _SETTINGS_STORE.pop(_settings_key(self.node), None)
        except Exception:
            pass

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
        reset_backend_cache()

    def onActiveNodeChanged(self, kwargs):
        self.node = kwargs.get("active_node", None)
        self._ensure_parm()

    def _find_hda(self):
        # Scoped to /img only — avoids O(n) allSubChildren() on heavy scenes
        img = hou.node("/img")
        if img is None:
            return None
        for n in img.children():
            try:
                tname = n.type().name()
                if tname in ("gero::depth_map_renderer",
                             "limbic_depth_map_renderer"):
                    return n
                if tname in {"copnet", "cop2net"} and (
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
            be = backend()
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
            add_dm_settings_parm(self.node)

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

    # ═══ HDA Spawner ════════════════════════════════════════════════════════
    btn_spawn = QtWidgets.QPushButton("⊕  Spawn Depth Map HDA")
    btn_spawn.setToolTip("Create a new limbic_depth_map_renderer node in /img")
    outer.addWidget(btn_spawn)

    # ═══ Depth Range ══════════════════════════════════════════════════════
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

    # ═══ Depth Adjustments ════════════════════════════════════════════════
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

    # ═══ Output ══════════════════════════════════════════════════════════
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

    # ═══ Animation ════════════════════════════════════════════════════════
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

    # ═══ Mask Export ══════════════════════════════════════════════════════
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

    # ═══ Action Buttons ═════════════════════════════════════════════════
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

    def _collect() -> dict:
        near_val = spin_near.value()
        far_val = spin_far.value()
        scale_val = spin_scale.value()
        if cb_custom.isChecked() and near_val >= far_val:
            hou.ui.displayMessage(
                f"Near ({near_val:.3f}) must be less than Far ({far_val:.3f}).",
                title="Depth Map — Validation",
                severity=hou.severityType.Warning,
            )
            far_val = near_val + 1.0
            spin_far.setValue(far_val)
        if scale_val == 0.0:
            hou.ui.displayMessage(
                "Scale Factor cannot be zero — reset to 1.0.",
                title="Depth Map — Validation",
                severity=hou.severityType.Warning,
            )
            scale_val = 1.0
            spin_scale.setValue(scale_val)
        s = DepthMapSettings(
            use_custom_range=cb_custom.isChecked(),
            near=near_val,
            far=far_val,
            normalization=combo_norm.currentText(),
            invert=cb_inv.isChecked(),
            scale_factor=scale_val,
            brightness=slider_bright.value() / 100.0,
            contrast=slider_ctr.value() / 100.0,
            output_path=edit_path.text().strip(),
            format=combo_fmt.currentText(),
            bit_depth="16" if combo_bits.currentText() == "16-bit" else "8",
            preview=cb_preview.isChecked(),
            animation=cb_anim.isChecked(),
            use_scene_range=cb_scene.isChecked(),
            frame_start=spin_start.value(),
            frame_end=spin_end.value(),
            mask_enabled=cb_mask_on.isChecked(),
            mask_source=combo_mask_src.currentText(),
            mask_index=spin_midx.value(),
            mask_format=combo_mask_fmt.currentText(),
            mask_output_path=edit_mask_path.text().strip(),
        )
        return s.to_dict()

    def _load_ui():
        s = DepthMapSettings.from_dict(panel._current_settings())
        cb_custom.setChecked(s.use_custom_range)
        spin_near.setValue(s.near)
        spin_far.setValue(s.far)
        combo_norm.setCurrentText(s.normalization)
        cb_inv.setChecked(s.invert)
        spin_scale.setValue(s.scale_factor)
        slider_bright.setValue(int(s.brightness * 100))
        lbl_bright.setText(f"{s.brightness:.2f}")
        slider_ctr.setValue(int(s.contrast * 100))
        lbl_ctr.setText(f"{s.contrast:.2f}")
        edit_path.setText(s.output_path)
        combo_fmt.setCurrentText(s.format)
        combo_bits.setCurrentText(
            "16-bit" if s.bit_depth == "16" else "8-bit")
        cb_preview.setChecked(s.preview)
        cb_anim.setChecked(s.animation)
        cb_scene.setChecked(s.use_scene_range)
        spin_start.setValue(s.frame_start)
        spin_end.setValue(s.frame_end)
        cb_mask_on.setChecked(s.mask_enabled)
        combo_mask_src.setCurrentText(s.mask_source)
        spin_midx.setValue(s.mask_index)
        combo_mask_fmt.setCurrentText(s.mask_format)
        edit_mask_path.setText(s.mask_output_path)

    def _on_setup():
        try:
            s = _collect()
            panel._refresh_node()
            if panel._ensure_node():
                panel._save(s)
                with hou.undos.group("Depth Map: Setup Depth Network"):
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
                with hou.undos.group("Depth Map: Render Depth Map"):
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
                with hou.undos.group("Depth Map: Render Depth Animation"):
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
                with hou.undos.group("Depth Map: Reset Depth Map"):
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
                with hou.undos.group("Depth Map: Setup Mask Network"):
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
                with hou.undos.group("Depth Map: Render Mask"):
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
                with hou.undos.group("Depth Map: Render Mask Animation"):
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
                with hou.undos.group("Depth Map: Reset Mask"):
                    OpReset.execute(panel.node, mask_only=True)
            else:
                hou.ui.displayMessage(
                    "No COP network to reset.", title="Depth Map",
                    severity=hou.severityType.Warning)
        except Exception as e:
            hou.ui.displayMessage(f"Mask reset failed:\n{e}",
                                  title="Depth Map Error",
                                  severity=hou.severityType.Error)

    def _on_spawn():
        try:
            new_node = spawn_hda()
            if new_node is not None:
                panel.node = new_node
                panel._ensure_parm()
                _load_ui()
        except Exception as e:
            hou.ui.displayMessage(
                f"Spawn failed:\n{e}",
                title="Depth Map Error",
                severity=hou.severityType.Error,
            )

    btn_spawn.clicked.connect(_on_spawn)
    btn_setup.clicked.connect(_on_setup)
    btn_render.clicked.connect(_on_render)
    btn_anim.clicked.connect(_on_anim)
    btn_reset.clicked.connect(_on_reset)
    mask_btn_setup.clicked.connect(_on_mask_setup)
    mask_btn_render.clicked.connect(_on_mask_render)
    mask_btn_anim.clicked.connect(_on_mask_anim)
    mask_btn_reset.clicked.connect(_on_mask_reset)

    _load_ui()


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