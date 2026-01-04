# Aiko3993's Sideload Source for iOS

[![Web Interface](https://img.shields.io/badge/Web_Interface-View_Source-blue?style=for-the-badge&logo=safari)](https://aiko3993.github.io/iOS-Sideload-Source/)
[![Add App](https://img.shields.io/badge/Contribute-Add_App-green?style=for-the-badge&logo=github)](.github/CONTRIBUTING_CN.md)

这是一个适用于 **AltStore**、**SideStore** 和 **LiveContainer** 的个人侧载应用源，或许还有更多。
它会自动从 GitHub Releases 获取最新的 IPA，并生成通用的源文件。 
此外，它还提供了一个用于浏览应用的网页界面。

[English](README.md)

## 使用方法

### 方法 1：网页界面
访问 **[网页界面](https://aiko3993.github.io/iOS-Sideload-Source/)** 浏览应用，并且：
*   使用 **Install** 按钮一键安装到 AltStore、SideStore 或 LiveContainer。

### 方法 2：手动添加

将这些添加到您的侧载工具中：

```
https://raw.githubusercontent.com/Aiko3993/iOS-Sideload-Source/main/sources/standard/source.json
```

## 提交应用

想添加新应用？非常简单！
👉 **[阅读应用提交指南](.github/CONTRIBUTING_CN.md)**

## 支持应用列表
 
> *支持的应用列表由脚本自动生成。*
 
👉 **[查看支持应用列表](.github/APPS.md)**
 
## 自动化机制

本仓库完全基于 GitHub Actions 运行：
*   **每小时更新**: 自动检查所有应用的新版本。
*   **Artifact 支持**: 支持直接从 **GitHub Actions Workflow Artifacts** 抓取 IPA，适用于没有正式 Release 的应用。
*   **智能解析**: 直接从 IPA 文件中提取元数据 (版本号、BundleID、主题色)。
*   **自动同步**: 自动将发现的 `icon_url` 和 `bundle_id` 同步回 `apps.json`，减少维护成本。
*   **自动版本发现**: 自动识别名称中的 `Nightly`、`Beta` 等版本，并结合 GitHub Tag 进行动态匹配。
*   **高质量图标发现**: 自动扫描仓库图标，并通过评分系统在用户提供和自动发现的图标中择优使用。
*   **自动验证**: 提交 PR 时会自动检查 `apps.json` 格式是否正确。

## 其他源

**NSFW 源:**

```
https://raw.githubusercontent.com/Aiko3993/iOS-Sideload-Source/main/sources/nsfw/source.json
```

## 安全与完整性

> **我们不会向 IPA 中注入任何代码。**

对于应用变体（如 UTM HV、LiveContainer Nightly），我们仅修改 `Info.plist` 中的 `CFBundleIdentifier` 以确保唯一的 Bundle ID。这是必需的，因为 AltStore/SideStore 会拒绝包含重复 Bundle ID 的源。

### 我们修改了什么
- **仅限**: `Info.plist` → `CFBundleIdentifier` 字段
- **其他均未修改**: 无代码注入、无库文件更改、无二进制修改

### 如何验证
1. **SHA256 校验**: `source.json` 中的每个 IPA 都包含 `sha256` 字段
2. **手动验证**:
   ```bash
   # 下载后验证
   shasum -a 256 downloaded.ipa
   # 与 source.json 中的 sha256 对比
   ```
3. **检查变更**: 解压 IPA 并对比 `Payload/App.app/Info.plist` 与原版 Release

### 透明度
- 所有源代码在本仓库中公开可审计
- GitHub Actions 日志完整记录了所有修改操作
- Cached releases 仅包含重打包的 IPA，无额外文件

## 免责声明
 
本仓库仅作为搬运和索引，所有应用版权归原作者所有。请在使用前自行评估风险。
