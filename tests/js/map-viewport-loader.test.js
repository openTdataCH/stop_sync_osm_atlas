const fs = require('fs');
const path = require('path');

function loadProductionScript() {
  const scriptPath = path.join(__dirname, '../../static/js/components/map-viewport-loader.js');
  window.MapComponents = undefined;
  window.eval(fs.readFileSync(scriptPath, 'utf8'));
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

function createMap() {
  const handlers = new Map();
  const map = {
    bounds: { name: 'initial', pad: jest.fn(function () { return this; }) },
    zoom: 12,
    getBounds: jest.fn(() => map.bounds),
    getZoom: jest.fn(() => map.zoom),
    on: jest.fn((eventName, handler) => {
      if (!handlers.has(eventName)) handlers.set(eventName, new Set());
      handlers.get(eventName).add(handler);
    }),
    off: jest.fn((eventName, handler) => {
      if (handlers.has(eventName)) handlers.get(eventName).delete(handler);
    }),
    emit(eventName) {
      Array.from(handlers.get(eventName) || []).forEach((handler) => handler({ type: eventName }));
    }
  };
  return map;
}

describe('MapViewportLoader', () => {
  let map;
  let abortControllers;

  beforeEach(() => {
    jest.useFakeTimers();
    abortControllers = [];
    window.AbortController = class {
      constructor() {
        this.signal = { aborted: false };
        abortControllers.push(this);
      }

      abort() {
        this.signal.aborted = true;
      }
    };
    loadProductionScript();
    map = createMap();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  test('debounces configured map events and passes explicit request context', async () => {
    const load = jest.fn(() => Promise.resolve({ stops: [] }));
    const onData = jest.fn();
    const loader = window.MapComponents.MapViewportLoader.create({
      map,
      debounceMs: 180,
      bufferRatio: 0.25,
      getRequestIdentity: () => 'filters:all',
      load,
      onData
    });

    map.emit('moveend');
    map.emit('zoomend');
    expect(load).not.toHaveBeenCalled();
    jest.advanceTimersByTime(179);
    expect(load).not.toHaveBeenCalled();
    jest.advanceTimersByTime(1);
    await Promise.resolve();
    await Promise.resolve();

    expect(load).toHaveBeenCalledTimes(1);
    expect(map.bounds.pad).toHaveBeenCalledWith(0.25);
    expect(load.mock.calls[0][0]).toEqual(expect.objectContaining({
      map,
      bounds: map.bounds,
      requestBounds: map.bounds,
      zoom: 12,
      identity: 'filters:all',
      cacheHit: false
    }));
    expect(onData).toHaveBeenCalledWith({ stops: [] }, expect.any(Object));
    loader.destroy();
  });

  test('aborts the old request and rejects a late response even when abort is ignored', async () => {
    const first = deferred();
    const second = deferred();
    const load = jest.fn()
      .mockImplementationOnce(() => first.promise)
      .mockImplementationOnce(() => second.promise);
    const onData = jest.fn();
    const loader = window.MapComponents.MapViewportLoader.create({ map, load, onData });

    const firstRun = loader.reload();
    map.bounds = { name: 'new' };
    map.zoom = 15;
    const secondRun = loader.reload();

    expect(abortControllers[0].signal.aborted).toBe(true);
    second.resolve({ viewport: 'new' });
    await expect(secondRun).resolves.toEqual(expect.objectContaining({ status: 'loaded' }));
    first.resolve({ viewport: 'old' });
    await expect(firstRun).resolves.toEqual(expect.objectContaining({ status: 'stale' }));
    expect(onData).toHaveBeenCalledTimes(1);
    expect(onData.mock.calls[0][0]).toEqual({ viewport: 'new' });
  });

  test('reuses only cache accepted by the page hook and invalidates it explicitly', async () => {
    let identity = 'operator:all';
    const load = jest.fn(() => Promise.resolve({ request: load.mock.calls.length }));
    const onData = jest.fn();
    const loader = window.MapComponents.MapViewportLoader.create({
      map,
      getRequestIdentity: () => identity,
      // The loader itself must guard request identity before consulting this
      // page-specific bounds policy.
      shouldReuse: () => true,
      load,
      onData
    });

    await loader.reload();
    await expect(loader.reload()).resolves.toEqual(expect.objectContaining({ status: 'cached' }));
    expect(load).toHaveBeenCalledTimes(1);
    expect(onData).toHaveBeenCalledTimes(2);
    expect(onData.mock.calls[1][1].cacheHit).toBe(true);

    identity = 'operator:tl';
    await loader.reload();
    expect(load).toHaveBeenCalledTimes(2);

    loader.invalidate();
    expect(loader.getCache()).toBeNull();
    await loader.reload();
    expect(load).toHaveBeenCalledTimes(3);
  });

  test('pause tokens suppress programmatic events and destroy removes all listeners', () => {
    const load = jest.fn(() => Promise.resolve([]));
    const loader = window.MapComponents.MapViewportLoader.create({ map, load, onData: jest.fn() });
    const resume = loader.pause();

    map.emit('moveend');
    jest.runOnlyPendingTimers();
    expect(load).not.toHaveBeenCalled();
    resume();
    map.emit('moveend');
    jest.runOnlyPendingTimers();
    expect(load).toHaveBeenCalledTimes(1);

    loader.destroy();
    expect(map.off).toHaveBeenCalledWith('moveend', expect.any(Function));
    expect(map.off).toHaveBeenCalledWith('zoomend', expect.any(Function));
    map.emit('moveend');
    jest.runOnlyPendingTimers();
    expect(load).toHaveBeenCalledTimes(1);
  });
});
