#!/usr/bin/env python3
"""Limbic Depth Map Renderer — Houdini Installer.
==================================================
Run from Houdini Textport or any Python 3 interpreter with Houdini
in the path::

    >>> exec(open("/path/to/installer/install.py").read())

What it does:
    1. Copies the HDA (.otlc) → ~/houdini18.0/otls/
    2. Copies python_panels/  → ~/houdini18.0/python_panels/
    3. Copies cop2_filters/   → ~/houdini18.0/cop2_filters/
    4. Copies shelf actions   → ~/houdini18.0/toolbar/ (optional)
    5. Writes a Houdini Package file → ~/houdini18.0/packages/limbic_depth_map.json

After install restart Houdini or run:
    hou.hscript("opscripts -r")   # reload operators
"""

from __future__ import annotations

import os
import sys
import json
import shutil
import platform
import argparse
import textwrap
from pathlib import Path

# ─── Resolve Houdini home ────────────────────────────────────────────────────

def _houdini_home() -> Path:
    if "HFS" in os.environ:
        return Path(os.environ["HFS"])
    # Try common locations
    if platform.system() == "Windows":
        base = Path(os.environ.get("PROGRAMFILES", "C:/Program Files"))
        candidates = list(base.glob("Side Effects Software/Houdini *"))
    elif platform.system() == "Darwin":
        candidates = [Path(f"/Applications/Houdini {v}/Houdini {v}.app/Contents/Resources")
                      for v in ["18.0", "18.5", "19.0", "19.5", "20.0"]]
        for c in candidates:
            if c.exists():
                return c
    else:
        candidates = [Path(f"/opt/hfs{hv}") for hv in ["18.0", "18.5", "19.0", "19.5", "20.0"]]
    for c in candidates:
        if c.exists():
            return c
    raise RuntimeError(
        "Cannot find Houdini installation. Set $HFS or run with --hfs /path/to/houdini"
    )


def _version_folder(hfs: Path) -> str:
    """Return the Houdini version folder name e.g. 'houdini18.0'."""
    # HFS points to the versioned subdirectory on Linux/macOS
    name = hfs.name.lower()
    if name.startswith("houdini"):
        return name   # already a version folder
    # On Windows HFS → "Side Effects Software/Houdini 18.0"
    parts = str(hfs).split("/")
    for p in reversed(parts):
        if p.lower().startswith("houdini"):
            return p.lower().replace(" ", "")
    # Fallback: read from Houdini.env
    return "houdini18.0"


# ─── Package manifest ───────────────────────────────────────────────────────

PACKAGE_JSON = {
    "comment":    "Limbic Depth Map Renderer — https://github.com/limbicnation/houdini-depth-map-renderer",
    "env": [
        {
            "LIMBIC_DEPTH_MAP": "{HFS}/../houdini_depth_map_renderer"
        }
    ],
    "requires":   [],
    "paths": [
        "{HFS}/../houdini_depth_map_renderer/HDAs",
        "{HFS}/../houdini_depth_map_renderer/python_panels",
        "{HFS}/../houdini_depth_map_renderer/cop2_filters",
    ],
}


# ─── Installer class ────────────────────────────────────────────────────────

