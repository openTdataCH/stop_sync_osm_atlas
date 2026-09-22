const loadBrowserScript = require('./load-browser-script');
const path = require('path');

// Exercise canonical adapters/layout in page tests while page lifecycle dependencies stay mocked.
module.exports = function loadMapComponents() {
    window.AppConstants = global.AppConstants = {
        ...window.AppConstants,
        MARKERS: { CLUSTER_OFFSET_RADIUS: 5, COORDINATE_TOLERANCE: 0.00001,
            DEFAULT_RADIUS: 6, DEFAULT_WEIGHT: 2, DEFAULT_FILL_OPACITY: 0.5,
            ...window.AppConstants.MARKERS }
    };
    ['map-shared', 'map-entity-adapters', 'map-renderer', 'line-renderer'].forEach(name => {
        loadBrowserScript(path.join(__dirname, '../../static/js/components/' + name + '.js'));
    });
};
