import { TRANSLATIONS } from './config.js';
import { getState } from './state.js';
import { fetchSource } from './data.js';

let startY = 0;
let currentY = 0;
let isPulling = false;
let isRefreshing = false;
const THRESHOLD = 60;
const MAX_PULL = 88;

export function initPullToRefresh() {
    const indicator = document.getElementById('pull-refresh-indicator');
    const pill = document.getElementById('pull-refresh-pill');
    const icon = document.getElementById('pull-refresh-icon');
    const spinner = document.getElementById('pull-refresh-spinner');
    const label = document.getElementById('pull-refresh-label');
    if (!indicator || !pill || !icon || !spinner || !label) return;

    function isModalActive() {
        if (document.body.style.overflow === 'hidden') return true;
        const modalBackdrop = document.getElementById('modal-backdrop');
        const versionsBackdrop = document.getElementById('versions-modal-backdrop');
        return (modalBackdrop && !modalBackdrop.classList.contains('hidden')) ||
               (versionsBackdrop && !versionsBackdrop.classList.contains('hidden'));
    }

    let hasVibrated = false;

    window.addEventListener('touchstart', (e) => {
        if (isRefreshing || isModalActive()) return;
        if (e.target && e.target.closest('#modal-panel, #versions-modal-panel, #modal-backdrop, #versions-modal-backdrop')) return;
        if (window.scrollY > 0 || document.documentElement.scrollTop > 0) return;
        if (!e.touches || e.touches.length !== 1) return;

        indicator.style.transition = '';
        startY = e.touches[0].clientY;
        currentY = startY;
        isPulling = false;
        hasVibrated = false;
    }, { passive: true });

    window.addEventListener('touchmove', (e) => {
        if (!startY || isRefreshing || isModalActive()) return;
        if (window.scrollY > 0 || document.documentElement.scrollTop > 0) {
            startY = 0;
            resetIndicator();
            return;
        }
        if (!e.touches || e.touches.length !== 1) return;

        currentY = e.touches[0].clientY;
        const delta = currentY - startY;

        if (delta > 8) {
            isPulling = true;
            const pullDistance = Math.min(MAX_PULL, (delta - 8) * 0.4);
            const progress = Math.min(1, pullDistance / THRESHOLD);

            indicator.style.transform = `translateY(${pullDistance}px)`;
            indicator.style.opacity = progress.toFixed(2);
            pill.style.transform = `scale(${0.92 + 0.08 * progress})`;

            const { currentLang } = getState();
            const t = TRANSLATIONS[currentLang] || TRANSLATIONS.en;

            if (pullDistance >= THRESHOLD) {
                icon.style.transform = 'rotate(180deg)';
                label.textContent = t.releaseToRefresh || 'Release to refresh';
                if (!hasVibrated) {
                    if (navigator.vibrate) navigator.vibrate(12);
                    hasVibrated = true;
                }
            } else {
                icon.style.transform = 'rotate(0deg)';
                label.textContent = t.pullToRefresh || 'Pull to refresh';
                hasVibrated = false;
            }
        }
    }, { passive: true });

    window.addEventListener('touchend', async () => {
        if (!isPulling || isRefreshing) {
            startY = 0;
            isPulling = false;
            return;
        }

        const delta = currentY - startY;
        const pullDistance = Math.min(MAX_PULL, (delta - 8) * 0.4);
        startY = 0;
        isPulling = false;

        indicator.style.transition = 'transform 0.35s cubic-bezier(0.32, 0.72, 0, 1), opacity 0.35s ease';

        if (pullDistance >= THRESHOLD) {
            isRefreshing = true;
            indicator.style.transform = `translateY(${THRESHOLD}px)`;
            indicator.style.opacity = '1';
            pill.style.transform = 'scale(1)';
            icon.classList.add('hidden');
            spinner.classList.remove('hidden');

            const { currentLang, currentSource } = getState();
            const t = TRANSLATIONS[currentLang] || TRANSLATIONS.en;
            label.textContent = t.refreshing || 'Refreshing...';

            try {
                await fetchSource(currentSource, true);
                label.textContent = t.refreshed || 'Updated';
            } catch (err) {
                console.error(err);
            }

            setTimeout(() => {
                resetIndicator();
                setTimeout(() => {
                    isRefreshing = false;
                }, 350);
            }, 600);
        } else {
            resetIndicator();
        }
    }, { passive: true });

    function resetIndicator() {
        indicator.style.transform = '';
        indicator.style.opacity = '';
        pill.style.transform = '';
        icon.classList.remove('hidden');
        icon.style.transform = '';
        spinner.classList.add('hidden');
        const { currentLang } = getState();
        const t = TRANSLATIONS[currentLang] || TRANSLATIONS.en;
        label.textContent = t.pullToRefresh || 'Pull to refresh';
    }
}
