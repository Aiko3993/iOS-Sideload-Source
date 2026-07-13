
import { getState } from './state.js';

// Base config for paths
export const PATH_CONFIG = {
    isLocalDev: window.location.pathname.includes('/website/'),
    productionBase: 'https://raw.githubusercontent.com/{{AUTHOR}}/{{REPO}}/gh-pages/'
};

const _authorMatch = PATH_CONFIG.productionBase.match(/github(?:usercontent)?\.com\/([^/]+)\//);
let author = _authorMatch ? _authorMatch[1] : 'Unknown';
if (author === '{{' + 'AUTHOR}}') author = 'Local Environment';
export const RESOLVED_AUTHOR = author;

export const TRANSLATIONS = {
    en: {
        title: "iOS Sideload Source",
        sourceTitle: "{{AUTHOR}}",
        subtitle: "Discover & Install Apps",
        searchPlaceholder: "Search...",
        sourceAll: "All Apps",
        sourceAllDesc: "All available apps",
        sourceStandard: "Standard",
        sourceStandardDesc: "Normal apps",
        sourceNSFW: "NSFW",
        sourceNSFWDesc: "Adult content",
        sortLatest: "Latest",
        sortName: "Name",
        sortSize: "Size",
        noApps: "No apps found",
        noAppsDesc: "Try adjusting your search or switching sources.",
        download: "Download IPA",
        details: "Details",
        copyBtn: "Copy Source URL",
        sourceCopied: "source URL copied!",
        copyFailed: "Failed to copy URL",
        thirdParty: "Third-party Source",
        close: "Close",
        whatsNew: "What's New",
        description: "Description",
        installAltStore: "AltStore",
        installSideStore: "SideStore",
        installLiveContainer: "LiveContainer",
        ipa: "IPA",
        bundleId: "Bundle ID",
        minOS: "Min OS",
        updated: "Updated",
        developer: "Developer",
        linkCopiedFor: "Link copied for",
        failedToCopy: "Failed to copy",
        riskWarning: "Third-party Source",
        riskOwnRisk: "Use at your own risk",
        loadFailedTitle: "Failed to load source",
        loadFailedDesc: "Could not load apps. Please check your internet connection or try again later.",
        retry: "Retry",
        noDescription: "No description available.",
        noChangelog: "No changelog available.",
        coexistOff: "Original",
        coexistOn: "Coexist",
        variantsButton: "Variants ({0})",
        variantsAvailable: "{0} Variants Available",
        variantsTitle: "Variants",
        versions: "Versions"
    },
    zh: {
        title: "iOS 侧载源",
        sourceTitle: "{{AUTHOR}}",
        subtitle: "Discover & Install Apps",
        searchPlaceholder: "搜索应用...",
        sourceAll: "全部应用",
        sourceAllDesc: "所有可用应用",
        sourceStandard: "标准",
        sourceStandardDesc: "常用应用",
        sourceNSFW: "NSFW",
        sourceNSFWDesc: "成人内容",
        sortLatest: "最新",
        sortName: "名称",
        sortSize: "大小",
        noApps: "未找到应用",
        noAppsDesc: "尝试调整搜索关键词或切换源。",
        download: "下载 IPA",
        details: "详情",
        copyBtn: "拷贝源地址",
        sourceCopied: "源地址已拷贝！",
        copyFailed: "拷贝失败",
        thirdParty: "第三方源",
        close: "关闭",
        whatsNew: "更新日志",
        description: "应用介绍",
        installAltStore: "AltStore",
        installSideStore: "SideStore",
        installLiveContainer: "LiveContainer",
        ipa: "IPA",
        bundleId: "包名",
        minOS: "最低系统",
        updated: "更新时间",
        developer: "开发者",
        linkCopiedFor: "已拷贝链接：",
        failedToCopy: "拷贝失败",
        riskWarning: "第三方源",
        riskOwnRisk: "风险自负",
        loadFailedTitle: "无法加载源",
        loadFailedDesc: "无法加载应用列表，请检查您的网络连接或稍后重试。",
        retry: "重试",
        noDescription: "暂无描述。",
        noChangelog: "暂无更新日志。",
        coexistOff: "原版",
        coexistOn: "共存",
        variantsButton: "变体 ({0})",
        variantsAvailable: "{0} 个可用变体",
        variantsTitle: "变体",
        versions: "版本"
    }
};

// Icons
export const ICONS = {
    standard: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 7.5l-9-5.25L3 7.5m18 0l-9 5.25m9-5.25v9l-9 5.25M3 7.5l9 5.25M3 7.5v9l9 5.25m0-9v9" />',
    nsfw: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21"></path>',
    all: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z"></path>',
    search: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path>',
    copy: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"></path>',
    sortLatest: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"></path>',
    sortName: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 7h.01M7 3h5c.512 0 1.024.195 1.414.586l7 7a2 2 0 010 2.828l-7 7a2 2 0 01-2.828 0l-7-7A1.994 1.994 0 013 12V7a4 4 0 014-4z"></path>',
    sortSize: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4"></path>',
    noApps: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.172 16.172a4 4 0 015.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path>',
    warning: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path>',
    arrowUp: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 10l7-7m0 0l7 7m-7-7v18"></path>',
    close: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>',
    check: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path>',
    developer: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"></path>',
    details: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path>',
    download: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />',
    altstore: '<rect x="5" y="5" width="14" height="14" rx="5" transform="rotate(45 12 12)" stroke="currentColor" stroke-width="2"/><circle cx="12" cy="12" r="2.5" fill="currentColor"/>',
    sidestore: '<g stroke="none"><path fill="#932dd5" d="M11.98 2.7h.04l.1.16.07.1.04.06.13.2.34.52.15.22.2.32.53.8.19.29.04.06.07.11.04.05.03.05q.02.03.02.08h-1.03v.6q.03.55-.2 1.07l-.02.07a3.2 3.2 0 0 1-1.75 1.7l-.38.12-.07.02c-.3.07-.6.06-.92.06H7.85c-.38 0-.74 0-1.1.16l-.05.02q-.34.17-.6.44l-.05.05a2 2 0 0 0 .07 2.74q.32.3.72.45l.07.02c.26.1.53.09.8.09h1.82c.96 0 1.89.24 2.61.9l.16.18.05.06c.52.61.6 1.3.6 2.08v2.57c0 .28-.04.48-.2.7l-.05.08a1 1 0 0 1-.6.29c-.32 0-.55-.07-.8-.3a1 1 0 0 1-.24-.6v-3.03q.02-.48-.3-.82c-.35-.31-.76-.3-1.2-.3H7.85c-.74 0-1.43-.11-2.08-.47l-.08-.04a3.7 3.7 0 0 1-1.52-1.57L4.15 13a3.7 3.7 0 0 1-.24-2.8 4 4 0 0 1 .92-1.51l.03-.04a4 4 0 0 1 1.69-1.03l.05-.01c.4-.12.82-.13 1.24-.13h1.77c.38 0 .38 0 .75-.1l.05-.03c.24-.1.42-.31.53-.54q.05-.11.07-.23l.02-.04.02-.23V6.1l.01-.38h-1.03l.11-.22.04-.06.04-.06.05-.07.1-.16.26-.4.14-.2.33-.5.43-.67.07-.1.07-.11.16-.25.03-.04.05-.09z"/><path fill="#932ed5" d="M7.45 10.47h12.03a1 1 0 0 1 .66.26c.2.22.27.43.27.72a1 1 0 0 1-.28.66 1 1 0 0 1-.35.2l-.06.02a1 1 0 0 1-.29.03H7.47a1 1 0 0 1-.72-.29 1 1 0 0 1-.26-.7 1 1 0 0 1 .32-.68 1 1 0 0 1 .64-.22"/><path fill="#932dd5" d="M15.64 13.56a1 1 0 0 1 .32.62v4.73c.01.37 0 .7-.26 1a1 1 0 0 1-.73.28 1 1 0 0 1-.68-.31 1 1 0 0 1-.18-.29l-.03-.06q-.04-.15-.03-.3v-4.98a1 1 0 0 1 .27-.64 1 1 0 0 1 1.32-.05"/><path fill="#9939d6" d="M14.48 13.48c0 .07 0 .07-.06.13l-.05.05-.07-.02z"/></g>',
    livecontainer: '<rect x="4" y="4" width="16" height="16" rx="4" stroke-width="2" stroke="currentColor"/><circle cx="12" cy="12" r="3" stroke-width="2" stroke="currentColor"/>',
    error: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path>'
};

export const APP_MODES = {
    standard: {
        path: 'sources/standard',
        labelKey: 'sourceStandard',
        nextMode: 'nsfw',
        theme: 'standard',
        themeColor: '#10b981',
        iconId: 'icon-standard',
        uiOffset: -24,
        faviconPath: "M21 7.5l-9-5.25L3 7.5m18 0l-9 5.25m9-5.25v9l-9 5.25M3 7.5l9 5.25M3 7.5v9l9 5.25m0-9v9"
    },
    nsfw: {
        path: 'sources/nsfw',
        labelKey: 'sourceNSFW',
        nextMode: 'all',
        theme: 'nsfw',
        themeColor: '#db2777',
        iconId: 'icon-nsfw',
        uiOffset: -48,
        faviconPath: "M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21"
    },
    all: {
        path: null,
        labelKey: 'sourceAll',
        nextMode: 'standard',
        theme: 'all',
        themeColor: '#2563eb',
        iconId: 'icon-all',
        uiOffset: 0,
        faviconPath: "M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z"
    }
};

export function getDisplayBundleId(app) {
    return app.bundleIdentifier;
}

export function resolveDownloadURL(app) {
    return app.downloadURL;
}

export const BUTTON_CONFIG = {
    download: {
        labelKey: 'ipa',
        defaultLabel: 'IPA',
        icon: 'download',
        getHref: (app) => resolveDownloadURL(app),
        getAttrs: (app) => `download="${app.name}.ipa" onclick="window.handleDownloadClick(event)"`,
    },
    altstore: {
        labelKey: 'installAltStore',
        defaultLabel: 'AltStore',
        icon: 'altstore',
        getHref: (app) => `altstore://install?url=${encodeURIComponent(resolveDownloadURL(app))}`,
        getAttrs: () => `onclick="window.handleDownloadClick(event)"`,
    },
    sidestore: {
        labelKey: 'installSideStore',
        defaultLabel: 'SideStore',
        icon: 'sidestore',
        getHref: (app) => `sidestore://install?url=${encodeURIComponent(resolveDownloadURL(app))}`,
        getAttrs: () => `onclick="window.handleDownloadClick(event)"`,
    },
    livecontainer: {
        labelKey: 'installLiveContainer',
        defaultLabel: 'LiveContainer',
        icon: 'livecontainer',
        getHref: (app) => `livecontainer://install?url=${encodeURIComponent(resolveDownloadURL(app))}`,
        getAttrs: (app) => `onclick="window.handleDownloadClick(event)"`,
    }
};

export const SORT_MODES = ['date', 'name', 'size'];
export const SORT_MAP = { 'date': 0, 'name': 1, 'size': 2 };
