(function () {
  'use strict';

  var operatorDropdown = null;
  var osmOperatorDropdown = null;
  var headerSummaryController = null;
  var routeMaps = new Map();
  var removeRouteMapListeners = [];
  // One controller for every route map: a stop loaded on one map opens at
  // once on another (static/js/components/map-popup-controller.js).
  var stopPopupController = null;
  // Pixel padding keeps a variant large in a narrow map; pad() scales with the route.
  var FIT_OPTIONS = { padding: [28, 28], maxZoom: 17 };

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
          label: SharedUtils.sourceLabel() + ' Operator: ' + op,
          badgeClass: 'filter-chip-operator',
          data: { type: 'operator', value: op },
          removeLabel: 'Remove ' + SharedUtils.sourceLabel() + ' operator ' + op
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

  // A matched route compares both sides, so its two detail cards open and close together.
  function bindPairedRouteMeta() {
    document.addEventListener('toggle', function (event) {
      var meta = event.target;
      if (!meta || !meta.classList || !meta.classList.contains('route-meta')) return;
      var header = meta.closest('.route-card__header--matched');
      if (!header) return;
      header.querySelectorAll('.route-meta').forEach(function (other) {
        if (other !== meta && other.open !== meta.open) other.open = meta.open;
      });
    }, true);
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


  // The page scrolls past a preview map; the wheel zooms it only after a click
  // on the map, until the pointer leaves. A hint explains this on wheel.
  function guardWheelZoom(map, mapElement) {
    var shell = mapElement.closest('.route-card__map-shell');
    var hintTimer = null;
    if (!map.scrollWheelZoom) return function () {};
    function enable() {
      map.scrollWheelZoom.enable();
      if (shell) shell.classList.remove('is-wheel-hint');
    }
    function disable() {
      map.scrollWheelZoom.disable();
    }
    function hint() {
      if (map.scrollWheelZoom.enabled() || !shell) return;
      shell.classList.add('is-wheel-hint');
      clearTimeout(hintTimer);
      hintTimer = setTimeout(function () { shell.classList.remove('is-wheel-hint'); }, 1500);
    }
    mapElement.addEventListener('click', enable);
    mapElement.addEventListener('mouseleave', disable);
    mapElement.addEventListener('wheel', hint, { passive: true });
    return function () {
      clearTimeout(hintTimer);
      mapElement.removeEventListener('click', enable);
      mapElement.removeEventListener('mouseleave', disable);
      mapElement.removeEventListener('wheel', hint);
    };
  }

  function mainMapUrl() {
    return (window.routesPageConfig && window.routesPageConfig.mainMapUrl) || '/';
  }

  // The card's "Main map" link opens the main map on the variants this map
  // shows, with the routes page's keys (?atlas_variant= / ?osm_variant=): a
  // route filter narrowed to them, at this map's view. A comparison sets
  // mapState.mainMapVariants; otherwise the panel's own variants are used.
  function followMainMapLink(mapState, mapElement) {
    var shell = mapElement.closest('.route-card__map-shell');
    var link = shell && shell.querySelector('.variant-map__main-map');
    var panel = mapElement.closest('.route-card__panel--map');
    if (!link) return function () {};
    function update() {
      var variants = mapState.mainMapVariants || {
        atlas_variant: (panel && panel.dataset.atlasVariant) || null,
        osm_variant: (panel && panel.dataset.osmVariant) || null
      };
      var query = Permalinks.encodeParams(variants);
      var hash = '';
      try { hash = Permalinks.currentMapHash(mapState.map); } catch (error) { hash = ''; }  // no view yet
      link.href = mainMapUrl() + (query ? '?' + query : '') + hash;
    }
    mapState.updateMainMapLink = update;
    mapState.map.on('moveend', update);
    update();
    return function () { mapState.map.off('moveend', update); };
  }

  // The main map's link to one stop, with its popup open (?sloid= / ?osm=).
  function mainMapStopUrl(type, ref) {
    var params = Permalinks.stopParams(type, ref);
    return params ? mainMapUrl() + '?' + Permalinks.encodeParams(params) : null;
  }

  // Route stops name their source stop; /api/data rows name their stop row.
  function stopPopupQuery(entity) {
    var ref = entity.popupRef || {};
    var params = ref.id != null ? { stop_id: ref.id }
      : ref.sloid ? { sloid: ref.sloid }
        : ref.osm_node_id ? { osm_node_id: ref.osm_node_id } : null;
    if (!params) return null;
    params.view_type = entity.entityType;
    return buildQueryString(params);
  }

  function renderStopPopup(payload, entityType) {
    var stop = payload && (payload.stop || payload);
    if (!stop) throw new Error('The popup endpoint returned no stop data.');
    var options = { mainMapUrl: mainMapStopUrl };
    if (stop.stop_type === 'atlas_unmatched') {
      return entityType === 'atlas'
        ? PopupRenderer.generateSingleAtlasBubbleHtml(stop, true, options)
        : PopupRenderer.generateSingleOsmBubbleHtml(stop, true, options);
    }
    return PopupRenderer.generatePopupHtml(stop, entityType, options);
  }

  function getStopPopupController() {
    if (!stopPopupController) {
      stopPopupController = window.MapComponents.MapPopupController.create({
        cache: 'payload',
        // Redraws replace markers; keep loaded stops for the replacements.
        retainCacheOnDetach: true,
        errorContent: '<div class="popup-error">Unable to load stop details. Click the marker to retry.</div>',
        onError: function (error) { console.error('Failed to load stop popup:', error); }
      });
    }
    return stopPopupController;
  }

  // The map is a card beside the stop list: one popup at a time, panned clear
  // of the zoom control and the card's buttons, and no taller than the map.
  var POPUP_PAN_TOP_LEFT = [56, 48];
  var POPUP_PAN_BOTTOM_RIGHT = [12, 12];
  function createStopPopupBinder(mapState) {
    return function (marker, entity) {
      var query = stopPopupQuery(entity);
      if (!query) return;
      mapState.popupMarkers.push({ marker: marker, key: entity.key });
      getStopPopupController().attach(marker, {
        key: entity.key,
        load: function (context) {
          return fetch('/api/stop_popup?' + query, { signal: context.signal }).then(function (response) {
            if (!response.ok) throw new Error('Stop details request failed with status ' + response.status);
            return response.json();
          });
        },
        render: function (payload) { return renderStopPopup(payload, entity.entityType); },
        createPopup: function (content) {
          return window.MapRenderer.createPopupWithOptions(content, {
            autoClose: true, closeOnClick: true, autoPan: true,
            autoPanPaddingTopLeft: POPUP_PAN_TOP_LEFT, autoPanPaddingBottomRight: POPUP_PAN_BOTTOM_RIGHT,
            singleBubbleMapShare: 0.9,
            maxHeight: Math.max(160, mapState.map.getSize().y - POPUP_PAN_TOP_LEFT[1] - POPUP_PAN_BOTTOM_RIGHT[1] - 32)
          });
        }
      });
    };
  }

  // Detaches the stop popups before a redraw and returns the open one's key.
  function detachStopPopups(mapState) {
    var openKey = null;
    mapState.popupMarkers.forEach(function (entry) {
      if (typeof entry.marker.isPopupOpen === 'function' && entry.marker.isPopupOpen()) openKey = entry.key;
      if (stopPopupController) stopPopupController.detach(entry.marker);
    });
    mapState.popupMarkers = [];
    return openKey;
  }

  function reopenStopPopup(mapState, key) {
    if (key == null || !stopPopupController) return;
    var entry = mapState.popupMarkers.find(function (candidate) { return candidate.key === key; });
    if (entry) stopPopupController.open(entry.marker);
  }

  function createRouteMap(mapElement) {
    var defaultCenter = AppConstants.MAP.DEFAULT_CENTER;
    var defaultZoom = AppConstants.MAP.DEFAULT_ZOOM;
    var minZoom = AppConstants.MAP.MIN_ZOOM;
    var maxZoom = AppConstants.MAP.MAX_ZOOM;
    var maxBounds = AppConstants.MAP.MAX_BOUNDS;

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
        zoomControl: true,
        scrollWheelZoom: false
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
        lines: true,
        highlight: true
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
      highlightLayer: core.layers.highlight || null,
      loaded: false,
      loading: false,
      requestSequence: 0,
      requestController: null,
      contextSequence: 0,
      contextController: null,
      source: null,
      contextStops: [],
      showContext: false,
      markerMode: null,
      popupMarkers: []  // [{ marker, key }] bound to stop popups
    };

    function refreshMarkersAtZoomThreshold() {
      var nextMode = getMarkerMode(mapState.map.getZoom());
      if (mapState.markerMode === nextMode) return;
      mapState.markerMode = nextMode;
      if (mapState.source) renderMapSnapshot(mapState);
    }

    mapState.markerMode = getMarkerMode(mapInstance.getZoom());
    mapState.bindPopup = createStopPopupBinder(mapState);
    mapInstance.on('zoomend', refreshMarkersAtZoomThreshold);
    var removeMainMapLink = followMainMapLink(mapState, mapElement);
    var removeWheelGuard = guardWheelZoom(mapInstance, mapElement);
    // The map card follows the height of the stop list, e.g. when a fold opens.
    var resizeObserver = typeof ResizeObserver === 'function'
      ? new ResizeObserver(function () { mapInstance.invalidateSize(); }) : null;
    if (resizeObserver) resizeObserver.observe(mapElement);
    mapState.removeZoomListener = function () {
      mapInstance.off('zoomend', refreshMarkersAtZoomThreshold);
      removeMainMapLink();
      removeWheelGuard();
      if (resizeObserver) resizeObserver.disconnect();
    };

    return mapState;
  }

  /** Ring the stops of a hovered comparison row; a click also zooms to them. */
  function highlightStops(mapState, points, reveal) {
    if (!mapState.highlightLayer) return;
    mapState.highlightLayer.clearLayers();
    (points || []).forEach(function (point) {
      mapState.highlightLayer.addLayer(L.circleMarker(point, {
        radius: 14, weight: 3, color: (AppConstants.COLORS || {}).GTFS_MATCHED || '#F0AD4E',
        fill: false, interactive: false
      }));
    });
    if (reveal && points && points.length) {
      var center = L.latLngBounds(points).getCenter();
      mapState.map.setView(center, Math.max(mapState.map.getZoom(), 16));
    }
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

  function getMarkerMode(zoom) {
    var threshold = (window.AppConstants && window.AppConstants.MAP &&
      window.AppConstants.MAP.LABEL_ICON_MIN_ZOOM) || 18;
    return Number(zoom) >= threshold ? 'label' : 'circle';
  }

  function addContextStops(mapState) {
    if (!mapState.showContext || !Array.isArray(mapState.contextStops)) return;

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

    // Partners drawn faded by drawComparisonMarks are not drawn again.
    var comparison = mapState.source && mapState.source.type === 'variant' && mapState.source.data.stop_comparison;
    ((comparison && comparison.rows) || []).forEach(function (row) {
      [row.atlas, row.osm].forEach(function (stop) {
        ((stop && stop.partners) || []).forEach(function (partner) { sourceIds.add(String(partner.stop_id)); });
      });
    });

    var stops = mapState.contextStops.filter(function (stop) {
      return !sourceIds.has(String(stop.sloid)) && !sourceIds.has(String(stop.osm_node_id));
    });
    var snapshot = window.MapEntityAdapters.stops(stops, { emphasis: 'subdued' });
    window.MapRenderer.renderEntities(snapshot.entities, mapState.markersLayer, {
      map: mapState.map, zoom: mapState.map.getZoom(), overlap: false, bindPopup: mapState.bindPopup
    });
  }

  function comparisonStopKey(source, stop) {
    return source + ':' + ((stop.stop_ids || [])[0] || stop.id);
  }

  /**
   * The stop list, drawn on the map. Marker colours stay those of stop
   * matching, as on the main map; the comparison adds marks of its own: a solid
   * line joins the same stop in both variants, a dashed line the same station
   * at another platform, and a dashed ring circles a stop the other variant
   * does not have. A thin line joins each stop to its own stop matches; a
   * match that neither variant calls at is returned, to be drawn faded. All
   * marks are drawn over the stops and not clickable, so a click reaches the
   * stop's popup.
   */
  function drawComparisonMarks(mapState, comparison) {
    var rows = (comparison && comparison.rows) || [];
    var colors = AppConstants.COLORS || {};
    var positionOf = function (stop) { return stop && window.MapShared.finitePosition(stop.lat, stop.lon); };
    // A variant listed on its own has nothing to compare with.
    var compared = rows.some(function (row) { return row.atlas; }) && rows.some(function (row) { return row.osm; });
    var shared = new Set();
    rows.forEach(function (row) {
      if (row.match_type) shared.add(comparisonStopKey('atlas', row.atlas)).add(comparisonStopKey('osm', row.osm));
    });
    var drawn = new Set();
    function draw(key, layer) {
      if (drawn.has(key)) return;
      drawn.add(key);
      mapState.linesLayer.addLayer(layer);
    }
    rows.forEach(function (row) {
      var atlas = positionOf(row.atlas);
      var osm = positionOf(row.osm);
      if ((row.match_type || row.same_station) && atlas && osm) {
        draw('line:' + atlas.join(',') + ':' + osm.join(','), L.polyline([atlas, osm], row.match_type
          ? { color: colors.LINE_ATLAS_OSM || '#174092', weight: 2, opacity: 0.8, interactive: false }
          : { color: colors.NOT_SHARED || '#D97706', weight: 2, opacity: 0.9, dashArray: '4,4', interactive: false }));
      }
      if (!compared || row.match_type) return;
      [['atlas', atlas], ['osm', osm]].forEach(function (side) {
        var stop = row[side[0]];
        if (!side[1] || shared.has(comparisonStopKey(side[0], stop))) return;
        draw('ring:' + comparisonStopKey(side[0], stop), L.circleMarker(side[1], {
          radius: 10, weight: 2, color: colors.NOT_SHARED || '#D97706', dashArray: '3,3',
          fill: false, interactive: false
        }));
      });
    });

    var onMap = new Set();
    rows.forEach(function (row) {
      ['atlas', 'osm'].forEach(function (source) {
        if (row[source] && row[source].source_id) onMap.add(source + ':' + row[source].source_id);
      });
    });
    var faded = new Map();
    rows.forEach(function (row) {
      ['atlas', 'osm'].forEach(function (source) {
        var stop = row[source];
        var from = positionOf(stop);
        var other = source === 'atlas' ? 'osm' : 'atlas';
        (from ? stop.partners || [] : []).forEach(function (partner) {
          var to = positionOf(partner);
          // The same stop in both variants: its solid line already joins them.
          if (!to || (row.match_type && row[other] && row[other].source_id === partner.stop_id)) return;
          var partnerKey = other + ':' + partner.stop_id;
          draw('match:' + [source + ':' + stop.source_id, partnerKey].sort().join('|'), L.polyline([from, to], {
            color: colors.LINE_ATLAS_OSM || '#174092', weight: 1.5, opacity: 0.5, interactive: false
          }));
          if (onMap.has(partnerKey) || faded.has(partnerKey)) return;
          faded.set(partnerKey, window.MapEntityAdapters.stopEntity(other, {}, {
            identifier: partner.stop_id, position: to, status: 'matched', emphasis: 'subdued',
            popupRef: other === 'atlas' ? { sloid: partner.stop_id } : { osm_node_id: partner.stop_id }
          }));
        });
      });
    });
    return Array.from(faded.values()).filter(Boolean);
  }

  function renderMapSnapshot(mapState) {
    if (!mapState.source) return [];
    var snapshot = mapState.source.type === 'variant'
      ? window.MapEntityAdapters.routeDirection(mapState.source.data)
      : window.MapEntityAdapters.stops(mapState.source.data);
    var openPopupKey = detachStopPopups(mapState);
    mapState.markersLayer.clearLayers();
    mapState.linesLayer.clearLayers();
    window.MapRenderer.renderEntities(snapshot.entities, mapState.markersLayer, {
      map: mapState.map, zoom: mapState.map.getZoom(), overlap: false, bindPopup: mapState.bindPopup
    });
    var partners = drawComparisonMarks(mapState, mapState.source.type === 'variant' && mapState.source.data.stop_comparison);
    window.MapRenderer.renderEntities(partners, mapState.markersLayer, {
      map: mapState.map, zoom: mapState.map.getZoom(), overlap: false, bindPopup: mapState.bindPopup
    });
    addContextStops(mapState);
    reopenStopPopup(mapState, openPopupKey);
    return snapshot.entities.map(entity => entity.sourcePosition);
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
      limit: 'all'
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
      btn.innerHTML = '<i class="fas fa-eye-slash" aria-hidden="true"></i> Hide other markers';
      btn.setAttribute('aria-pressed', 'true');

      if (mapState.source && mapState.source.type === 'variant') {
        var directionData = mapState.source.data;
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
      btn.innerHTML = '<i class="fas fa-eye" aria-hidden="true"></i> See other markers';
      btn.setAttribute('aria-pressed', 'false');
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
              mapState.map.fitBounds(bounds, FIT_OPTIONS);
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
        mapState.map.fitBounds(bounds, FIT_OPTIONS);
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

    if (mapState.comparisonBounds) {
      mapState.map.fitBounds(mapState.comparisonBounds, FIT_OPTIONS);
      mapState.comparisonBounds = null;
    }

    if (!mapState.loaded) {
      loadRouteMapData(mapElement, mapState);
      return;
    }

    clearTimeout(mapState.resizeTimer);
    mapState.resizeTimer = setTimeout(function () {
      mapState.map.invalidateSize();
    }, 120);
  }

  function initRouteMapPanels() {
    var panels = document.querySelectorAll('.route-card__panel--map');
    panels.forEach(function (panel) {
      function onToggle() {
        if (panel.open) {
          ensureMapLoadedForPanel(panel);
        }
      }
      panel.addEventListener('toggle', onToggle);
      removeRouteMapListeners.push(function () {
        panel.removeEventListener('toggle', onToggle);
      });
    });

    // Attach toggle context handlers
    function onContextClick(e) {
      var btn = e.target.closest('.toggle-context-btn');
      if (btn) {
        toggleContext(btn);
      }
    }
    document.addEventListener('click', onContextClick);
    removeRouteMapListeners.push(function () {
      document.removeEventListener('click', onContextClick);
    });

    function onComparisonChange(event) {
      var panel = event.target.closest('.route-card__panel--map');
      if (!panel) return;
      var mapElement = panel.querySelector('.route-card__map');
      if (!mapElement) return;
      var mapState = routeMaps.get(mapElement);
      if (!mapState) return;
      mapState.contextSequence += 1;
      if (mapState.contextController) mapState.contextController.abort();
      mapState.contextStops = [];
      var comparison = event.detail;
      mapState.mainMapVariants = comparison ? {
        atlas_variant: (comparison.atlas && comparison.atlas.source_itinerary_id) || null,
        osm_variant: (comparison.osm && comparison.osm.source_itinerary_id) || null
      } : null;
      if (mapState.updateMainMapLink) mapState.updateMainMapLink();
      if (!comparison) {
        mapState.comparisonBounds = null;
        loadRouteMapData(mapElement, mapState);
        return;
      }
      var directionData = { stop_comparison: comparison };
      ['atlas', 'osm'].forEach(function (source) {
        directionData[source + '_uic_groups'] = [{ members: comparison.rows.filter(function (row) {
          return row[source];
        }).map(function (row) {
          var stop = row[source];
          return {
            stop_id: (stop.stop_ids || [])[0] || String(stop.id),
            lat: stop.lat, lon: stop.lon,
            // Stop matching, as on the main map; the comparison draws its own marks.
            stop_type: stop.stop_type || source + '_unmatched'
          };
        }) }];
      });
      mapState.source = { type: 'variant', data: directionData };
      var points = renderMapSnapshot(mapState);
      setMapStatus(mapElement, points.length ? '' : 'No geolocated stops in this comparison.', false);
      if (points.length) {
        var bounds = L.latLngBounds(points);
        if (panel.open) mapState.map.fitBounds(bounds, FIT_OPTIONS);
        else mapState.comparisonBounds = bounds;
        if (mapState.showContext) loadContextMarkers(mapElement, mapState, points);
      }
    }
    document.addEventListener('routecomparisonchange', onComparisonChange);
    removeRouteMapListeners.push(function () {
      document.removeEventListener('routecomparisonchange', onComparisonChange);
    });

    function panelMapState(event) {
      var panel = event.target.closest('.route-card__panel--map');
      var mapElement = panel && panel.querySelector('.route-card__map');
      return mapElement ? routeMaps.get(mapElement) : null;
    }
    function onComparisonHover(event) {
      var mapState = panelMapState(event);
      if (mapState) highlightStops(mapState, event.detail, false);
    }
    function onComparisonFocus(event) {
      var mapState = panelMapState(event);
      if (mapState) highlightStops(mapState, event.detail, true);
    }
    document.addEventListener('routecomparisonhover', onComparisonHover);
    document.addEventListener('routecomparisonfocus', onComparisonFocus);
    removeRouteMapListeners.push(function () {
      document.removeEventListener('routecomparisonhover', onComparisonHover);
      document.removeEventListener('routecomparisonfocus', onComparisonFocus);
    });
  }

  // Permalinks (static/js/shared/permalinks.js): the open variant is kept in
  // ?atlas_variant= (ATLAS itinerary id) and ?osm_variant= (OSM relation id).
  // The server renders the page that holds a linked variant; this opens it.
  var VARIANT_KEYS = ['atlas_variant', 'osm_variant'];

  // Encoded as the server's canonical URLs (safe=','), so a reload does not
  // redirect.
  function variantQuery(panel) {
    return Permalinks.encodeParams({
      atlas_variant: panel.dataset.atlasVariant || null,
      osm_variant: panel.dataset.osmVariant || null
    }, ',');
  }

  function findLinkedVariant(panels) {
    var params = new URLSearchParams(window.location.search);
    var atlasVariant = params.get('atlas_variant');
    var osmVariant = params.get('osm_variant');
    if (!atlasVariant && !osmVariant) return { requested: false, panel: null };
    var panel = panels.find(function (candidate) {
      return (!atlasVariant || candidate.dataset.atlasVariant === atlasVariant) &&
        (!osmVariant || candidate.dataset.osmVariant === osmVariant);
    });
    return { requested: true, panel: panel || null };
  }

  function initVariantPermalinks() {
    var panels = Array.prototype.slice.call(document.querySelectorAll('details.route-card__panel--map'))
      .filter(function (panel) { return panel.dataset.atlasVariant || panel.dataset.osmVariant; });
    var tracker = Permalinks.createSelectionTracker(VARIANT_KEYS);

    panels.forEach(function (panel) {
      var button = panel.querySelector('.route-copy-link');
      function onToggle() {
        if (panel.open) tracker.open(panel, variantQuery(panel));
        else tracker.close(panel);
      }
      function onCopy() {
        var search = Permalinks.buildSearch(window.location.search, VARIANT_KEYS, variantQuery(panel));
        Permalinks.copyLink(button, Permalinks.pageUrl(search, ''));
      }
      panel.addEventListener('toggle', onToggle);
      if (button) button.addEventListener('click', onCopy);
      removeRouteMapListeners.push(function () {
        panel.removeEventListener('toggle', onToggle);
        if (button) button.removeEventListener('click', onCopy);
      });
    });
    removeRouteMapListeners.push(function () {
      tracker.clear();
      Permalinks.cancelCopyFeedback();
    });

    var linked = findLinkedVariant(panels);
    if (linked.panel) {
      linked.panel.open = true;
      if (linked.panel.scrollIntoView) linked.panel.scrollIntoView({ block: 'start' });
    } else if (linked.requested) {
      Permalinks.replaceUrl({ search: Permalinks.buildSearch(window.location.search, VARIANT_KEYS, '') });
      SharedUtils.showTemporaryMessage(
        'The linked route variant is not in this list: it does not match these filters, or a newer import changed it.',
        'warning',
        6000
      );
    }
  }

  function destroyRouteMaps() {
    removeRouteMapListeners.forEach(function (remove) { remove(); });
    removeRouteMapListeners = [];
    if (stopPopupController) stopPopupController.destroy();
    stopPopupController = null;
    routeMaps.forEach(function (mapState) {
      clearTimeout(mapState.resizeTimer);
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
    bindPairedRouteMeta();
    initOperatorDropdown();
    initOsmOperatorDropdown();
    initStatusFilter();
    bindAutoSubmit();
    updateActiveFiltersUI();
    handleChipRemoval();
    headerSummaryController = initSummaryToggle();
    initRouteMapPanels();
    initVariantPermalinks();
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
