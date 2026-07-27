const fs = require('fs');
const path = require('path');

describe('MapShared identities', () => {
  beforeAll(() => {
    window.AppConstants = global.AppConstants = {
      MAP: {
        MAX_ZOOM: 20,
        MAX_NATIVE_ZOOM: 19,
        ZOOM_MARKER_THRESHOLD: 13,
        ADDITIONAL_BANNER_ZOOM_LEVELS: 2,
      },
      DATA_LOADING: { GENERAL_LIMIT: 1800 },
    };
    L.tileLayer = jest.fn(() => ({}));
    const scriptPath = path.join(__dirname, '../../static/js/components/map-shared.js');
    window.eval(fs.readFileSync(scriptPath, 'utf8'));
  });

  test('builds type-prefixed stable entity keys', () => {
    expect(window.MapShared.createEntityKey('atlas', { sloid: 'ch:1:sloid:1' }))
      .toBe('atlas:ch:1:sloid:1');
    expect(window.MapShared.createEntityKey('osm', { osm_node_id: 123 }))
      .toBe('osm:123');
    expect(window.MapShared.createEntityKey('gtfs', { stop_id: '8500:0:1' }))
      .toBe('gtfs:8500:0:1');
  });

  test('prefers canonical ATLAS identifiers', () => {
    expect(window.MapShared.getAtlasMarkerIdentity({ sloid: 'S1', representative_sloid: 'S2', id: 4 }))
      .toBe('S1');
  });

  test('returns null instead of creating an unstable key', () => {
    expect(window.MapShared.createEntityKey('gtfs', { id: 3 })).toBeNull();
    expect(window.MapShared.createEntityKey('unknown', { id: 3 })).toBeNull();
  });

  test('publishes the shared map namespace alias', () => {
    expect(window.MapComponents.MapShared).toBe(window.MapShared);
  });

  test.each([
    [12, 'overview', true, false, 1800],
    [13, 'limited', false, false, 1800],
    [14, 'limited', false, false, 1800],
    [15, 'full', false, true, null],
  ])('uses the shared viewport policy at zoom %s', (zoom, mode, isOverview, isFullDetail, limit) => {
    expect(window.MapShared.getViewportZoomPolicy(zoom)).toEqual(expect.objectContaining({
      mode,
      isOverview,
      isFullDetail,
      shouldShowBanner: !isFullDetail,
      limit,
    }));
  });
});
