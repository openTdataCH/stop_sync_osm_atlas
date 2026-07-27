const fs = require('fs');
const path = require('path');

describe('LineRenderer production component', () => {
  let layer;

  beforeAll(() => {
    window.AppConstants = global.AppConstants = {
      MAP: { ZOOM_OSM_GROUP_LINE_THRESHOLD: 17 },
      COLORS: {
        LINE_ATLAS_OSM: '#174092',
        LINE_OSM_GROUP: '#4CAF50',
        LINE_OSM_GROUP_DASH: '6,4',
      },
    };
    const scriptPath = path.join(__dirname, '../../static/js/components/line-renderer.js');
    window.eval(fs.readFileSync(scriptPath, 'utf8'));
  });

  beforeEach(() => {
    L.polyline = jest.fn((coordinates, options) => ({ coordinates, options }));
    layer = {
      addLayer: jest.fn(),
      clearLayers: jest.fn(),
    };
  });

  test('draws and deduplicates production ATLAS/OSM lines', () => {
    const stop = {
      stop_type: 'matched',
      sloid: 'ch:1:sloid:1',
      atlas_lat: 46.5,
      atlas_lon: 6.6,
      osm_matches: [
        { osm_node_id: '123', osm_lat: 46.51, osm_lon: 6.61 },
        { osm_node_id: '123', osm_lat: 46.51, osm_lon: 6.61 },
      ],
    };

    const count = window.LineRenderer.drawAll([stop], layer, {
      showAtlas: true,
      showOsm: true,
      minZoom: 13,
      currentZoom: 18,
      isContext: false,
    });

    expect(count).toBe(1);
    expect(layer.addLayer).toHaveBeenCalledTimes(1);
    expect(L.polyline).toHaveBeenCalledWith(
      [[46.5, 6.6], [46.51, 6.61]],
      expect.objectContaining({ color: '#174092', weight: 2 })
    );
  });

  test('draws context lines with reduced opacity', () => {
    window.LineRenderer.drawAll([{
      stop_type: 'matched',
      sloid: 'S1',
      atlas_lat: 46.5,
      atlas_lon: 6.6,
      osm_node_id: '1',
      osm_lat: 46.6,
      osm_lon: 6.7,
    }], layer, {
      showAtlas: true,
      showOsm: true,
      minZoom: 13,
      currentZoom: 18,
      isContext: true,
    });

    expect(L.polyline.mock.calls[0][1]).toEqual(expect.objectContaining({ opacity: 0.4 }));
  });

  test('does not draw below the configured threshold', () => {
    const count = window.LineRenderer.drawAll([{
      stop_type: 'matched',
      atlas_lat: 46.5,
      atlas_lon: 6.6,
      osm_node_id: '1',
      osm_lat: 46.6,
      osm_lon: 6.7,
    }], layer, {
      showAtlas: true,
      showOsm: true,
      minZoom: 13,
      currentZoom: 12,
      isContext: false,
    });

    expect(count).toBe(0);
    expect(layer.addLayer).not.toHaveBeenCalled();
  });

  test('clears the supplied production layer', () => {
    window.LineRenderer.clearLines(layer);
    expect(layer.clearLayers).toHaveBeenCalledTimes(1);
  });

  test('publishes the production renderer in the shared namespace', () => {
    expect(window.MapComponents.LineRenderer).toBe(window.LineRenderer);
  });
});
