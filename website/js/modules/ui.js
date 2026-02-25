import { TRANSLATIONS, APP_MODES, getDisplayBundleId } from './config.js';
import { getIcon, formatBytes, timeAgo, cleanMarkdown, copyToClipboard, getPublicUrl, roundRect } from './utils.js';
import { getAppTheme, applyModalTheme } from './theme.js';
import { getState, setState } from './state.js';

// DOM Elements
const grid = document.getElementById('apps-grid');
const searchInput = document.getElementById('search-input');
const emptyState = document.getElementById('empty-state');
const toastContainer = document.getElementById('toast-container');

export function createInstallButtons(app, isModal = false) {
    const ic = 'w-5 h-5 flex-shrink-0 transition-transform duration-500 transform-gpu';
    const lc = 'max-w-0 opacity-0 group-hover/btn:max-w-[200px] group-hover/btn:opacity-100 group-hover/btn:ml-2 group-focus/btn:max-w-[200px] group-focus/btn:opacity-100 group-focus/btn:ml-2 group-data-[expanded=true]/btn:max-w-[200px] group-data-[expanded=true]/btn:opacity-100 group-data-[expanded=true]/btn:ml-2 transition-all duration-500 ease-[cubic-bezier(0.25,1,0.5,1)] whitespace-nowrap font-bold text-xs truncate';
    const bc = 'group/btn flex-1 h-10 rounded-xl flex items-center justify-center gap-0 transition-all duration-500 ease-[cubic-bezier(0.25,1,0.5,1)] active:scale-95 shadow-sm overflow-hidden hover:shadow-md min-w-0';

    return `<div class="flex gap-2 w-full">
                    <a href="${app.downloadURL}" onclick="window.handleDownloadClick(event)" data-is-modal="${isModal}"
                       class="${bc} bg-gray-500/5 dark:bg-white/5 text-gray-600 dark:text-gray-400 hover:bg-gray-500/10 dark:hover:bg-white/10 focus:bg-gray-500/10 dark:focus:bg-white/10 hover:flex-[3] focus:flex-[3] data-[expanded=true]:flex-[3] ring-1 ring-gray-500/20 dark:ring-white/10 hover:ring-gray-500/40 dark:hover:ring-white/20"
                       title="IPA">
                        ${getIcon('download', ic)}
                        <span class="${lc}">IPA</span>
                    </a>
                    <a href="altstore://install?url=${encodeURIComponent(app.downloadURL)}" onclick="window.handleDownloadClick(event)" data-is-modal="${isModal}"
                       class="${bc} bg-[#00A97F]/5 text-[#00A97F] hover:bg-[#00A97F]/10 focus:bg-[#00A97F]/10 hover:flex-[3] focus:flex-[3] data-[expanded=true]:flex-[3] ring-1 ring-[#00A97F]/20 hover:ring-[#00A97F]/40"
                       title="AltStore">
                        ${getIcon('altstore', ic)}
                        <span class="${lc}">AltStore</span>
                    </a>
                    <a href="sidestore://install?url=${encodeURIComponent(app.downloadURL)}" onclick="window.handleDownloadClick(event)" data-is-modal="${isModal}"
                       class="${bc} bg-[#A359FF]/5 text-[#A359FF] hover:bg-[#A359FF]/10 focus:bg-[#A359FF]/10 hover:flex-[3] focus:flex-[3] data-[expanded=true]:flex-[3] ring-1 ring-[#A359FF]/20 hover:ring-[#A359FF]/40"
                       title="SideStore">
                        ${getIcon('sidestore', ic)}
                        <span class="${lc}">SideStore</span>
                    </a>
                    <a href="livecontainer://install?url=${encodeURIComponent(app.downloadURL)}" onclick="window.handleDownloadClick(event)" data-is-modal="${isModal}"
                       class="${bc} bg-[#2563EB]/5 text-[#2563EB] hover:bg-[#2563EB]/10 focus:bg-[#2563EB]/10 hover:flex-[4] focus:flex-[4] data-[expanded=true]:flex-[4] ring-1 ring-[#2563EB]/20 hover:ring-[#2563EB]/40"
                       title="LiveContainer">
                        ${getIcon('livecontainer', ic)}
                        <span class="${lc}">LiveContainer</span>
                    </a>
                </div>`;
}

