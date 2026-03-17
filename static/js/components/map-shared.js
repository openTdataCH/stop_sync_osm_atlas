(function (global) {
  'use strict';

  function getAtlasMarkerIdentity(stopData) {
    if (!stopData) return null;
    if (stopData.sloid != null && stopData.sloid !== '') return String(stopData.sloid);
    if (stopData.representative_sloid != null && stopData.representative_sloid !== '') return String(stopData.representative_sloid);
    if (stopData.id != null && stopData.id !== '') return String(stopData.id);
    return null;
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

  global.MapShared = {
    getAtlasMarkerIdentity: getAtlasMarkerIdentity,
    createBaseTileLayers: createBaseTileLayers
  };
})(window);
