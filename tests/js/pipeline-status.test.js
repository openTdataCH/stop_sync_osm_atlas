const loadBrowserScript = require('./load-browser-script');
const path = require('path');

const scriptPath = path.join(__dirname, '../../static/js/shared/pipeline-status.js');

function jsonResponse(body, status = 200) {
  return Promise.resolve({ ok: status >= 200 && status < 300, status, json: jest.fn(() => Promise.resolve(body)) });
}

async function settle() {
  for (let index = 0; index < 10; index += 1) {
    await Promise.resolve();
  }
}

describe('pipeline status polling', () => {
  let updates;
  const recordUpdate = event => updates.push(event.detail);

  beforeEach(() => {
    jest.useFakeTimers();
    updates = [];
    document.body.innerHTML = '<strong id="pipelinePhase">idle</strong>';
    document.addEventListener('pipeline-status:update', recordUpdate);
  });

  afterEach(() => {
    document.removeEventListener('pipeline-status:update', recordUpdate);
    // The poller runs for the page's lifetime and has no teardown; each test asserts its pending work first.
    jest.clearAllTimers();
    jest.useRealTimers();
    delete window.fetch;
    delete window.initialPipelineStatus;
    delete window.latestPipelineStatus;
  });

  test('applies the fetched status and polls again at the running interval', async () => {
    window.fetch = jest.fn(() => jsonResponse({ status: 'running', phase: 'matching' }));
    loadBrowserScript(scriptPath);

    expect(window.fetch).toHaveBeenCalledTimes(1);
    const [url, options] = window.fetch.mock.calls[0];
    expect(url).toBe('/api/system/pipeline_status');
    expect(options.cache).toBe('no-store');
    expect(options.signal.aborted).toBe(false);

    await settle();
    expect(document.getElementById('pipelinePhase').textContent).toBe('matching');
    expect(updates).toEqual([{ status: 'running', phase: 'matching' }]);
    // The elapsed-time clock and the next poll: the settled request left no timeout behind.
    expect(jest.getTimerCount()).toBe(2);

    jest.advanceTimersByTime(1499);
    expect(window.fetch).toHaveBeenCalledTimes(1);
    jest.advanceTimersByTime(1);
    expect(window.fetch).toHaveBeenCalledTimes(2);
  });

  test('an error response keeps the last status and polls again at the idle interval', async () => {
    window.initialPipelineStatus = { status: 'idle', phase: 'idle' };
    window.fetch = jest.fn(() => jsonResponse({ error: 'Service unavailable' }, 503));
    loadBrowserScript(scriptPath);

    await settle();
    expect(updates).toEqual([{ status: 'idle', phase: 'idle' }]);
    expect(window.latestPipelineStatus).toEqual({ status: 'idle', phase: 'idle' });
    expect(jest.getTimerCount()).toBe(2);

    jest.advanceTimersByTime(9999);
    expect(window.fetch).toHaveBeenCalledTimes(1);
    jest.advanceTimersByTime(1);
    expect(window.fetch).toHaveBeenCalledTimes(2);
  });

  test('a request without an answer is aborted after five seconds and polling continues', async () => {
    window.fetch = jest.fn((url, options) => new Promise((resolve, reject) => {
      options.signal.addEventListener('abort', () => reject(new Error('aborted')));
    }));
    loadBrowserScript(scriptPath);
    const { signal } = window.fetch.mock.calls[0][1];

    jest.advanceTimersByTime(4999);
    expect(signal.aborted).toBe(false);
    jest.advanceTimersByTime(1);
    expect(signal.aborted).toBe(true);

    await settle();
    expect(updates).toEqual([]);
    expect(jest.getTimerCount()).toBe(2);
    jest.advanceTimersByTime(10000);
    expect(window.fetch).toHaveBeenCalledTimes(2);
  });
});
