# Aiko3993's Sideload Source for iOS

[![Web Interface](https://img.shields.io/badge/Web_Interface-View_Source-blue?style=for-the-badge&logo=safari)](https://aiko3993.github.io/iOS-Sideload-Source/)
[![Add App](https://img.shields.io/badge/Contribute-Add_App-green?style=for-the-badge&logo=github)](.github/CONTRIBUTING_CN.md)

适用于 **AltStore**、**SideStore** 和 **LiveContainer** 的侧载源。主要通过 GitHub Actions 定时从 Releases/Artifacts 拉取最新 IPA 并构建通用的 `source.json`。

[English](README.md)

## 软件源

**标准源:**
```text
https://raw.githubusercontent.com/Aiko3993/iOS-Sideload-Source/main/sources/standard/source.json
```

**NSFW 源:**
```text
https://raw.githubusercontent.com/Aiko3993/iOS-Sideload-Source/main/sources/nsfw/source.json
```

## 机制
* **CI 抓取**: 通过 GitHub Workflows 定时拉取并解析 Releases 或 Artifacts 中的应用构建包。
* **属性注入**: 自动解包 IPA 以注入并修正实际的 `version`、`bundleIdentifier` 与 `tintColor` 参数。
* **变体应用处理**: 识别各类 Nightly 或分支构建并主动为其 Bundle ID 挂载 `.coexist` 定位符，规避侧载源在索引同名应用时的 ID 唯一性冲突，并解决设备上的覆盖安装报错。

## 安全与完整性
**我们不注入任何代码。** 针对 Nightly 变体或相同应用多分支的情景，仅以重打包形式修改 `Info.plist` 中的 `CFBundleIdentifier` 以防安装冲突。
所有文件均在下载后直接生成 `sha256` 校验和以供端侧校验。所有缓存文件内仅存留原版或重新重签包名的 IPA。

## 相关链接
- [网页界面](https://aiko3993.github.io/iOS-Sideload-Source/)
- [支持的应用列表](.github/APPS.md)
- [添加应用指南](.github/CONTRIBUTING_CN.md)

## 免责声明
本仓库仅作搬运与索引，应用版权归原作者所有。请在侧载前自行评估安全风险。
