#!/usr/bin/env python3
"""Build script for the Depth Map Renderer HDA.

Houdini .hda files use a proprietary binary format that can only be
created through the Houdini API (hou module). This script generates a
Houdini Python script that, when run inside Houdini (Python console or
shelf), creates the full HDA with parameters, network contents, and
Python modules.

Usage:
    # Generate the build script (run outside Houdini):
    python3 build.py

    # Then inside Houdini's Python console:
    exec(open("/path/to/HDAs/build_hda.py").read())

    # Or install the pre-built HDA directly:
    hou.hda.installFile("/path/to/HDAs/gero_depth_map_renderer.hda")
"""

from __future__ import annotations

import os, sys, json
from pathlib import Path
from datetime import datetime, timezone

SRC_ROOT = Path(__file__).parent.resolve()

HDA_METADATA = {
    "name":            "depth_map_renderer",
    "namespace":       "gero",
    "table":           "Cop2",
    "label":           "Depth Map Renderer",
    "category":        "Limbicnation",
    "version":         (2, 1, 0),
    "min_houdini":     (18, 0),
    "python":          True,
    "python_module":   "scripts.python_module",
    "description":     (
        "Limbic Depth Map Renderer — one-click depth map pipeline. "
        "Mirrors the Blender Depth Map Generator workflow: Z-pass → Range → "
        "Contrast → Grayscale → PNG/TIFF/EXR output. "
        "Supports COP2 (H18-H20) and new COP (H21+)."
    ),
    "creator":         "Limbicnation",
    "license":         "Apache 2.0",
    "external_data":   False,
}

H21_COP_NODES = {
    "source":      {"type": "file",      "name": "DM_Source",      "label": "Z-Depth Source"},
    "range":       {"type": "remap",     "name": "DM_RangeMap",    "label": "Depth Range Mapper"},
    "log":         {"type": "function",  "name": "DM_LOG",         "label": "Log Normalize"},
    "brightness":  {"type": "bright",    "name": "DM_Brightness",  "label": "Brightness"},
    "contrast":    {"type": "contrast",  "name": "DM_Contrast",    "label": "Depth Contrast"},
    "scale":       {"type": "function",  "name": "DM_Scale",       "label": "Depth Scale"},
    "invert":      {"type": "invert",    "name": "DM_Invert",      "label": "Depth Invert"},
    "grayscale":   {"type": "mono",      "name": "DM_Grayscale",   "label": "Grayscale Output"},
    "file_output": {"type": "rop_image", "name": "DM_FileOut",     "label": "Depth File Output"},
    "viewer":      {"type": "output",    "name": "DM_Viewer",      "label": "Depth Viewer"},
    "m_source":    {"type": "file",      "name": "DM_MSource",     "label": "Mask Source"},
    "m_idtomask":  {"type": "idtomask",  "name": "DM_MIdToMask",   "label": "ID to Mask"},
    "m_grayscale": {"type": "mono",      "name": "DM_MGrayscale",  "label": "Mask Grayscale"},
    "m_rgba":      {"type": "monotorgba","name": "DM_MConvertRGBA","label": "Mask Mono→RGBA"},
    "m_fileout":   {"type": "rop_image", "name": "DM_MaskFileOut", "label": "Mask File Output"},
    "m_viewer":    {"type": "output",    "name": "DM_MaskViewer",  "label": "Mask Viewer"},
}

COP2_COMPAT_NODES = {
    "source":      {"type": "cop2::deep",        "name": "DM_Source",    "label": "Z-Depth Source"},
    "range":       {"type": "cop2::range",        "name": "DM_RangeMap",  "label": "Depth Range Mapper"},
    "log":         {"type": "cop2::ln",           "name": "DM_LOG",       "label": "Log Normalize"},
    "brightness":  {"type": "cop2::brightness",   "name": "DM_Brightness","label": "Brightness"},
    "contrast":    {"type": "cop2::contrast",     "name": "DM_Contrast",  "label": "Depth Contrast"},
    "scale":       {"type": "cop2::multiply",     "name": "DM_Scale",     "label": "Depth Scale"},
    "grayscale":   {"type": "cop2::convert",      "name": "DM_Grayscale", "label": "Grayscale Output"},
    "file_output": {"type": "cop2::file_output",  "name": "DM_FileOut",   "label": "Depth File Output"},
    "viewer":      {"type": "cop2::viewer",       "name": "DM_Viewer",    "label": "Depth Viewer"},
}


