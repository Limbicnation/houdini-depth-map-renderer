"""Depth Map Renderer (gero::depth_map_renderer) — HDA PythonModule.
==================================================================
Thin wrapper that imports from the shared core module.
Embedded in the gero::depth_map_renderer HDA.

This module enables direct HDA parameter-driven workflows
(OnCreated, shelf tools, scripting) without requiring the
Python Panel UI.

COP2 backend only (H18+).  COP (H21+) backend is gated behind
_ENABLE_COP_BACKEND and not yet active.
"""

import sys
import os

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
        _core_dir = os.path.join(os.getcwd(), "scripts")

if _core_dir not in sys.path:
    sys.path.insert(0, _core_dir)

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
