# How to Submit New Apps

[中文文档](CONTRIBUTING_CN.md)

Want to add an app to this source? There are two ways to do it.

### Method 1: The Easy Way (Recommended)

You don't need to edit any files. Just fill out a simple form!

1.  Go to the **[Issues](../../issues/new/choose)** tab.
2.  Click **"Get started"** next to **Add App Issue**.
3.  Fill in the **App Name**, **GitHub Repository** (e.g., `Owner/Repo`), and select the **Category**.
    *   **Tip**: To get a Nightly or Beta version, simply include "(Nightly)" or "(Beta)" in the **App Name**. The system will automatically configure the indexing logic for you!
4.  Click **Submit new issue**.

Once an admin approves your request, the system will **automatically** add the app for you! 🎉

---

### Method 2: The Advanced Way (Pull Request)

If you prefer editing files directly or want to add multiple apps at once:

### Step 1: Choose Your Category

First, decide where your app belongs. **Do not mix categories.**

---

### Step 2: Edit the File

1.  Look for the **pencil icon** (✏️) in the top right corner of the file view to start editing.
2.  Scroll to the bottom of the list.
3.  Copy the code block below and paste it **before the last `]` bracket**.
4.  **Important**: Make sure to check if the previous item's closing brace `}` is followed by a comma `,`. Missing a comma will make the JSON invalid.

**Copy this template:**

```json
    ,
    {
        "name": "App Name Here",
        "github_repo": "DeveloperName/RepoName",
        "icon_url": "https://example.com/icon.png"
    }
```

#### Field Guide (Strictly Enforced)

*   **`name`** (Required): The display name of the app. Please use **English** or concise **Chinese**.
*   **`github_repo`** (Required): The GitHub repository (e.g., `Aiko3993/MyCoolApp`).
    *   ✅ **Recommended**: `Aiko3993/MyCoolApp`
    *   ✅ **Supported**: `https://github.com/Aiko3993/MyCoolApp` (System will auto-parse)
*   **`icon_url`** (Optional): A **direct link** to the app icon image.
    *   **Smart Selection**: If omitted, the system automatically scans the repo for the best icon. If provided, the system will still compare its quality with discovered icons and use the best one.
*   **`pre_release`** (Optional): Boolean (`true` or `false`). Set to `true` to opt-in for beta/nightly versions. (Note: The system also auto-detects this if the app name contains "Nightly" or "Beta").
*   **`github_workflow`** (Optional): The filename of a GitHub Actions workflow (e.g., `build.yml`). Use this if the app doesn't have formal Releases and you want to pull IPAs from **GitHub Actions Artifacts**.
*   **`artifact_name`** (Optional): A regular expression to match a specific artifact name when using `github_workflow`. **Tip**: The system uses a 5-step intelligent heuristic (including IPA suffix matching and keyword search), so you can usually omit this.
*   **`tag_regex`** (Optional): A regular expression to filter releases by tag name (e.g., `^v1\.2`).
*   **`ipa_regex`** (Optional): A regular expression to select a specific IPA file from releases (e.g., `.*Standard.*`). This is useful when a release contains multiple IPA files (e.g., Standard vs. Plus versions).
*   **`tint_color`** (Optional): A hex color code (e.g., `#FF0000`) for the app's accent color. If omitted, the system automatically extracts the dominant color from the app icon.

---

### **Automation & Intelligent Features**

To make contributing easier, our system performs several automated tasks:

*   **Metadata Extraction**: The system automatically downloads the IPA to extract the exact `version`, `bundleIdentifier`, and `size`. You don't need to provide these.
*   **Bundle ID Conflict Prevention**: If you add multiple versions of the same app (e.g., "App Name" and "App Name Remote"), the system automatically adds a suffix to the Bundle ID to prevent installation conflicts on your device.
*   **Visual Intelligence**:
    *   **Smart Icon Selection**: If you don't provide an `icon_url`, the system scans the repository and ranks found icons based on resolution, aspect ratio, and transparency to pick the best one.
    *   **Auto-Sync**: If you update the `name` or `icon_url` in `apps.json`, the system will sync these changes to the source immediately, even if the app version hasn't changed.
*   **IPA Repackaging & Direct Hosting**: 
    *   **No more Zip issues**: For artifacts provided as `.app` or Zip files, the system automatically repackages them into standard `.ipa` files.
    *   **Direct Download Links**: All artifacts are automatically uploaded to a dedicated local release (`app-artifacts`), providing **standard IPA direct links** compatible with LiveContainer, SideStore, and AltStore.
    *   **Nightly.link (Fallback)**: Used only as a last-resort fallback to ensure high availability.

---

### Step 3: Submit for Review

> ⚠️ **Warning**: Do not add `description`, `version`, or other fields not listed here. The system handles these automatically, and manually added fields will be **discarded**.

1.  Scroll to the top right and click the green **"Commit changes..."** button.
2.  In the popup window, click **"Propose changes"**.
3.  On the next page, click **"Create pull request"**.

🎉 **Done!**
GitHub Actions will automatically validate your JSON format. If it passes, a maintainer will merge your submission shortly.
If it fails (Red ❌), please check if you missed a comma or used wrong quotes.

---

## For Maintainers

If you are a project maintainer or an AI assistant, please refer to the [Maintenance Manual](MAINTENANCE.md) for architecture details and operational guidelines.
