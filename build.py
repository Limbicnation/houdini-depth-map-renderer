#!/usr/bin/env python3
"""Build script — generates the compiled .otlc HDA file.

The .otlc is a tar archive containing:
    - Houdini archive (.hda) format files
    - The embedded Python module (depth_map_panel.py)
    - Node definition XML

Usage:
    python3 build.py                          # default output: ./HDAs/
    python3 build.py --out ./HDAs/my.otlc     # custom output path
    python3 build.py --install                # build and install to ~/houdini18.0/otls/
"""

from __future__ import annotations

import os, sys, json, argparse, tarfile, io
from pathlib import Path
from datetime import datetime, timezone

SRC_ROOT = Path(__file__).parent.resolve()

# ── HDA archive manifest ─────────────────────────────────────────────────────

HDA_METADATA = {
    "name":            "limbic_depth_map_renderer",
    "table":           "Driver/cop",
    "label":           "Depth Map Renderer",
    "category":        "Limic",
    "version":         (2, 0, 0),
    "min_houdini":     (18, 0),
    "python":          True,
    "python_module":   "python_panels.depth_map_panel",
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

# Nodes created at runtime (semantic keys — actual types depend on Houdini version)
COP_NODES = [
    {"id": 1, "key": "source",      "name": "DM_Source",    "label": "Z-Depth Source"},
    {"id": 2, "key": "range",       "name": "DM_RangeMap",  "label": "Depth Range Mapper"},
    {"id": 3, "key": "contrast",    "name": "DM_Contrast",  "label": "Depth Contrast"},
    {"id": 4, "key": "grayscale",   "name": "DM_Grayscale", "label": "Grayscale Output"},
    {"id": 5, "key": "file_output", "name": "DM_FileOut",   "label": "Depth File Output"},
]


# ── Build functions ─────────────────────────────────────────────────────────

def _hda_archive(otlc_path: Path, src_root: Path):
    """Generate a minimal .otlc (tar) archive.

    Real Houdini .otlc files contain compiled C++ HDAs.
    For a Python-only plugin this script creates a *scaffold* .otlc that:
      1. Registers the Python Panel interface
      2. Sets up the COP HDA type
      3. Embeds the Python source for runtime network construction

    Users running this should import the resulting .otlc in Houdini via:
        File → Import → HDA File...
    """

    members = []

    # 1. Contents manifest
    manifest = {
        "build_date":    datetime.now(timezone.utc).isoformat(),
        "build_host":    os.environ.get("HOSTNAME", "unknown"),
        "metadata":      HDA_METADATA,
        "cop_nodes":     COP_NODES,
        "python_files": [],
    }

    # 2. Embed python_panels/depth_map_panel.py
    panel_src = src_root / "python_panels" / "depth_map_panel.py"
    if panel_src.exists():
        manifest["python_files"].append(str(panel_src.relative_to(src_root)))
        members.append(("python_panels/depth_map_panel.py", panel_src.read_bytes()))

    # 3. Embed installer
    installer_src = src_root / "installer" / "install.py"
    if installer_src.exists():
        manifest["python_files"].append(str(installer_src.relative_to(src_root)))
        members.append(("installer/install.py", installer_src.read_bytes()))

    # 4. Embed shelf actions
    shelf_src = src_root / "config" / "shelf_actions.py"
    if shelf_src.exists():
        manifest["python_files"].append(str(shelf_src.relative_to(src_root)))
        members.append(("config/shelf_actions.py", shelf_src.read_bytes()))

    # 5. Write manifest
    manifest_json = json.dumps(manifest, indent=2).encode("utf-8")
    members.append(("manifest.json", manifest_json))

    # 6. Write README
    readme_src = src_root / "README.md"
    if readme_src.exists():
        members.append(("README.md", readme_src.read_bytes()))

    # 7. Write AGENTS.md
    agents_src = src_root / "AGENTS.md"
    if agents_src.exists():
        members.append(("AGENTS.md", agents_src.read_bytes()))

    # 8. Embed NodeDefinition XML so Houdini registers the operator correctly
    node_def_xml = _generate_node_def().encode("utf-8")
    members.append(("NodeDefinition.xml", node_def_xml))

    # 9. Build tar
    otlc_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(otlc_path, "w:xz", preset=6) as tar:
        for name, data in members:
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))

    return otlc_path


def _generate_node_def() -> str:
    """Return a NodeDefinition XML string for the HDA.

    This is what Houdini parses when importing the .otlc to understand
    the operator's parameters, type, and Python script interface.
    """
    return f"""\
<?xml version="1.0" encoding="UTF-8"?>
<source type="copnet">
<name>limbic_depth_map_renderer</name>
<label>Depth Map Renderer</label>
<table>Driver/cop</table>
<parmlist>
  <parm name="dm_settings" stype="string" default="" len="1"
        label="Internal Settings" visible="0"/>
</parmlist>
<python_callbacks>
  <callback oncreate="python_panels.depth_map_panel.register_operators"/>
  <callback onview="python_panels.depth_map_panel.register_operators"/>
</python_callbacks>
<help>\
Limbic Depth Map Renderer — one-click depth map pipeline.
See README.md for usage instructions.
</help>
</source>
"""


# ── CLI ─────────────────────────────────────────────────────────────────────

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
        help="Also copy to ~/houdini18.0/otls/ after building",
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

    print("\n✅ HDA scaffold built.")
    print("   Next: open Houdini → File → Import → HDA File… → select this .otlc")

    if args.install:
        import shutil
        # Detect Houdini version from $HFS (same logic as installer/install.py)
        hfs = os.environ.get("HFS", "")
        if hfs:
            hver = Path(hfs).name.lower()
            if not hver.startswith("houdini"):
                hver = "houdini18.0"  # fallback if HFS path is unexpected
        else:
            hver = "houdini18.0"  # fallback when $HFS not set
        hda_dest = Path.home() / hver / "otls" / path.name
        hda_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, hda_dest)
        print(f"\n   Also installed → {hda_dest}")


if __name__ == "__main__":
    main()
