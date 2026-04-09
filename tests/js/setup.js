/**
 * Jest Test Setup
 * 
 * This file runs before each test file and sets up the global environment
 * to simulate the browser environment with Leaflet.js and jQuery mocks.
 */

// Mock Leaflet.js
global.L = {
    polyline: jest.fn(() => ({
        addTo: jest.fn().mockReturnThis(),
        remove: jest.fn(),
        getBounds: jest.fn(),
        setStyle: jest.fn(),
        bindPopup: jest.fn().mockReturnThis(),
        on: jest.fn().mockReturnThis()
    })),
    marker: jest.fn(() => ({
        addTo: jest.fn().mockReturnThis(),
        remove: jest.fn(),
        bindPopup: jest.fn().mockReturnThis(),
        on: jest.fn().mockReturnThis(),
        setIcon: jest.fn()
    })),
    layerGroup: jest.fn(() => ({
        addTo: jest.fn().mockReturnThis(),
        clearLayers: jest.fn(),
        addLayer: jest.fn(),
        removeLayer: jest.fn(),
        eachLayer: jest.fn()
    })),
    map: jest.fn(() => ({
        getZoom: jest.fn().mockReturnValue(15),
        setView: jest.fn(),
        on: jest.fn(),
        fitBounds: jest.fn()
    })),
    latLng: jest.fn((lat, lng) => ({ lat, lng })),
    latLngBounds: jest.fn(() => ({
        extend: jest.fn().mockReturnThis(),
        isValid: jest.fn().mockReturnValue(true)
    })),
    icon: jest.fn(() => ({})),
    divIcon: jest.fn(() => ({}))
};

// Mock jQuery ($)
global.$ = jest.fn(() => ({
    val: jest.fn().mockReturnValue(''),
    text: jest.fn(),
    html: jest.fn(),
    on: jest.fn(),
    off: jest.fn(),
    click: jest.fn(),
    show: jest.fn(),
    hide: jest.fn(),
    addClass: jest.fn(),
    removeClass: jest.fn(),
    toggleClass: jest.fn(),
    hasClass: jest.fn().mockReturnValue(false),
    prop: jest.fn(),
    attr: jest.fn(),
    css: jest.fn(),
    find: jest.fn().mockReturnThis(),
    each: jest.fn(),
    append: jest.fn(),
    remove: jest.fn(),
    empty: jest.fn()
}));

global.$.ajax = jest.fn();
global.$.get = jest.fn();
global.$.post = jest.fn();

// Mock window.AppConstants
global.AppConstants = {
    ZOOM_LINE_THRESHOLD: 13,
    ZOOM_MARKER_THRESHOLD: 13,
    LINE_STYLES: {
        MATCHED: { color: '#174092', weight: 2, opacity: 0.8 },
        SUSPICIOUS: { color: '#ffc107', weight: 2, opacity: 0.8, dashArray: '5, 5' },
        MANUAL: { color: '#174092', weight: 2, opacity: 0.8 },
        DEFAULT: { color: '#6c757d', weight: 2, opacity: 0.6 }
    }
};

// Mock console methods to reduce noise in tests (optional)
// Uncomment if you want to suppress console output during tests
// global.console = {
//     ...console,
//     log: jest.fn(),
//     warn: jest.fn(),
//     error: jest.fn()
// };

// Reset mocks before each test
beforeEach(() => {
    jest.clearAllMocks();
});