export function createFlatCard(app, index) {
    const { tint, accessibleColors, glowRgbLight, glowRgbDark } = getAppTheme(app);
    const { currentLang } = getState();
    const t = TRANSLATIONS[currentLang];

    let descSummary = app.subtitle || app.localizedDescription || app.description || "";
    descSummary = descSummary.replace(/\[([^\]]+)\]\([^\)]+\)/g, '$1').replace(/!\[[^\]]*\]\([^\)]+\)/g, '');
    if (descSummary.length > 60) descSummary = descSummary.substring(0, 60) + '...';

    const searchStr = [app.name, app.developerName, getDisplayBundleId(app), app.bundleIdentifier, app.localizedDescription, app.description].filter(Boolean).join(' ').toLowerCase().replace(/"/g, '&quot;');

    return `
        <div class="app-card group relative bg-white dark:bg-gray-900 rounded-3xl p-5 hover:-translate-y-1 transition-all duration-500 ease-[cubic-bezier(0.32,0.72,0,1)] flex flex-col h-full animate-slide-up ring-1 ring-gray-100 dark:ring-gray-800 hover:ring-2 hover:ring-primary-500/20 dark:hover:ring-primary-500/20 dynamic-app-glow group-hover:glow-active"
             data-search="${searchStr}"
             style="animation-delay: ${index * 50}ms; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05); --app-glow-light: ${glowRgbLight}; --app-glow-dark: ${glowRgbDark};">

            <!-- Glow on Hover -->
            <div class="glow-target absolute inset-0 rounded-3xl opacity-0 transition-opacity duration-500 pointer-events-none"></div>

            <div class="flex items-start justify-between mb-4 z-10">
                <div class="relative">
                     <img src="${app.iconURL}" alt="${app.name}" loading="lazy"
                         class="w-16 h-16 rounded-[1.25rem] object-cover bg-gray-100 dark:bg-gray-800 shadow-sm group-hover:shadow-md transition-all duration-300 group-hover:scale-105"
                         style="box-shadow: 0 4px 12px -2px rgba(var(--current-glow), var(--icon-glow-opacity));">
                </div>

                <div class="flex flex-col items-end gap-1.5">
                     <span class="badge-dynamic-text inline-flex items-center px-2.5 py-0.5 rounded-md text-[10px] font-bold shadow-sm border tracking-wide uppercase"
                           title="v${app.version}"
                           style="--badge-text-light: ${accessibleColors.textLight}; --badge-text-dark: ${accessibleColors.textDark}; border-color: rgba(var(--current-glow), 0.3); background-color: rgba(var(--current-glow), 0.15); color: rgb(var(--current-text));">
                        v${app.version.length > 12 ? app.version.substring(0, 10) + '...' : app.version}
                    </span>
                    <span class="text-[10px] font-medium text-gray-400 dark:text-gray-300 bg-gray-100 dark:bg-white/10 px-2 py-0.5 rounded-md">
                        ${formatBytes(app.size)}
                    </span>
                </div>
            </div>

            <div class="mb-4 z-10 flex-grow">
                <h3 class="text-lg font-bold text-gray-900 dark:text-gray-100 leading-tight mb-1 line-clamp-1 group-hover:text-[var(--app-tint-light)] dark:group-hover:text-[var(--app-tint-dark)] transition-colors duration-300"
                    title="${app.name}"
                    style="--app-tint-light: rgb(${accessibleColors.textLight}); --app-tint-dark: rgb(${accessibleColors.textDark});">
                    ${app.name}
                </h3>
                <p class="text-xs font-medium text-gray-500 dark:text-gray-400 mb-1.5 line-clamp-1 flex items-center gap-1">
                    <svg class="w-3 h-3 opacity-60" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"></path></svg>
                    ${app.developerName}
                </p>
                ${descSummary ? `<p class="text-xs text-gray-400 dark:text-gray-500 line-clamp-2 leading-relaxed">${descSummary}</p>` : ''}
            </div>

            <div class="mt-auto space-y-3 z-10">
                <div class="flex items-center justify-between text-xs text-gray-400 dark:text-gray-500 border-t border-gray-100 dark:border-white/5 pt-3 mb-1">
                     <button onclick="window.openModal('${app.bundleIdentifier}')" class="group/btn py-1 flex items-center gap-1 transition-colors"
                             style="color: rgba(var(--current-text), 0.7); --hover-color: rgb(var(--current-text));"
                             onmouseover="this.style.color='var(--hover-color)'"
                             onmouseout="this.style.color='rgba(var(--current-text), 0.7)'">
                        <span class="bg-gray-100 dark:bg-white/10 p-1 rounded-md group-hover/btn:bg-[rgba(var(--current-glow),0.1)] transition-colors">
                            <svg class="w-3.5 h-3.5 transition-transform transform-gpu" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                        </span>
                        <span class="font-medium">${t.details}</span>
                    </button>
                    <span class="font-medium opacity-70" title="${new Date(app.versionDate).toLocaleDateString()}">${timeAgo(app.versionDate, currentLang)}</span>
                </div>

                ${createInstallButtons(app)}
            </div>
        </div>
    `;
}