def _generate_houdini_build_script(output_path: Path) -> Path:
    hda_name = f'{HDA_METADATA["namespace"]}::{HDA_METADATA["name"]}'
    hda_label = HDA_METADATA["label"]
    src_root = str(SRC_ROOT)

    scripts = {
        "PythonModule": (SRC_ROOT / "scripts" / "python_module.py").read_text(),
        "OnCreated":    (SRC_ROOT / "scripts" / "on_created.py").read_text(),
        "limbic_depth_map_core": (SRC_ROOT / "scripts" / "limbic_depth_map_core.py").read_text(),
        "settings_model": (SRC_ROOT / "scripts" / "settings_model.py").read_text(),
        "depth_map_panel": (SRC_ROOT / "python_panels" / "depth_map_panel.py").read_text(),
    }

    scripts_json = json.dumps(scripts, indent=2)

    cop_nodes_json = json.dumps(H21_COP_NODES, indent=2)

    hda_file = str(output_path.parent / f"{HDA_METADATA['namespace']}_{HDA_METADATA['name']}.hda")

    script = f'''#!/usr/bin/env python3
"""Auto-generated HDA build script — run inside Houdini.

Creates the {hda_name} HDA with full network contents and Python modules.
Generated by build.py on {datetime.now(timezone.utc).isoformat()}.
"""

import hou
import json

HDA_NAME = "{hda_name}"
HDA_LABEL = "{hda_label}"
HDA_FILE = "{hda_file}"
SRC_ROOT = "{src_root}"

COP_NODES = {cop_nodes_json}
SCRIPTS = {scripts_json}


def build_hda():
    img = hou.node("/img")
    if img is None:
        img = hou.node("/obj").createNode("img", "img")

    # Remove existing build instances
    for n in list(img.children()):
        try:
            if "gero" in n.type().name():
                n.destroy()
        except Exception:
            pass

    # Create base cop2net — Cop2 context for proper table registration
    subnet = img.createNode("cop2net", "_dmr_build_base")

    # Convert to digital asset (registers in Cop2 table)
    hda_def = subnet.createDigitalAsset(
        name=HDA_NAME,
        hda_file_name="Embedded",
        description=HDA_LABEL,
        min_num_inputs=0,
        max_num_inputs=0,
    )

    # Allow editing
    subnet.allowEditingOfContents()

    # Clear default contents
    for child in list(subnet.children()):
        child.destroy()

    # ── Build Parameter Interface ──
    parm_group = hou.ParmTemplateGroup()

    p = hou.StringParmTemplate("dm_settings", "Internal Settings", 1, default_value=[""])
    p.hide(True)
    parm_group.append(p)

    p = hou.StringParmTemplate("cop_backend", "COP Backend", 1, default_value=[""])
    p.hide(True)
    parm_group.append(p)

    depth_folder = hou.FolderParmTemplate("depth_folder", "Depth Settings")
    depth_folder.addParmTemplate(hou.ToggleParmTemplate("usecustomrange", "Custom Near/Far Range", default_value=False))
    depth_folder.addParmTemplate(hou.FloatParmTemplate("near", "Near", 1, default_value=[0.1]))
    depth_folder.addParmTemplate(hou.FloatParmTemplate("far", "Far", 1, default_value=[1000.0]))
    depth_folder.addParmTemplate(hou.StringParmTemplate("normalization", "Normalization", 1,
        default_value=["LINEAR"], menu_items=["LINEAR", "LOGARITHMIC", "RAW"],
        menu_labels=["LINEAR", "LOGARITHMIC", "RAW"]))
    depth_folder.addParmTemplate(hou.FloatParmTemplate("scalefactor", "Scale Factor", 1, default_value=[1.0]))
    depth_folder.addParmTemplate(hou.ToggleParmTemplate("invert", "Invert", default_value=True))
    depth_folder.addParmTemplate(hou.FloatParmTemplate("contrast", "Contrast", 1, default_value=[0.2]))
    depth_folder.addParmTemplate(hou.FloatParmTemplate("brightness", "Brightness", 1, default_value=[0.0]))
    depth_folder.addParmTemplate(hou.StringParmTemplate("outputpath", "Output Path", 1, default_value=[""]))
    depth_folder.addParmTemplate(hou.StringParmTemplate("format", "Format", 1,
        default_value=["PNG"], menu_items=["PNG", "TIFF", "EXR"],
        menu_labels=["PNG", "TIFF", "EXR"]))
    depth_folder.addParmTemplate(hou.StringParmTemplate("bitdepth", "Bit Depth", 1,
        default_value=["16"], menu_items=["8", "16"], menu_labels=["8", "16"]))
    depth_folder.addParmTemplate(hou.ToggleParmTemplate("preview", "Preview", default_value=False))
    parm_group.append(depth_folder)

    anim_folder = hou.FolderParmTemplate("anim_folder", "Animation")
    anim_folder.addParmTemplate(hou.ToggleParmTemplate("animation", "Animation", default_value=False))
    anim_folder.addParmTemplate(hou.ToggleParmTemplate("usescenerange", "Use Scene Range", default_value=True))
    anim_folder.addParmTemplate(hou.IntParmTemplate("framestart", "Frame Start", 1, default_value=[1]))
    anim_folder.addParmTemplate(hou.IntParmTemplate("frameend", "Frame End", 1, default_value=[250]))
    parm_group.append(anim_folder)

    mask_folder = hou.FolderParmTemplate("mask_folder", "Mask Settings")
    mask_folder.addParmTemplate(hou.ToggleParmTemplate("maskenabled", "Mask Enabled", default_value=False))
    mask_folder.addParmTemplate(hou.StringParmTemplate("masksource", "Mask Source", 1,
        default_value=["OBJECT_INDEX"], menu_items=["OBJECT_INDEX", "CRYPTOMATTE"],
        menu_labels=["OBJECT_INDEX", "CRYPTOMATTE"]))
    mask_folder.addParmTemplate(hou.IntParmTemplate("maskindex", "Object Index", 1, default_value=[1]))
    mask_folder.addParmTemplate(hou.StringParmTemplate("maskformat", "Mask Format", 1,
        default_value=["GRAYSCALE"], menu_items=["GRAYSCALE", "RGBA"],
        menu_labels=["GRAYSCALE", "RGBA"]))
    mask_folder.addParmTemplate(hou.StringParmTemplate("maskoutputpath", "Mask Output Path", 1, default_value=[""]))
    parm_group.append(mask_folder)

    hda_def.setParmTemplateGroup(parm_group)

    # ── Build Network Contents ──
    copnet = subnet.createNode("copnet", "depth_map_cop")

    nodes = {{}}
    for key, info in COP_NODES.items():
        nodes[key] = copnet.createNode(info["type"], info["name"])

    # Wire depth pipeline: source -> invert -> range -> brightness -> contrast -> scale -> grayscale -> fileout -> viewer
    nodes["invert"].setInput(0, nodes["source"])
    nodes["range"].setInput(0, nodes["invert"])
    nodes["brightness"].setInput(0, nodes["range"])
    nodes["contrast"].setInput(0, nodes["brightness"])
    nodes["scale"].setInput(0, nodes["contrast"])
    nodes["grayscale"].setInput(0, nodes["scale"])
    nodes["file_output"].setInput(0, nodes["grayscale"])
    nodes["viewer"].setInput(0, nodes["grayscale"])

    # Wire mask pipeline: m_source -> m_idtomask -> m_grayscale / m_rgba -> m_fileout -> m_viewer
    nodes["m_idtomask"].setInput(0, nodes["m_source"])
    nodes["m_grayscale"].setInput(0, nodes["m_idtomask"])
    nodes["m_rgba"].setInput(0, nodes["m_idtomask"])
    nodes["m_fileout"].setInput(0, nodes["m_grayscale"])
    nodes["m_viewer"].setInput(0, nodes["m_grayscale"])

    copnet.layoutChildren()

    # ── Add Python Sections ──
    for section_name, content in SCRIPTS.items():
        hda_def.addSection(section_name, content)

    # ── Save to File ──
    hda_def.updateFromNode(subnet)
    hda_def.copyToHDAFile(HDA_FILE)

    # Clean up build node
    subnet.destroy()

    # Install from file
    hou.hda.installFile(HDA_FILE)

    print(f"HDA built and installed: {{HDA_FILE}}")

    # Verify
    test = img.createNode(HDA_NAME, "_dmr_verify")
    assert test.parm("normalization") is not None, "Parameters missing!"
    test.destroy()

    print("Verification passed!")


build_hda()
'''

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(script)
    return output_path


