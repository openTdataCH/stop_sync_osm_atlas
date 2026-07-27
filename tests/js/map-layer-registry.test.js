const fs = require('fs');
const path = require('path');

function loadProductionScript() {
  const scriptPath = path.join(__dirname, '../../static/js/components/map-layer-registry.js');
  window.MapComponents = undefined;
  window.eval(fs.readFileSync(scriptPath, 'utf8'));
}

function descriptor(key, signature, position, data) {
  return {
    key,
    renderSignature: signature,
    position: position || [46, 7],
    data: data || { key }
  };
}

describe('MapLayerRegistry', () => {
  let group;
  let created;
  let updated;
  let removed;
  let registry;

  beforeEach(() => {
    loadProductionScript();
    group = {
      addLayer: jest.fn(),
      removeLayer: jest.fn()
    };
    created = [];
    updated = [];
    removed = [];
    registry = window.MapComponents.MapLayerRegistry.create({
      layerGroup: group,
      create: jest.fn((item) => {
        const layer = { key: item.key, setLatLng: jest.fn() };
        created.push(layer);
        return layer;
      }),
      update: jest.fn((layer, next, previous) => {
        updated.push({ layer, next, previous });
        layer.setLatLng(next.position);
      }),
      onRemove: jest.fn((layer, item, details) => {
        removed.push({ layer, item, details });
      })
    });
  });

  test('creates, updates, replaces, and removes by stable key', () => {
    const first = registry.reconcile([
      descriptor('atlas:a', 'atlas|circle', [46.1, 7.1]),
      descriptor('gtfs:b', 'gtfs|circle', [46.2, 7.2])
    ]);

    expect(first).toEqual({
      created: ['atlas:a', 'gtfs:b'],
      updated: [],
      replaced: [],
      removed: [],
      size: 2
    });
    const atlasLayer = registry.get('atlas:a');
    const oldGtfsLayer = registry.get('gtfs:b');

    const second = registry.reconcile([
      descriptor('atlas:a', 'atlas|circle', [46.3, 7.3], { current: true }),
      descriptor('gtfs:b', 'gtfs|label', [46.2, 7.2])
    ]);

    expect(registry.get('atlas:a')).toBe(atlasLayer);
    expect(updated[0].layer).toBe(atlasLayer);
    expect(registry.getDescriptor('atlas:a').data).toEqual({ current: true });
    expect(registry.get('gtfs:b')).not.toBe(oldGtfsLayer);
    expect(removed[0].details.replacementLayer).toBe(registry.get('gtfs:b'));
    expect(removed[0].details.replacementDescriptor.renderSignature).toBe('gtfs|label');
    expect(second.updated).toEqual(['atlas:a']);
    expect(second.replaced).toEqual(['gtfs:b']);
    expect(removed[0].details.reason).toBe('replace');

    const third = registry.reconcile([
      descriptor('atlas:a', 'atlas|circle', [46.4, 7.4])
    ]);
    expect(third.removed).toEqual(['gtfs:b']);
    expect(registry.has('gtfs:b')).toBe(false);
    expect(removed[1].details.reason).toBe('remove');
  });

  test('validates all keys before mutating the current layer set', () => {
    registry.reconcile([descriptor('atlas:a', 'circle')]);
    group.addLayer.mockClear();
    group.removeLayer.mockClear();

    expect(() => registry.reconcile([
      descriptor('atlas:a', 'circle'),
      descriptor('atlas:a', 'label')
    ])).toThrow('duplicate key');

    expect(group.addLayer).not.toHaveBeenCalled();
    expect(group.removeLayer).not.toHaveBeenCalled();
    expect(registry.keys()).toEqual(['atlas:a']);
  });

  test('clear and destroy explicitly remove owned layers', () => {
    registry.reconcile([
      descriptor('atlas:a', 'circle'),
      descriptor('atlas:b', 'circle')
    ]);

    expect(registry.clear('reset')).toEqual(['atlas:a', 'atlas:b']);
    expect(removed.map((item) => item.details.reason)).toEqual(['reset', 'reset']);
    expect(registry.size()).toBe(0);

    registry.reconcile([descriptor('atlas:c', 'circle')]);
    registry.destroy();
    expect(removed[2].details.reason).toBe('destroy');
    expect(() => registry.reconcile([])).toThrow('destroyed');
  });

  test('uses setLatLng as the default update behavior', () => {
    const layer = { setLatLng: jest.fn() };
    const basicRegistry = window.MapComponents.MapLayerRegistry.create({
      layerGroup: group,
      create: () => layer
    });
    basicRegistry.reconcile([descriptor('atlas:a', 'circle', [46, 7])]);
    basicRegistry.reconcile([descriptor('atlas:a', 'circle', [47, 8])]);

    expect(layer.setLatLng).toHaveBeenCalledWith([47, 8]);
  });
});
