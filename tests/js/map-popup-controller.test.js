const fs = require('fs');
const path = require('path');

function loadProductionScript() {
  const scriptPath = path.join(__dirname, '../../static/js/components/map-popup-controller.js');
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

function createMarker(options = {}) {
  const handlers = new Map();
  let popupOpen = false;
  let leafletClickHandler = null;
  const marker = {
    popup: null,
    on: jest.fn((eventName, handler) => {
      if (!handlers.has(eventName)) handlers.set(eventName, new Set());
      handlers.get(eventName).add(handler);
      return marker;
    }),
    off: jest.fn((eventName, handler) => {
      if (handlers.has(eventName)) handlers.get(eventName).delete(handler);
      return marker;
    }),
    bindPopup: jest.fn((popup) => {
      marker.popup = popup;
      if (options.leafletPopupClicks && !leafletClickHandler) {
        leafletClickHandler = () => {
          if (popupOpen) marker.closePopup();
          else marker.openPopup();
        };
        marker.on('click', leafletClickHandler);
      }
      return marker;
    }),
    getPopup: jest.fn(() => marker.popup),
    openPopup: jest.fn(() => {
      popupOpen = true;
      return marker;
    }),
    closePopup: jest.fn(() => {
      popupOpen = false;
      return marker;
    }),
    unbindPopup: jest.fn(() => {
      if (leafletClickHandler) {
        marker.off('click', leafletClickHandler);
        leafletClickHandler = null;
      }
      marker.popup = null;
      popupOpen = false;
      return marker;
    }),
    isPopupOpen: jest.fn(() => popupOpen),
    emit(eventName) {
      Array.from(handlers.get(eventName) || []).forEach((handler) => handler({ type: eventName }));
    },
    listenerCount(eventName) {
      return (handlers.get(eventName) || new Set()).size;
    }
  };
  return marker;
}

describe('MapPopupController', () => {
  let abortControllers;

  beforeEach(() => {
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
  });

  test('deduplicates a concurrent entity load across markers', async () => {
    const pending = deferred();
    const load = jest.fn(() => pending.promise);
    const render = jest.fn((payload) => `<p>${payload.name}</p>`);
    const createPopup = jest.fn((html) => ({ html }));
    const controller = window.MapComponents.MapPopupController.create({ load, render, createPopup });
    const first = createMarker();
    const second = createMarker();
    controller.attach(first, { key: 'atlas:a' });
    controller.attach(second, { key: 'atlas:a' });

    const firstOpen = controller.open(first);
    const secondOpen = controller.open(second);
    expect(load).toHaveBeenCalledTimes(1);

    pending.resolve({ name: 'Lausanne' });
    await Promise.all([firstOpen, secondOpen]);
    expect(render).toHaveBeenCalledTimes(2);
    expect(first.openPopup).toHaveBeenCalledTimes(1);
    expect(second.openPopup).toHaveBeenCalledTimes(1);
    expect(first.popup.html).toBe('<p>Lausanne</p>');
  });

  test('keeps an attached popup when the same marker is updated', async () => {
    const load = jest.fn(() => Promise.resolve({ name: 'Initial' }));
    const marker = createMarker();
    const controller = window.MapComponents.MapPopupController.create({
      load,
      render: (payload) => payload.name
    });
    controller.attach(marker, { key: 'gtfs:1' });
    await controller.open(marker);
    const popup = marker.popup;

    controller.attach(marker, {
      key: 'gtfs:1',
      render: (payload) => `Updated ${payload.name}`
    });
    await controller.open(marker);

    expect(marker.listenerCount('click')).toBe(1);
    expect(marker.popup).toBe(popup);
    expect(load).toHaveBeenCalledTimes(1);
    expect(marker.openPopup).toHaveBeenCalledTimes(2);
  });

  test('lets Leaflet reopen a loaded popup without toggling it closed again', async () => {
    const marker = createMarker({ leafletPopupClicks: true });
    const controller = window.MapComponents.MapPopupController.create({
      load: () => Promise.resolve({ name: 'Loaded' }),
      render: (payload) => payload.name
    });
    controller.attach(marker, { key: 'atlas:a' });
    await controller.open(marker);
    marker.closePopup();
    marker.openPopup.mockClear();
    marker.closePopup.mockClear();

    marker.emit('click');

    expect(marker.isPopupOpen()).toBe(true);
    expect(marker.openPopup).toHaveBeenCalledTimes(1);
    expect(marker.closePopup).not.toHaveBeenCalled();
  });

  test('transfers an open cached popup to a same-key replacement marker', async () => {
    const load = jest.fn(() => Promise.resolve({ name: 'Lausanne' }));
    const controller = window.MapComponents.MapPopupController.create({
      load,
      render: (payload) => payload.name
    });
    const circleMarker = createMarker();
    const labelMarker = createMarker();
    controller.attach(circleMarker, { key: 'atlas:a' });
    await controller.open(circleMarker);
    controller.attach(labelMarker, { key: 'atlas:a' });

    await controller.transfer(circleMarker, labelMarker);

    expect(controller.has(circleMarker)).toBe(false);
    expect(controller.has(labelMarker)).toBe(true);
    expect(circleMarker.isPopupOpen()).toBe(false);
    expect(labelMarker.isPopupOpen()).toBe(true);
    expect(labelMarker.popup).toBe('Lausanne');
    expect(load).toHaveBeenCalledTimes(1);
  });

  test('allows retry after an error and exposes a small error popup', async () => {
    const load = jest.fn()
      .mockRejectedValueOnce(new Error('network down'))
      .mockResolvedValueOnce({ name: 'Recovered' });
    const onError = jest.fn();
    const marker = createMarker();
    const controller = window.MapComponents.MapPopupController.create({
      load,
      render: (payload) => payload.name,
      onError
    });
    controller.attach(marker, { key: 'atlas:a' });

    await expect(controller.open(marker)).resolves.toEqual(expect.objectContaining({ status: 'error' }));
    expect(onError).toHaveBeenCalledTimes(1);
    expect(marker.popup).toContain('Click the marker to retry');

    await expect(controller.open(marker)).resolves.toEqual(expect.objectContaining({ status: 'loaded' }));
    expect(load).toHaveBeenCalledTimes(2);
    expect(marker.popup).toBe('Recovered');
  });

  test('detaching aborts an orphaned load and a late result cannot open the marker', async () => {
    const pending = deferred();
    const marker = createMarker();
    const controller = window.MapComponents.MapPopupController.create({
      load: () => pending.promise,
      render: (payload) => payload.name
    });
    controller.attach(marker, { key: 'atlas:a' });
    const opening = controller.open(marker);

    expect(controller.detach(marker)).toBe(true);
    expect(abortControllers[0].signal.aborted).toBe(true);
    expect(marker.listenerCount('click')).toBe(0);
    pending.resolve({ name: 'Too late' });
    await expect(opening).resolves.toEqual(expect.objectContaining({ status: 'removed' }));
    expect(marker.openPopup).not.toHaveBeenCalled();
    expect(controller.has(marker)).toBe(false);
  });

  test('cache invalidation also rejects obsolete asynchronous rendering', async () => {
    const staleRender = deferred();
    const load = jest.fn()
      .mockResolvedValueOnce({ name: 'Stale' })
      .mockResolvedValueOnce({ name: 'Fresh' });
    const render = jest.fn()
      .mockImplementationOnce(() => staleRender.promise)
      .mockImplementationOnce((payload) => payload.name);
    const marker = createMarker();
    const controller = window.MapComponents.MapPopupController.create({
      cache: 'content',
      load,
      render
    });
    controller.attach(marker, { key: 'atlas:a' });

    const obsoleteOpen = controller.open(marker);
    await Promise.resolve();
    await Promise.resolve();
    controller.invalidate('atlas:a');
    staleRender.resolve('Stale');
    await expect(obsoleteOpen).resolves.toEqual(expect.objectContaining({ status: 'removed' }));

    await controller.open(marker);
    expect(load).toHaveBeenCalledTimes(2);
    expect(marker.popup).toBe('Fresh');
  });

  test('destroy detaches every listener and rejects later attachment clearly', () => {
    const controller = window.MapComponents.MapPopupController.create({
      load: () => Promise.resolve({}),
      render: () => 'content'
    });
    const first = createMarker();
    const second = createMarker();
    controller.attach(first, { key: 'atlas:a' });
    controller.attach(second, { key: 'atlas:b' });

    controller.destroy();
    expect(first.listenerCount('click')).toBe(0);
    expect(second.listenerCount('click')).toBe(0);
    expect(() => controller.attach(createMarker(), { key: 'atlas:c' })).toThrow('destroyed');
  });
});