def main():
    import argparse

    ap = argparse.ArgumentParser(description="Build Limbic Depth Map Renderer HDA")
    ap.add_argument(
        "--out",
        type=Path,
        default=SRC_ROOT / "HDAs" / "build_hda.py",
        help="Output build script path (default: ./HDAs/build_hda.py)",
    )
    ap.add_argument(
        "--install",
        action="store_true",
        help="Also copy pre-built .hda to ~/houdiniXX.X/otls/",
    )
    args = ap.parse_args()

    out = args.out.resolve()

    print(f"Generating Houdini build script: {out}")
    path = _generate_houdini_build_script(out)

    size_kb = path.stat().st_size / 1024
    print(f"  → {path}  ({size_kb:.1f} KB)")

    print(f"\nTo build the HDA, run inside Houdini's Python console:")
    print(f'  exec(open("{path}").read())')

    prebuilt = path.parent / f"{HDA_METADATA['namespace']}_{HDA_METADATA['name']}.hda"
    if prebuilt.exists():
        print(f"\nOr install the pre-built HDA directly:")
        print(f'  hou.hda.installFile("{prebuilt}")')

    if args.install:
        import shutil
        hfs = os.environ.get("HFS", "")
        if hfs:
            hver = Path(hfs).name.lower()
            if not hver.startswith("houdini"):
                hver = "houdini21.0"
        else:
            hver = "houdini21.0"
        if prebuilt.exists():
            hda_dest = Path.home() / hver / "otls" / prebuilt.name
            hda_dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(prebuilt, hda_dest)
            print(f"\n   Installed → {hda_dest}")


if __name__ == "__main__":
    main()
