// API-specific normalization belongs here; renderers receive only canonical entities and relationships.
(function (global) {
  'use strict';
  const shared = global.MapShared;
  const isDuplicate = value => value != null && !['', 'false', '0', 'none', 'null', 'undefined'].includes(String(value).trim().toLowerCase());

  const firstIdentifier = (...values) => values.find(value => value != null && value !== '');

  function stopEntity(type, stop, options = {}) {
    const atlas = type === 'atlas';
    const position = options.position || (atlas
      ? [stop.atlas_lat ?? stop.lat, stop.atlas_lon ?? stop.lon]
      : [stop.osm_lat, stop.osm_lon]);
    return shared.createEntity(type, options.identifier ?? (atlas
      ? firstIdentifier(stop.sloid, stop.representative_sloid, stop.id) : firstIdentifier(stop.osm_node_id, stop.node_id, stop.id)), position, {
      status: options.status || stop.match_status || stop.stop_type,
      emphasis: options.emphasis,
      label: atlas ? (isDuplicate(stop.has_atlas_duplicate) ? 'D' : null)
        : ({ platform: 'P', railway_station: 'S' }[stop.osm_node_type] || null),
      popupRef: options.popupRef || { id: stop.id }
    });
  }

  function snapshot() {
    const entities = new Map(), relationships = new Map(), sourcePositionsByKey = new Map();
    return {
      add(entity) {
        if (entity && !entities.has(entity.key)) entities.set(entity.key, entity);
        if (entity) sourcePositionsByKey.set(entity.key, entity.sourcePosition);
        return entity;
      },
      link(from, to, relationshipType = 'stop_match', distanceM = null) {
        if (!from || !to) return;
        sourcePositionsByKey.set(from.key, from.sourcePosition);
        sourcePositionsByKey.set(to.key, to.sourcePosition);
        const keys = [from.key, to.key].sort();
        const key = relationshipType + ':' + keys.join('|');
        relationships.set(key, Object.freeze({ key, fromKey: from.key, toKey: to.key,
          relationshipType, status: 'matched', distanceM }));
      },
      result() { return { entities: [...entities.values()], relationships: [...relationships.values()], sourcePositionsByKey }; }
    };
  }

  function stops(rows, options = {}) {
    const result = snapshot();
    const osmMatches = new Map();
    (rows || []).forEach(stop => {
      const atlas = (stop.sloid || stop.representative_sloid || stop.stop_type === 'atlas_unmatched')
        ? stopEntity('atlas', stop, options) : null;
      if (options.showAtlas !== false) result.add(atlas);
      const matches = Array.isArray(stop.osm_matches) && stop.osm_matches.length ? stop.osm_matches : [stop];
      matches.forEach(match => {
        const data = match === stop ? stop : { ...stop, ...match, id: match.osm_id || stop.id };
        const osm = stopEntity('osm', data, options);
        if (options.showOsm !== false) result.add(osm);
        if (stop.stop_type === 'matched') result.link(atlas, osm, 'stop_match', match.distance_m ?? stop.distance_m);
        if (osm && atlas && match !== stop && options.multiMatchPopups) {
          const group = osmMatches.get(osm.key) || { data, matches: [] };
          group.matches.push({ ...stop, distance_m: match.distance_m, match_type: match.match_type || stop.match_type });
          osmMatches.set(osm.key, group);
        }
      });
      const osm = stopEntity('osm', stop, options);
      const links = [...(stop.osm_trio_links || []), ...(stop.osm_group_partner ? [stop.osm_group_partner] : [])];
      links.forEach(link => result.link(osm, shared.createEntity('osm', link.partner_node_id,
        [link.partner_osm_lat, link.partner_osm_lon]), 'group_link'));
    });
    const data = result.result();
    data.entities = data.entities.map(entity => {
      const group = osmMatches.get(entity.key);
      if (!group || group.matches.length < 2) return entity;
      return Object.freeze({ ...entity, popupRef: { id: group.data.id, payload: {
        ...group.data, stop_type: 'matched', is_osm_node: true, atlas_matches: group.matches
      } } });
    });
    return data;
  }

  function gtfs(payload) {
    const result = snapshot();
    (payload.atlasStops || []).forEach(stop => result.add(stopEntity('atlas', stop)));
    (payload.gtfsStops || []).forEach(stop => result.add(shared.createEntity('gtfs', stop.stop_id,
      [stop.stop_lat, stop.stop_lon], { status: stop.match_status })));
    const entities = new Map(result.result().entities.map(entity => [entity.key, entity]));
    (payload.matches || []).forEach(match => result.link(
      entities.get('atlas:' + match.sloid) || shared.createEntity('atlas', match.sloid, [match.atlas_lat, match.atlas_lon]),
      entities.get('gtfs:' + match.stop_id) || shared.createEntity('gtfs', match.stop_id, [match.gtfs_stop_lat, match.gtfs_stop_lon]),
      'gtfs_identity', match.distance_m));
    const data = result.result();
    return data;
  }

  function topMatches(rows, options) {
    return stops(rows.filter(stop => stop.stop_type === 'matched' &&
      shared.finitePosition(stop.atlas_lat, stop.atlas_lon) && shared.finitePosition(stop.osm_lat, stop.osm_lon))
      .map(stop => ({ ...stop, osm_matches: [] })), options);
  }

  function routeDirection(direction) {
    const result = snapshot();
    ['atlas', 'osm'].forEach(type => (direction[type + '_uic_groups'] || []).forEach(group =>
      (group.members || []).forEach(member => result.add(stopEntity(type, member, {
        identifier: member.stop_id, position: [member.lat, member.lon]
      })))));
    return result.result();
  }

  global.MapEntityAdapters = Object.freeze({ stopEntity, stops, gtfs, topMatches, routeDirection });
  global.MapComponents = global.MapComponents || {};
  global.MapComponents.MapEntityAdapters = global.MapEntityAdapters;
})(window);
