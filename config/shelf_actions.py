"""Limbic Depth Map Renderer — Shelf Actions.
===============================================
Register shelf tools that call the depth map operators.
Copy to:  ~/houdini18.0/toolbar/limbic_depth_map.py
"""

import os
import sys

_limbic_path = os.environ.get("LIMBIC_DEPTH_MAP", "")
if _limbic_path not in sys.path:
    sys.path.insert(0, _limbic_path)

import hou

try:
    from python_panels.depth_map_panel import OpSetup, OpRender, OpReset
except ImportError as e:
    hou.ui.displayMessage(
        f"[Limbic Depth Map] Could not import panel:\n{e}",
        title="Import Error",
        severity=hou.severityType.Error,
    )
    raise


def _active_cop_node():
    pane = hou.ui.curPaneTab()
    if pane is None:
        return None
    if pane.type() == hou.paneTabType.CompositorViewer:
        return pane.currentNode()
    cop_cats = set()
    for cat_name in ("Cop2", "Cop"):
        cat = hou.nodeTypeCategories().get(cat_name)
        if cat is not None:
            cop_cats.add(cat)
    for n in hou.selectedNodes():
        if n.type().category() in cop_cats:
            return n
    return None


def limbic_setup():
    node = _active_cop_node()
    if node is None:
        hou.ui.displayMessage(
            "Select a COP node first.", title="Depth Map")
        return
    try:
        ok = OpSetup.execute(node)
        if ok:
            hou.ui.setStatusMessage(
                "Limbic Depth Map: network created",
                severity=hou.severityType.Important)
    except Exception as e:
        hou.ui.displayMessage(f"Setup failed:\n{e}", title="Error",
                              severity=hou.severityType.Error)


def limbic_render():
    node = _active_cop_node()
    if node is None:
        hou.ui.displayMessage("Select a COP network node first.")
        return
    try:
        OpRender.execute(node, animation=False)
    except Exception as e:
        hou.ui.displayMessage(f"Render failed:\n{e}", title="Error",
                              severity=hou.severityType.Error)


def limbic_render_animation():
    node = _active_cop_node()
    if node is None:
        hou.ui.displayMessage("Select a COP network node first.")
        return
    try:
        OpRender.execute(node, animation=True)
    except Exception as e:
        hou.ui.displayMessage(f"Render failed:\n{e}", title="Error",
                              severity=hou.severityType.Error)


def limbic_reset():
    node = _active_cop_node()
    if node is None:
        hou.ui.displayMessage("Select a COP network node first.")
        return
    try:
        OpReset.execute(node)
    except Exception as e:
        hou.ui.displayMessage(f"Reset failed:\n{e}", title="Error",
                              severity=hou.severityType.Error)


# ── Shelf registration ──────────────────────────────────────────────────────

try:
    shelf = hou.shelves.fetch("Limbic", create=True)
except Exception:
    shelf = None

if shelf is not None:
    def _add_tool(name, label, icon_path, callback, help_text):
        try:
            existing = next((t for t in shelf.tools() if t.name() == name), None)
            if existing:
                shelf.removeTool(existing)
            tool = hou.shelves.createTool(
                "Python/source", name,
                label=label,
                icon=icon_path,
                help=help_text,
                callback=callback,
            )
            shelf.addTool(tool)
        except Exception as e:
            print(f"[shelf] could not add {name}: {e}")

    ICON = "$LIMBIC_DEPTH_MAP/icons"

    _add_tool("limbic_dm_setup",  "⚙ Setup",
              f"{ICON}/depth_setup.svg", limbic_setup,
              "Build the depth map network")
    _add_tool("limbic_dm_render", "▶ Render",
              f"{ICON}/depth_render.svg", limbic_render,
              "Render single-frame depth map")
    _add_tool("limbic_dm_anim",   "▶▶ Anim",
              f"{ICON}/depth_anim.svg", limbic_render_animation,
              "Render depth map animation")
    _add_tool("limbic_dm_reset",  "✕ Reset",
              f"{ICON}/depth_reset.svg", limbic_reset,
              "Remove depth map network")
