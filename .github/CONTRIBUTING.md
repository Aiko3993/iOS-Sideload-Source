# Contributing

[中文文档](https://github.com/Aiko3993/iOS-Sideload-Source/blob/main/.github/CONTRIBUTING_CN.md)

## Via Issues (Recommended)
Submit an **[Add App Issue](https://github.com/Aiko3993/iOS-Sideload-Source/issues/new/choose)**. Provide the App Name, GitHub repository (`Owner/Repo`), and Category.

- Nightly builds: include `(Nightly)` in the App Name (Artifacts-only).
- Pre-releases on Releases: include `(Beta)` in the App Name.
- Advanced configuration (regex/workflow/branch): use a Pull Request to edit `apps.json`.

---

## Via Pull Request (apps.json)
Append new app entries to the respective `apps.json` under `sources/standard/` or `sources/nsfw/`. Apps added here will automatically appear in both the Original and Coexist editions of the source.

### JSON Template
```json
    ,
    {
        "name": "App Name",
        "github_repo": "Owner/Repo"
    }
```

### Fields Reference
*   **`name`** (Required): App display name.
*   **`github_repo`** (Required): GitHub repository slug (`Owner/Repo`) or URL.
*   **`icon_url`** (Optional): Direct link to an app icon. Omit to let the CI pipeline scan the source tree for optimal icons automatically.
*   **`bundle_id`** (Optional): Override the auto-detected bundle identifier from the IPA.
*   **`pre_release`** (Optional): Set `true` to allow selecting pre-releases when they are newer than stable releases.
*   **`tag_regex`** (Optional): Regex filter applied to `release.tag_name` when selecting a Release. If set, the resolver switches to listing releases (instead of `releases/latest`). Over-filtering may cause “no Release candidate” and trigger artifact fallback.
*   **`github_workflow`** (Optional): Workflow filename (e.g., `build.yml`) to extract `.app` or `.ipa` artifacts from when formal Releases are not deployed.
*   **`artifact_name`** (Optional): Regex filter to match a specific artifact name for `github_workflow` pipelines.
*   **`ipa_regex`** (Optional): Regex filter to select a specific IPA file from releases containing multiple IPAs (e.g., `.*Standard.*`).
*   **`artifact_only`** (Optional): Set `true` to skip Releases entirely and resolve builds from Actions/Artifacts. This is the intended “Nightly” mode.
*   **`github_branch`** (Optional): Branch name used when searching workflow runs (defaults to the repo default branch).
*   **`tint_color`** (Optional): Hex color code. System extracts dominant icon colors if omitted.

### CI/CD Behaviors
- The workflow automatically extracts `version`, `bundleIdentifier`, `size`, `minOSVersion`, `appPermissions` (entitlements and privacy descriptions), and `sha256` from the IPA binary. Do not provide these manually.
- Apps are published in two editions: **Original** (upstream bundleIdentifier) and **Coexist** (`.coexist` suffix appended to bundleIdentifier to allow parallel installation).
- Fetched assets are deployed to `Builds` releases to persist direct download links.
- Output fields are governed by the `ALLOWED_APP_FIELDS` and `ALLOWED_VERSION_FIELDS` schemas in `update_source.py`. Removing a field from the schema automatically strips it from `source.json` on the next CI run.
- Metadata such as `category`, `screenshots`, `tintColor`, and `subtitle` is automatically discovered from upstream AltStore-compatible sources when available.
