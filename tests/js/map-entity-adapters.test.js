describe('Canonical map entities and page adapters', () => {
  const stop = { id: 1, sloid: 'source:a', osm_node_id: '2', stop_type: 'matched',
    atlas_lat: 47, atlas_lon: 8, osm_lat: 47, osm_lon: 8,
    has_atlas_duplicate: true, osm_node_type: 'platform' };

  beforeEach(() => {
    window.AppConstants = { MAP: { MAX_ZOOM: 20, LABEL_ICON_MIN_ZOOM: 18 } };
    require('./load-map-components')();
    window.L = global.L = { polyline: jest.fn((positions, style) => ({ positions, style })) };
  });

  test.each([[null, 8], ['', 8], [' ', 8], [NaN, 8], [Infinity, 8], [91, 8], [47, 181]])(
    'rejects invalid coordinates %p,%p', (lat, lon) => {
      expect(window.MapShared.createEntity('atlas', 'id', [lat, lon])).toBeNull();
    });

  test('zero coordinates and numeric IDs are valid, source coordinates are copied and immutable', () => {
    const source = [0, 0];
    const entity = window.MapShared.createEntity('osm', 0, source);
    source[0] = 70;
    expect(entity.key).toBe('osm:0');
    expect(entity.sourcePosition).toEqual([0, 0]);
    expect(Object.isFrozen(entity)).toBe(true);
    expect(Object.isFrozen(entity.sourcePosition)).toBe(true);
  });

  test.each(['atlas', 'osm', 'gtfs'])('all statuses and emphasis for %s use shared styles', type => {
    const entity = status => window.MapShared.createEntity(type, '1', [0, 0], { status });
    expect(window.MapRenderer.getEntityStyle(entity('matched')).color)
      .toBe(window.MapRenderer.getEntityStyle(entity('effectively_matched')).color);
    expect(window.MapRenderer.getEntityStyle(entity('unmatched')).color)
      .not.toBe(window.MapRenderer.getEntityStyle(entity('matched')).color);
    expect(window.MapRenderer.getEntityStyle({ ...entity('matched'), emphasis: 'context' }).opacity).toBe(0.6);
    expect(window.MapRenderer.getEntityStyle({ ...entity('matched'), emphasis: 'subdued' }))
      .toEqual(expect.objectContaining({ opacity: 0.4, fillOpacity: 0.2 }));
    expect(window.MapRenderer.getEntityStyle({ ...entity('matched'), emphasis: 'focused' }).opacity).toBe(1);
  });

  test.each([true, 'true', 1])('normalizes duplicate flag %p into the ATLAS D label', value => {
    expect(window.MapEntityAdapters.stopEntity('atlas', { ...stop, has_atlas_duplicate: value }).label).toBe('D');
  });

  test.each([false, 'false', '0', '', null])('normalizes absent duplicate flag %p', value => {
    expect(window.MapEntityAdapters.stopEntity('atlas', { ...stop, has_atlas_duplicate: value }).label).toBeNull();
  });

  test('label validation keeps GTFS circular and restricts labels to their entity type', () => {
    expect(window.MapEntityAdapters.stopEntity('osm', { ...stop, osm_node_type: 'railway_station' }).label).toBe('S');
    expect(window.MapShared.createEntity('gtfs', '1', [0, 0], { label: 'D' }).label).toBeNull();
    expect(window.MapShared.createEntity('atlas', '1', [0, 0], { label: 'P' }).label).toBeNull();
  });

  test('Index nested one-to-many and many-to-one matches produce unique entities and rich popup models', () => {
    const rows = [
      { ...stop, osm_matches: [{ osm_node_id: '2', osm_id: 10, osm_lat: 47, osm_lon: 8, osm_node_type: 'platform', distance_m: 4 },
        { osm_node_id: '3', osm_id: 11, osm_lat: 47.01, osm_lon: 8.01 }] },
      { ...stop, id: 2, sloid: 'source:b', osm_matches: [{ osm_node_id: '2', osm_id: 10, osm_lat: 47, osm_lon: 8, distance_m: 9 }] }
    ];
    const snapshot = window.MapEntityAdapters.stops(rows, { multiMatchPopups: true });
    expect(snapshot.entities.map(entity => entity.key)).toEqual(['atlas:source:a', 'osm:2', 'osm:3', 'atlas:source:b']);
    expect(snapshot.relationships).toHaveLength(3);
    const osm = snapshot.entities.find(entity => entity.key === 'osm:2');
    expect(osm.popupRef.id).toBe(10);
    expect(osm.popupRef.payload.atlas_matches.map(match => [match.sloid, match.distance_m]))
      .toEqual([['source:a', 4], ['source:b', 9]]);
    expect(osm).not.toHaveProperty('stopData');
    expect(osm).not.toHaveProperty('osm_node_type');
    expect(window.MapEntityAdapters.stops(rows).entities.find(entity => entity.key === 'osm:2').popupRef)
      .toEqual({ id: 10 });
  });

  test('Top-N only displays the selected primary pairs and respects side filters', () => {
    const snapshot = window.MapEntityAdapters.topMatches([{ ...stop,
      osm_matches: [{ osm_node_id: 'other', osm_lat: 48, osm_lon: 9 }] }], { showOsm: false });
    expect(snapshot.entities.map(entity => entity.key)).toEqual(['atlas:source:a']);
    expect(snapshot.relationships.map(edge => edge.toKey)).toEqual(['osm:2']);
  });

  test('Problems context normalizes mixed rows without introducing an ATLAS marker for standalone OSM', () => {
    const snapshot = window.MapEntityAdapters.stops([
      { id: 4, stop_type: 'atlas_unmatched', lat: '0', lon: '0' },
      { id: 5, stop_type: 'effectively_matched', osm_node_id: '5', lat: 1, lon: 1, osm_lat: 1, osm_lon: 1 }
    ], { emphasis: 'context' });
    expect(snapshot.entities.map(entity => [entity.key, entity.status, entity.emphasis]))
      .toEqual([['atlas:4', 'unmatched', 'context'], ['osm:5', 'effectively_matched', 'context']]);
  });

  test('relationship endpoints share overlap layout while source positions remain unchanged', () => {
    const snapshot = window.MapEntityAdapters.stops([stop]);
    const layout = window.MapRenderer.layoutEntities(snapshot.entities, { zoom: 20, sourcePositionsByKey: snapshot.sourcePositionsByKey });
    const layer = { addLayer: jest.fn() };
    window.LineRenderer.drawRelationships(snapshot.relationships, layer, layout.displayPositionsByKey);
    expect(L.polyline.mock.calls[0][0]).toEqual(layout.descriptors.map(item => item.displayPosition));
    expect(layout.descriptors[0].displayPosition).not.toEqual([47, 8]);
    expect(snapshot.entities.every(entity => entity.sourcePosition[0] === 47 && entity.sourcePosition[1] === 8)).toBe(true);
  });

  test('pair/trio links deduplicate both directions and retain hidden partner source positions', () => {
    const partner = { partner_node_id: '3', partner_osm_lat: 47.01, partner_osm_lon: 8.01 };
    const snapshot = window.MapEntityAdapters.stops([{ ...stop, osm_group_partner: partner, osm_trio_links: [partner] }]);
    expect(snapshot.relationships.filter(edge => edge.relationshipType === 'group_link')).toHaveLength(1);
    expect(snapshot.sourcePositionsByKey.get('osm:3')).toEqual([47.01, 8.01]);
    const layer = { addLayer: jest.fn() };
    expect(window.LineRenderer.drawRelationships(snapshot.relationships, layer, snapshot.sourcePositionsByKey,
      { currentZoom: 16, showAtlas: false })).toBe(0);
    expect(window.LineRenderer.drawRelationships(snapshot.relationships, layer, snapshot.sourcePositionsByKey,
      { currentZoom: 17, showAtlas: false })).toBe(1);
    expect(L.polyline.mock.calls[0][1]).toEqual(expect.objectContaining({ dashArray: '6,4' }));
  });

  test('route direction grouping preserves source order, status, labels and deduplicates repeated stops', () => {
    const snapshot = window.MapEntityAdapters.routeDirection({ atlas_uic_groups: [
      { uic_ref: 'second', members: [{ stop_id: 'b', lat: 47, lon: 8, stop_type: 'atlas_unmatched', has_atlas_duplicate: true }] },
      { uic_ref: 'first', members: [{ stop_id: 'a', lat: 48, lon: 9, stop_type: 'matched' }, { stop_id: 'b', lat: 47, lon: 8 }] }
    ], osm_uic_groups: [{ members: [{ stop_id: '2', lat: 47, lon: 8, stop_type: 'effectively_matched', osm_node_type: 'platform' }] }] });
    expect(snapshot.entities.map(entity => entity.key)).toEqual(['atlas:b', 'atlas:a', 'osm:2']);
    expect(snapshot.entities[0]).toEqual(expect.objectContaining({ label: 'D', status: 'unmatched' }));
    expect(snapshot.entities[2]).toEqual(expect.objectContaining({ label: 'P', status: 'effectively_matched' }));
    const layout = window.MapRenderer.layoutEntities(snapshot.entities, { zoom: 20, overlap: false });
    expect(layout.descriptors.map(item => item.displayPosition)).toEqual(snapshot.entities.map(entity => entity.sourcePosition));
  });

  test('GTFS relationships resolve by endpoint identity even when cached coordinate snapshots are stale', () => {
    const snapshot = window.MapEntityAdapters.gtfs({
      atlasStops: [stop], gtfsStops: [{ stop_id: 'gtfs:1', stop_lat: 47.01, stop_lon: 8.01, match_status: 'matched' }],
      matches: [{ sloid: stop.sloid, stop_id: 'gtfs:1', atlas_lat: null, atlas_lon: null, gtfs_stop_lat: 0, gtfs_stop_lon: 0 }]
    });
    expect(snapshot.relationships).toHaveLength(1);
    expect(snapshot.sourcePositionsByKey.get('gtfs:gtfs:1')).toEqual([47.01, 8.01]);
  });
});
