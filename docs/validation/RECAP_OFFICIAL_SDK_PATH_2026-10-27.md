# Autodesk ReCap official project and SDK path — 2026-10-27

This note records only Autodesk-published behavior relevant to SCAN's FARO station workflow. It does not treat undocumented DLL interfaces or third-party RCP writers as supported SDKs.

## Findings

- Autodesk documents the Reality Solutions SDK as able to read spatial data and RCP/RCS metadata and write RCP/RCS projects. The documented access path is a request in the ReCap Community Forum with “Reality Solutions SDK” in the subject or ADN Standard/Professional membership. The API package is not described as a public GitHub SDK. SCAN should continue using installed Autodesk DeCap or obtain the official SDK; it must not implement a proprietary RCS/RCP writer.
- Autodesk's supported-format matrix lists RCS and Faro FLS/FWS as import formats, RCP/RCS as export formats, and structured E57 export with individual scans and registration transforms.
- ReCap registration guidance says automatic registration starts after all files are imported; manual registration can start after the first structured scan, and manual registration is unavailable for unstructured data. Therefore a valid project bundle alone is not evidence of registered station coordinates.
- Autodesk documents the RCP as a project file linked to a project-named Support folder. Renaming linked assets can break references; unifying/exporting can remove scan-location information. A transferable deliverable must be validated as the complete RCP + Support bundle and opened after copying it to another directory.

## SCAN implication

The current SCAN code delegates native RCP creation to Autodesk `DeCap.exe`; it verifies the RCP manifest, linked scans, and bundle paths. The remaining proof is a live ReCap GUI open/round-trip and verification of station origins/registration on an exported derivative. The current FARO source nodes say `registered=false`; pairwise ICP, the existing BEV coarse matcher, and tested Euler interpretations did not yield an acceptable candidate in the read-only station-pair diagnostic. Do not mark those stations registered or export a transform as measured.

## Autodesk sources

- [Reality Solutions SDK](https://help.autodesk.com/cloudhelp/ENU/Reality-Capture/files/Product_Overview/recap_sdk.html)
- [Supported File Formats](https://help.autodesk.com/view/RECAP/ENU/?contextId=supported_file_formats)
- [Register Scans](https://help.autodesk.com/cloudhelp/ENU/Reality-Capture/files/Creating_Scan_Projects/register_scans.html)
- [Scan locations missing in a ReCap Pro project](https://help.autodesk.com/view/RECAP/ENU/?caas=caas%2Fsfdcarticles%2Fsfdcarticles%2FScan-locations-missing-in-ReCap-Pro-project.html)