# 提交应用

[English](https://github.com/Aiko3993/iOS-Sideload-Source/blob/main/.github/CONTRIBUTING.md)

## 通过 Issues 提交 (推荐)
提交一个 **[Add App Issue](https://github.com/Aiko3993/iOS-Sideload-Source/issues/new/choose)**。填写应用名称、GitHub 仓库 (`Owner/Repo`) 以及所属分类。若需追踪预览版，在应用名称中加入 `(Nightly)` 或 `(Beta)` 即可。

---

## 通过 Pull Request 提交 (修改 apps.json)
将新增应用追加至 `sources/standard/` 或 `sources/nsfw/` 下对应的 `apps.json` 文件末尾。添加的应用会自动出现在 Original（原始版）和 Coexist（共存版）两个版本的源中。

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
*   **`icon_url`** (选填): 图标图片直链。若省略，CI 将扫描源码树自动选用高质量的图标文件。
*   **`bundle_id`** (选填): 手动指定 Bundle Identifier，覆盖从 IPA 中自动检测的值。
*   **`pre_release`** (选填): 设置为 `true` 以跟踪预发布版本。名称含 "Nightly"/"Beta" 也会触发相同推导。
*   **`github_workflow`** (选填): 当无正式 Release 时，指定 Workflow 名称 (如 `build.yml`) 以直接从 Artifacts 提取。
*   **`artifact_name`** (选填): 配合 `github_workflow` 使用的正则表达式，过滤特定产物名称。
*   **`tag_regex`** (选填): 通过正则过滤特定标签的 Release (例如 `^v1\.2`)。
*   **`ipa_regex`** (选填): 从包含多个 IPA 的 Release 中拣选特定文件 (例如 `.*Standard.*`)。
*   **`tint_color`** (选填): 十六进制色彩代码。不设定时从图标主色调自动提取。

### 构建机制说明
- CI 会自动从 IPA 二进制中提取 `version`、`bundleIdentifier`、`size`、`minOSVersion`、`appPermissions`（权限与隐私描述）和 `sha256` 校验和。请勿手动编写这些值。
- 应用会自动生成两个版本：**Original**（保留上游 bundleIdentifier）和 **Coexist**（追加 `.coexist` 后缀，解决部分侧载 app 对同一应用的多个变体之间的 bundleIdentifier 冲突，允许并存安装）。
- CI 获取的 Artifacts 将被清理封装，并部署至 `builds-*` Release 生成持久化直链。
