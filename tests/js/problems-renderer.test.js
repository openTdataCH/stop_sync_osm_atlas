const fs = require('fs');
const path = require('path');

function createMarker(order, eventName) {
  return {
    bindPopup: jest.fn().mockReturnThis(),
    addTo: jest.fn().mockReturnThis(),
    openPopup: jest.fn().mockReturnThis(),
    recordCreation() {
      order.push(eventName);
      return this;
    },
  };
}

describe('ProblemsRenderer final-view marker construction', () => {
  let order;
  let map;
  let layers;
  let atlasMarker;
  let osmMarker;

  beforeEach(() => {
    order = [];
    map = {
      fitBounds: jest.fn(() => order.push('fitBounds')),
      setView: jest.fn(() => order.push('setView')),
      getZoom: jest.fn(() => {
        order.push('getZoom');
        return 18;
      }),
    };
    layers = {
      markersLayer: { clearLayers: jest.fn() },
      linesLayer: { clearLayers: jest.fn() },
    };
    atlasMarker = createMarker(order, 'createAtlasMarker');
    osmMarker = createMarker(order, 'createOsmMarker');

    window.AppConstants = global.AppConstants = {
      COLORS: {
        ATLAS_MATCHED: '#174092',
        OSM_MATCHED: '#4CAF50',
        ATLAS_UNMATCHED: '#DC3545',
        OSM_UNMATCHED: '#6C757D',
        LINE_ATLAS_OSM: '#174092',
      },
    };
    window.MapRenderer = global.MapRenderer = {
      createAtlasMarker: jest.fn(() => atlasMarker.recordCreation()),
      createOsmMarker: jest.fn(() => osmMarker.recordCreation()),
      createMarkersWithOverlapHandling: jest.fn(() => {
        order.push('createMarkersWithOverlapHandling');
        return [];
      }),
      createPopupWithOptions: jest.fn(content => ({ content })),
    };
    window.PopupRenderer = global.PopupRenderer = {
      generatePopupHtml: jest.fn(() => 'matched popup'),
      generateSingleAtlasBubbleHtml: jest.fn(() => 'atlas popup'),
      generateSingleOsmBubbleHtml: jest.fn(() => 'osm popup'),
    };
    window.L = global.L = {
      latLngBounds: jest.fn(() => ({ pad: jest.fn(() => ({ padded: true })) })),
      polyline: jest.fn(() => ({ addTo: jest.fn().mockReturnThis() })),
    };

    delete window.ProblemsRenderer;
    const scriptPath = path.join(__dirname, '../../static/js/pages/problems-renderer.js');
    window.eval(fs.readFileSync(scriptPath, 'utf8'));
    global.ProblemsRenderer = window.ProblemsRenderer;
  });

  test('fits a matched problem before reading zoom and constructing its markers', () => {
    ProblemsRenderer.drawProblemOnMap(map, {
      problem: 'distance',
      stop_type: 'matched',
      atlas_lat: 46.53,
      atlas_lon: 6.64,
      osm_lat: 46.54,
      osm_lon: 6.65,
      has_atlas_duplicate: true,
      osm_node_type: 'platform',
    }, layers);

    expect(order).toEqual([
      'fitBounds',
      'getZoom',
      'createAtlasMarker',
      'createOsmMarker',
    ]);
    expect(MapRenderer.createAtlasMarker).toHaveBeenCalledWith(
      46.53, 6.64, '#174092', true, 18
    );
    expect(MapRenderer.createOsmMarker).toHaveBeenCalledWith(
      46.54, 6.65, '#4CAF50', 'platform', 18
    );
  });

  test.each([
    {
      label: 'ATLAS',
      stop: {
        problem: 'unmatched',
        stop_type: 'atlas_unmatched',
        atlas_lat: 46.53,
        atlas_lon: 6.64,
        has_atlas_duplicate: true,
      },
      creationEvent: 'createAtlasMarker',
      markerFactory: 'createAtlasMarker',
    },
    {
      label: 'OSM',
      stop: {
        problem: 'unmatched',
        stop_type: 'osm_unmatched',
        osm_lat: 46.54,
        osm_lon: 6.65,
        osm_node_type: 'railway_station',
      },
      creationEvent: 'createOsmMarker',
      markerFactory: 'createOsmMarker',
    },
  ])('sets the unmatched $label view before reading zoom and constructing its marker', ({ stop, creationEvent, markerFactory }) => {
    ProblemsRenderer.drawProblemOnMap(map, stop, layers);

    expect(order).toEqual(['setView', 'getZoom', creationEvent]);
    expect(MapRenderer[markerFactory].mock.calls[0][4]).toBe(18);
  });

  test('fits duplicate bounds before reading zoom and constructing offset markers', () => {
    ProblemsRenderer.drawProblemOnMap(map, {
      problem: 'duplicates',
      group_type: 'atlas',
      members: [{
        id: 10,
        sloid: 'ch:1:sloid:10',
        atlas_lat: 46.54,
        atlas_lon: 6.65,
        has_atlas_duplicate: true,
      }],
    }, layers);

    expect(order).toEqual([
      'fitBounds',
      'getZoom',
      'createMarkersWithOverlapHandling',
    ]);
    expect(MapRenderer.createMarkersWithOverlapHandling.mock.calls[0][2]).toEqual({
      map,
      zoom: 18,
    });
  });
});