export function createStackCard(group, index) {
    const sortedGroup = [...group].sort((a, b) => a.name.length - b.name.length);
    const primaryApp = sortedGroup[0] || group[0];
    const { accessibleColors, glowRgbLight, glowRgbDark } = getAppTheme(primaryApp);
    const { currentLang } = getState();
    const t = TRANSLATIONS[currentLang];

    let descSummary = primaryApp.subtitle || primaryApp.localizedDescription || primaryApp.description || "";
    descSummary = descSummary.replace(/\[([^\]]+)\]\([^\)]+\)/g, '$1').replace(/!\[[^\]]*\]\([^\)]+\)/g, '');
    if (descSummary.length > 60) descSummary = descSummary.substring(0, 60) + '...';

    const repoKey = primaryApp.githubRepo || `${primaryApp.developerName}::${primaryApp.name}`;
    const searchStr = group.map(a => [a.name, a.developerName, getDisplayBundleId(a), a.bundleIdentifier, a.localizedDescription, a.description].filter(Boolean).join(' ')).join(' ').toLowerCase().replace(/"/g, '&quot;');

    const bgHTML = `
        <div class="absolute inset-0 bg-white dark:bg-gray-900 rounded-3xl ring-1 ring-gray-200 dark:ring-gray-800 transition-all duration-300 stack-bg-1 shadow-sm"></div>
        ${group.length > 2 ? '<div class="absolute inset-0 bg-white dark:bg-gray-900 rounded-3xl ring-1 ring-gray-200 dark:ring-gray-800 transition-all duration-300 stack-bg-2 shadow-sm"></div>' : ''}
    `;

    return `
        <div class="app-card group/stack relative h-full animate-slide-up select-none hover:-translate-y-1 transition-all duration-500 ease-[cubic-bezier(0.32,0.72,0,1)]"
             data-search="${searchStr}"
             style="animation-delay: ${index * 50}ms;">

            ${bgHTML}

            <div class="relative bg-white dark:bg-gray-900 rounded-3xl p-5 transition-all duration-500 ease-[cubic-bezier(0.32,0.72,0,1)] flex flex-col h-full ring-1 ring-gray-100 dark:ring-gray-800 group-hover/stack:ring-2 group-hover/stack:ring-primary-500/20 dark:group-hover/stack:ring-primary-500/20 dynamic-app-glow group-hover/stack:glow-active z-10"
                 style="box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05); --app-glow-light: ${glowRgbLight}; --app-glow-dark: ${glowRgbDark};">

                <div class="glow-target absolute inset-0 rounded-3xl opacity-0 transition-opacity duration-500 pointer-events-none"></div>

                <div class="flex items-start justify-between mb-4 z-10">
                    <div class="relative">
                         <img src="${primaryApp.iconURL}" alt="${primaryApp.name}" loading="lazy"
                             class="w-16 h-16 rounded-[1.25rem] object-cover bg-gray-100 dark:bg-gray-800 shadow-sm group-hover/stack:shadow-md transition-all duration-300 group-hover/stack:scale-105"
                             style="box-shadow: 0 4px 12px -2px rgba(var(--current-glow), var(--icon-glow-opacity));">
                    </div>

                    <div class="flex flex-col items-end gap-1.5">
                         <span class="badge-dynamic-text inline-flex items-center px-2.5 py-0.5 rounded-md text-[10px] font-bold shadow-sm border tracking-wide uppercase"
                               title="v${primaryApp.version}"
                               style="--badge-text-light: ${accessibleColors.textLight}; --badge-text-dark: ${accessibleColors.textDark}; border-color: rgba(var(--current-glow), 0.3); background-color: rgba(var(--current-glow), 0.15); color: rgb(var(--current-text));">
                            v${primaryApp.version.length > 12 ? primaryApp.version.substring(0, 10) + '...' : primaryApp.version}
                        </span>
                        <span class="text-[10px] font-medium text-gray-400 dark:text-gray-300 bg-gray-100 dark:bg-white/10 px-2 py-0.5 rounded-md">
                            ${formatBytes(primaryApp.size)}
                        </span>
                    </div>
                </div>

                <div class="mb-4 z-10 flex-grow">
                    <h3 class="text-lg font-bold text-gray-900 dark:text-gray-100 leading-tight mb-1 line-clamp-1 group-hover/stack:text-[var(--app-tint-light)] dark:group-hover/stack:text-[var(--app-tint-dark)] transition-colors duration-300"
                        title="${primaryApp.name}"
                        style="--app-tint-light: rgb(${accessibleColors.textLight}); --app-tint-dark: rgb(${accessibleColors.textDark});">
                        ${primaryApp.name}
                    </h3>
                    <p class="text-xs font-medium text-gray-500 dark:text-gray-400 mb-1.5 line-clamp-1 flex items-center gap-1">
                        <svg class="w-3 h-3 opacity-60" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"></path></svg>
                        ${primaryApp.developerName}
                    </p>
                    ${descSummary ? `<p class="text-xs text-gray-400 dark:text-gray-500 line-clamp-2 leading-relaxed">${descSummary}</p>` : ''}
                </div>

                <div class="mt-auto space-y-3 z-10">
                    <div class="flex items-center justify-between text-xs text-gray-400 dark:text-gray-500 border-t border-gray-100 dark:border-white/5 pt-3 mb-1">
                         <div class="flex items-center gap-2">
                             <button onclick="window.openModal('${primaryApp.bundleIdentifier}')" class="group/btn py-1 flex items-center gap-1 transition-colors"
                                     style="color: rgba(var(--current-text), 0.7); --hover-color: rgb(var(--current-text));"
                                     onmouseover="this.style.color='var(--hover-color)'"
                                     onmouseout="this.style.color='rgba(var(--current-text), 0.7)'">
                                <span class="bg-gray-100 dark:bg-white/10 p-1 rounded-md group-hover/btn:bg-[rgba(var(--current-glow),0.1)] transition-colors">
                                    <svg class="w-3.5 h-3.5 transition-transform transform-gpu" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                                </span>
                                <span class="font-medium">${t.details}</span>
                            </button>
                            <button onclick="window.openVersionsModal('${repoKey}')" class="group/btn py-1 flex items-center gap-1 transition-colors"
                                     style="color: rgba(var(--current-text), 0.7); --hover-color: rgb(var(--current-text));"
                                     onmouseover="this.style.color='var(--hover-color)'"
                                     onmouseout="this.style.color='rgba(var(--current-text), 0.7)'">
                                <span class="bg-gray-100 dark:bg-white/10 p-1 rounded-md group-hover/btn:bg-[rgba(var(--current-glow),0.1)] transition-colors">
                                    <svg class="w-3.5 h-3.5 transition-transform transform-gpu" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"></path></svg>
                                </span>
                                <span class="font-medium">Editions (${group.length})</span>
                            </button>
                         </div>
                         <span class="font-medium opacity-70" title="${new Date(primaryApp.versionDate).toLocaleDateString()}">${timeAgo(primaryApp.versionDate, currentLang)}</span>
                    </div>

                    ${createInstallButtons(primaryApp)}
                </div>
            </div>
        </div>
    `;
}

