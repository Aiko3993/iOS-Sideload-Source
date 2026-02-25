# 提交应用

[English](https://github.com/Aiko3993/iOS-Sideload-Source/blob/main/.github/CONTRIBUTING.md)

## 通过 Issues 提交 (推荐)
提交一个 **[Add App Issue](../../issues/new/choose)**。填写应用名称、GitHub 仓库 (`Owner/Repo`) 以及所属分类。若需追踪处于预览版的分支，在应用名称中加入 `(Nightly)` 或 `(Beta)` 即可。

---

## 通过 Pull Request 提交 (修改 apps.json)
将新增应用追加至对应分类的 `apps.json` 文件末尾。

### 数据模板
```json
    ,
    {
        "name": "应用名称",
        "github_repo": "Developer/Repo"
    }
```

### 字段参考
*   **`name`** (必填): 显示名称。
*   **`github_repo`** (必填): GitHub 仓库相对路径 (`Owner/Repo`) 或其 URL。
*   **`icon_url`** (选填): 图标图片直链。若省略，此值将交由 CI 扫描源码树，自动评判分辨率与留白透明度并选用高质量的图标文件。
*   **`pre_release`** (选填): 设置为 `true` 以跟踪预发布版本。名称含 "Nightly"/"Beta" 也会触发相同的推导结果。
*   **`github_workflow`** (选填): 当无正式 Release 构建时，指定其使用的 Workflow 名称 (如 `build.yml`) 以直接解压 Artifacts。
*   **`artifact_name`** (选填): 在配置了 `github_workflow` 的前提下，用于指代过滤特定产物名称正则表达式。
*   **`tag_regex`** (选填): 通过正则表达式过滤特定标签所在的 Release (例如 `^v1\.2`)。
*   **`ipa_regex`** (选填): 通过正则表达式拣选 Release 中特定的 IPA（例如 `.*Standard.*`）。
*   **`tint_color`** (选填): 十六进制色彩代码。不设定时从提取到的图标主偏色生成。

### 构建机制说明
- 诸如 `version`、`bundleIdentifier` 及 `size` 等详细元数据会在 CI 实际解析 IPA 后**被构建脚本强制提取和覆盖**，请勿在源内显式定义这些值。
- 同一应用产生不同的共存变体索引时（例如标准版与远程连接版），系统将重新打包原始 IPA，注入以 `.coexist` 定位后缀修改 Bundle ID 解决在真机上的覆盖安装报错。
- 由于 GitHub 网络隔离或提取的构建格式复杂，CI 获取的 Artifacts 将被重新清理封装，并在同一仓库的 `cached-*` Release 分发生成持久化高速直链。
