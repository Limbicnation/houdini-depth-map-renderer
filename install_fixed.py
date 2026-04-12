#!/usr/bin/env python3
"""
Limbic Depth Map Renderer — Fixed Installer
============================================
Run from Houdini Textport:
    >>> exec(open("/home/gero/GitHub/limbicnation/houdini-depth-map-renderer/install_fixed.py").read())

Or from a terminal:
    hython install_fixed.py
    python3 install_fixed.py   (detects Houdini prefs dir automatically)

What it does:
  1. Detects your Houdini user prefs dir (e.g. ~/houdini21.0/)
  2. Copies depth_map_panel.py  → <prefs>/python_panels/
  3. Writes depth_map_panel.pypanel (correct CDATA format) → <prefs>/python_panels/
  4. Removes any fake .otlc scaffold from <prefs>/otls/  (avoids "not a valid OTL" error)
  5. Writes limbic_depth_map_install.shelf → <prefs>/toolbar/  (shelf tool with correct API)
  6. Live-registers the panel if running inside Houdini
"""

from __future__ import annotations
import os, sys, shutil, tarfile
from pathlib import Path

# ─── Helpers ─────────────────────────────────────────────────────────────────

try:
    REPO = Path(__file__).parent.resolve()
except NameError:
    # Running via exec() in Houdini Textport — __file__ is not defined
    _THIS = '/home/gero/GitHub/limbicnation/houdini-depth-map-renderer'
    REPO = Path(_THIS).resolve()
PANEL_SRC = REPO / "python_panels" / "depth_map_panel.py"
FAKE_OTL  = "limbic_depth_map_renderer.otlc"

def _detect_prefs() -> Path:
    """Return the highest-versioned ~/houdiniXX.X/ user prefs dir."""
    home = Path.home()
    candidates = sorted(
        [d for d in home.iterdir()
         if d.is_dir() and d.name.startswith("houdini") and d.name[7:8].isdigit()],
        reverse=True
    )
    if not candidates:
        raise RuntimeError(
            "No ~/houdiniXX.X/ directory found. "
            "Open Houdini at least once to create it."
        )
    return candidates[0]


def _is_fake_otlc(path: Path) -> bool:
    """Return True if the file is a tar archive masquerading as an OTL."""
    try:
        return tarfile.is_tarfile(str(path))
    except Exception:
        return False


def _build_shelf_xml(installer_path: Path) -> str:
    """Build the .shelf XML for the one-click installer shelf tool."""
    script = f"""import hou, runpy
from pathlib import Path

INSTALLER = Path(r"{installer_path}")

if not INSTALLER.exists():
    hou.ui.displayMessage(
        f"Installer not found:\\n{{INSTALLER}}",
        severity=hou.severityType.Error,
        title="Depth Map Installer",
    )
else:
    runpy.run_path(str(INSTALLER), run_name="__main__")
    hou.ui.displayMessage(
        "Depth Map panel installed.\\n\\nOpen it via: any pane [+] → Python Panel → Depth Map",
        title="Depth Map Installer",
    )
"""
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<shelfDocument>
  <!-- Limbic Depth Map Renderer installer shelf tool -->
  <tool name="limbic_depth_map_install" label="Depth Map" icon="MISC_python">
    <toolMenuContext name="viewer">
      <contextNetType>OBJ</contextNetType>
      <contextNetType>SOP</contextNetType>
      <contextNetType>COP2</contextNetType>
      <contextNetType>COP</contextNetType>
    </toolMenuContext>
    <script scriptType="python"><![CDATA[
{script}]]></script>
  </tool>
</shelfDocument>
'''


def _build_pypanel_xml(panel_source: str) -> str:
    """Build the correct Houdini .pypanel XML with embedded CDATA script."""
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<pythonPanelDocument>
  <!-- Limbic Depth Map Renderer — https://github.com/limbicnation/houdini-depth-map-renderer -->
  <interface name="LimbicDepthMapRenderer" label="Depth Map" icon="MISC_python"
    help_url="https://github.com/limbicnation/houdini-depth-map-renderer">
    <script><![CDATA[
{panel_source}

def createInterface():
    return DepthMapPanel()
]]></script>
  </interface>
</pythonPanelDocument>
'''

