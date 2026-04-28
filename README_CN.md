# iOS Sideload Source by Aiko3993

[![Web Interface](https://img.shields.io/badge/Web_Interface-View_Source-blue?style=for-the-badge&logo=safari)](https://aiko3993.github.io/iOS-Sideload-Source/)
[![Add App](https://img.shields.io/badge/Contribute-Add_App-green?style=for-the-badge&logo=github)](.github/CONTRIBUTING_CN.md)

一个 iOS 侧载源。主要通过 GitHub Actions 定时从 Releases/Artifacts 拉取最新 IPA 并构建通用的 `source.json`。

[English](README.md)

## 软件源

每个源均提供两个版本：
- **Original（原始版）** — 保留上游的 Bundle ID 不变。
- **Coexist（共存版）** — 在 Bundle ID 后追加 `.coexist`，解决部分侧载 app 对同一应用的多个变体之间的 bundleIdentifier 冲突，允许并存安装。

### 标准源

| 版本 | URL |
|------|-----|
| Original | `https://raw.githubusercontent.com/Aiko3993/iOS-Sideload-Source/main/sources/standard/original/source.json` |
| Coexist | `https://raw.githubusercontent.com/Aiko3993/iOS-Sideload-Source/main/sources/standard/coexist/source.json` |

### NSFW 源

| 版本 | URL |
|------|-----|
| Original | `https://raw.githubusercontent.com/Aiko3993/iOS-Sideload-Source/main/sources/nsfw/original/source.json` |
| Coexist | `https://raw.githubusercontent.com/Aiko3993/iOS-Sideload-Source/main/sources/nsfw/coexist/source.json` |

## 机制
* **CI 抓取**: 通过 GitHub Workflows 定时拉取并解析 Releases 或 Artifacts 中的应用构建包。
* **IPA 元数据提取**: 从 `Info.plist` 解析 `version`、`bundleIdentifier`、`size`、`minOSVersion`。通过纯 Python 直接从 Mach-O 二进制的代码签名中提取 entitlements，从 plist 中提取隐私权限描述，无需 macOS 工具。
* **变体应用处理**: 识别各类 Nightly 或分支构建并主动为 Bundle ID 挂载 `.coexist` 后缀，解决设备上的覆盖安装报错。
* **官方源发现**: 自动从上游仓库中发现兼容标准格式的官方源，补全截图、分类、主色调等元数据。

## 安全与完整性
**我们不注入任何代码。** 对于同一应用的多个侧载变体（如 Stable 与 Nightly 并存），仅以重打包形式修改 `Info.plist` 中的 `CFBundleIdentifier` 以解决 Bundle ID 冲突。
所有文件均在下载后直接生成 `sha256` 校验和以供端侧校验。所有 Release 发布项内仅存留原版或重签包名的 IPA。

## 相关链接
- [网页界面](https://aiko3993.github.io/iOS-Sideload-Source/)
- [支持的应用列表](.github/APPS.md)
- [添加应用指南](.github/CONTRIBUTING_CN.md)

## 免责声明
本仓库仅作搬运与索引，应用版权归原作者所有。请在侧载前自行评估安全风险。
