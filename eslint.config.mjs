import globals from 'globals';

// Classic browser scripts publish these entry points across ordered script tags.
const browserEntrypoints = Object.fromEntries([
    '$', 'L', 'bootstrap', 'mermaid',
    'AppConstants', 'FilterChipUtils', 'HeaderSummary', 'LineRenderer',
    'MapComponents', 'MapCore', 'MapEntityAdapters', 'MapLayerRegistry',
    'MapPopupController', 'MapRenderer', 'MapShared', 'MapViewportLoader',
    'MobileFilters', 'OperatorDropdown', 'PopupRenderer', 'PopupUtils',
    'ProblemsData', 'ProblemsMap', 'ProblemsRenderer', 'ProblemsState', 'ProblemsUI',
    'SharedUtils', 'activeFilters', 'topNLayer', 'stopsById',
    'fetchAndCenterSpecificStop', 'loadDataForViewport', 'updateHeaderSummary',
    'loadTopNMatches', 'initFilterEventHandlers', 'updateFiltersUI',
    'updateActiveFilters', 'getActiveFilterCount', 'parseSmartSearchInput'
].map(name => [name, 'readonly']));

const correctness = {
    'constructor-super': 'error',
    'for-direction': 'error',
    'getter-return': 'error',
    'no-async-promise-executor': 'error',
    'no-const-assign': 'error',
    'no-dupe-args': 'error',
    'no-dupe-else-if': 'error',
    'no-dupe-keys': 'error',
    'no-duplicate-case': 'error',
    'no-func-assign': 'error',
    'no-import-assign': 'error',
    'no-unreachable': 'error',
    'no-unsafe-finally': 'error',
    'no-unsafe-negation': 'error',
    'no-undef': 'error',
    'no-unused-vars': ['error', { vars: 'local', args: 'none', caughtErrors: 'none' }],
    'valid-typeof': 'error'
};

export default [
    { ignores: ['static/vendor/**', 'node_modules/**', 'quality/raw/**'] },
    {
        files: ['static/js/**/*.js', 'tests/js/**/*.js', 'tests/js/**/*.cjs', 'scripts/**/*.mjs', 'scripts/**/*.cjs', 'scripts/**/*.js'],
        languageOptions: { globals: { ...globals.browser, ...browserEntrypoints } },
        rules: correctness
    },
    {
        files: ['static/js/**/*.js'],
        languageOptions: { sourceType: 'script' }
    },
    {
        files: ['tests/js/**/*.js', 'tests/js/**/*.cjs'],
        languageOptions: { sourceType: 'commonjs', globals: { ...globals.node, ...globals.jest } }
    },
    {
        files: ['tests/js/**/*.test.js', 'tests/js/setup.js', 'tests/js/load-map-components.js'],
        rules: {
            'no-restricted-syntax': ['error', {
                selector: "CallExpression[callee.property.name='eval']",
                message: 'Use load-browser-script so production browser code is included in coverage.'
            }]
        }
    },
    {
        files: ['scripts/**'],
        languageOptions: { globals: globals.node }
    }
];