export function openVersionsModal(repoKey) {
    const { currentApps, currentLang } = getState();
    const t = TRANSLATIONS[currentLang];

    // Exact match the group key created in renderApps()
    const group = currentApps.filter(a => (a.githubRepo || `${a.developerName}::${a.name}`) === repoKey);
    if (!group.length) return;

    group.sort((a, b) => a.name.length - b.name.length);
    const primaryApp = group[0];

    document.getElementById('versions-modal-icon').src = primaryApp.iconURL;
    document.getElementById('versions-modal-title').textContent = primaryApp.githubRepo ? primaryApp.githubRepo.split('/')[1] : primaryApp.name;
    document.getElementById('versions-modal-count').textContent = `${group.length} Editions Available`;

    const listHtml = group.map(app => {
        return `
            <div class="bg-white dark:bg-white/5 p-4 rounded-[1.25rem] flex flex-col gap-4 ring-1 ring-gray-100 dark:ring-white/5 shadow-sm hover:shadow-md transition-shadow">
                <div class="flex items-start justify-between gap-4">
                    <div class="flex-1 min-w-0">
                        <h4 class="font-bold text-[17px] text-gray-900 dark:text-gray-100 truncate">${app.name}</h4>
                        <p class="text-[11px] text-gray-500 dark:text-gray-400 mt-1.5 flex items-center flex-wrap gap-1.5">
                            <span class="font-bold bg-gray-100 dark:bg-gray-800 px-2 py-0.5 rounded-md text-[10px] uppercase text-gray-600 dark:text-gray-300">v${app.version}</span>
                            <span class="w-1 h-1 rounded-full bg-gray-300 dark:bg-gray-600"></span>
                            <span>${formatBytes(app.size)}</span>
                            <span class="w-1 h-1 rounded-full bg-gray-300 dark:bg-gray-600"></span>
                            <span>${new Date(app.versionDate).toLocaleDateString()}</span>
                        </p>
                    </div>
                    <button onclick="window.closeVersionsModal(); setTimeout(() => window.openModal('${app.bundleIdentifier}'), 300);" class="flex-shrink-0 p-2 rounded-xl bg-gray-100 dark:bg-white/10 text-gray-400 hover:text-gray-600 dark:text-gray-400 dark:hover:text-gray-200 transition-colors mt-0.5" title="${t.details || 'Details'}">
                        ${getIcon('details', 'w-5 h-5')}
                    </button>
                </div>
                <div class="w-full">
                    ${createInstallButtons(app, true)}
                </div>
            </div>
        `;
    }).join('');

    document.getElementById('versions-modal-list').innerHTML = listHtml;

    const backdrop = document.getElementById('versions-modal-backdrop');
    const panel = document.getElementById('versions-modal-panel');
    const panelInner = panel.firstElementChild;

    document.body.style.overflow = 'hidden';
    backdrop.classList.remove('hidden');
    panel.classList.remove('hidden');

    // Force reflow
    void panel.offsetWidth;

    backdrop.classList.remove('opacity-0');
    panelInner.classList.remove('translate-y-full', 'sm:scale-95', 'opacity-0');
    panelInner.classList.add('translate-y-0', 'sm:scale-100', 'opacity-100');
}

