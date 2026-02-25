
// State Management
const state = {
    currentApps: [],
    currentSource: 'standard',
    currentSort: 'date',
    currentLang: 'en',
    coexistMode: false,
    themeCache: new Map()
};

export const getState = () => state;

export const setState = (key, value) => {
    state[key] = value;
};

export const getThemeCache = () => state.themeCache;
