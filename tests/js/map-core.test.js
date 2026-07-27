const fs = require('fs');
const path = require('path');

function loadProductionScript() {
  const scriptPath = path.join(__dirname, '../../static/js/components/map-core.js');
  window.MapComponents = undefined;
  window.eval(fs.readFileSync(scriptPath, 'utf8'));
}

function createLeafletMock() {
  const maps = [];

  function makeMap(container, options) {
    const handlers = new Map();
    const map = {
      container,
      options,
      zoom: null,
      renderer: options.renderer,
      setView: jest.fn((center, zoom) => {
        map.center = center;
        map.zoom = zoom;
        return map;
      }),
      getZoom: jest.fn(() => map.zoom),
      getRenderer: jest.fn(() => map.renderer),
      on: jest.fn((eventName, handler) => {
        if (!handlers.has(eventName)) handlers.set(eventName, new Set());
        handlers.get(eventName).add(handler);
        return map;
      }),
      off: jest.fn((eventName, handler) => {
        if (handlers.has(eventName)) handlers.get(eventName).delete(handler);
        return map;
      }),
      addLayer: jest.fn(),
      invalidateSize: jest.fn(() => 'invalidated'),
      remove: jest.fn(),
      emit(eventName, event) {
        Array.from(handlers.get(eventName) || []).forEach((handler) => handler(event || { type: eventName }));
      },
      listenerCount(eventName) {
        return (handlers.get(eventName) || new Set()).size;
      }
    };
    maps.push(map);
    return map;
  }

  function makeLayer() {
    return {
      addLayer: jest.fn(),
      removeLayer: jest.fn(),
      addTo: jest.fn(function () { return this; })
    };
  }

  function makeControl() {
    return {
      addTo: jest.fn(function () { return this; }),
      remove: jest.fn()
    };
  }

  const leaflet = {
    map: jest.fn(makeMap),
    layerGroup: jest.fn(makeLayer),
    svg: jest.fn((options) => ({ options: { ...options } })),
    control: {
      zoom: jest.fn(makeControl),
      layers: jest.fn(makeControl)
    }
  };
  return { leaflet, maps, makeLayer };
}

describe('MapCore', () => {
  let mock;

  beforeEach(() => {
    mock = createLeafletMock();
    window.L = mock.leaflet;
    window.MapShared = undefined;
    delete window.map;
    loadProductionScript();
  });

  test('creates independent maps and named layers without ambient map state', () => {
    const first = window.MapComponents.MapCore.create({
      container: 'first-map',
      view: { center: [46, 7], zoom: 12 },
      baseLayers: false,
      layerGroups: {
        markers: { label: 'Markers' },
        context: { visible: false }
      },
      controls: { zoom: { position: 'bottomleft' }, layers: true }
    });
    const second = window.MapComponents.MapCore.create({
      container: 'second-map',
      view: { center: [47, 8], zoom: 14 },
      baseLayers: false,
      layerGroups: { markers: true }
    });

    expect(first.map).not.toBe(second.map);
    expect(first.layers.markers).not.toBe(second.layers.markers);
    expect(first.map.setView).toHaveBeenCalledWith([46, 7], 12);
    expect(second.map.setView).toHaveBeenCalledWith([47, 8], 14);
    expect(first.layers.context.addTo).not.toHaveBeenCalled();
    expect(mock.leaflet.control.layers).toHaveBeenCalledWith(
      {},
      { Markers: first.layers.markers },
      {}
    );
    expect(window.map).toBeUndefined();
  });

  test('uses shared base layers by default and adds the selected base layer', () => {
    const osm = mock.makeLayer();
    const transport = mock.makeLayer();
    const satellite = mock.makeLayer();
    window.MapShared = {
      createBaseTileLayers: jest.fn(() => ({ osm, transport, satellite }))
    };

    const result = window.MapComponents.MapCore.create({
      container: 'map',
      center: [46, 7],
      zoom: 10,
      layerGroups: {},
      controls: { layers: { position: 'bottomleft' } },
      defaultBaseLayer: 'Transport Map'
    });

    expect(transport.addTo).toHaveBeenCalledWith(result.map);
    expect(osm.addTo).not.toHaveBeenCalled();
    expect(result.baseLayers).toEqual({
      OpenStreetMap: osm,
      'Transport Map': transport,
      Satellite: satellite
    });
  });

  test('updates renderer padding and popup positions with removable handlers', () => {
    const updateAllLines = jest.fn();
    const result = window.MapComponents.MapCore.create({
      container: 'map',
      center: [46, 7],
      zoom: 15,
      baseLayers: false,
      rendererPadding: (zoom) => zoom >= 16 ? 0.5 : 0.1,
      popupBehavior: { updateAllLines }
    });
    const popup = {
      _line: {},
      _updatePosition: jest.fn(),
      _removeLine: jest.fn()
    };

    expect(result.map.renderer.options.padding).toBe(0.1);
    result.map.zoom = 16;
    result.map.emit('zoomend');
    expect(result.map.renderer.options.padding).toBe(0.5);
    result.map.emit('popupopen', { popup });
    result.map.emit('move');
    expect(updateAllLines).toHaveBeenCalledWith(result.map);
    expect(popup._updatePosition).toHaveBeenCalledTimes(1);
    result.map.emit('popupclose', { popup });
    expect(popup._removeLine).toHaveBeenCalledTimes(1);

    result.destroy();
    expect(result.map.listenerCount('zoomend')).toBe(0);
    expect(result.map.listenerCount('move')).toBe(0);
    expect(result.map.remove).toHaveBeenCalledTimes(1);
    result.destroy();
    expect(result.map.remove).toHaveBeenCalledTimes(1);
  });

  test('optionally binds and cleans up window resize invalidation', () => {
    const result = window.MapComponents.MapCore.create({
      container: 'map',
      baseLayers: false,
      invalidateOnResize: true
    });
    window.dispatchEvent(new Event('resize'));
    expect(result.map.invalidateSize).toHaveBeenCalledTimes(1);

    result.destroy();
    window.dispatchEvent(new Event('resize'));
    expect(result.map.invalidateSize).toHaveBeenCalledTimes(1);
  });
});
