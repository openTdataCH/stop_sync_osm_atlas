const fs = require('fs');
const path = require('path');

describe('ProblemsRenderer final-view marker construction', () => {
  let order, map, layers, markers;
  const matched = { id: 1, sloid: 'ch:1:sloid:1', osm_node_id: '2', problem: 'distance', stop_type: 'matched',
    atlas_lat: 46.53, atlas_lon: 6.64, osm_lat: 46.54, osm_lon: 6.65,
    has_atlas_duplicate: true, osm_node_type: 'platform' };

  beforeEach(() => {
    order = []; markers = [];
    map = {
      fitBounds: jest.fn(() => order.push('fitBounds')),
      setView: jest.fn(() => order.push('setView')),
      getZoom: jest.fn(() => { order.push('getZoom'); return 18; })
    };
    layers = { markersLayer: { clearLayers: jest.fn(), addLayer: jest.fn() },
      linesLayer: { clearLayers: jest.fn(), addLayer: jest.fn() } };
    window.AppConstants = { MAP: { LABEL_ICON_MIN_ZOOM: 18, MAX_ZOOM: 20 } };
    require('./load-map-components')();
    window.MapRenderer = { ...window.MapRenderer, createPopupWithOptions: jest.fn(content => ({ content })) };
    window.PopupRenderer = {
      generatePopupHtml: jest.fn(() => 'matched popup'),
      generateSingleAtlasBubbleHtml: jest.fn(() => 'atlas popup'),
      generateSingleOsmBubbleHtml: jest.fn(() => 'osm popup')
    };
    function marker(position, options) {
      order.push('marker');
      const value = { position, options, bindPopup: jest.fn().mockReturnThis(), openPopup: jest.fn() };
      markers.push(value);
      return value;
    }
    window.L = global.L = {
      marker: jest.fn(marker), circleMarker: jest.fn(marker), divIcon: jest.fn(options => options),
      latLngBounds: jest.fn(() => ({ pad: jest.fn(() => ({ padded: true })) })),
      polyline: jest.fn((positions, options) => ({ positions, options }))
    };
    window.eval(fs.readFileSync(path.join(__dirname, '../../static/js/pages/problems-renderer.js'), 'utf8'));
  });

  test('fits matched bounds before construction, preserves source positions and opens the ATLAS popup', () => {
    window.ProblemsRenderer.drawProblemOnMap(map, matched, layers);
    expect(order).toEqual(['fitBounds', 'getZoom', 'marker', 'marker']);
    expect(markers.map(marker => marker.position)).toEqual([[46.53, 6.64], [46.54, 6.65]]);
    expect(markers[0].options.icon.html).toContain('>D</text>');
    expect(markers[1].options.icon.html).toContain('>P</text>');
    expect(L.polyline).toHaveBeenCalledWith(markers.map(marker => marker.position), expect.objectContaining({ color: '#174092' }));
    expect(markers[0].openPopup).toHaveBeenCalled();
    expect(markers[1].openPopup).not.toHaveBeenCalled();
  });

  test.each(['atlas', 'osm'])('sets the unmatched %s view before reading zoom', type => {
    window.ProblemsRenderer.drawProblemOnMap(map, { ...matched, problem: 'unmatched', stop_type: type + '_unmatched' }, layers);
    expect(order).toEqual(['setView', 'getZoom', 'marker']);
    expect(markers).toHaveLength(1);
    expect(markers[0].openPopup).toHaveBeenCalled();
    expect(L.polyline).not.toHaveBeenCalled();
  });

  test('fits duplicates before overlap layout and opens at most six focused popups', () => {
    const members = Array.from({ length: 8 }, (_, index) => ({ ...matched, id: index, sloid: 's' + index }));
    window.ProblemsRenderer.drawProblemOnMap(map, { problem: 'duplicates', group_type: 'atlas', members }, layers);
    expect(order.slice(0, 2)).toEqual(['fitBounds', 'getZoom']);
    expect(markers).toHaveLength(8);
    expect(markers.filter(marker => marker.openPopup.mock.calls.length)).toHaveLength(6);
    expect(new Set(markers.map(marker => marker.position.join(','))).size).toBe(8);
    expect(members.every(member => member.atlas_lat === 46.53 && member.atlas_lon === 6.64)).toBe(true);
  });

  test('a zoom redraw retains the current view', () => {
    window.ProblemsRenderer.drawProblemOnMap(map, matched, layers, { fitView: false });
    expect(map.fitBounds).not.toHaveBeenCalled();
    expect(map.setView).not.toHaveBeenCalled();
  });
});
