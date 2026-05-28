"""Depth Map Renderer (gero::depth_map_renderer) — HDA PythonModule.
==================================================================
Thin wrapper that imports from the shared core module.
Embedded in the gero::depth_map_renderer HDA.

This module enables direct HDA parameter-driven workflows
(OnCreated, shelf tools, scripting) without requiring the
Python Panel UI.

Dual COP backend: COP2 (H18-H20) and Copernicus / new COP (H21+),
auto-detected from the Houdini version at runtime.
"""

import sys
import os
import tempfile

HDA_TYPE_NAME = "gero::depth_map_renderer"

# Modules the HDA depends on (core imports settings_model).
_EMBEDDED_MODULES = ("settings_model", "limbic_depth_map_core")

# Private temp dir holding the extracted module sources; created once per
# session via mkdtemp (0700, unpredictable name — no symlink race).
_CACHE_DIR = None


def _bootstrap_core():
    """Make the shared core modules importable.

    Two resolution paths so the asset works for both developers and end users:

    1. **Dev mode** — if ``$LIMBIC_DEPTH_MAP/scripts`` exists, import from disk
       so edits are picked up live without rebuilding the HDA.
    2. **Self-contained** — otherwise extract the modules embedded in this
       HDA's own sections to a temp dir and import them from there.  End users
       hit this path: no env var and no external files, the asset just works.
    """
    global _CACHE_DIR
    env = os.environ.get("LIMBIC_DEPTH_MAP", "")
    disk = os.path.join(env, "scripts") if env else ""
    if disk and os.path.exists(os.path.join(disk, "limbic_depth_map_core.py")):
        if disk not in sys.path:
            sys.path.insert(0, disk)
        return

    import hou
    nt = hou.nodeType(hou.objNodeTypeCategory(), HDA_TYPE_NAME)
    definition = nt.definition() if nt else None
    if definition is None:
        return  # fall through to a normal import attempt below

    if _CACHE_DIR is None:
        _CACHE_DIR = tempfile.mkdtemp(prefix="limbic_dmr_")
    sections = definition.sections()
    for modname in _EMBEDDED_MODULES:
        sec = sections.get(modname)
        if sec is None:
            continue
        try:
            # Always rewrite so an updated HDA replaces stale cached code.
            with open(os.path.join(_CACHE_DIR, modname + ".py"), "w",
                      encoding="utf-8") as fh:
                fh.write(sec.contents())
        except OSError:
            pass
        sys.modules.pop(modname, None)  # drop any stale/partial import
    if _CACHE_DIR not in sys.path:
        sys.path.insert(0, _CACHE_DIR)


_bootstrap_core()

from limbic_depth_map_core import (  # noqa: E402
    NODE_PREFIX,
    HDA_CATEGORY,
    DEFAULT_SETTINGS,
    backend,
    reset_backend_cache,
    load_settings,
    save_settings,
    add_dm_settings_parm,
    has_explicit_parms,
    dm_children,
    output_dir,
    filename,
    frame_range,
    notify,
    resolve_script_path,
    build_depth_network,
    build_mask_network,
    setup_depth,
    render_depth,
    reset_depth,
)


# ─────────────────────────────────────────────────────────────────────────────
# HDA Button Callbacks
# ─────────────────────────────────────────────────────────────────────────────
# These wrap core functions for Houdini ButtonParmTemplate script_callback.
# Houdini passes kwargs = {'node': hou.Node, 'parm': hou.Parm, ...}

def on_setup(kwargs):
    return setup_depth(kwargs['node'])


def on_render(kwargs):
    return render_depth(kwargs['node'])


def on_render_animation(kwargs):
    return render_depth(kwargs['node'], animation=True)


def on_setup_mask(kwargs):
    return setup_depth(kwargs['node'], mask_only=True)


def on_reset(kwargs):
    return reset_depth(kwargs['node'])


# ─────────────────────────────────────────────────────────────────────────────
# OnCreated initialisation
# ─────────────────────────────────────────────────────────────────────────────

def init_node(node):
    """Initialise a freshly created HDA instance.

    Tags the detected backend, ensures the settings parm exists, and builds
    the depth network once so the Near/Far/Brightness/Contrast/Scale sliders
    are immediately live (wired via ch() expressions) without the user having
    to click Setup first.
    """
    add_dm_settings_parm(node)
    p = node.parm("cop_backend")
    if p is not None:
        p.set(backend())
    # Build the initial network only if it hasn't been set up yet (avoids
    # clobbering an existing network on copy/paste or re-init).
    if not load_settings(node).get("setup_complete", False):
        setup_depth(node)
