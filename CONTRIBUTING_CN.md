# 如何提交新应用

[English](CONTRIBUTING.md)

想在这个源里添加一个新应用吗？有两种方法。

### 方法一：简单模式 (推荐)

你不需要编辑任何代码文件，只需要填写一个表格！

1.  进入 **[Issues](../../issues/new/choose)** 页面。
2.  点击 **Add App Issue** 旁边的 **"Get started"** 按钮。
3.  填写 **应用名称 (App Name)**、**GitHub 仓库 (GitHub Repository)** (格式如 `Owner/Repo`)，并选择 **分类 (Category)**。
    *   **提示**：如果你想索引 Nightly 或 Beta 版本，只需在**应用名称**中包含 "(Nightly)" 或 "(Beta)" 即可，系统会自动为你配置索引逻辑！
4.  点击 **Submit new issue** 提交。

一旦管理员批准你的请求，系统会自动帮你添加应用！🎉

---

### 方法二：高级模式 (Pull Request)

如果你更喜欢直接编辑文件，或者想一次性添加多个应用：

### 第一步：选择分类

首先，确定您的应用属于哪一类。**请勿混淆分类。**

---

### 第二步：编辑文件

1.  在文件页面的右上角找到 **铅笔图标** (✏️) 并点击它。
2.  滚动到文件最底部。
3.  复制下面的代码块，并粘贴到**最后一个方括号 `]` 之前**。
4.  **重要**：务必检查上一项的结束花括号 `}` 后面是否有逗号 `,`。如果缺少逗号，JSON 将无效。

**复制此模板：**

```json
    ,
    {
        "name": "这里写应用名称",
        "github_repo": "开发者/仓库名",
        "icon_url": "https://example.com/icon.png"
    }
```

#### 字段说明 (严格遵守)

*   **`name`** (必填): 应用在源列表中显示的名称。请使用**英文**或**简洁的中文**。
*   **`github_repo`** (必填): 应用的 GitHub 仓库地址 (例如 `Aiko3993/MyCoolApp`)。
    *   ✅ **推荐**: `Aiko3993/MyCoolApp`
    *   ✅ **支持**: `https://github.com/Aiko3993/MyCoolApp` (系统会自动识别)
*   **`pre_release`** (选填): 布尔值 (`true` 或 `false`)。设置为 `true` 以获取 Beta/Nightly 版本。(提示：如果应用名包含 "Nightly" 或 "Beta"，系统会自动识别)。
*   **`github_workflow`** (选填): GitHub Actions 工作流文件名 (例如 `build.yml`)。如果应用没有正式 Release，希望从 **GitHub Actions Artifacts** 抓取 IPA 时使用。
*   **`artifact_name`** (选填): 使用 `github_workflow` 时，用于匹配特定 Artifact 名称的正则表达式。**提示**：系统内置了 5 步智能启发式搜索（包括 IPA 后缀匹配和关键字搜索），通常情况下您可以省略此字段。
*   **`tag_regex`** (选填): 用于按标签名过滤 Release 的正则表达式 (例如 `^v1\.2`)。
*   **`ipa_regex`** (选填): 用于从 Release 中选择特定 IPA 文件的正则表达式 (例如 `.*Standard.*`)。当一个 Release 中包含多个 IPA（如标准版和插件版）时非常有用。
*   **`tint_color`** (选填): 十六进制颜色代码 (例如 `#FF0000`)。如果省略，系统会自动从应用图标中提取主色调。

---

### **自动化与智能化特性**

为了简化提交过程，我们的系统会自动执行以下任务：

*   **元数据自动提取**: 系统会自动下载 IPA 以提取精确的 `version` (版本号)、`bundleIdentifier` (包名) 和 `size` (文件大小)。您无需手动提供这些信息。
*   **Bundle ID 冲突预防**: 如果您添加了同一应用的多个版本（例如 "App Name" 和 "App Name Remote"），系统会自动为包名添加后缀（如 `.remote`），以防止在设备上发生安装冲突。
*   **视觉智能**:
    *   **智能图标选择**: 如果未提供 `icon_url`，系统会扫描仓库，并根据分辨率、长宽比和透明度对找到的图标进行评分，选择质量最高的一个。
    *   **自动同步**: 如果您在 `apps.json` 中更新了 `name` 或 `icon_url`，系统会立即同步这些更改，即使应用版本没有更新。
*   **IPA 自动重构与直链托管**: 
    *   **告别 Zip 困扰**: 针对只提供 `.app` 或 Zip 的 Artifact，系统会自动将其重构为标准的 `.ipa` 格式。
    *   **仓库直链**: 所有 Artifact 都会被自动上传至本仓库的专用 Release (`app-artifacts`)，提供**标准的 IPA 直链**，完美兼容 LiveContainer、SideStore 等侧载工具。
    *   **Nightly.link (保底)**: 仅在极端情况下作为备选方案，确保服务高可用。

---

### 第三步：提交审核

> ⚠️ **警告**：不要添加 `description`、`version` 或其他未列出的字段。系统会自动处理这些信息，手动添加会被直接丢弃。

1.  滚动到页面右上角，点击绿色的 **"Commit changes..."** 按钮。
2.  在弹出的窗口中，选择 **"Propose changes"**。
3.  在下一个页面，点击 **"Create pull request"**。

🎉 **提交完成！**
GitHub Actions 会自动检查您的 JSON 格式。如果检查通过，管理员会尽快合并您的提交。
如果检查失败 (显示红色 ❌)，请检查您是否遗漏了逗号或弄错了引号。

---

## 维护者指南

如果您是项目维护者或 AI 助手，请参阅 [维护手册 (MAINTENANCE.md)](MAINTENANCE.md) 以了解架构详情和操作指南。
