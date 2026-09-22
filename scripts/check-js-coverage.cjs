const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const coverage = JSON.parse(fs.readFileSync(path.join(root, 'quality/raw/javascript-coverage.json'), 'utf8'));
const files = fs.readdirSync(path.join(root, 'static/js'), { recursive: true })
    .filter(file => file.endsWith('.js')).map(file => path.join(root, 'static/js', file));

for (const filename of files) {
    assert(coverage[filename], 'Coverage is missing first-party JavaScript: ' + filename);
    const entry = coverage[filename];
    for (const field of ['statementMap', 'fnMap', 'branchMap', 's', 'f', 'b']) {
        assert(entry[field] && typeof entry[field] === 'object', filename + ': missing ' + field);
    }
}
assert(files.some(filename => Object.values(coverage[filename].s).some(count => count > 0)),
    'No production statements executed: check browser-script instrumentation.');
assert(files.some(filename => Object.values(coverage[filename].b).some(counts => counts.some(count => count > 0))),
    'No production branches executed: check browser-script instrumentation.');
console.log('JavaScript coverage verified: ' + files.length + ' first-party files, with executed statements and branches.');
