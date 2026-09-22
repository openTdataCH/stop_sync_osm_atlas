const { TestEnvironment } = require('jest-environment-jsdom');
const { setTimeout: wait } = require('node:timers/promises');
const { format } = require('node:util');

/** Keep errors and pending browser work from disappearing when JSDOM is closed. */
module.exports = class StrictBrowserEnvironment extends TestEnvironment {
    async setup() {
        await super.setup();
        this.errors = [];
        this.timers = new Map();
        this.global.console.error = (...args) => {
            this.errors.push(new Error('Unexpected console.error: ' + format(...args)));
        };
        this.global.addEventListener('error', event => {
            this.errors.push(event.error || new Error(event.message));
        });
        this.global.addEventListener('unhandledrejection', event => {
            this.errors.push(new Error('Unhandled browser rejection: ' + String(event.reason)));
        });

        const restoreRealTimers = this.fakeTimersModern.useRealTimers.bind(this.fakeTimersModern);
        this.fakeTimersModern.useRealTimers = () => {
            this.recordPendingFakeTimers();
            return restoreRealTimers();
        };

        for (const [scheduleName, cancelName, repeats] of [
            ['setTimeout', 'clearTimeout', false],
            ['setInterval', 'clearInterval', true],
            ['requestAnimationFrame', 'cancelAnimationFrame', false]
        ]) {
            const schedule = this.global[scheduleName].bind(this.global);
            const cancel = this.global[cancelName].bind(this.global);
            const key = handle => (scheduleName === 'requestAnimationFrame' ? 'frame:' : 'timer:') + handle;
            this.global[scheduleName] = (callback, ...args) => {
                const origin = new Error('Leaked browser work: ' + scheduleName);
                const handle = schedule((...callbackArgs) => {
                    if (!repeats) this.timers.delete(key(handle));
                    if (typeof callback === 'function') callback(...callbackArgs);
                    else this.global.eval(String(callback));
                }, ...args);
                this.timers.set(key(handle), origin);
                return handle;
            };
            this.global[cancelName] = handle => {
                this.timers.delete(key(handle));
                return cancel(handle);
            };
        }
    }

    recordPendingFakeTimers() {
        const clock = this.global.setTimeout.clock;
        if (clock && clock.countTimers() > 0) {
            this.errors.push(new Error('Leaked fake browser timers: ' + clock.countTimers()));
        }
    }

    async handleTestEvent(event, state) {
        if (event.name === 'test_done' || event.name === 'run_finish') {
            // Native JSDOM events (including <details> toggle) do not use Jest's
            // fake clock. Let them and their promise callbacks complete before
            // reporting success or disposing the browser.
            await wait(0);
            await wait(0);
            if (event.name === 'run_finish') this.recordPendingFakeTimers();
            const destination = event.name === 'test_done' ? event.test.errors : state.unhandledErrors;
            destination.push(...this.errors.splice(0));
            if (event.name === 'run_finish') {
                destination.push(...this.timers.values());
            }
        }
    }
};