# ─── Install steps ────────────────────────────────────────────────────────────

def install(prefs: Path | None = None) -> None:
    if prefs is None:
        prefs = _detect_prefs()

    log: list[str] = []

    print("\n" + "=" * 62)
    print("  Limbic Depth Map Renderer — Installer")
    print("=" * 62)
    print(f"  Repo  : {REPO}")
    print(f"  Prefs : {prefs}")
    print()

    # Security: ensure paths are within expected boundaries
    assert PANEL_SRC.exists(), f"Source not found: {PANEL_SRC}"
    assert REPO.is_relative_to(Path.home()), "Repo must be under home directory"

    pp_dir      = prefs / "python_panels"
    otls_dir    = prefs / "otls"
    toolbar_dir = prefs / "toolbar"

    pp_dir.mkdir(parents=True, exist_ok=True)
    otls_dir.mkdir(parents=True, exist_ok=True)
    toolbar_dir.mkdir(parents=True, exist_ok=True)

    # 1. Copy panel source
    dst_py = pp_dir / "depth_map_panel.py"
    shutil.copy2(PANEL_SRC, dst_py)
    log.append(f"  ✓ Copied   depth_map_panel.py  →  {dst_py}")

    # 2. Write correct .pypanel XML
    panel_source = PANEL_SRC.read_text()
    pypanel_xml  = _build_pypanel_xml(panel_source)
    dst_pypanel  = pp_dir / "depth_map_panel.pypanel"
    dst_pypanel.write_text(pypanel_xml)
    log.append(f"  ✓ Written  depth_map_panel.pypanel  ({dst_pypanel.stat().st_size/1024:.1f} KB)")

    # 3. Remove fake .otlc scaffold (causes "not a valid OTL" error)
    for fake in [otls_dir / FAKE_OTL, REPO / "HDAs" / FAKE_OTL]:
        if fake.exists() and _is_fake_otlc(fake):
            fake.unlink()
            log.append(f"  ✓ Removed  {fake.name}  (was a tar scaffold, not a real OTL)")

    # 3b. Write installer shelf tool
    shelf_xml  = _build_shelf_xml(PANEL_SRC.parent.parent / "install_fixed.py")
    dst_shelf  = toolbar_dir / "limbic_depth_map_install.shelf"
    dst_shelf.write_text(shelf_xml)
    log.append(f"  ✓ Written  limbic_depth_map_install.shelf  →  {dst_shelf}")

    # 4. Live register inside Houdini (no restart needed)
    try:
        import hou
        hou.pypanel.installFile(str(dst_pypanel))
        registered = "LimbicDepthMapRenderer" in hou.pypanel.interfaces()
        if registered:
            log.append("  ✓ Registered  LimbicDepthMapRenderer  (live, no restart needed)")
        else:
            log.append("  ⚠ Panel written but live-register returned empty — restart Houdini")
    except ImportError:
        log.append("  ℹ Running outside Houdini — restart Houdini to load the panel")
    except Exception as e:
        log.append(f"  ⚠ Live-register error: {e}  — restart Houdini to load the panel")

    # ─── Summary ─────────────────────────────────────────────────────────────
    print("\n".join(log))
    print()
    print("=" * 62)
    print("  Done.")
    print()
    print("  To open the panel in Houdini:")
    print("    1. Shelf: drag 'Depth Map' tool from toolbar → click it")
    print("    OR")
    print("    2. Any pane tab → [+] New Pane Tab → Python Panel → Depth Map")
    print("    3. For full compositor integration: use a Composite Desk pane")
    print("=" * 62)


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Install Limbic Depth Map Renderer")
    ap.add_argument("--prefs", type=Path, default=None,
                    help="Houdini user prefs dir (default: auto-detect ~/houdiniXX.X/)")
    args = ap.parse_args()
    install(args.prefs)
else:
    # Called via exec() from Houdini Textport
    install()
