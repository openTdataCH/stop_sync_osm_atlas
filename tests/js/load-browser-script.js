const fs = require('node:fs');
const path = require('node:path');
const { createInstrumenter } = require('istanbul-lib-instrument');

const scripts = new Map();

/** Evaluate browser globals as script tags do, while recording real source coverage. */
module.exports = function loadBrowserScript(filename) {
    const absolutePath = path.resolve(filename);
    if (!scripts.has(absolutePath)) {
        const instrumenter = createInstrumenter({ produceSourceMap: true });
        const source = fs.readFileSync(absolutePath, 'utf8');
        scripts.set(absolutePath, instrumenter.instrumentSync(source, absolutePath));
    }
    window.eval(scripts.get(absolutePath) + '\n//# sourceURL=' + absolutePath);
};

/** Load one map component as the only script that has defined window.MapComponents. */
module.exports.loadMapComponent = function loadMapComponent(name) {
    window.MapComponents = undefined;
    module.exports(path.join(__dirname, '../../static/js/components', name + '.js'));
};
