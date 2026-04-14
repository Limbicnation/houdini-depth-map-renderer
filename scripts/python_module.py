"""Limbic Depth Map Renderer — HDA PythonModule.
===============================================
Thin wrapper that imports from the shared core module.
Embedded in the limbic_depth_map_renderer HDA.

This module enables direct HDA parameter-driven workflows
(OnCreated, shelf tools, scripting) without requiring the
Python Panel UI.

Dual COP backend: cop2 (H18-H20) / cop (H21+).
"""

import sys
import os

_core_dir = os.path.dirname(os.path.abspath(__file__))
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
