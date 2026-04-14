"""Limbic Depth Map Renderer — HDA OnCreated Script.
=====================================================
Runs when the HDA node is first placed in a network.
Sets up the dm_settings parm, detects COP backend, and
initialises default values.

H21+ note: OpNodeType.inputNames() was removed.  This script
avoids calling it — any node type introspection goes through
_safe_node_type() which catches AttributeError.
"""

import hou
import sys


def onCreate(kwargs):
    node = kwargs.get("node")
    if node is None:
        return

    try:
        _ensure_parms(node)
        _ensure_settings(node)
        _detect_backend(node)
    except Exception as e:
        print(f"[Limbic Depth Map] OnCreated error: {e}", file=sys.stderr)


def _ensure_parms(node):
    if node.parm("dm_settings") is not None:
        return
    try:
        pg = node.parmTemplateGroup()
        pg.addParmTemplate(hou.StringParmTemplate(
            "dm_settings", "", 1,
            default_value='{"setup_complete": false, "mask_setup_complete": false}',
            hide=True))
        node.setParmTemplateGroup(pg)
    except Exception as e:
        print(f"[Limbic Depth Map] Could not add dm_settings parm: {e}",
              file=sys.stderr)


def _ensure_settings(node):
    p = node.parm("dm_settings")
    if p is not None and not p.eval():
        import json
        p.set(json.dumps({
            "setup_complete": False,
            "mask_setup_complete": False,
        }))


def _detect_backend(node):
    try:
        img = hou.node("/img")
        if img is not None:
            child_types = img.childTypeCategory().nodeTypes()
            has_copnet = "copnet" in child_types
            be = "cop" if has_copnet else "cop2"
        else:
            be = "cop" if hou.applicationVersion()[0] >= 21 else "cop2"
    except Exception:
        be = "cop2"

    p = node.parm("cop_backend")
    if p is not None:
        p.set(be)


def _safe_node_type(node_type_name, category_name="Cop"):
    """Get a node type without triggering inputNames() on H21+.

    In H21+ the new COP framework removed OpNodeType.inputNames().
    Any code that iterates inputs/outputs on a COP OpNodeType will
    raise AttributeError.  This helper returns the type object safely
    or None if it doesn't exist.
    """
    try:
        cat = hou.nodeTypeCategories().get(category_name)
        if cat is None:
            return None
        return cat.nodeType(node_type_name)
    except (AttributeError, TypeError):
        return None