const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

// Each probe would pass on its own; the strict environment must fail every one
// except the last. One probe per file, so each gets a fresh environment, all
// in one nested Jest run.
const REJECTED = {
    'console error': ["console.error('quality-probe');", /Unexpected console.error/],
    'browser exception': ["setTimeout(() => { throw new Error('quality-probe'); }, 0);", /quality-probe/],
    'unhandled rejection': ["Promise.reject(new Error('quality-probe'));", /quality-probe/],
    'pending timer': ['setTimeout(() => {}, 60000);', /Leaked browser work/],
    'discarded fake timer': ['jest.useFakeTimers(); setTimeout(() => {}, 60000); jest.useRealTimers();', /Leaked fake browser timers/]
};
const ACCEPTED = `
    const error = jest.spyOn(console, 'error').mockImplementation(() => {});
    console.error('expected');
    expect(error).toHaveBeenCalledWith('expected');
    error.mockRestore();
    const timer = setTimeout(() => {}, 60000);
    clearTimeout(timer);
    jest.useFakeTimers();
    const fakeTimer = setTimeout(() => {}, 60000);
    clearTimeout(fakeTimer);
    jest.useRealTimers();
`;

const fileName = name => name.replace(/ /g, '-') + '.test.js';
let results;

beforeAll(() => {
    const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'atlas-jest-'));
    try {
        const probes = { ...Object.fromEntries(Object.entries(REJECTED).map(([name, [body]]) => [name, body])), accepted: ACCEPTED };
        for (const [name, body] of Object.entries(probes)) {
            fs.writeFileSync(path.join(directory, fileName(name)), `test('probe', () => { ${body} });`);
        }
        const output = path.join(directory, 'results.json');
        const run = spawnSync(process.execPath, [
            require.resolve('jest/bin/jest'), '--runInBand', '--json', '--outputFile', output, '--config', JSON.stringify({
                rootDir: directory,
                testEnvironment: path.join(__dirname, 'strict-environment.cjs')
            })
        ], { encoding: 'utf8', timeout: 60000 });
        if (run.error) throw run.error;
        results = new Map(JSON.parse(fs.readFileSync(output, 'utf8')).testResults
            .map(result => [path.basename(result.name), result]));
    } finally {
        fs.rmSync(directory, { recursive: true, force: true });
    }
}, 70000);

test.each(Object.entries(REJECTED))('rejects an otherwise passing test with %s', (name, [, expected]) => {
    const result = results.get(fileName(name));
    expect(result.status).toBe('failed');
    expect(result.message).toMatch(expected);
});

test('accepts an asserted expected error and correctly cleared work', () => {
    const result = results.get(fileName('accepted'));
    expect(result.message).toBe('');
    expect(result.status).toBe('passed');
});
