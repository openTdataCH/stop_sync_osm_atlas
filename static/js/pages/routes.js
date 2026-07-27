(function () {
  'use strict';

  var operatorDropdown = null;
  var osmOperatorDropdown = null;
  var headerSummaryController = null;
  var routeMaps = new Map();

  function getMultiValueParams(params, paramName) {
    var values = [];
    params.getAll(paramName).forEach(function (rawValue) {
      String(rawValue || '').split(',').forEach(function (value) {
        var normalized = value.trim();
        if (normalized && values.indexOf(normalized) === -1) {
          values.push(normalized);
        }
      });
    });
    return values;
  }

  function setMultiValueParam(params, paramName, values) {
    params.delete(paramName);
    if (values.length > 0) {
      params.set(paramName, values.join(','));
    }
  }

  function buildFilterRemovalUrl(currentHref, type, value) {
    var url = new URL(currentHref, window.location.origin);
    var params = url.searchParams;

    if (type === 'matched') {
      params.delete('matched');
    } else if (type === 'q') {
      params.delete('q');
    } else if (type === 'operator') {
      setMultiValueParam(
        params,
        'atlas_operator',
        getMultiValueParams(params, 'atlas_operator').filter(function (operator) {
          return operator !== value;
        })
      );
    } else if (type === 'osmOperator') {
      setMultiValueParam(
        params,
        'osm_operator',
        getMultiValueParams(params, 'osm_operator').filter(function (operator) {
          return operator !== value;
        })
      );
    }

    params.delete('page');
    var query = params.toString();
    return url.pathname + (query ? '?' + query : '') + url.hash;
  }

  function parseSelectedOperators() {
    var configElement = document.getElementById('routesPageConfig');
    var config = {};
    if (configElement) {
      try {
        config = JSON.parse(configElement.textContent);
      } catch (e) {
        console.error('Failed to parse routesPageConfig', e);
      }
    }
    var selected = config.selectedAtlasOperators;
    if (!Array.isArray(selected)) {
      return [];
    }
    return selected.filter(function (value) {
      return typeof value === 'string' && value.trim() !== '';
    });
  }

  function syncOperatorInput(selectedOperators) {
    var hiddenInput = document.getElementById('routesAtlasOperatorInput');
    if (!hiddenInput) {
      return;
    }
    hiddenInput.value = (selectedOperators || []).join(',');
  }

  function initOperatorDropdown() {
    var container = document.getElementById('atlasOperatorFilterRoutes');
    if (!container || typeof window.OperatorDropdown !== 'function') {
      return;
    }

    var initialSelection = parseSelectedOperators();

    operatorDropdown = new window.OperatorDropdown('#atlasOperatorFilterRoutes', {
      placeholder: 'Select operators...',
      multiple: true,
      onSelectionChange: function (selectedOperators) {
        syncOperatorInput(selectedOperators);
      }
    });

    operatorDropdown.setSelection(initialSelection);
    syncOperatorInput(initialSelection);

    // Auto-submit when dropdown closes if selection changed
    var dropdownEl = document.getElementById('routesAtlasDropdown');
    if (dropdownEl) {
      dropdownEl.addEventListener('hide.bs.dropdown', function () {
        var current = (operatorDropdown.getSelection() || []).join(',');
        var initial = (parseSelectedOperators() || []).join(',');
        if (current !== initial) {
          document.getElementById('routesToolbarForm').submit();
        }
      });
    }
  }

  function parseSelectedOsmOperators() {
    var configElement = document.getElementById('routesPageConfig');
    var config = {};
    if (configElement) {
      try {
        config = JSON.parse(configElement.textContent);
      } catch (e) {
        console.error('Failed to parse routesPageConfig', e);
      }
    }
    var selected = config.selectedOsmOperators;
    if (!Array.isArray(selected)) {
      return [];
    }
    return selected.filter(function (value) {
      return typeof value === 'string' && value.trim() !== '';
    });
  }

  function syncOsmOperatorInput(selectedOperators) {
    var hiddenInput = document.getElementById('routesOsmOperatorInput');
    if (!hiddenInput) {
      return;
    }
    hiddenInput.value = (selectedOperators || []).join(',');
  }

  function initOsmOperatorDropdown() {
    var container = document.getElementById('osmOperatorFilterRoutes');
    if (!container || typeof window.OperatorDropdown !== 'function') {
      return;
    }

    var initialSelection = parseSelectedOsmOperators();

    osmOperatorDropdown = new window.OperatorDropdown('#osmOperatorFilterRoutes', {
      apiUrl: '/api/osm_route_operators',
      placeholder: 'Select OSM route operators...',
      multiple: true,
      onSelectionChange: function (selectedOperators) {
        syncOsmOperatorInput(selectedOperators);
      }
    });

    osmOperatorDropdown.setSelection(initialSelection);
    syncOsmOperatorInput(initialSelection);

    // Auto-submit when dropdown closes if selection changed
    var dropdownEl = document.getElementById('routesOsmDropdown');
    if (dropdownEl) {
      dropdownEl.addEventListener('hide.bs.dropdown', function () {
        var current = (osmOperatorDropdown.getSelection() || []).join(',');
        var initial = (parseSelectedOsmOperators() || []).join(',');
        if (current !== initial) {
          document.getElementById('routesToolbarForm').submit();
        }
      });
    }
  }

  function initStatusFilter() {
    var form = document.getElementById('routesToolbarForm');
    var hiddenInput = document.getElementById('routesMatchedInput');
    var checkboxes = Array.prototype.slice.call(document.querySelectorAll('.routes-status-checkbox'));
    var statusAll = document.getElementById('matchedAll');
    var statusMatched = document.getElementById('matchedOnly');
    var statusUnmatched = document.getElementById('unmatchedOnly');
    var statusUnmatchedAtlas = document.getElementById('unmatchedAtlasOnly');
    var statusUnmatchedOsm = document.getElementById('unmatchedOsmOnly');

    if (!form || !hiddenInput || checkboxes.length === 0 || !statusAll || !statusMatched || !statusUnmatched || !statusUnmatchedAtlas || !statusUnmatchedOsm) {
      return;
    }

    function syncSelection(value) {
      var normalizedValue = value || 'all';
      hiddenInput.value = normalizedValue;
      statusAll.checked = normalizedValue === 'all';
      statusMatched.checked = normalizedValue === 'matched';
      statusUnmatched.checked = normalizedValue === 'unmatched';
      statusUnmatchedAtlas.checked = normalizedValue === 'unmatched' || normalizedValue === 'unmatched_atlas';
      statusUnmatchedOsm.checked = normalizedValue === 'unmatched' || normalizedValue === 'unmatched_osm';
    }

    syncSelection(hiddenInput.value);

    checkboxes.forEach(function (checkbox) {
      checkbox.addEventListener('change', function () {
        var nextValue = hiddenInput.value || 'all';

        if (checkbox === statusAll) {
          nextValue = 'all';
        } else if (checkbox === statusMatched) {
          nextValue = checkbox.checked ? 'matched' : 'all';
        } else if (checkbox === statusUnmatched) {
          nextValue = checkbox.checked ? 'unmatched' : 'all';
        } else if (checkbox === statusUnmatchedAtlas) {
          if (checkbox.checked) {
            nextValue = statusUnmatchedOsm.checked ? 'unmatched' : 'unmatched_atlas';
          } else {
            nextValue = statusUnmatchedOsm.checked ? 'unmatched_osm' : 'all';
          }
        } else if (checkbox === statusUnmatchedOsm) {
          if (checkbox.checked) {
            nextValue = statusUnmatchedAtlas.checked ? 'unmatched' : 'unmatched_osm';
          } else {
            nextValue = statusUnmatchedAtlas.checked ? 'unmatched_atlas' : 'all';
          }
        }

        syncSelection(nextValue);
        form.submit();
      });
    });
  }

  function bindAutoSubmit() {
    var form = document.getElementById('routesToolbarForm');
    if (!form) return;

    form.querySelectorAll('.filter-auto-submit').forEach(function (el) {
      el.addEventListener('change', function () {
        form.submit();
      });
    });

    var searchInput = document.getElementById('routesSearchInput');
    if (searchInput) {
      searchInput.addEventListener('keypress', function (e) {
        if (e.key === 'Enter') {
          e.preventDefault();
          form.submit();
        }
      });
    }
  }

  function updateActiveFiltersUI() {
    var config = window.routesPageConfig || {};
    var container = document.getElementById('activeFilters');
    var label = document.getElementById('headerSummaryFiltersLabel');
    var clearAll = document.getElementById('clearAllFilters');
    var panel = document.getElementById('headerSummaryFiltersPanel');

    if (!container || !window.FilterChipUtils) return;

    var filterGroups = [];
    var activeFilterCount = 0;
    var buildRemovableChip = window.FilterChipUtils.buildRemovableChip;
    var joinWithAnd = window.FilterChipUtils.joinWithAndHtml;
    var buildOrGroup = window.FilterChipUtils.buildOrGroupHtml;

    // Status chip (only if not default all)
    if (config.matchedFilter && config.matchedFilter !== 'all') {
      var matchLabel = (config.matchFilterLabels && config.matchFilterLabels[config.matchedFilter]) || config.matchedFilter;
      filterGroups.push(buildRemovableChip({
        label: 'Status: ' + matchLabel,
        badgeClass: config.matchedFilter === 'matched' ? 'filter-chip-matched' : 'filter-chip-unmatched',
        data: { type: 'matched', value: config.matchedFilter },
        removeLabel: 'Remove route status filter'
      }));
      activeFilterCount += 1;
    }

    // ATLAS Operator chips
    if (config.selectedAtlasOperators && config.selectedAtlasOperators.length > 0) {
      var atlasOperatorChips = config.selectedAtlasOperators.map(function (op) {
        return buildRemovableChip({
          label: 'ATLAS Operator: ' + op,
          badgeClass: 'filter-chip-operator',
          data: { type: 'operator', value: op },
          removeLabel: 'Remove ATLAS operator ' + op
        });
      });
      filterGroups.push(buildOrGroup(atlasOperatorChips));
      activeFilterCount += atlasOperatorChips.length;
    }

    // OSM Operator chips
    if (config.selectedOsmOperators && config.selectedOsmOperators.length > 0) {
      var osmOperatorChips = config.selectedOsmOperators.map(function (op) {
        return buildRemovableChip({
          label: 'OSM Route Operator: ' + op,
          badgeClass: 'filter-chip-osm',
          data: { type: 'osmOperator', value: op },
          removeLabel: 'Remove OSM route operator ' + op
        });
      });
      filterGroups.push(buildOrGroup(osmOperatorChips));
      activeFilterCount += osmOperatorChips.length;
    }

    // Search chip
    if (config.q) {
      filterGroups.push(buildRemovableChip({
        label: 'Search: ' + config.q,
        badgeClass: 'filter-chip-secondary',
        data: { type: 'q', value: config.q },
        removeLabel: 'Remove route search filter'
      }));
      activeFilterCount += 1;
    }

    if (filterGroups.length > 0) {
      container.innerHTML = joinWithAnd(filterGroups);
      if (label) label.textContent = 'Filters: ' + activeFilterCount + ' active';
      if (clearAll) clearAll.classList.remove('d-none');
      if (panel) panel.classList.remove('d-none');
    } else {
      container.innerHTML = '<span class="badge filter-chip-badge filter-chip-secondary">All entries</span>';
      if (label) label.textContent = 'Filters: None (All entries)';
      if (clearAll) clearAll.classList.add('d-none');
      if (panel) panel.classList.add('d-none');
    }
  }

  function handleChipRemoval() {
    var container = document.getElementById('activeFilters');
    if (!container) return;

    container.addEventListener('click', function (e) {
      var removeBtn = e.target.closest('.remove-filter');
      if (!removeBtn) return;

      e.preventDefault();
      var type = removeBtn.dataset.type;
      var value = removeBtn.dataset.value;
      window.location.href = buildFilterRemovalUrl(window.location.href, type, value);
    });

    var clearAll = document.getElementById('clearAllFilters');
    if (clearAll) {
      clearAll.addEventListener('click', function (e) {
        e.preventDefault();
        var config = window.routesPageConfig || {};
        window.location.href = config.baseUrl || '/routes';
      });
    }
  }

  function initSummaryToggle() {
    if (!window.HeaderSummary || typeof window.HeaderSummary.bind !== 'function') return null;

    return window.HeaderSummary.bind({
      activeFilterCount: document.querySelectorAll('#activeFilters .remove-filter').length,
      filtersExpanded: false,
      collapsed: false
    });
  }

  function bindSearchHint() {
    var input = document.getElementById('routesSearchInput');
    var hint = document.getElementById('routesSearchHint');
    if (!input || !hint) {
      return;
    }

    var hideTimer = null;

    function showHint() {
      if (hideTimer) {
        clearTimeout(hideTimer);
        hideTimer = null;
      }
      hint.classList.remove('d-none');
    }

    function hideHintSoon() {
      hideTimer = setTimeout(function () {
        hint.classList.add('d-none');
      }, 120);
    }

    input.addEventListener('focus', showHint);
    input.addEventListener('blur', hideHintSoon);
    input.addEventListener('mouseenter', showHint);
    input.addEventListener('mouseleave', hideHintSoon);
  }



  function createRouteMap(mapElement) {
    var defaultCenter = (window.AppConstants && window.AppConstants.MAP && window.AppConstants.MAP.DEFAULT_CENTER) || [47.3769, 8.5417];
    var defaultZoom = (window.AppConstants && window.AppConstants.MAP && window.AppConstants.MAP.DEFAULT_ZOOM) || 11;
    var minZoom = (window.AppConstants && window.AppConstants.MAP && window.AppConstants.MAP.MIN_ZOOM) || 8;
    var maxZoom = (window.AppConstants && window.AppConstants.MAP && window.AppConstants.MAP.MAX_ZOOM) || 20;
    var maxBounds = (window.AppConstants && window.AppConstants.MAP && window.AppConstants.MAP.MAX_BOUNDS) || [[45.5, 5.5], [48.0, 11.0]];

    if (!window.MapComponents || !window.MapComponents.MapCore) {
      throw new Error('Route preview maps require MapComponents.MapCore.');
    }

    var core = window.MapComponents.MapCore.create({
      container: mapElement,
      view: { center: defaultCenter, zoom: defaultZoom },
      mapOptions: {
        minZoom: minZoom,
        maxZoom: maxZoom,
        maxBounds: maxBounds,
        maxBoundsViscosity: 1.0,
        zoomControl: true
      },
      baseLayers: function () {
        var layers = window.MapShared.createBaseTileLayers();
        return {
          OpenStreetMap: layers.osm,
          Transport: layers.transport,
          Satellite: layers.satellite
        };
      },
      layerGroups: {
        markers: true,
        lines: true
      },
      controls: {
        layers: { position: 'bottomleft' }
      }
    });

    var mapInstance = core.map;

    var mapState = {
      core: core,
      map: mapInstance,
      markersLayer: core.layers.markers,
      linesLayer: core.layers.lines,
      loaded: false,
      loading: false,
      requestSequence: 0,
      requestController: null,
      contextSequence: 0,
      contextController: null,
      source: null,
      contextStops: [],
      showContext: false,
      markerMode: null
    };

    function refreshMarkersAtZoomThreshold() {
      var nextMode = getMarkerMode(mapState.map.getZoom());
      if (mapState.markerMode === nextMode) return;
      mapState.markerMode = nextMode;
      if (mapState.source) renderMapSnapshot(mapState);
    }

    mapState.markerMode = getMarkerMode(mapInstance.getZoom());
    mapInstance.on('zoomend', refreshMarkersAtZoomThreshold);
    mapState.removeZoomListener = function () {
      mapInstance.off('zoomend', refreshMarkersAtZoomThreshold);
    };

    return mapState;
  }

  function parseRouteMapPayload(responseData) {
    if (!responseData) {
      return [];
    }
    if (Array.isArray(responseData)) {
      return responseData;
    }
    if (Array.isArray(responseData.stops)) {
      return responseData.stops;
    }
    return [];
  }

  function getMapColors() {
    var colors = (window.AppConstants && window.AppConstants.COLORS) || {};
    return {
      atlasMatched: colors.ATLAS_MATCHED || '#174092',
      osmMatched: colors.OSM_MATCHED || '#4CAF50',
      atlasUnmatched: colors.ATLAS_UNMATCHED || '#DC3545',
      osmUnmatched: colors.OSM_UNMATCHED || '#6C757D'
    };
  }

  function isMatchedLikeStopType(stopType) {
    return stopType === 'matched' || stopType === 'effectively_matched';
  }

  function getAtlasStopMarkerColor(stopType, colors) {
    return stopType === 'atlas_unmatched' ? colors.atlasUnmatched : colors.atlasMatched;
  }

  function getOsmStopMarkerColor(stopType, colors) {
    return stopType === 'osm_unmatched' ? colors.osmUnmatched : colors.osmMatched;
  }

  function getMarkerMode(zoom) {
    var threshold = (window.AppConstants && window.AppConstants.MAP &&
      window.AppConstants.MAP.LABEL_ICON_MIN_ZOOM) || 18;
    return Number(zoom) >= threshold ? 'label' : 'circle';
  }

  function addContextStops(mapState) {
    if (!mapState.showContext || !Array.isArray(mapState.contextStops)) return;

    var colors = getMapColors();
    var sourceIds = new Set();
    if (mapState.source && mapState.source.type === 'variant') {
      [mapState.source.data.atlas_uic_groups, mapState.source.data.osm_uic_groups].forEach(function (groups) {
        (groups || []).forEach(function (group) {
          (group.members || []).forEach(function (member) {
            if (member.stop_id != null) sourceIds.add(String(member.stop_id));
          });
        });
      });
    }

    mapState.contextStops.forEach(function (stop) {
      if (sourceIds.has(String(stop.sloid)) || sourceIds.has(String(stop.osm_node_id))) return;

      if (stop.atlas_lat != null && stop.atlas_lon != null) {
        var atlasMarker = window.MapRenderer.createAtlasMarker(
          stop.atlas_lat,
          stop.atlas_lon,
          getAtlasStopMarkerColor(stop.stop_type, colors),
          stop.has_atlas_duplicate,
          mapState.map.getZoom()
        );
        window.MapRenderer.setMarkerOpacity(atlasMarker, 0.4, 0.2);
        atlasMarker.addTo(mapState.markersLayer);
      }
      if (stop.osm_lat != null && stop.osm_lon != null) {
        var osmMarker = window.MapRenderer.createOsmMarker(
          stop.osm_lat,
          stop.osm_lon,
          getOsmStopMarkerColor(stop.stop_type, colors),
          stop.osm_node_type,
          mapState.map.getZoom()
        );
        window.MapRenderer.setMarkerOpacity(osmMarker, 0.4, 0.2);
        osmMarker.addTo(mapState.markersLayer);
      }
    });
  }

  function renderMapSnapshot(mapState) {
    if (!mapState.source) return [];
    var points = mapState.source.type === 'variant'
      ? renderVariantStops(mapState, mapState.source.data)
      : renderRouteStops(mapState, mapState.source.data);
    addContextStops(mapState);
    return points;
  }

  function renderRouteStops(mapState, stops) {
    mapState.markersLayer.clearLayers();
    mapState.linesLayer.clearLayers();

    var colors = getMapColors();
    var points = [];

    stops.forEach(function (stop) {
      var stopType = stop.stop_type;
      var atlasLat = stop.atlas_lat;
      var atlasLon = stop.atlas_lon;
      var osmLat = stop.osm_lat;
      var osmLon = stop.osm_lon;

      if (isMatchedLikeStopType(stopType) && atlasLat != null && atlasLon != null && osmLat != null && osmLon != null) {
        var atlasMarker = window.MapRenderer.createAtlasMarker(atlasLat, atlasLon, getAtlasStopMarkerColor(stopType, colors), stop.has_atlas_duplicate, mapState.map.getZoom());
        atlasMarker.addTo(mapState.markersLayer);

        var osmMarker = window.MapRenderer.createOsmMarker(osmLat, osmLon, getOsmStopMarkerColor(stopType, colors), stop.osm_node_type, mapState.map.getZoom());
        osmMarker.addTo(mapState.markersLayer);

        points.push([atlasLat, atlasLon]);
        points.push([osmLat, osmLon]);
        return;
      }

      if (atlasLat != null && atlasLon != null) {
        var atlasColor = getAtlasStopMarkerColor(stopType, colors);
        window.MapRenderer.createAtlasMarker(atlasLat, atlasLon, atlasColor, stop.has_atlas_duplicate, mapState.map.getZoom()).addTo(mapState.markersLayer);
        points.push([atlasLat, atlasLon]);
      }

      if (osmLat != null && osmLon != null) {
        var osmColor = getOsmStopMarkerColor(stopType, colors);
        window.MapRenderer.createOsmMarker(osmLat, osmLon, osmColor, stop.osm_node_type, mapState.map.getZoom()).addTo(mapState.markersLayer);
        points.push([osmLat, osmLon]);
      }
    });

    return points;
  }
  function renderVariantStops(mapState, direction) {
    mapState.markersLayer.clearLayers();
    mapState.linesLayer.clearLayers();

    var colors = getMapColors();
    var points = [];

    if (direction.atlas_uic_groups) {
      direction.atlas_uic_groups.forEach(function (group) {
        if (group.members) {
          group.members.forEach(function (member) {
            if (member.lat != null && member.lon != null) {
              var stopType = member.stop_type;
              var color = getAtlasStopMarkerColor(stopType, colors);
              window.MapRenderer.createAtlasMarker(member.lat, member.lon, color, member.has_atlas_duplicate, mapState.map.getZoom()).addTo(mapState.markersLayer);
              points.push([member.lat, member.lon]);
            }
          });
        }
      });
    }

    if (direction.osm_uic_groups) {
      direction.osm_uic_groups.forEach(function (group) {
        if (group.members) {
          group.members.forEach(function (member) {
            if (member.lat != null && member.lon != null) {
              var stopType = member.stop_type;
              var color = getOsmStopMarkerColor(stopType, colors);
              window.MapRenderer.createOsmMarker(member.lat, member.lon, color, member.osm_node_type, mapState.map.getZoom()).addTo(mapState.markersLayer);
              points.push([member.lat, member.lon]);
            }
          });
        }
      });
    }
    
    return points;
  }

  function loadContextMarkers(mapElement, mapState, points) {
    if (!points || points.length === 0) return;

    if (mapState.contextController) mapState.contextController.abort();
    mapState.contextController = new AbortController();
    var controller = mapState.contextController;
    var sequence = ++mapState.contextSequence;
    
    var bounds = L.latLngBounds(points);
    var pad = 0.01; // roughly 1km
    var params = {
      min_lat: bounds.getSouth() - pad,
      max_lat: bounds.getNorth() + pad,
      min_lon: bounds.getWest() - pad,
      max_lon: bounds.getEast() + pad,
      limit: 100
    };
    
    var query = buildQueryString(params);
    
    fetch('/api/data?' + query, { signal: controller.signal })
      .then(function(r) {
        if (!r.ok) throw new Error('Context request failed with status ' + r.status);
        return r.json();
      })
      .then(function(data) {
        if (sequence !== mapState.contextSequence || !mapState.showContext) return;
        mapState.contextStops = parseRouteMapPayload(data);
        renderMapSnapshot(mapState);
        setMapStatus(mapElement, '', false);
      })
      .catch(function (error) {
        if (error && error.name === 'AbortError') return;
        if (sequence !== mapState.contextSequence || !mapState.showContext) return;
        setMapStatus(mapElement, 'Could not load surrounding map context.', true);
        console.error('Failed to load route context', error);
      })
      .finally(function () {
        if (mapState.contextController === controller) mapState.contextController = null;
      });
  }

  function toggleContext(btn) {
    var mapIndex = btn.dataset.mapIndex;
    var mapElement = document.getElementById('routeMap' + mapIndex);
    if (!mapElement) return;
    
    var mapState = routeMaps.get(mapElement);
    if (!mapState) return;
    
    mapState.showContext = !mapState.showContext;
    
    if (mapState.showContext) {
      btn.innerHTML = '<i class="fas fa-eye-slash"></i> Hide other markers';
      btn.classList.add('btn-secondary');
      btn.classList.remove('btn-outline-secondary');
      
      // We need the points to know where to look
      var scriptElement = document.querySelector('script.variant-data[data-map-index="' + mapIndex + '"]');
      if (scriptElement) {
        var directionData = JSON.parse(scriptElement.textContent);
        var points = [];
        [directionData.atlas_uic_groups, directionData.osm_uic_groups].forEach(function(groups) {
          if (groups) groups.forEach(function(g) {
            if (g.members) g.members.forEach(function(m) {
              if (m.lat != null && m.lon != null) points.push([m.lat, m.lon]);
            });
          });
        });
        loadContextMarkers(mapElement, mapState, points);
      }
    } else {
      mapState.contextSequence += 1;
      if (mapState.contextController) {
        mapState.contextController.abort();
        mapState.contextController = null;
      }
      mapState.contextStops = [];
      setMapStatus(mapElement, '', false);
      btn.innerHTML = '<i class="fas fa-eye"></i> See other markers';
      btn.classList.remove('btn-secondary');
      btn.classList.add('btn-outline-secondary');
      
      renderMapSnapshot(mapState);
    }
  }
  function getGlobalBboxParams() {
    var bounds = (window.AppConstants && window.AppConstants.MAP && window.AppConstants.MAP.MAX_BOUNDS) || [[45.5, 5.5], [48.0, 11.0]];
    return {
      min_lat: bounds[0][0],
      min_lon: bounds[0][1],
      max_lat: bounds[1][0],
      max_lon: bounds[1][1]
    };
  }

  function buildRouteRequestParams(mapElement) {
    var params = getGlobalBboxParams();

    params.station_filter = mapElement.dataset.stationFilter || '';
    params.filter_types = mapElement.dataset.filterTypes || '';
    params.route_directions = mapElement.dataset.routeDirections || '';
    params.limit = 'all';
    params.include_meta = 'true';

    var atlasOperators = mapElement.dataset.atlasOperators || '';
    if (atlasOperators) {
      params.atlas_operator = atlasOperators;
    }

    return params;
  }

  function buildQueryString(params) {
    var query = new URLSearchParams();
    Object.keys(params).forEach(function (key) {
      if (params[key] == null || params[key] === '') {
        return;
      }
      query.set(key, String(params[key]));
    });
    return query.toString();
  }

  function setMapStatus(mapElement, text, isError) {
    var shell = mapElement.closest('.route-card__map-shell');
    if (!shell) {
      return;
    }

    var status = shell.querySelector('.route-card__map-status');
    if (!status) {
      status = document.createElement('div');
      status.className = 'route-card__map-status';
      shell.insertBefore(status, mapElement);
    }

    status.textContent = text;
    status.classList.toggle('route-card__map-status--error', !!isError);
    status.classList.toggle('d-none', !text);
  }

  function loadRouteMapData(mapElement, mapState) {
    if (mapState.requestController) mapState.requestController.abort();
    mapState.requestController = null;
    var sequence = ++mapState.requestSequence;
    mapState.loading = true;
    setMapStatus(mapElement, 'Loading route points on map...', false);

    var mapIndex = mapElement.dataset.mapIndex;
    var scriptElement = document.querySelector('script.variant-data[data-map-index="' + mapIndex + '"]');
    
    if (scriptElement) {
        try {
            var directionData = JSON.parse(scriptElement.textContent);
            mapState.source = { type: 'variant', data: directionData };
            var points = renderMapSnapshot(mapState);
            
            if (!points || points.length === 0) {
              setMapStatus(mapElement, 'No geolocated route points were returned for this variant.', false);
            } else {
              setMapStatus(mapElement, '', false);
              var bounds = L.latLngBounds(points);
              mapState.map.fitBounds(bounds.pad(0.2));
            }
            mapState.loaded = true;
        } catch (e) {
            setMapStatus(mapElement, 'Could not load route map data.', true);
            console.error('Failed to parse inline variant data', e);
        } finally {
            mapState.loading = false;
        }
        return;
    }

    var params = buildRouteRequestParams(mapElement);
    var query = buildQueryString(params);
    var controller = new AbortController();
    mapState.requestController = controller;

    fetch('/api/data?' + query, { signal: controller.signal })
      .then(function (response) {
        if (!response.ok) {
          throw new Error('Map request failed with status ' + response.status);
        }
        return response.json();
      })
      .then(function (data) {
        if (sequence !== mapState.requestSequence) return;
        var stops = parseRouteMapPayload(data);
        mapState.source = { type: 'routes', data: stops };
        var points = renderMapSnapshot(mapState);

        if (!points || points.length === 0) {
          setMapStatus(mapElement, 'No geolocated route points were returned for this filter.', false);
          mapState.loaded = true;
          return;
        }

        setMapStatus(mapElement, '', false);
        var bounds = L.latLngBounds(points);
        mapState.map.fitBounds(bounds.pad(0.2));
        mapState.loaded = true;
      })
      .catch(function (error) {
        if (error && error.name === 'AbortError') return;
        if (sequence !== mapState.requestSequence) return;
        setMapStatus(mapElement, 'Could not load route map data.', true);
        console.error('Failed to load route map data', error);
      })
      .finally(function () {
        if (sequence === mapState.requestSequence) {
          mapState.loading = false;
          if (mapState.requestController === controller) mapState.requestController = null;
        }
      });
  }

  function ensureMapLoadedForPanel(panel) {
    var mapElement = panel.querySelector('.route-card__map');
    if (!mapElement) {
      return;
    }

    var mapState = routeMaps.get(mapElement);
    if (!mapState) {
      mapState = createRouteMap(mapElement);
      routeMaps.set(mapElement, mapState);
    }

    var filterContainer = panel.querySelector('.map-direction-filter-container');
    if (filterContainer && window.FilterChipUtils && filterContainer.children.length === 0) {
      var currentDir = mapElement.dataset.routeDirections || '';
      var mapIndex = mapElement.dataset.mapIndex || '';
      var routeId = mapElement.dataset.routeId || '';
      var chipHtml = window.FilterChipUtils.buildDirectionDropdownHtml({
        direction: currentDir,
        mapIndex: mapIndex,
        routeLabel: routeId ? 'Route: ' + routeId : '',
        showClose: false
      });
      filterContainer.innerHTML = chipHtml;
    }

    mapState.map.invalidateSize();

    if (!mapState.loaded) {
      loadRouteMapData(mapElement, mapState);
      return;
    }

    setTimeout(function () {
      mapState.map.invalidateSize();
    }, 120);
  }

  function initRouteMapPanels() {
    var panels = document.querySelectorAll('.route-card__panel--map');
    panels.forEach(function (panel) {
      panel.addEventListener('toggle', function () {
        if (panel.open) {
          ensureMapLoadedForPanel(panel);
        }
      });
    });

    // Attach toggle context handlers
    document.addEventListener('click', function(e) {
      var btn = e.target.closest('.toggle-context-btn');
      if (btn) {
        toggleContext(btn);
      }
    });
  }

  function destroyRouteMaps() {
    routeMaps.forEach(function (mapState) {
      mapState.requestSequence += 1;
      mapState.contextSequence += 1;
      if (mapState.requestController) mapState.requestController.abort();
      if (mapState.contextController) mapState.contextController.abort();
      if (mapState.removeZoomListener) mapState.removeZoomListener();
      if (mapState.core) mapState.core.destroy();
    });
    routeMaps.clear();
    if (headerSummaryController) {
      headerSummaryController.destroy();
      headerSummaryController = null;
    }
  }

  function init() {
    var configElement = document.getElementById('routesPageConfig');
    if (configElement) {
      try {
        window.routesPageConfig = JSON.parse(configElement.textContent);
      } catch (e) {
        console.error('Failed to parse routesPageConfig', e);
      }
    }

    bindSearchHint();
    initOperatorDropdown();
    initOsmOperatorDropdown();
    initStatusFilter();
    bindAutoSubmit();
    updateActiveFiltersUI();
    handleChipRemoval();
    headerSummaryController = initSummaryToggle();
    initRouteMapPanels();
    window.addEventListener('pagehide', function (event) {
      if (!event.persisted) destroyRouteMaps();
    }, { once: true });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  window.RoutesPageFilters = {
    buildFilterRemovalUrl: buildFilterRemovalUrl,
    getMultiValueParams: getMultiValueParams,
    updateActiveFiltersUI: updateActiveFiltersUI
  };
})();
