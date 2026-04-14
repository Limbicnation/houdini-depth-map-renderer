#!/usr/bin/env python3
"""Build script — generates the compiled .otlc HDA file.

The .otlc is a tar archive containing:
    - Houdini archive (.hda) format files
    - The shared core module (limbic_depth_map_core.py)
    - The HDA PythonModule wrapper (python_module.py)
    - The OnCreated callback (on_created.py)
    - The Python Panel UI (depth_map_panel.py)
    - Node definition XML with explicit parameter interface

Usage:
    python3 build.py                          # default output: ./HDAs/
    python3 build.py --out ./HDAs/my.otlc     # custom output path
    python3 build.py --install                # build and install to ~/houdiniXX.X/otls/
"""

from __future__ import annotations

import os, sys, json, argparse, tarfile, io
from pathlib import Path
from datetime import datetime, timezone

SRC_ROOT = Path(__file__).parent.resolve()

HDA_METADATA = {
    "name":            "limbic_depth_map_renderer",
    "table":           "Driver/cop",
    "label":           "Depth Map Renderer",
    "category":        "Limic",
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

COP_NODES = [
    {"id": 1, "key": "source",      "name": "DM_Source",    "label": "Z-Depth Source"},
    {"id": 2, "key": "range",       "name": "DM_RangeMap",  "label": "Depth Range Mapper"},
    {"id": 3, "key": "log",         "name": "DM_LOG",       "label": "Log Normalize"},
    {"id": 4, "key": "brightness",  "name": "DM_Brightness","label": "Brightness"},
    {"id": 5, "key": "contrast",    "name": "DM_Contrast",  "label": "Depth Contrast"},
    {"id": 6, "key": "scale",       "name": "DM_Scale",     "label": "Depth Scale"},
    {"id": 7, "key": "grayscale",   "name": "DM_Grayscale", "label": "Grayscale Output"},
    {"id": 8, "key": "file_output", "name": "DM_FileOut",   "label": "Depth File Output"},
]


def _hda_archive(otlc_path: Path, src_root: Path):
    members = []

    manifest = {
        "build_date":    datetime.now(timezone.utc).isoformat(),
        "build_host":    os.environ.get("HOSTNAME", "unknown"),
        "metadata":      HDA_METADATA,
        "cop_nodes":     COP_NODES,
        "python_files": [],
    }

    python_files = [
        ("scripts/limbic_depth_map_core.py", src_root / "scripts" / "limbic_depth_map_core.py"),
        ("scripts/python_module.py",         src_root / "scripts" / "python_module.py"),
        ("scripts/on_created.py",            src_root / "scripts" / "on_created.py"),
        ("python_panels/depth_map_panel.py", src_root / "python_panels" / "depth_map_panel.py"),
        ("config/shelf_actions.py",          src_root / "config" / "shelf_actions.py"),
    ]

    for arc_name, src_path in python_files:
        if src_path.exists():
            manifest["python_files"].append(arc_name)
            members.append((arc_name, src_path.read_bytes()))

    installer_src = src_root / "installer" / "install.py"
    if installer_src.exists():
        manifest["python_files"].append("installer/install.py")
        members.append(("installer/install.py", installer_src.read_bytes()))

    manifest_json = json.dumps(manifest, indent=2).encode("utf-8")
    members.append(("manifest.json", manifest_json))

    readme_src = src_root / "README.md"
    if readme_src.exists():
        members.append(("README.md", readme_src.read_bytes()))

    node_def_xml = _generate_node_def().encode("utf-8")
    members.append(("NodeDefinition.xml", node_def_xml))

    otlc_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(otlc_path, "w:xz", preset=6) as tar:
        for name, data in members:
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))

    return otlc_path


def _generate_node_def() -> str:
    sys.path.insert(0, str(SRC_ROOT / "scripts"))
    from limbic_depth_map_core import PARM_DEFS

    parm_lines = []
    parm_lines.append(
        '  <parm name="dm_settings" stype="string" default="" len="1" '
        'label="Internal Settings" visible="0"/>'
    )
    parm_lines.append(
        '  <parm name="cop_backend" stype="string" default="" len="1" '
        'label="COP Backend" visible="0"/>'
    )

    for parm_name, label, ptype, default, menu_items in PARM_DEFS:
        if ptype == "toggle":
            parm_lines.append(
                f'  <parm name="{parm_name}" stype="int" default="{default}" '
                f'len="1" label="{label}"/>'
            )
        elif ptype == "float":
            parm_lines.append(
                f'  <parm name="{parm_name}" stype="float" default="{default}" '
                f'len="1" label="{label}"/>'
            )
        elif ptype == "int":
            parm_lines.append(
                f'  <parm name="{parm_name}" stype="int" default="{default}" '
                f'len="1" label="{label}"/>'
            )
        elif ptype == "string":
            if menu_items:
                menu_str = "\\n".join(
                    f"{item}\\n{item}" for item in menu_items
                )
                parm_lines.append(
                    f'  <parm name="{parm_name}" stype="string" '
                    f'default="{default}" len="1" label="{label}" '
                    f'menu="{{menu_str}}"/>'
                )
            else:
                parm_lines.append(
                    f'  <parm name="{parm_name}" stype="string" '
                    f'default="{default}" len="1" label="{label}"/>'
                )

    parmlist = "\n".join(parm_lines)

    return f"""\
<?xml version="1.0" encoding="UTF-8"?>
<source type="copnet">
<name>limbic_depth_map_renderer</name>
<label>Depth Map Renderer</label>
<table>Driver/cop</table>
<parmlist>
{parmlist}
</parmlist>
<python_callbacks>
  <callback oncreate="scripts.on_created.onCreate"/>
</python_callbacks>
<help>\
Limbic Depth Map Renderer — one-click depth map pipeline.
See README.md for usage instructions.
</help>
</source>
"""


def main():
    ap = argparse.ArgumentParser(description="Build Limbic Depth Map Renderer HDA")
    ap.add_argument(
        "--out",
        type=Path,
        default=SRC_ROOT / "HDAs" / "limbic_depth_map_renderer.otlc",
        help="Output .otlc path (default: ./HDAs/limbic_depth_map_renderer.otlc)",
    )
    ap.add_argument(
        "--install",
        action="store_true",
        help="Also copy to ~/houdiniXX.X/otls/ after building",
    )
    ap.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print contents of the generated archive",
    )
    args = ap.parse_args()

    out = args.out.resolve()

    print(f"Building HDA: {out}")
    path = _hda_archive(out, SRC_ROOT)

    size_kb = path.stat().st_size / 1024
    print(f"  → {path}  ({size_kb:.1f} KB)")

    if args.verbose:
        print("\nArchive contents:")
        with tarfile.open(path) as tar:
            for m in tar.getmembers():
                print(f"  {m.name:<50}  {m.size:>8} bytes")

    print("\nHDA built successfully.")
    print("   Next: open Houdini → File → Import → HDA File → select this .otlc")

    if args.install:
        import shutil
        hfs = os.environ.get("HFS", "")
        if hfs:
            hver = Path(hfs).name.lower()
            if not hver.startswith("houdini"):
                hver = "houdini18.0"
        else:
            hver = "houdini18.0"
        hda_dest = Path.home() / hver / "otls" / path.name
        hda_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, hda_dest)
        print(f"\n   Also installed → {hda_dest}")


if __name__ == "__main__":
    main()