export function closeVersionsModal() {
    const backdrop = document.getElementById('versions-modal-backdrop');
    const panel = document.getElementById('versions-modal-panel');
    if (!panel) return;
    const panelInner = panel.firstElementChild;
    if (!backdrop || backdrop.classList.contains('hidden')) return;

    backdrop.classList.add('opacity-0');
    panelInner.classList.remove('translate-y-0', 'sm:scale-100', 'opacity-100');
    panelInner.classList.add('translate-y-full', 'sm:scale-95', 'opacity-0');

    setTimeout(() => {
        backdrop.classList.add('hidden');
        panel.classList.add('hidden');
        if (!document.getElementById('modal-backdrop') || document.getElementById('modal-backdrop').classList.contains('opacity-0')) {
            document.body.style.overflow = '';
        }
    }, 500);
}

export function renderApps() {
    const { currentApps, currentSort, currentLang } = getState();

    let sorted = [...currentApps];

    sorted.sort((a, b) => {
        switch (currentSort) {
            case 'date': return new Date(b.versionDate) - new Date(a.versionDate);
            case 'name': return a.name.localeCompare(b.name);
            case 'size': return b.size - a.size;
            default: return 0;
        }
    });

    // Group apps by githubRepo (or developerName::name if omitted)
    const groups = new Map();
    sorted.forEach(app => {
        const key = app.githubRepo || `${app.developerName}::${app.name}`;
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(app);
    });

    const groupedArray = Array.from(groups.values());
    grid.innerHTML = groupedArray.map((group, index) => {
        if (group.length > 1) {
            return createStackCard(group, index);
        }
        return createFlatCard(group[0], index);
    }).join('');

    filterApps();
}

export function filterApps(isSearchEvent = false) {
    if (!searchInput) return;
    const query = searchInput.value.toLowerCase().trim();
    let visibleCount = 0;
    const cards = grid.querySelectorAll('.app-card');

    cards.forEach(card => {
        if (isSearchEvent) card.classList.remove('animate-slide-up');
        if (!query || card.dataset.search.includes(query)) {
            card.style.display = '';
            visibleCount++;
        } else {
            card.style.display = 'none';
        }
    });

    if (visibleCount === 0) {
        emptyState.classList.remove('hidden');
    } else {
        emptyState.classList.add('hidden');
    }
}

