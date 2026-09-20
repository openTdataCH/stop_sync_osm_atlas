const fs = require('fs');
const path = require('path');

describe('MapRenderer production component', () => {
  beforeAll(() => {
    window.AppConstants = global.AppConstants = {
      MAP: { LABEL_ICON_MIN_ZOOM: 18, MAX_ZOOM: 20 },
      MARKERS: {
        CLUSTER_OFFSET_RADIUS: 5,
        COORDINATE_TOLERANCE: 0.00001,
        DEFAULT_RADIUS: 6,
        DEFAULT_WEIGHT: 2,
        DEFAULT_FILL_OPACITY: 0.5,
      },
      POPUP: { MULTI_BUBBLE_RESIZE_MAX_WIDTH_PX: 900 },
    };
    L.circleMarker = jest.fn((position, options) => ({ position, options }));
    L.marker = jest.fn((position, options) => ({ position, options }));
    L.divIcon = jest.fn(options => options);

    require('./load-map-components')();
  });

  afterAll(() => {
    delete window.map;
  });

  test('reconciles adapter output through the real marker registry and updates its display position', () => {
    window.eval(fs.readFileSync(path.join(__dirname,
      '../../static/js/components/map-layer-registry.js'), 'utf8'));
    const group = { addLayer: jest.fn(), removeLayer: jest.fn() };
    const registry = window.MapComponents.MapLayerRegistry.create({
      layerGroup: group,
      create: window.MapRenderer.createEntityMarker,
    });
    function descriptors(lat) {
      const snapshot = window.MapEntityAdapters.stops([{
        id: 1, sloid: 'source:1', stop_type: 'atlas_unmatched',
        atlas_lat: lat, atlas_lon: 6.6,
      }]);
      return window.MapRenderer.layoutEntities(snapshot.entities, { zoom: 14 }).descriptors;
    }

    expect(registry.reconcile(descriptors(46.5)).created).toEqual(['atlas:source:1']);
    const marker = registry.get('atlas:source:1');
    expect(marker.position).toEqual([46.5, 6.6]);
    marker.setLatLng = jest.fn();
    expect(registry.reconcile(descriptors(46.6)).updated).toEqual(['atlas:source:1']);
    expect(marker.setLatLng).toHaveBeenCalledWith([46.6, 6.6]);
    expect(group.addLayer).toHaveBeenCalledTimes(1);
  });

  test('uses the explicit zoom instead of ambient window.map state', () => {
    window.map = { getZoom: () => 4 };

    window.MapRenderer.createEntityMarker({ entity: window.MapShared.createEntity('atlas', '1', [46.5, 6.6], { status: 'matched', label: 'D' }), displayPosition: [46.5, 6.6], zoom: 18 });

    expect(L.marker).toHaveBeenCalledTimes(1);
    expect(L.circleMarker).not.toHaveBeenCalled();
  });

  test('switches labeled markers to circles below the label threshold', () => {
    window.MapRenderer.createEntityMarker({ entity: window.MapShared.createEntity('osm', '1', [46.5, 6.6], { status: 'matched', label: 'P' }), displayPosition: [46.5, 6.6], zoom: 17 });

    expect(L.circleMarker).toHaveBeenCalledTimes(1);
    expect(L.marker).not.toHaveBeenCalled();
  });

  test('calculates deterministic overlap offsets at the reference zoom', () => {
    const map = {
      getMaxZoom: jest.fn(() => 20),
      project: jest.fn(([lat, lon]) => ({ x: lon * 100, y: lat * 100 })),
      unproject: jest.fn(point => ({ lat: point.y / 100, lng: point.x / 100 })),
    };
    const manager = new window.MapRenderer.MarkerClusterManager({ map, zoom: 18 });
    manager.addMarker(46.5, 6.6, { key: 'osm:2', entityType: 'osm' });
    manager.addMarker(46.5, 6.6, { key: 'atlas:1', entityType: 'atlas' });

    const entries = manager.getClusteredData();

    expect(entries.map(entry => entry.markerData.key)).toEqual(['atlas:1', 'osm:2']);
    expect(entries[0].lon).toBeCloseTo(6.65);
    expect(entries[1].lon).toBeCloseTo(6.55);
    expect(map.project).toHaveBeenCalledWith([46.5, 6.6], 20);
    expect(map.unproject).toHaveBeenCalledTimes(2);
  });

  test('keeps display coordinates fixed while their visible offset shrinks at lower zooms', () => {
    const map = {
      getMaxZoom: () => 20,
      project: ([lat, lon], zoom) => {
        const scale = 2 ** (zoom - 20);
        return { x: lon * scale, y: lat * scale };
      },
      unproject: (point, zoom) => {
        const scale = 2 ** (zoom - 20);
        return { lat: point.y / scale, lng: point.x / scale };
      },
    };
    function positionsAt(currentZoom) {
      const manager = new window.MapRenderer.MarkerClusterManager({ map, zoom: currentZoom });
      manager.addMarker(46.5, 6.6, { key: 'atlas:1', entityType: 'atlas' });
      manager.addMarker(46.5, 6.6, { key: 'osm:2', entityType: 'osm' });
      return manager.getClusteredData();
    }

    const atZoom17 = positionsAt(17);
    const atZoom20 = positionsAt(20);
    expect(atZoom17.map(entry => [entry.lat, entry.lon]))
      .toEqual(atZoom20.map(entry => [entry.lat, entry.lon]));

    const sourceAt19 = map.project([46.5, 6.6], 19);
    const displayAt19 = map.project([atZoom20[0].lat, atZoom20[0].lon], 19);
    expect(Math.abs(displayAt19.x - sourceAt19.x)).toBeCloseTo(2.5);

    const sourceAt18 = map.project([46.5, 6.6], 18);
    const displayAt18 = map.project([atZoom20[0].lat, atZoom20[0].lon], 18);
    expect(Math.abs(displayAt18.x - sourceAt18.x)).toBeCloseTo(1.25);
  });

  test('skips overlap projection when the stable offset would be subpixel', () => {
    const map = {
      getMaxZoom: () => 20,
      project: jest.fn(([lat, lon]) => ({ x: lon, y: lat })),
      unproject: jest.fn(point => ({ lat: point.y, lng: point.x })),
    };
    const manager = new window.MapRenderer.MarkerClusterManager({ map, zoom: 16 });
    manager.addMarker(46.5, 6.6, { key: 'atlas:1', entityType: 'atlas' });
    manager.addMarker(46.5, 6.6, { key: 'gtfs:1', entityType: 'gtfs' });

    expect(manager.getClusteredData().map(entry => [entry.lat, entry.lon]))
      .toEqual([[46.5, 6.6], [46.5, 6.6]]);
    expect(map.project).not.toHaveBeenCalled();
    expect(map.unproject).not.toHaveBeenCalled();
  });

  test('groups across spatial-cell boundaries without creating transitive chains', () => {
    const map = {
      getMaxZoom: () => 20,
      project: ([lat, lon]) => ({ x: lon, y: lat }),
      unproject: point => ({ lat: point.y, lng: point.x }),
    };
    const manager = new window.MapRenderer.MarkerClusterManager({
      map,
      overlapDistance: 10
    });
    manager.addMarker(0, 9, { key: 'atlas:a', entityType: 'atlas' });
    manager.addMarker(0, 18, { key: 'osm:b', entityType: 'osm' });
    manager.addMarker(0, 27, { key: 'gtfs:c', entityType: 'gtfs' });

    const byKey = new Map(manager.getClusteredData().map(entry => [entry.markerData.key, entry]));

    expect(byKey.get('atlas:a').lon).toBeCloseTo(4);
    expect(byKey.get('osm:b').lon).toBeCloseTo(23);
    expect(byKey.get('gtfs:c').lon).toBeCloseTo(27);
  });

  test('is input-order independent and limits every displacement to five reference pixels', () => {
    const map = {
      getMaxZoom: () => 20,
      project: ([lat, lon]) => ({ x: lon, y: lat }),
      unproject: point => ({ lat: point.y, lng: point.x }),
    };
    const sourceByKey = new Map([
      ['atlas:a', [0, 9.9]],
      ['osm:b', [0, 10.1]],
      ['gtfs:c', [0.1, 10]]
    ]);
    function layout(keys) {
      const manager = new window.MapRenderer.MarkerClusterManager({ map, overlapDistance: 10 });
      keys.forEach((key) => {
        const [lat, lon] = sourceByKey.get(key);
        const type = key.split(':')[0];
        manager.addMarker(lat, lon, { key, type, entityType: type });
      });
      return new Map(manager.getClusteredData().map(entry => [entry.markerData.key, [entry.lat, entry.lon]]));
    }

    const forward = layout(['atlas:a', 'osm:b', 'gtfs:c']);
    const reverse = layout(['gtfs:c', 'osm:b', 'atlas:a']);
    expect(reverse).toEqual(forward);
    forward.forEach((position, key) => {
      const source = sourceByKey.get(key);
      expect(Math.hypot(position[0] - source[0], position[1] - source[1])).toBeCloseTo(5);
    });
  });

  test('rejects missing and non-finite source coordinates before projection', () => {
    const map = {
      getMaxZoom: () => 20,
      project: jest.fn(([lat, lon]) => ({ x: lon, y: lat })),
      unproject: point => ({ lat: point.y, lng: point.x }),
    };
    const manager = new window.MapRenderer.MarkerClusterManager({ map });

    expect(manager.addMarker(null, 7, { key: 'atlas:null', entityType: 'atlas' })).toBe(false);
    expect(manager.addMarker(' ', 7, { key: 'atlas:blank', entityType: 'atlas' })).toBe(false);
    expect(manager.addMarker(46, Infinity, { key: 'atlas:infinity', entityType: 'atlas' })).toBe(false);
    expect(manager.addMarker(46, 7, { key: 'atlas:valid', entityType: 'atlas' })).toBe(true);
    expect(manager.getClusteredData()).toHaveLength(1);
    expect(map.project).toHaveBeenCalledTimes(1);
  });

  test('spreads a dense exact-coordinate group at realistic projected magnitudes', () => {
    const map = {
      getMaxZoom: () => 20,
      project: ([lat, lon]) => ({ x: lon, y: lat }),
      unproject: point => ({ lat: point.y, lng: point.x }),
    };
    const source = [80000000, 100000000];
    const manager = new window.MapRenderer.MarkerClusterManager({ map });
    for (let index = 0; index < 10; index += 1) {
      manager.addMarker(source[0], source[1], {
        key: `atlas:${index}`,
        entityType: 'atlas'
      });
    }

    const entries = manager.getClusteredData();
    const uniquePositions = new Set(entries.map(entry => (
      `${entry.lat.toFixed(6)}:${entry.lon.toFixed(6)}`
    )));

    expect(uniquePositions.size).toBe(10);
    entries.forEach((entry) => {
      expect(Math.hypot(entry.lat - source[0], entry.lon - source[1])).toBeCloseTo(5);
    });
  });

  test.each(['atlas', 'osm'])('signatures track visible labels and emphasis for %s', type => {
    const plain = window.MapShared.createEntity(type, '1', [46.5, 6.6], { status: 'matched' });
    const labeled = window.MapShared.createEntity(type, '1', [46.5, 6.6], { status: 'matched', label: type === 'atlas' ? 'D' : 'P' });
    const signature = window.MapRenderer.getEntityRenderSignature;
    expect(signature(plain, 17)).toBe(signature(plain, 18));
    expect(signature(plain, 17)).toBe(signature(labeled, 17));
    expect(signature(labeled, 17)).not.toBe(signature(labeled, 18));
    expect(signature({ ...plain, emphasis: 'context' }, 18)).not.toBe(signature(plain, 18));
  });

  test('cancels stale chunk insertion without adding the remaining markers', async () => {
    jest.useFakeTimers();
    const layer = { addLayer: jest.fn() };
    const markers = window.MapRenderer.renderEntities([
      window.MapShared.createEntity('atlas', '1', [46.5, 6.6]),
      window.MapShared.createEntity('atlas', '2', [46.6, 6.7]),
      window.MapShared.createEntity('atlas', '3', [46.7, 6.8])
    ], layer, { batchAdd: true, batchSize: 1, zoom: 17 });

    expect(layer.addLayer).toHaveBeenCalledTimes(1);
    markers.cancelBatch();
    jest.runOnlyPendingTimers();

    await expect(markers.batchComplete).resolves.toEqual({ status: 'cancelled', added: 1 });
    expect(layer.addLayer).toHaveBeenCalledTimes(1);
    jest.useRealTimers();
  });
});
