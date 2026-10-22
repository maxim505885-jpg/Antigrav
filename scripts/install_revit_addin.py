"""Install SCAN Revit 2027 Add-in to user's Revit AddIns directory."""
from __future__ import annotations

import os
from pathlib import Path

def install_addin() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise RuntimeError("APPDATA environment variable not found")

    revit_addins = Path(appdata) / "Autodesk" / "Revit" / "Addins" / "2027"
    revit_addins.mkdir(parents=True, exist_ok=True)

    plugin_dll = Path("integrations/revit/Scan.Plugin/bin/Release/net10.0-windows/Scan.Revit.Plugin.dll").resolve()
    if not plugin_dll.is_file():
        raise FileNotFoundError(f"Plugin DLL not found: {plugin_dll}")

    manifest_xml = f"""<?xml version="1.0" encoding="utf-8" standalone="no"?>
<RevitAddIns>
  <AddIn Type="Command">
    <Name>SCAN BIM — импорт конструкций</Name>
    <Assembly>{plugin_dll}</Assembly>
    <AddInId>cd825db8-599c-48fc-a205-9a30794ee295</AddInId>
    <FullClassName>Scan.Revit.Plugin.ImportStructuralModelCommand</FullClassName>
    <Text>Импорт SCAN BIM JSON</Text>
    <VendorId>SCAN</VendorId>
    <VendorDescription>Intelligent Scan-to-BIM</VendorDescription>
  </AddIn>
</RevitAddIns>
"""
    manifest_path = revit_addins / "SCAN.StructuralModel.addin"
    manifest_path.write_text(manifest_xml, encoding="utf-8")
    print(f"Manifest written to: {manifest_path}")

    # Also install to ProgramData if writable
    programdata = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
    pd_addins = Path(programdata) / "Autodesk" / "Revit" / "Addins" / "2027"
    try:
        pd_addins.mkdir(parents=True, exist_ok=True)
        pd_manifest = pd_addins / "SCAN.StructuralModel.addin"
        pd_manifest.write_text(manifest_xml, encoding="utf-8")
        print(f"ProgramData manifest written to: {pd_manifest}")
    except Exception as exc:
        print(f"ProgramData installation skipped: {exc}")

    return manifest_path

if __name__ == "__main__":
    install_addin()