export function updateLanguage(lang) {
    setState('currentLang', lang);
    const t = TRANSLATIONS[lang];
    document.querySelectorAll('[data-i18n]').forEach(el => {
        const key = el.getAttribute('data-i18n');
        if (t[key]) el.textContent = t[key];
    });
    if (searchInput) searchInput.placeholder = t.searchPlaceholder;

    const { currentSource, currentApps } = getState();
    updateSourceUI(currentSource);
    if (currentApps.length > 0) renderApps();
}

export function showToast(message, type = 'success') {
    const toast = document.createElement('div');
    toast.className = `flex items-center gap-3 px-4 py-3 rounded-xl shadow-xl border backdrop-blur-md animate-slide-up transform transition-all duration-300 ${type === 'success'
        ? 'bg-white/90 dark:bg-gray-800/90 border-green-200 dark:border-green-900 text-green-700 dark:text-green-400'
        : 'bg-white/90 dark:bg-gray-800/90 border-red-200 dark:border-red-900 text-red-700 dark:text-red-400'
        }`;
    const icon = type === 'success' ? getIcon('check', 'w-5 h-5') : getIcon('close', 'w-5 h-5');
    toast.innerHTML = `${icon}<span class="text-sm font-medium">${message}</span>`;
    toastContainer.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(10px)';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

export function copySourceURL(specificSource = null) {
    const { currentSource, currentLang } = getState();
    const targetMode = specificSource || currentSource;
    const key = (targetMode === 'all') ? 'standard' : targetMode;
    const fullUrl = getPublicUrl(APP_MODES[key]?.path || APP_MODES['standard'].path);
    const t = TRANSLATIONS[currentLang];
    const name = t[APP_MODES[key].labelKey];
    copyToClipboard(fullUrl, `${name} ${t.sourceCopied}`, t.copyFailed, showToast);
}

export function updateSourceUI(activeKey) {
    const track = document.getElementById('source-label-track');
    const mode = APP_MODES[activeKey];
    if (track && mode) {
        track.style.transform = `translateY(${mode.uiOffset}px)`;
        updateCopyButtonUI(activeKey);
    }
}

export function updateCopyButtonUI(mode) {
    const wrapper = document.getElementById('copy-btn-wrapper');
    if (!wrapper) return;
    wrapper.style.transform = 'scale(1)';
    wrapper.style.opacity = '1';

    if (mode === 'all') {
        wrapper.className = "flex flex-col items-center justify-center gap-1.5 transition-all duration-300 ease-out flex-shrink-0 min-w-[40px]";
        const btnClass = 'hover:bg-emerald-50 dark:hover:bg-emerald-900/30';
        const btnClass2 = 'hover:bg-pink-50 dark:hover:bg-pink-900/30';

        wrapper.innerHTML = `
            <button onclick="window.copySourceURL('standard')" class="p-1.5 rounded-lg text-emerald-500 ${btnClass} transition-all active:scale-95 group/std" title="Copy Standard Source" style="animation: split-up 0.3s ease-out forwards;">${getIcon('copy', 'w-4 h-4')}</button>
            <button onclick="window.copySourceURL('nsfw')" class="p-1.5 rounded-lg text-pink-500 ${btnClass2} transition-all active:scale-95 group/nsfw" title="Copy NSFW Source" style="animation: split-down 0.3s ease-out forwards;">${getIcon('copy', 'w-4 h-4')}</button>
        `;
    } else {
        wrapper.className = "flex flex-col items-center justify-center gap-1.5 transition-all duration-300 ease-out flex-shrink-0 min-w-[40px]";
        // Standard (or others) now gets colored by default (Emerald) instead of gray
        let colorClass = mode === 'nsfw'
            ? 'text-pink-500 hover:bg-pink-50 dark:hover:bg-pink-900/30'
            : 'text-emerald-500 hover:bg-emerald-50 dark:hover:bg-emerald-900/30';

        wrapper.innerHTML = `<button onclick="window.copySourceURL('${mode}')" class="p-2 rounded-xl ${colorClass} transition-all active:scale-95" title="Copy Source URL">${getIcon('copy', 'w-5 h-5')}</button>`;
    }
}

export function updateHeaderIcon(sourceKey) {
    const mode = APP_MODES[sourceKey];
    ['icon-standard', 'icon-nsfw', 'icon-all'].forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            if (id === mode.iconId) el.classList.remove('hidden');
            else el.classList.add('hidden');
        }
    });
}

