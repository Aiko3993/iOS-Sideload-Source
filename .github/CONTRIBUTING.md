# Contributing

[中文文档](https://github.com/Aiko3993/iOS-Sideload-Source/blob/main/.github/CONTRIBUTING_CN.md)

## Via Issues (Recommended)
Submit an **[Add App Issue](https://github.com/Aiko3993/iOS-Sideload-Source/issues/new/choose)**. Provide the App Name, GitHub repository (`Owner/Repo`), and Category. To target pre-releases, include `(Nightly)` or `(Beta)` in the App Name.

---

## Via Pull Request (apps.json)
Append new app entries to the respective `apps.json`.

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
*   **`pre_release`** (Optional): Set `true` to track pre-releases. (Inferred automatically if `name` suffix contains "Nightly" or "Beta").
*   **`github_workflow`** (Optional): Workflow filename (e.g., `build.yml`) to extract `.app` or `.ipa` artifacts from when formal Releases are not deployed.
*   **`artifact_name`** (Optional): Regex filter to match a specific artifact name for `github_workflow` pipelines.
*   **`tag_regex`** (Optional): Regex filter to target specific releases by tag (e.g., `^v1\.2`).
*   **`ipa_regex`** (Optional): Regex filter to select a specific IPA file from releases containing multiple IPAs (e.g., `.*Standard.*`).
*   **`tint_color`** (Optional): Hex color code. System extracts dominant icon colors if omitted.

### CI/CD Behaviors
- The workflow automatically overrides explicitly declared `version`, `bundleIdentifier`, and `size` fields during IPA acquisition. Do not provide these manually.
- Conflicting Bundle IDs (caused by indexing same-repo variants) are dynamically resolved via repackaging and `.coexist` suffixing to permit parallel installations.
- Fetched assets (Artifact zips, raw `.app` directories, repacked IPAs) are deployed immediately to `builds-*` releases to persist direct download links.
