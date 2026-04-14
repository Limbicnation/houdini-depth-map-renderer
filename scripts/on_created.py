"""Limbic Depth Map Renderer — HDA OnCreated Script.
====================================================
Runs when the HDA node is first placed in a network.
Sets up the dm_settings parm, detects COP backend, and
initialises default values.
"""

import os
import sys

import hou

# Locate core module — use _find_core_dir from the same directory or
# fall back to __file__-based resolution.
try:
    _core_dir = os.path.dirname(os.path.abspath(__file__))
    _core_file = os.path.join(_core_dir, "limbic_depth_map_core.py")
    if not os.path.exists(_core_file):
        raise NameError
except NameError:
    # __file__ not defined (e.g., embedded in HDA)
    _env = os.environ.get("LIMBIC_DEPTH_MAP", "")
    if _env and os.path.exists(os.path.join(_env, "scripts", "limbic_depth_map_core.py")):
        _core_dir = os.path.join(_env, "scripts")
    else:
        try:
            _core_dir = os.path.dirname(os.path.abspath(
                hou.expandString("$HH/scripts/limbic_depth_map_core.py")))
        except Exception:
            _core_dir = os.path.join(os.getcwd(), "scripts")

if _core_dir not in sys.path:
    sys.path.insert(0, _core_dir)

from limbic_depth_map_core import (  # noqa: E402
    add_dm_settings_parm,
    DEFAULT_SETTINGS,
    backend,
    has_explicit_parms,
)


def onCreate(kwargs):
    node = kwargs.get("node")
    if node is None:
        return

    try:
        add_dm_settings_parm(node)
        _init_settings(node)
        _detect_backend(node)
    except Exception as e:
        print(f"[Limbic Depth Map] OnCreated error: {e}", file=sys.stderr)


def _init_settings(node):
    p = node.parm("dm_settings")
    if p is not None and not p.eval():
        import json
        p.set(json.dumps({
            "setup_complete": False,
            "mask_setup_complete": False,
        }))


def _detect_backend(node):
    be = backend()
    p = node.parm("cop_backend")
    if p is not None:
        p.set(be)
