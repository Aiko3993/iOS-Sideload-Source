# 提交应用

[English](https://github.com/Aiko3993/iOS-Sideload-Source/blob/main/.github/CONTRIBUTING.md)

## 通过 Issues 提交 (推荐)
提交一个 **[Add App Issue](https://github.com/Aiko3993/iOS-Sideload-Source/issues/new/choose)**。填写应用名称、GitHub 仓库 (`Owner/Repo`) 以及所属分类。

- Nightly 构建：在应用名称中加入 `(Nightly)`（Artifacts-only）。
- Release 预发布：在应用名称中加入 `(Beta)`。
- 高级配置（regex/workflow/branch）：请通过 Pull Request 修改 `apps.json`。

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
*   **`pre_release`** (选填): 设置为 `true` 允许在预发布版本比稳定版更新时选择预发布 Release。
*   **`tag_regex`** (选填): 按 `release.tag_name` 的正则过滤 Release。设置后会改为拉取 releases 列表而不是 `releases/latest`；过滤过窄会导致“无 Release 候选”，进而触发 artifacts 回退。
*   **`github_workflow`** (选填): 当无正式 Release 时，指定 Workflow 名称 (如 `build.yml`) 以直接从 Artifacts 提取。
*   **`artifact_name`** (选填): 配合 `github_workflow` 使用的正则表达式，过滤特定产物名称。
*   **`ipa_regex`** (选填): 从包含多个 IPA 的 Release 中拣选特定文件 (例如 `.*Standard.*`)。
*   **`artifact_only`** (选填): 设置为 `true` 将完全跳过 Releases，仅从 Actions/Artifacts 解析构建产物（这就是 Nightly 语义）。
*   **`github_branch`** (选填): 搜索 workflow runs 的分支名（默认使用仓库默认分支）。
*   **`tint_color`** (选填): 十六进制色彩代码。不设定时从图标主色调自动提取。

### 构建机制说明
- CI 会自动从 IPA 二进制中提取 `version`、`bundleIdentifier`、`size`、`minOSVersion`、`appPermissions`（权限与隐私描述）和 `sha256` 校验和。请勿手动编写这些值。
- 应用会自动生成两个版本：**Original**（保留上游 bundleIdentifier）和 **Coexist**（追加 `.coexist` 后缀，允许并存安装）。
- CI 获取的 Artifacts 将被清理封装，并部署至 `Builds` Release 生成持久化直链。
- 输出字段由 `update_source.py` 中的 `ALLOWED_APP_FIELDS` 和 `ALLOWED_VERSION_FIELDS` 声明式 schema 管控。从 schema 中移除字段时，下次 CI 运行会自动将其从 `source.json` 中清除。
- `category`、`screenshots`、`tintColor`、`subtitle` 等元数据会自动从上游兼容 AltStore 格式的官方源中发现并补全。
