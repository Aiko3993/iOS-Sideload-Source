import { getState } from './state.js';
import { fetchSource } from './data.js';

const GESTURE_SLOP_PX = 8;
const ARM_DISTANCE_PX = 110;
const OVERSHOOT_RATIO = 0.35;
const OVERSHOOT_STIFFNESS = 1.5;
const RETRACT_MS = 450;
const MIN_SPIN_MS = 600;
const RESULT_MS = { done: 900, failed: 1600 };
// Without viewport-fit=cover, iOS reports a zero top inset under the black-translucent status bar.
const IOS_STATUS_BAR_INSET = '48px';

const installedWebAppQuery = window.matchMedia('(display-mode: standalone), (display-mode: fullscreen)');
const hasTouch = 'ontouchstart' in window || navigator.maxTouchPoints > 0;

const delay = (ms) => new Promise(resolve => setTimeout(resolve, ms));

function isInstalledWebApp() {
    return installedWebAppQuery.matches || navigator.standalone === true;
}

function isModalActive() {
    if (document.body.style.overflow === 'hidden') return true;
    const modalBackdrop = document.getElementById('modal-backdrop');
    const versionsBackdrop = document.getElementById('versions-modal-backdrop');
    return (modalBackdrop && !modalBackdrop.classList.contains('hidden')) ||
           (versionsBackdrop && !versionsBackdrop.classList.contains('hidden'));
}

function startsInScrolledArea(el) {
    for (; el && el !== document.body && el !== document.documentElement; el = el.parentElement) {
        if (el.scrollTop > 0) return true;
    }
    return false;
}

function pullProgress(dy) {
    const ratio = dy / ARM_DISTANCE_PX;
    if (ratio <= 1) return Math.max(0, ratio);
    const stretch = (ratio - 1) * OVERSHOOT_STIFFNESS;
    return 1 + OVERSHOOT_RATIO * (1 - 1 / (stretch + 1));
}

export function initPullToRefresh() {
    const indicator = document.getElementById('pull-refresh-indicator');
    if (!indicator || !hasTouch) return;

    let enabled = false;
    let phase = 'idle';
    let gesture = null;
    let refreshInProgress = false;
    let retractTimer = null;

    const setPhase = (next) => {
        phase = next;
        indicator.dataset.state = next;
    };

    const setProgress = (p) => {
        indicator.style.setProperty('--ptr-p', p.toFixed(3));
        indicator.style.setProperty('--ptr-fill', Math.min(1, p).toFixed(3));
    };

    const retract = () => {
        clearTimeout(retractTimer);
        delete indicator.dataset.dragging;
        setProgress(0);
        return new Promise(resolve => {
            retractTimer = setTimeout(() => {
                setPhase('idle');
                resolve();
            }, RETRACT_MS);
        });
    };

    const syncEnabled = () => {
        enabled = isInstalledWebApp();
        document.documentElement.classList.toggle('ptr-enabled', enabled);
        if (!enabled && gesture) {
            gesture = null;
            retract();
        }
    };

    async function refresh() {
        refreshInProgress = true;
        setPhase('refreshing');
        setProgress(1);

        const started = performance.now();
        const ok = await fetchSource(getState().currentSource, true);
        await delay(Math.max(0, MIN_SPIN_MS - (performance.now() - started)));

        const result = ok === false ? 'failed' : 'done';
        setPhase(result);
        await delay(RESULT_MS[result]);
        await retract();
        refreshInProgress = false;
    }

    window.addEventListener('touchstart', (e) => {
        gesture = null;
        if (!enabled || refreshInProgress || e.touches.length !== 1) return;
        if (window.scrollY > 0 || isModalActive() || startsInScrolledArea(e.target)) return;
        gesture = { x: e.touches[0].clientX, y: e.touches[0].clientY, locked: false };
    }, { passive: true });

    window.addEventListener('touchmove', (e) => {
        if (!gesture) return;
        if (e.touches.length !== 1 || window.scrollY > 0) {
            if (gesture.locked) retract();
            gesture = null;
            return;
        }

        const dx = e.touches[0].clientX - gesture.x;
        const dy = e.touches[0].clientY - gesture.y;

        if (!gesture.locked) {
            if (Math.abs(dx) < GESTURE_SLOP_PX && Math.abs(dy) < GESTURE_SLOP_PX) return;
            if (dy <= 0 || Math.abs(dx) > Math.abs(dy)) {
                gesture = null;
                return;
            }
            gesture.locked = true;
            clearTimeout(retractTimer);
            indicator.dataset.dragging = '';
        }

        const p = pullProgress(dy);
        setProgress(p);

        const next = p >= 1 ? 'armed' : 'pulling';
        if (next !== phase) {
            if (next === 'armed' && navigator.vibrate) navigator.vibrate(10);
            setPhase(next);
        }
    }, { passive: true });

    window.addEventListener('touchend', () => {
        if (!gesture) return;
        const shouldRefresh = gesture.locked && phase === 'armed';
        const wasPulling = gesture.locked;
        gesture = null;
        delete indicator.dataset.dragging;
        if (shouldRefresh) refresh();
        else if (wasPulling) retract();
    }, { passive: true });

    window.addEventListener('touchcancel', () => {
        if (gesture && gesture.locked) retract();
        gesture = null;
    }, { passive: true });

    if (navigator.standalone === true) indicator.style.setProperty('--ptr-min-inset', IOS_STATUS_BAR_INSET);
    syncEnabled();
    installedWebAppQuery.addEventListener('change', syncEnabled);
}