class Installer:
    def __init__(self, src_root: Path, hfs: Path, dry_run: bool = False, verbose: bool = False):
        self.src       = src_root
        self.hfs       = hfs
        self.hver      = _version_folder(hfs)
        self.dry_run   = dry_run
        self.verbose   = verbose
        self.changes: list[str] = []

    # ── path helpers ────────────────────────────────────────────────────────

    def _dest(self, *parts) -> Path:
        base = self.hfs.parent   # go up from versioned HFS dir
        return base / self.hver / Path(*parts)

    def _cp(self, src_path: Path, dest_dir: Path, rename: str = None):
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / (rename or src_path.name)
        if self.dry_run:
            self.changes.append(f"  [dry-run] cp  {src_path} → {dest}")
            return
        shutil.copy2(src_path, dest)
        self.changes.append(f"  cp  {src_path.name} → {dest.relative_to(dest.parents[1])}")

    # ── copy sections ───────────────────────────────────────────────────────

    def _install_hda(self):
        dest = self._dest("otls")
        for f in sorted((self.src / "HDAs").glob("*.otlc")):
            self._cp(f, dest)
        for f in sorted((self.src / "HDAs").glob("*.hda")):
            self._cp(f, dest)

    def _install_python_panels(self):
        dest = self._dest("python_panels")
        for f in sorted((self.src / "python_panels").glob("*.py")):
            self._cp(f, dest)

    def _install_cop2_filters(self):
        dest = self._dest("cop2_filters")
        for f in sorted((self.src / "cop2_filters").rglob("*")):
            if f.is_file():
                self._cp(f, dest / f.relative_to(self.src / "cop2_filters"))

    def _install_package(self):
        pkg_dir = self._dest("packages")
        pkg_file = pkg_dir / "limbic_depth_map.json"
        if self.dry_run:
            self.changes.append(f"  [dry-run] write  {pkg_file}")
            return
        pkg_dir.mkdir(parents=True, exist_ok=True)
        text = json.dumps(PACKAGE_JSON, indent=2)
        if self.verbose:
            text = text.replace("{HFS}", str(self.hfs))
        pkg_file.write_text(text)
        self.changes.append(f"  write {pkg_file.relative_to(pkg_file.parents[1])}")

    def _install_readme(self):
        readme_src = self.src / "README.md"
        if readme_src.exists():
            dest = self._dest()
            self._cp(readme_src, dest, rename="README_limbic_depth_map.md")

    def _register_hda(self):
        """Trigger Houdini to scan the new OTL directory."""
        if self.dry_run:
            self.changes.append("  [dry-run] houdini: scan OTL paths")
            return
        try:
            import hou
            hou.hscript("opscripts -r")
            self.changes.append("  ✓ triggered OTL scan")
        except Exception as e:
            self.changes.append(f"  ⚠ could not trigger scan (restart Houdini manually): {e}")

    # ── main ────────────────────────────────────────────────────────────────

    def run(self):
        print(f"\n{'='*60}")
        print(f"  Limbic Depth Map Renderer — Installer")
        print(f"{'='*60}")
        print(f"  Source:    {self.src}")
        print(f"  Houdini:   {self.hfs}  ({self.hver})")
        print(f"  Dry run:   {self.dry_run}")
        print()

        steps = [
            ("Copying HDA files…",        self._install_hda),
            ("Copying Python Panels…",    self._install_python_panels),
            ("Copying COP2 Filters…",     self._install_cop2_filters),
            ("Writing Package file…",      self._install_package),
            ("Copying README…",           self._install_readme),
            ("Registering with Houdini…", self._register_hda),
        ]

        for label, fn in steps:
            print(f"\n  {label}")
            fn()

        print(f"\n{'='*60}")
        print("  Changes made:")
        for c in self.changes:
            print(c)
        print(f"{'='*60}")

        if not self.dry_run:
            print("""
  ✅ Install complete.

  NEXT STEPS:
    1. Restart Houdini  (or run:  houdini -r  to reload)
    2. In Houdini: File → Import → HDA File... →
         select: houdini_depth_map_renderer.otlc
    3. Drop the HDA onto a COP2 network.
    4. Open the "Composite" desk and look for the
       "Depth Map" Python Panel.
    5. Click "⚙  Setup Depth Network" to build the pipeline.
""")
        else:
            print("\n  (dry-run — no files written)")


# ─── CLI entrypoint ────────────────────────────────────────────────────────

def _main():
    ap = argparse.ArgumentParser(description="Install Limbic Depth Map Renderer for Houdini")
    ap.add_argument(
        "--src",
        type=Path,
        default=Path(__file__).parent.parent,
        help="Source directory (default: ../)",
    )
    ap.add_argument(
        "--hfs",
        type=Path,
        default=Path(os.environ.get("HFS", "")),
        help="Houdini installation root (default: $HFS)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be installed without writing files",
    )
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    try:
        hfs = args.hfs or _houdini_home()
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    Installer(args.src, hfs, dry_run=args.dry_run, verbose=args.verbose).run()


if __name__ == "__main__":
    _main()
