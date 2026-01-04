# Aiko3993's Sideload Source for iOS

[![Web Interface](https://img.shields.io/badge/Web_Interface-View_Source-blue?style=for-the-badge&logo=safari)](https://aiko3993.github.io/iOS-Sideload-Source/)
[![Add App](https://img.shields.io/badge/Contribute-Add_App-green?style=for-the-badge&logo=github)](.github/CONTRIBUTING.md)

This is a sideload app source compatible with **AltStore**, **SideStore**, and **LiveContainer**, and maybe more.
It automatically fetches the latest IPAs from GitHub Releases and generates a universal source file.  
It also provides a web interface for browsing apps.

[中文文档](README_CN.md)

## Usage

### Method 1: Web Interface
Visit the **[Web Interface](https://aiko3993.github.io/iOS-Sideload-Source/)** to:
*   Browse the complete app catalog.
*   Use the **Install** buttons for AltStore/SideStore/LiveContainer.

### Method 2: Add Source Manually

Copy the link below into your preferred sideloading tool:

```
https://raw.githubusercontent.com/Aiko3993/iOS-Sideload-Source/main/sources/standard/source.json
```

## Contributing

Want to add a new app?
👉 **[Read the Contributing Guide](.github/CONTRIBUTING.md)**

## Supported Apps

> *The supported app list is automatically generated.*

👉 **[View Supported Apps List](.github/APPS.md)**

## Automation

This project runs on GitHub Actions:
*   **Hourly Updates**: Checks for new releases every hour.
*   **Artifact Support**: Can pull IPAs directly from **GitHub Actions Workflow Artifacts** for apps without formal releases.
*   **Smart Parsing**: Extracts metadata (Version, BundleID, TintColor) directly from the IPA.
*   **Auto-Sync**: Automatically updates `apps.json` with discovered `icon_url` and `bundle_id` to keep the source clean.
*   **Auto Version Discovery**: Automatically identifies `Nightly`, `Beta`, etc., versions from app names and cross-references GitHub tags for pre-release matching.
*   **Quality-First Icon Discovery**: Automatically scans repository for icons and selects the highest-quality version based on scoring.
*   **Validation**: Automatically checks `apps.json` syntax on Pull Requests.

## Additional Sources

**NSFW Source:**:

```
https://raw.githubusercontent.com/Aiko3993/iOS-Sideload-Source/main/sources/nsfw/source.json
```

## Security & Integrity

> **We do NOT inject any code into the IPAs.**

For app variants (e.g., UTM HV, LiveContainer Nightly), we only modify the `CFBundleIdentifier` in `Info.plist` to ensure unique bundle IDs. This is required because AltStore/SideStore reject sources with duplicate bundle IDs.

### What We Modify
- **Only**: `Info.plist` → `CFBundleIdentifier` field
- **Nothing else**: No code injection, no library changes, no binary modifications

### How to Verify
1. **SHA256 Checksums**: Every IPA in `source.json` includes a `sha256` field
2. **Manual Verification**:
   ```bash
   # Download and verify
   shasum -a 256 downloaded.ipa
   # Compare with sha256 in source.json
   ```
3. **Inspect Changes**: Unzip the IPA and compare `Payload/App.app/Info.plist` with the original release

### Transparency
- All source code is open and auditable in this repository
- GitHub Actions logs show exactly what modifications are made
- Cached releases contain only repackaged IPAs, no additional files

## Disclaimer

This repository serves only as a mirror and index. All app copyrights belong to their original authors. Please assess the risks yourself before use.