export function updateFavicon(sourceKey) {
    const mode = APP_MODES[sourceKey];
    let link = document.querySelector("link[rel~='icon']");
    if (!link) {
        link = document.createElement('link');
        link.rel = 'icon';
        document.head.appendChild(link);
    }
    const canvas = document.createElement('canvas');
    canvas.width = 64; canvas.height = 64;
    const ctx = canvas.getContext('2d');
    if (!ctx) return; // Safety check
    ctx.fillStyle = mode.themeColor;
    ctx.clearRect(0, 0, 64, 64);
    ctx.beginPath();
    roundRect(ctx, 0, 0, 64, 64, 14);
    ctx.fill();
    ctx.strokeStyle = 'white';
    ctx.lineWidth = 3; ctx.lineCap = 'round'; ctx.lineJoin = 'round'; ctx.fillStyle = 'none';
    ctx.save();
    ctx.translate(32, 32); ctx.scale(1.6, 1.6); ctx.translate(-12, -12);
    const p = new Path2D(mode.faviconPath);
    ctx.stroke(p);
    ctx.restore();
    link.href = canvas.toDataURL();
}

// Modal Logic
export function openModal(identifier) {
    const { currentApps, currentLang } = getState();
    const app = currentApps.find(a => a.bundleIdentifier === identifier || a.name === identifier);
    if (!app) return;
    const theme = getAppTheme(app);
    applyModalTheme(theme);
    renderModalHeader(app);
    document.getElementById('modal-meta-grid').innerHTML = buildModalMeta(app, currentLang);
    document.getElementById('modal-content').innerHTML = buildModalContent(app, currentLang);

    const modalBackdrop = document.getElementById('modal-backdrop');
    const modalPanel = document.getElementById('modal-panel');
    const modalContentPanel = modalPanel.querySelector('div');

    document.body.style.overflow = 'hidden';
    modalBackdrop.classList.remove('hidden');
    modalPanel.classList.remove('hidden');

    void modalPanel.offsetWidth;

    modalBackdrop.classList.remove('opacity-0');
    modalContentPanel.classList.remove('translate-y-full', 'sm:scale-95', 'opacity-0');
    modalContentPanel.classList.add('translate-y-0', 'sm:scale-100', 'opacity-100');
}

export function closeModal() {
    const modalBackdrop = document.getElementById('modal-backdrop');
    const modalPanel = document.getElementById('modal-panel');
    const modalContentPanel = modalPanel.querySelector('div');
    modalBackdrop.classList.add('opacity-0');
    modalContentPanel.classList.remove('translate-y-0', 'sm:scale-100', 'opacity-100');
    modalContentPanel.classList.add('translate-y-full', 'sm:scale-95', 'opacity-0');
    setTimeout(() => {
        modalBackdrop.classList.add('hidden');
        modalPanel.classList.add('hidden');
        document.body.style.overflow = '';
    }, 500);
}

function renderModalHeader(app) {
    const modalTitle = document.getElementById('modal-title');
    const modalVersionBadge = document.getElementById('modal-version-badge');
    const modalSize = document.getElementById('modal-size');
    const modalIcon = document.getElementById('modal-icon');

    modalTitle.textContent = app.name;
    modalTitle.className = "text-2xl font-bold leading-tight mb-0.5 text-[var(--modal-tint-light)] dark:text-[var(--modal-tint-dark)] transition-colors duration-300";

    // Show subtitle under app name if available
    const subtitleEl = document.getElementById('modal-subtitle');
    if (subtitleEl) {
        if (app.subtitle) {
            subtitleEl.textContent = app.subtitle;
            subtitleEl.className = "text-xs text-gray-500 dark:text-gray-400 mb-1 line-clamp-2 leading-relaxed";
            subtitleEl.style.display = '';
        } else {
            subtitleEl.style.display = 'none';
        }
    }

    modalVersionBadge.textContent = `v${app.version.length > 12 ? app.version.substring(0, 10) + '...' : app.version}`;
    modalVersionBadge.title = `v${app.version}`;
    modalVersionBadge.style.cssText = `background-color: rgba(var(--current-modal-glow), 0.15); color: rgb(var(--current-modal-text)); border-color: rgba(var(--current-modal-glow), 0.3);`;
    modalSize.textContent = formatBytes(app.size);
    modalIcon.src = app.iconURL;
    modalIcon.className = "w-14 h-14 rounded-xl bg-gray-100 dark:bg-gray-800 object-cover shadow-sm modal-icon-shadow-glow";
}

