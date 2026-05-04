(function () {
  'use strict';

  var config = window.routesGtfsStopIdSloidConfig || {};
  var mapElement = document.getElementById('routesGtfsStopIdSloidMap');
  if (!mapElement || typeof L === 'undefined') {
    return;
  }

  var bannerElement = document.getElementById('routesGtfsStopIdSloidBanner');
  var summaryElement = document.getElementById('headerSummaryStats');
  var activeRequestController = null;

  function setBanner(text, isError) {
    if (!bannerElement) {
      return;
    }
    bannerElement.textContent = text || '';
    bannerElement.classList.toggle('d-none', !text);
    bannerElement.classList.toggle('route-card__map-status--error', !!isError);
  }

  function formatCoordinate(value) {
    var numeric = Number(value);
    return Number.isFinite(numeric) ? numeric.toFixed(6) : 'n/a';
  }

  function formatDistance(value) {
    var numeric = Number(value);
    return Number.isFinite(numeric) ? numeric.toFixed(2) + ' m' : 'n/a';
  }

  function buildListHtml(items, formatter) {
    if (!Array.isArray(items) || items.length === 0) {
      return '<p class="routes-gtfs-popup__empty">None</p>';
    }

    return '<ul class="routes-gtfs-popup__list">' + items.map(function (item) {
      return '<li>' + formatter(item) + '</li>';
    }).join('') + '</ul>';
  }

  function renderGtfsPopup(data) {
    return [
      '<div class="routes-gtfs-popup">',
      '<h5 class="routes-gtfs-popup__title">GTFS stop_id</h5>',
      '<p class="routes-gtfs-popup__meta">Green markers are matched GTFS stops. Gray markers are unmatched.</p>',
      '<table class="routes-gtfs-popup__table">',
      '<tr><td>stop_id</td><td><span class="routes-gtfs-popup__mono">' + (data.stop_id || 'n/a') + '</span></td></tr>',
      '<tr><td>Name</td><td>' + (data.stop_name || 'n/a') + '</td></tr>',
      '<tr><td>UIC</td><td><span class="routes-gtfs-popup__mono">' + (data.uic_number || 'n/a') + '</span></td></tr>',
      '<tr><td>local_ref</td><td><span class="routes-gtfs-popup__mono">' + (data.local_ref || 'n/a') + '</span></td></tr>',
      '<tr><td>normalized</td><td><span class="routes-gtfs-popup__mono">' + (data.normalized_local_ref || 'n/a') + '</span></td></tr>',
      '<tr><td>Coordinates</td><td><span class="routes-gtfs-popup__mono">' + formatCoordinate(data.stop_lat) + ', ' + formatCoordinate(data.stop_lon) + '</span></td></tr>',
      '<tr><td>Matched sloids</td><td>' + String(data.matched_sloid_count || 0) + '</td></tr>',
      '<tr><td>ATLAS candidates</td><td>' + String(data.candidate_atlas_count || 0) + '</td></tr>',
      '</table>',
      '<div class="routes-gtfs-popup__section">',
      '<h6>Matched ATLAS stops</h6>',
      buildListHtml(data.matched_sloids, function (item) {
        return '<span class="routes-gtfs-popup__mono">' + (item.sloid || 'n/a') + '</span>'
          + (item.atlas_designation_official ? ' / ' + item.atlas_designation_official : '')
          + (item.match_method ? ' / ' + item.match_method : '')
          + (item.distance_m != null ? ' / ' + formatDistance(item.distance_m) : '');
      }),
      '</div>',
      '<div class="routes-gtfs-popup__section">',
      '<h6>Same-UIC ATLAS candidates</h6>',
      buildListHtml(data.candidate_atlas, function (item) {
        return '<span class="routes-gtfs-popup__mono">' + (item.sloid || 'n/a') + '</span>'
          + (item.atlas_designation_official ? ' / ' + item.atlas_designation_official : '')
          + (item.atlas_business_org_abbr ? ' / ' + item.atlas_business_org_abbr : '');
      }),
      '</div>',
      '</div>'
    ].join('');
  }

  function renderAtlasPopup(data) {
    return [
      '<div class="routes-gtfs-popup">',
      '<h5 class="routes-gtfs-popup__title">ATLAS sloid</h5>',
      '<p class="routes-gtfs-popup__meta">Blue markers are matched ATLAS stops. Red markers are unmatched.</p>',
      '<table class="routes-gtfs-popup__table">',
      '<tr><td>Sloid</td><td><span class="routes-gtfs-popup__mono">' + (data.sloid || 'n/a') + '</span></td></tr>',
      '<tr><td>UIC</td><td><span class="routes-gtfs-popup__mono">' + (data.uic_ref || 'n/a') + '</span></td></tr>',
      '<tr><td>Name</td><td>' + (data.atlas_designation_official || 'n/a') + '</td></tr>',
      '<tr><td>Designation</td><td>' + (data.atlas_designation || 'n/a') + '</td></tr>',
      '<tr><td>Business org</td><td>' + (data.atlas_business_org_abbr || 'n/a') + '</td></tr>',
      '<tr><td>Coordinates</td><td><span class="routes-gtfs-popup__mono">' + formatCoordinate(data.atlas_lat) + ', ' + formatCoordinate(data.atlas_lon) + '</span></td></tr>',
      '<tr><td>Matched GTFS</td><td>' + String(data.matched_gtfs_count || 0) + '</td></tr>',
      '<tr><td>Same-UIC GTFS</td><td>' + String(data.same_uic_gtfs_count || 0) + '</td></tr>',
      '</table>',
      '<div class="routes-gtfs-popup__section">',
      '<h6>Matched GTFS stops</h6>',
      buildListHtml(data.matched_gtfs, function (item) {
        return '<span class="routes-gtfs-popup__mono">' + (item.stop_id || 'n/a') + '</span>'
          + (item.stop_name ? ' / ' + item.stop_name : '')
          + (item.match_method ? ' / ' + item.match_method : '')
          + (item.distance_m != null ? ' / ' + formatDistance(item.distance_m) : '');
      }),
      '</div>',
      '<div class="routes-gtfs-popup__section">',
      '<h6>Same-UIC GTFS candidates</h6>',
      buildListHtml(data.same_uic_gtfs, function (item) {
        return '<span class="routes-gtfs-popup__mono">' + (item.stop_id || 'n/a') + '</span>'
          + (item.stop_name ? ' / ' + item.stop_name : '')
          + (item.local_ref ? ' / ref ' + item.local_ref : '');
      }),
      '</div>',
      '</div>'
    ].join('');
  }

  function createGtfsMarker(lat, lon, color) {
    return L.circleMarker([lat, lon], {
      color: color,
      fillColor: color,
      radius: 5,
      weight: 1.5,
      fillOpacity: 0.85
    });
  }

  function buildPopupUrl(entityType, idValue) {
    var params = new URLSearchParams({ entity_type: entityType });
    if (entityType === 'atlas') {
      params.set('sloid', idValue);
    } else {
      params.set('stop_id', idValue);
    }
    return config.popupUrl + '?' + params.toString();
  }

  function attachPopupLoader(marker, entityType, idValue) {
    marker.on('click', function () {
      if (marker._gtfsPopupLoading) {
        return;
      }
      if (marker._gtfsPopupLoaded) {
        marker.openPopup();
        return;
      }

      marker._gtfsPopupLoading = true;
      fetch(buildPopupUrl(entityType, idValue))
        .then(function (response) {
          if (!response.ok) {
            throw new Error('Popup request failed with status ' + response.status);
          }
          return response.json();
        })
        .then(function (payload) {
          var html = entityType === 'atlas' ? renderAtlasPopup(payload) : renderGtfsPopup(payload);
          var popup = typeof createPopupWithOptions === 'function'
            ? createPopupWithOptions(html)
            : L.popup({ autoClose: false, closeOnClick: false, maxWidth: 900 }).setContent(html);
          marker.bindPopup(popup);
          marker._gtfsPopupLoaded = true;
          marker.openPopup();
        })
        .catch(function (error) {
          console.error('Failed to load GTFS popup', error);
        })
        .finally(function () {
          marker._gtfsPopupLoading = false;
        });
    });
  }

  function renderSummary(summary) {
    if (!summaryElement) {
      return;
    }

    var assignmentLine = 'Strict ' + String(summary.assignments.strict || 0)
      + ' / Coordinate ' + String(summary.assignments.coordinate_proximity || 0)
      + ' / Fallback ' + String(summary.assignments.unique_number_fallback || 0);

    summaryElement.innerHTML = [
      '<div class="header-summary__stat"><strong>' + String(summary.total_gtfs_stops || 0) + '</strong> GTFS stops, <span style="color:#2f9e44;font-weight:bold;">' + String(summary.gtfs_coverage_percent || 0) + '% matched</span></div>',
      '<div class="header-summary__stat"><strong>' + String(summary.total_atlas_stops || 0) + '</strong> ATLAS stops, <span style="color:#174092;font-weight:bold;">' + String(summary.atlas_coverage_percent || 0) + '% touched</span></div>',
      '<div class="header-summary__stat">' + assignmentLine + (summary.algorithm_version ? ' / ' + summary.algorithm_version : '') + '</div>'
    ].join('');
  }

  function syncSummaryLayout() {
    if (!window.HeaderSummary || typeof window.HeaderSummary.setCollapsed !== 'function') {
      return;
    }
    window.HeaderSummary.setCollapsed(window.matchMedia('(max-width: 768px)').matches);
  }

  function loadSummary() {
    fetch(config.summaryUrl)
      .then(function (response) {
        if (!response.ok) {
          throw new Error('Summary request failed with status ' + response.status);
        }
        return response.json();
      })
      .then(renderSummary)
      .catch(function (error) {
        console.error('Failed to load GTFS summary', error);
        if (summaryElement) {
          summaryElement.innerHTML = '<div class="header-summary__stat">Failed to load GTFS summary.</div>';
        }
      });
  }

  function createBaseLayers(mapInstance) {
    var baseLayers = (window.MapShared && typeof window.MapShared.createBaseTileLayers === 'function')
      ? window.MapShared.createBaseTileLayers()
      : null;

    var osmLayer = baseLayers ? baseLayers.osm : L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 20,
      maxNativeZoom: 19,
      attribution: '© OpenStreetMap'
    });

    var transportLayer = baseLayers ? baseLayers.transport : L.tileLayer('https://tile.memomaps.de/tilegen/{z}/{x}/{y}.png', {
      maxZoom: 20,
      maxNativeZoom: 18,
      attribution: 'Map memomaps.de, map data © OpenStreetMap contributors'
    });

    var satelliteLayer = baseLayers ? baseLayers.satellite : L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
      maxZoom: 20,
      maxNativeZoom: 19,
      attribution: 'Tiles © Esri'
    });

    osmLayer.addTo(mapInstance);
    L.control.layers({
      OpenStreetMap: osmLayer,
      Transport: transportLayer,
      Satellite: satelliteLayer
    }, {}, { position: 'bottomleft' }).addTo(mapInstance);
  }

  function buildClusteredEntries(payload) {
    var markerEntries = [];
    var canCluster = typeof MarkerClusterManager === 'function';
    if (!canCluster) {
      payload.atlas_stops.forEach(function (stop) {
        markerEntries.push({ lat: stop.atlas_lat, lon: stop.atlas_lon, markerData: { entityType: 'atlas', data: stop } });
      });
      payload.gtfs_stops.forEach(function (stop) {
        markerEntries.push({ lat: stop.stop_lat, lon: stop.stop_lon, markerData: { entityType: 'gtfs', data: stop } });
      });
      return markerEntries;
    }

    var clusterManager = new MarkerClusterManager();
    payload.atlas_stops.forEach(function (stop) {
      clusterManager.addMarker(stop.atlas_lat, stop.atlas_lon, {
        entityType: 'atlas',
        data: stop
      });
    });
    payload.gtfs_stops.forEach(function (stop) {
      clusterManager.addMarker(stop.stop_lat, stop.stop_lon, {
        entityType: 'gtfs',
        data: stop
      });
    });
    return clusterManager.getClusteredData();
  }

  var defaultCenter = (window.AppConstants && window.AppConstants.MAP && window.AppConstants.MAP.DEFAULT_CENTER) || [46.8182, 8.2275];
  var defaultZoom = (window.AppConstants && window.AppConstants.MAP && window.AppConstants.MAP.DEFAULT_ZOOM) || 8;
  var minZoom = (window.AppConstants && window.AppConstants.MAP && window.AppConstants.MAP.MIN_ZOOM) || 8;
  var maxZoom = (window.AppConstants && window.AppConstants.MAP && window.AppConstants.MAP.MAX_ZOOM) || 20;
  var maxBounds = (window.AppConstants && window.AppConstants.MAP && window.AppConstants.MAP.MAX_BOUNDS) || [[45.5, 5.5], [48.0, 11.0]];

  var map = L.map(mapElement, {
    closePopupOnClick: false,
    preferCanvas: false,
    renderer: L.svg({ padding: 0.1 }),
    minZoom: minZoom,
    maxZoom: maxZoom,
    maxBounds: maxBounds,
    maxBoundsViscosity: 1.0,
    zoomControl: false
  }).setView(defaultCenter, defaultZoom);

  createBaseLayers(map);
  L.control.zoom({ position: 'bottomleft' }).addTo(map);

  var atlasMarkersLayer = L.layerGroup().addTo(map);
  var gtfsMarkersLayer = L.layerGroup().addTo(map);
  var linesLayer = L.layerGroup().addTo(map);

  if (typeof attachPopupLineHandlersToMap === 'function') {
    attachPopupLineHandlersToMap(map);
  }

  function drawMatchLine(match) {
    if (!match || match.atlas_lat == null || match.atlas_lon == null || match.gtfs_stop_lat == null || match.gtfs_stop_lon == null) {
      return;
    }

    var styleOptions = {
      color: '#174092',
      weight: 1.6,
      opacity: 0.38,
      dashArray: '6 8'
    };

    if (window.LineRenderer && typeof window.LineRenderer.drawLine === 'function') {
      window.LineRenderer.drawLine(linesLayer, match.atlas_lat, match.atlas_lon, match.gtfs_stop_lat, match.gtfs_stop_lon, styleOptions);
      return;
    }

    L.polyline([
      [match.atlas_lat, match.atlas_lon],
      [match.gtfs_stop_lat, match.gtfs_stop_lon]
    ], styleOptions).addTo(linesLayer);
  }

  function renderPayload(payload) {
    atlasMarkersLayer.clearLayers();
    gtfsMarkersLayer.clearLayers();
    linesLayer.clearLayers();

    (payload.matches || []).forEach(drawMatchLine);

    buildClusteredEntries(payload).forEach(function (entry) {
      var markerData = entry.markerData || {};
      var data = markerData.data || {};
      var marker = null;

      if (markerData.entityType === 'atlas') {
        var atlasColor = data.match_status === 'matched' ? '#174092' : '#DC3545';
        marker = typeof createAtlasMarker === 'function'
          ? createAtlasMarker(entry.lat, entry.lon, atlasColor, data.has_atlas_duplicate, map.getZoom())
          : L.circleMarker([entry.lat, entry.lon], { color: atlasColor, radius: 6, fillOpacity: 0.8, weight: 2 });
        attachPopupLoader(marker, 'atlas', data.sloid);
        atlasMarkersLayer.addLayer(marker);
        return;
      }

      var gtfsColor = data.match_status === 'matched' ? '#2f9e44' : '#6C757D';
      marker = createGtfsMarker(entry.lat, entry.lon, gtfsColor);
      attachPopupLoader(marker, 'gtfs', data.stop_id);
      gtfsMarkersLayer.addLayer(marker);
    });

    var messages = [];
    if (payload.meta && payload.meta.overview_mode) {
      messages.push('Overview mode is active below zoom ' + String(config.detailZoom || 11) + '.');
    }
    if (payload.meta && payload.meta.atlas_capped) {
      messages.push('ATLAS markers capped at ' + String(payload.meta.overview_mode ? config.overviewLimit : config.detailLimit) + '.');
    }
    if (payload.meta && payload.meta.gtfs_capped) {
      messages.push('GTFS markers capped at ' + String(payload.meta.overview_mode ? config.overviewLimit : config.detailLimit) + '.');
    }
    if (payload.meta && payload.meta.matches_returned) {
      messages.push(String(payload.meta.matches_returned) + ' GTFS↔ATLAS lines visible.');
    }
    if (!messages.length && payload.meta && payload.meta.atlas_returned === 0 && payload.meta.gtfs_returned === 0) {
      messages.push('No GTFS or ATLAS stops fall inside the current viewport.');
    }
    setBanner(messages.join(' '), false);
  }

  function loadViewportData() {
    var bounds = map.getBounds();
    var params = new URLSearchParams({
      min_lat: String(bounds.getSouth()),
      min_lon: String(bounds.getWest()),
      max_lat: String(bounds.getNorth()),
      max_lon: String(bounds.getEast()),
      zoom: String(map.getZoom())
    });

    if (activeRequestController) {
      activeRequestController.abort();
    }
    activeRequestController = new AbortController();

    fetch(config.mapUrl + '?' + params.toString(), { signal: activeRequestController.signal })
      .then(function (response) {
        if (!response.ok) {
          throw new Error('Map request failed with status ' + response.status);
        }
        return response.json();
      })
      .then(renderPayload)
      .catch(function (error) {
        if (error && error.name === 'AbortError') {
          return;
        }
        console.error('Failed to load GTFS stop_id/sloid map payload', error);
        atlasMarkersLayer.clearLayers();
        gtfsMarkersLayer.clearLayers();
        linesLayer.clearLayers();
        setBanner('Failed to load GTFS stop_id to sloid map data.', true);
      });
  }

  function debounce(fn, waitMs) {
    var timeoutId = null;
    return function () {
      clearTimeout(timeoutId);
      timeoutId = setTimeout(fn, waitMs);
    };
  }

  syncSummaryLayout();
  window.addEventListener('resize', function () {
    syncSummaryLayout();
    map.invalidateSize();
  });

  loadSummary();
  loadViewportData();
  map.on('moveend zoomend', debounce(loadViewportData, 180));
})();