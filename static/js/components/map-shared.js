(function (global) {
  'use strict';

  function getAtlasMarkerIdentity(stopData) {
    if (!stopData) return null;
    if (stopData.sloid != null && stopData.sloid !== '') return String(stopData.sloid);
    if (stopData.representative_sloid != null && stopData.representative_sloid !== '') return String(stopData.representative_sloid);
    if (stopData.id != null && stopData.id !== '') return String(stopData.id);
    return null;
  }

  function getOsmMarkerIdentity(stopData) {
    if (!stopData) return null;
    if (stopData.osm_node_id != null && stopData.osm_node_id !== '') return String(stopData.osm_node_id);
    if (stopData.node_id != null && stopData.node_id !== '') return String(stopData.node_id);
    if (stopData.id != null && stopData.id !== '') return String(stopData.id);
    return null;
  }

  function getGtfsMarkerIdentity(stopData) {
    if (!stopData) return null;
    if (stopData.stop_id != null && stopData.stop_id !== '') return String(stopData.stop_id);
    return null;
  }

  function createEntityKey(entityType, stopData) {
    var normalizedType = String(entityType || '').toLowerCase();
    var identity = null;
    if (normalizedType === 'atlas') identity = getAtlasMarkerIdentity(stopData);
    if (normalizedType === 'osm') identity = getOsmMarkerIdentity(stopData);
    if (normalizedType === 'gtfs') identity = getGtfsMarkerIdentity(stopData);
    return identity == null ? null : normalizedType + ':' + identity;
  }

  /**
   * Shared completeness thresholds for viewport-driven maps.
   *
   * Pages still own their domain-specific overview query and visibility rules;
   * this only prevents the 13/15 zoom boundaries and result budget from
   * drifting between them.
   */
  function getViewportZoomPolicy(zoom) {
    var normalizedZoom = Number(zoom);
    var overviewZoom = AppConstants.MAP.ZOOM_MARKER_THRESHOLD;
    var fullDetailZoom = overviewZoom + AppConstants.MAP.ADDITIONAL_BANNER_ZOOM_LEVELS;
    var isOverview = normalizedZoom < overviewZoom;
    var isFullDetail = normalizedZoom >= fullDetailZoom;

    return {
      zoom: normalizedZoom,
      isOverview: isOverview,
      isFullDetail: isFullDetail,
      shouldShowBanner: !isFullDetail,
      limit: isFullDetail ? null : AppConstants.DATA_LOADING.GENERAL_LIMIT,
      mode: isOverview ? 'overview' : (isFullDetail ? 'full' : 'limited')
    };
  }

  function createBaseTileLayers() {
    var osm = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: AppConstants.MAP.MAX_ZOOM,
      maxNativeZoom: AppConstants.MAP.MAX_NATIVE_ZOOM,
      attribution: '© OpenStreetMap'
    });

    var transport = L.tileLayer('https://tile.memomaps.de/tilegen/{z}/{x}/{y}.png', {
      maxZoom: AppConstants.MAP.MAX_ZOOM,
      maxNativeZoom: 18,
      attribution: 'Map <a href="https://memomaps.de/">memomaps.de</a> <a href="http://creativecommons.org/licenses/by-sa/2.0/">CC-BY-SA</a>, map data &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    });

    var satellite = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
      maxZoom: AppConstants.MAP.MAX_ZOOM,
      maxNativeZoom: 19,
      attribution: 'Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EBP, and the GIS User Community'
    });

    return {
      osm: osm,
      transport: transport,
      satellite: satellite
    };
  }

  global.MapShared = Object.freeze({
    getAtlasMarkerIdentity: getAtlasMarkerIdentity,
    getOsmMarkerIdentity: getOsmMarkerIdentity,
    getGtfsMarkerIdentity: getGtfsMarkerIdentity,
    createEntityKey: createEntityKey,
    getViewportZoomPolicy: getViewportZoomPolicy,
    createBaseTileLayers: createBaseTileLayers
  });
  global.MapComponents = global.MapComponents || {};
  global.MapComponents.MapShared = global.MapShared;
})(window);
