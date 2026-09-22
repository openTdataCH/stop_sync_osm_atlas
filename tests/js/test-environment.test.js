const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

// Exercise failure modes in fresh Jest processes: this suite must remain green
// only when the supposedly passing probe is correctly rejected by the harness.
function probe(body) {
    const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'atlas-jest-'));
    try {
        fs.writeFileSync(path.join(directory, 'probe.test.js'), `test('probe', () => { ${body} });`);
        return spawnSync(process.execPath, [
            require.resolve('jest/bin/jest'), '--runInBand', '--config', JSON.stringify({
                rootDir: directory,
                testEnvironment: path.join(__dirname, 'strict-environment.cjs')
            })
        ], { encoding: 'utf8', timeout: 60000 });
    } finally {
        fs.rmSync(directory, { recursive: true, force: true });
    }
}

test.each([
    ['console error', "console.error('quality-probe');", /Unexpected console.error/],
    ['browser exception', "setTimeout(() => { throw new Error('quality-probe'); }, 0);", /quality-probe/],
    ['unhandled rejection', "Promise.reject(new Error('quality-probe'));", /quality-probe/],
    ['pending timer', 'setTimeout(() => {}, 60000);', /Leaked browser work/],
    ['discarded fake timer', 'jest.useFakeTimers(); setTimeout(() => {}, 60000); jest.useRealTimers();', /Leaked fake browser timers/]
])('rejects an otherwise passing test with %s', (_name, body, expected) => {
    const result = probe(body);
    expect(result.error).toBeUndefined();
    expect(result.status).toBe(1);
    expect(result.stderr).toMatch(expected);
}, 70000);

test('accepts an asserted expected error and correctly cleared work', () => {
    const result = probe(`
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
    `);
    expect(result.error).toBeUndefined();
    expect(result.stderr).toContain('PASS');
    expect(result.status).toBe(0);
}, 70000);