function buildModalMeta(app, currentLang) {
    const t = TRANSLATIONS[currentLang];
    let html = `<div class="bg-gray-50 dark:bg-white/5 p-3 rounded-xl border border-gray-100 dark:border-white/5 ${app.minOSVersion ? '' : 'col-span-2'}">
            <div class="text-[10px] uppercase tracking-wider text-gray-400 dark:text-gray-500 font-bold mb-0.5">${t.bundleId}</div>
            <div class="text-xs font-mono text-gray-600 dark:text-gray-200 break-all select-all">${getDisplayBundleId(app)}</div>
        </div>`;
    if (app.minOSVersion) html += `<div class="bg-gray-50 dark:bg-white/5 p-3 rounded-xl border border-gray-100 dark:border-white/5">
            <div class="text-[10px] uppercase tracking-wider text-gray-400 dark:text-gray-500 font-bold mb-0.5">${t.minOs}</div>
            <div class="text-xs font-medium text-gray-600 dark:text-gray-200">${app.minOSVersion}</div>
        </div>`;
    if (app.versionDate) html += `<div class="bg-gray-50 dark:bg-white/5 p-3 rounded-xl border border-gray-100 dark:border-white/5">
            <div class="text-[10px] uppercase tracking-wider text-gray-400 dark:text-gray-500 font-bold mb-0.5">${t.updated}</div>
            <div class="text-xs font-medium text-gray-600 dark:text-gray-200">${new Date(app.versionDate).toLocaleDateString()}</div>
        </div>`;
    if (app.developerName) html += `<div class="bg-gray-50 dark:bg-white/5 p-3 rounded-xl border border-gray-100 dark:border-white/5">
            <div class="text-[10px] uppercase tracking-wider text-gray-400 dark:text-gray-500 font-bold mb-0.5">${t.developer}</div>
            <div class="text-xs font-medium text-gray-600 dark:text-gray-200 truncate">${app.developerName}</div>
        </div>`;
    return html;
}

function buildModalContent(app, currentLang) {
    const t = TRANSLATIONS[currentLang];
    const desc = app.localizedDescription || app.description || t.noDescription;
    const changelog = app.versionDescription || t.noChangelog;
    let html = `<div class="mb-8">
            <h4 class="text-xs font-bold uppercase tracking-wider mb-3 opacity-70" style="color: rgb(var(--current-modal-text))">${t.description}</h4>
            <div class="markdown-body text-sm bg-transparent leading-relaxed text-gray-600 dark:text-gray-300">${marked.parse(cleanMarkdown(desc), { breaks: true, gfm: true })}</div>
        </div>`;
    if (changelog && changelog !== t.noChangelog) html += `<div class="mb-4 pt-6 border-t border-gray-100 dark:border-white/5">
            <h4 class="text-xs font-bold uppercase tracking-wider mb-3 opacity-70" style="color: rgb(var(--current-modal-text))">${t.whatsNew}</h4>
            <div class="markdown-body text-sm bg-transparent leading-relaxed text-gray-600 dark:text-gray-300">${marked.parse(cleanMarkdown(changelog), { breaks: true, gfm: true })}</div>
        </div>`;
    return html;
}

function buildModalFooter(currentLang) {
    const t = TRANSLATIONS[currentLang];
    return `<button onclick="window.closeModal()" class="w-full py-3.5 rounded-xl font-bold shadow-sm active:scale-95 transition-all duration-200 flex items-center justify-center gap-2 bg-gray-100 dark:bg-white/10 text-gray-900 dark:text-white hover:bg-gray-200 dark:hover:bg-white/20"><span class="tracking-wide">${t.close}</span></button>`;
}

export function collapseAllExpanded() {
    document.querySelectorAll('[data-expanded="true"]').forEach(el => delete el.dataset.expanded);
}

export function handleDownloadClick(e) {
    const { isMobile } = window;
    if (typeof isMobile === 'function' && !isMobile()) return;
    const btn = e.currentTarget;
    const isExpanded = btn.dataset.expanded === 'true';
    if (!isExpanded) {
        e.preventDefault();
        e.stopPropagation();
        collapseAllExpanded();
        btn.dataset.expanded = 'true';
        if (navigator.vibrate) navigator.vibrate(10);
    } else {
        if (navigator.vibrate) navigator.vibrate(20);
        setTimeout(() => delete btn.dataset.expanded, 1000);
        if (btn.dataset.isModal === 'true' && typeof window.closeVersionsModal === 'function') {
            window.closeVersionsModal();
        }
    }
}
