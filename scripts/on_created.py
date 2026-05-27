"""Depth Map Renderer (gero::depth_map_renderer) — HDA OnCreated Script.
=======================================================================
Runs when the HDA node is first placed in a network.  Delegates to the
HDA PythonModule (which handles importing the embedded core) so there is
a single bootstrap path.

NOTE: This section is executed as a script with ``kwargs`` in scope, so it
calls hou.phm() directly rather than defining a function that nothing calls.
"""

import sys

import hou

_node = kwargs.get("node")  # noqa: F821 — provided by the OnCreated event
if _node is not None:
    try:
        _node.hdaModule().init_node(_node)
    except Exception as _e:
        print(f"[Limbic Depth Map] OnCreated error: {_e}", file=sys.stderr)
