# Aiko3993's Sideload Source for iOS

[![Web Interface](https://img.shields.io/badge/Web_Interface-View_Source-blue?style=for-the-badge&logo=safari)](https://aiko3993.github.io/iOS-Sideload-Source/)
[![Add App](https://img.shields.io/badge/Contribute-Add_App-green?style=for-the-badge&logo=github)](.github/CONTRIBUTING.md)

A sideload app source compatible with **AltStore**, **SideStore**, and **LiveContainer**. Fetches the latest IPAs from GitHub Releases/Artifacts and builds a universal `source.json`.

[中文文档](README_CN.md)

## Sources

**Standard Source:**
```text
https://raw.githubusercontent.com/Aiko3993/iOS-Sideload-Source/main/sources/standard/source.json
```

**NSFW Source:**
```text
https://raw.githubusercontent.com/Aiko3993/iOS-Sideload-Source/main/sources/nsfw/source.json
```

## Features
* **CI Integration**: Workflows fetch new versions from GitHub Releases and Actions Artifacts periodically.
* **Property Injection**: Extracts `version`, `bundleIdentifier`, `size`, and `tintColor` iteratively from downloaded iOS application binaries.
* **Variant Generation**: Resolves Beta/Nightly distributions by branch/tag matching rules, appending `.coexist` to bundle IDs to prevent metadata collisions within the sideload source index and resolve installation conflicts on iOS devices.

## Integrity & Modifications
**We do not inject code.** For app variants (e.g., LiveContainer Nightly), we only repackage the `CFBundleIdentifier` in `Info.plist` to prevent installation conflicts.
All releases provide a `sha256` checksum for verification and contain only the unmodified or re-bundled IPAs.

## Links
- [Web Interface](https://aiko3993.github.io/iOS-Sideload-Source/)
- [Supported Apps](.github/APPS.md)
- [Contributing Guide](.github/CONTRIBUTING.md)

## Disclaimer
This repository serves as a mirror and index. App copyrights belong to their respective authors. Assess risks before sideloading.
