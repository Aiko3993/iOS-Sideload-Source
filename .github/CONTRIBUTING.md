# Contributing

[中文文档](https://github.com/Aiko3993/iOS-Sideload-Source/blob/main/.github/CONTRIBUTING_CN.md)

## Via Issues (Recommended)
Submit an **[Add App Issue](https://github.com/Aiko3993/iOS-Sideload-Source/issues/new/choose)**. Provide the App Name, GitHub repository (`Owner/Repo`), and Category. To target pre-releases, include `(Nightly)` or `(Beta)` in the App Name.

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
*   **`pre_release`** (Optional): Set `true` to track pre-releases. (Inferred automatically if `name` suffix contains "Nightly" or "Beta").
*   **`github_workflow`** (Optional): Workflow filename (e.g., `build.yml`) to extract `.app` or `.ipa` artifacts from when formal Releases are not deployed.
*   **`artifact_name`** (Optional): Regex filter to match a specific artifact name for `github_workflow` pipelines.
*   **`tag_regex`** (Optional): Regex filter to target specific releases by tag (e.g., `^v1\.2`).
*   **`ipa_regex`** (Optional): Regex filter to select a specific IPA file from releases containing multiple IPAs (e.g., `.*Standard.*`).
*   **`tint_color`** (Optional): Hex color code. System extracts dominant icon colors if omitted.

### CI/CD Behaviors
- The workflow automatically extracts `version`, `bundleIdentifier`, `size`, `minOSVersion`, `appPermissions` (entitlements and privacy descriptions), and `sha256` from the IPA binary. Do not provide these manually.
- Apps are published in two editions: **Original** (upstream bundleIdentifier) and **Coexist** (`.coexist` suffix appended to bundleIdentifier to allow parallel installation).
- Fetched assets are deployed to `Builds` releases to persist direct download links.
- Output fields are governed by the `ALLOWED_APP_FIELDS` and `ALLOWED_VERSION_FIELDS` schemas in `update_source.py`. Removing a field from the schema automatically strips it from `source.json` on the next CI run.
- Metadata such as `category`, `screenshots`, `tintColor`, and `subtitle` is automatically discovered from upstream AltStore-compatible sources when available.
