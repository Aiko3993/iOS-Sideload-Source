# iOS Sideload Source by Aiko3993

[![Web Interface](https://img.shields.io/badge/Web_Interface-View_Source-blue?style=for-the-badge&logo=safari)](https://aiko3993.github.io/iOS-Sideload-Source/)
[![Add App](https://img.shields.io/badge/Contribute-Add_App-green?style=for-the-badge&logo=github)](.github/CONTRIBUTING.md)

A iOS sideload source. Fetches the latest IPAs from GitHub Releases/Artifacts and builds a universal `source.json`.

[中文文档](README_CN.md)

## Sources

Each source is available in two editions:
- **Original** — Uses the upstream bundle ID as-is.
- **Coexist** — Appends `.coexist` to the bundle ID to resolve bundleIdentifier conflicts that some sideload apps impose on multiple variants of the same app, allowing parallel installation.

### Standard

| Edition | URL |
|---------|-----|
| Original | `https://raw.githubusercontent.com/Aiko3993/iOS-Sideload-Source/main/sources/standard/original/source.json` |
| Coexist | `https://raw.githubusercontent.com/Aiko3993/iOS-Sideload-Source/main/sources/standard/coexist/source.json` |

### NSFW

| Edition | URL |
|---------|-----|
| Original | `https://raw.githubusercontent.com/Aiko3993/iOS-Sideload-Source/main/sources/nsfw/original/source.json` |
| Coexist | `https://raw.githubusercontent.com/Aiko3993/iOS-Sideload-Source/main/sources/nsfw/coexist/source.json` |

## Features
* **CI Integration**: Workflows fetch new versions from GitHub Releases and Actions Artifacts periodically.
* **IPA Metadata Extraction**: Parses `Info.plist` for `version`, `bundleIdentifier`, `size`, and `minOSVersion`. Extracts entitlements directly from the Mach-O binary's code signature and privacy usage descriptions from the plist — all via pure Python, no macOS tools required.
* **Variant Generation**: Resolves Beta/Nightly distributions by branch/tag matching rules, appending `.coexist` to bundle IDs to permit parallel installations on iOS devices.
* **Official Source Discovery**: Automatically discovers upstream sideload-compatible sources from app repositories to supplement metadata like screenshots.

## Integrity & Modifications
**We do not inject code.** To resolve bundle ID conflicts between sideloaded variants (e.g., Nightly alongside Stable), we only repackage the `CFBundleIdentifier` in `Info.plist`.
All releases provide a `sha256` checksum for verification and contain only the unmodified or re-bundled IPAs.

## Links
- [Web Interface](https://aiko3993.github.io/iOS-Sideload-Source/)
- [Supported Apps](.github/APPS.md)
- [Contributing Guide](.github/CONTRIBUTING.md)

## Disclaimer
This repository serves as a mirror and index. App copyrights belong to their respective authors. Assess risks before sideloading.
