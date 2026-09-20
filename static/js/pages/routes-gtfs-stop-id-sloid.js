(function (global) {
  'use strict';

  var RESERVED_FILTER_KEYS = new Set([
    'min_lat',
    'min_lon',
    'max_lat',
    'max_lon',
    'zoom',
    'limit',
    'include_matches',
    'search_kind',
    'search_value'
  ]);
  var SEARCH_KIND_LABELS = Object.freeze({
    sloid: 'SLOID',
    uic: 'UIC',
    gtfs_stop_id: 'GTFS stop_id'
  });
  var FILTER_STATUS_LABELS = Object.freeze({
    matched: 'Matched',
    gtfs_unmatched: 'GTFS unmatched',
    atlas_unmatched: 'ATLAS unmatched'
  });

  function parseConfig() {
    var element = document.getElementById('routesGtfsStopIdSloidConfig');
    if (!element) return {};

    try {
      return JSON.parse(element.textContent);
    } catch (error) {
      throw new Error('Invalid routesGtfsStopIdSloidConfig: ' + error.message);
    }
  }

  function requireFunction(value, name) {
    if (typeof value !== 'function') {
      throw new Error('The GTFS stop_id/SLOID map requires ' + name + '.');
    }
    return value;
  }

  function normalizeFilterState(input) {
    var normalized = {};

    Object.keys(input || {}).sort().forEach(function (key) {
      if (RESERVED_FILTER_KEYS.has(key)) return;

      var value = input[key];
      if (Array.isArray(value)) {
        var values = Array.from(new Set(value
          .filter(function (item) { return item != null; })
          .map(function (item) { return String(item).trim(); })
          .filter(function (item) { return item !== ''; })))
          .sort();
        if (values.length > 0) normalized[key] = values;
        return;
      }

      if (value != null && String(value).trim() !== '') {
        normalized[key] = String(value).trim();
      }
    });

    return normalized;
  }

  function cloneFilterState(state) {
    var clone = {};
    Object.keys(state).forEach(function (key) {
      clone[key] = Array.isArray(state[key]) ? state[key].slice() : state[key];
    });
    return clone;
  }

  function appendFilterParams(params, state) {
    Object.keys(state).forEach(function (key) {
      var value = state[key];
      if (Array.isArray(value)) {
        value.forEach(function (item) { params.append(key, item); });
      } else {
        params.append(key, value);
      }
    });
    return params;
  }

  function serializeFilterState(state) {
    return appendFilterParams(new URLSearchParams(), state).toString();
  }

  function countActiveFilters(state) {
    return Object.keys(state).reduce(function (count, key) {
      return count + (Array.isArray(state[key]) ? state[key].length : 1);
    }, 0);
  }

  function createFilterAdapter(initialState) {
    var state = normalizeFilterState(initialState);
    var cacheKey = serializeFilterState(state);

    return {
      replace: function (nextState) {
        var normalized = normalizeFilterState(nextState);
        var nextCacheKey = serializeFilterState(normalized);
        if (nextCacheKey === cacheKey) return false;
        state = normalized;
        cacheKey = nextCacheKey;
        return true;
      },
      appendRequestParams: function (params) {
        return appendFilterParams(params, state);
      },
      getCacheKey: function () {
        return cacheKey;
      },
      getActiveCount: function () {
        return countActiveFilters(state);
      },
      getState: function () {
        return cloneFilterState(state);
      }
    };
  }

  function parseIdentifierSearch(rawValue) {
    var value = String(rawValue || '').trim();
    if (!value) return { error: 'Enter a SLOID, UIC, or GTFS stop_id.' };
    if (value.length > 255) return { error: 'The identifier is too long.' };

    var explicitStopId = value.match(/^stop_id\s*:(.*)$/i);
    if (explicitStopId) {
      value = explicitStopId[1].trim();
      return value
        ? { kind: 'gtfs_stop_id', value: value }
        : { error: 'Enter a GTFS stop_id after “stop_id:”.' };
    }

    var explicitUic = value.match(/^uic\s*:(.*)$/i);
    if (explicitUic) {
      value = explicitUic[1].trim();
      return /^\d+$/.test(value)
        ? { kind: 'uic', value: value }
        : { error: 'A UIC must contain digits only.' };
    }

    var explicitSloid = value.match(/^sloid\s*:(.*)$/i);
    if (explicitSloid) value = explicitSloid[1].trim();
    if (/^ch:\d+:sloid:[^\s]+$/i.test(value)) {
      return { kind: 'sloid', value: value };
    }
    if (explicitSloid || /^ch:/i.test(value)) {
      return { error: 'Enter a complete SLOID, for example ch:1:sloid:123.' };
    }

    if (/^85\d{5}$/.test(value)) {
      return { kind: 'uic', value: value };
    }

    return { kind: 'gtfs_stop_id', value: value };
  }

  function createIdentifierSearchAdapter() {
    var state = null;

    return {
      replace: function (next) {
        var normalized = next ? {
          kind: String(next.kind),
          value: String(next.value),
          targets: Array.isArray(next.targets) ? next.targets.slice() : []
        } : null;
        var currentKey = state ? state.kind + '=' + state.value : '';
        var nextKey = normalized ? normalized.kind + '=' + normalized.value : '';
        state = normalized;
        return currentKey !== nextKey;
      },
      clear: function () {
        if (!state) return false;
        state = null;
        return true;
      },
      appendRequestParams: function (params) {
        if (state) {
          params.set('search_kind', state.kind);
          params.set('search_value', state.value);
        }
        return params;
      },
      getCacheKey: function () {
        if (!state) return '';
        return new URLSearchParams({
          search_kind: state.kind,
          search_value: state.value
        }).toString();
      },
      getState: function () {
        if (!state) return null;
        return {
          kind: state.kind,
          value: state.value,
          targets: state.targets.slice()
        };
      }
    };
  }

  function normalizePayload(payload) {
    payload = payload || {};
    return {
      atlasStops: Array.isArray(payload.atlas_stops) ? payload.atlas_stops : [],
      gtfsStops: Array.isArray(payload.gtfs_stops) ? payload.gtfs_stops : [],
      matches: Array.isArray(payload.matches) ? payload.matches : [],
      meta: payload.meta || {}
    };
  }

  function finiteCoordinate(value) {
    if (value == null || (typeof value === 'string' && value.trim() === '')) return null;
    var number = Number(value);
    return Number.isFinite(number) ? number : null;
  }


  function fetchJson(url, options) {
    return global.fetch(url, options || {}).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (payload) {
        if (!response.ok) {
          var error = new Error(payload.error || 'Request failed with status ' + response.status);
          error.status = response.status;
          error.payload = payload;
          throw error;
        }
        return payload;
      });
    });
  }

  var mapElement = document.getElementById('routesGtfsStopIdSloidMap');
  if (!mapElement) return;

  var config = parseConfig();
  var components = global.MapComponents || {};
  var mapRenderer = components.MapRenderer || global.MapRenderer;
  var mapShared = components.MapShared || global.MapShared;

  requireFunction(components.MapCore && components.MapCore.create, 'MapComponents.MapCore.create()');
  requireFunction(components.MapViewportLoader && components.MapViewportLoader.create, 'MapComponents.MapViewportLoader.create()');
  requireFunction(components.MapLayerRegistry && components.MapLayerRegistry.create, 'MapComponents.MapLayerRegistry.create()');
  requireFunction(components.MapPopupController && components.MapPopupController.create, 'MapComponents.MapPopupController.create()');
  requireFunction(mapShared && mapShared.createEntityKey, 'MapShared.createEntityKey()');
  requireFunction(mapShared && mapShared.getViewportZoomPolicy, 'MapShared.getViewportZoomPolicy()');
  requireFunction(mapRenderer && mapRenderer.layoutEntities, 'MapRenderer.layoutEntities()');
  requireFunction(mapRenderer && mapRenderer.createEntityMarker, 'MapRenderer.createEntityMarker()');
  requireFunction(mapRenderer && mapRenderer.createPopupWithOptions, 'MapRenderer.createPopupWithOptions()');
  requireFunction(global.PopupRenderer && global.PopupRenderer.generateGtfsStopIdSloidPopupHtml, 'PopupRenderer.generateGtfsStopIdSloidPopupHtml()');
  requireFunction(global.LineRenderer && global.LineRenderer.drawRelationships, 'LineRenderer.drawRelationships()');
  requireFunction(global.FilterChipUtils && global.FilterChipUtils.buildRemovableChip, 'FilterChipUtils.buildRemovableChip()');

  var summaryElement = document.getElementById('headerSummaryStats');
  var statusElement = document.getElementById('routesGtfsStopIdSloidStatus');
  var statusTextElement = document.getElementById('routesGtfsStopIdSloidStatusText');
  var retryButton = document.getElementById('routesGtfsStopIdSloidRetry');
  var searchForm = document.getElementById('routesGtfsStopIdSloidSearchForm');
  var searchInput = document.getElementById('routesGtfsStopIdSloidSearchInput');
  var searchButton = document.getElementById('routesGtfsStopIdSloidSearchButton');
  var searchHint = document.getElementById('routesGtfsStopIdSloidSearchHint');
  var searchFeedback = document.getElementById('routesGtfsStopIdSloidSearchFeedback');
  var filterControls = document.getElementById('routesGtfsStopIdSloidControls');
  var matchedAllCheckbox = document.getElementById('routesGtfsMatchedAll');
  var unmatchedGtfsCheckbox = document.getElementById('routesGtfsUnmatchedGtfs');
  var unmatchedAtlasCheckbox = document.getElementById('routesGtfsUnmatchedAtlas');
  var matchMethodsSection = document.getElementById('routesGtfsMatchMethodsSection');
  var matchMethodsContainer = document.getElementById('routesGtfsMatchMethods');
  var activeFiltersElement = document.getElementById('activeFilters');
  var filterAdapter = createFilterAdapter(config.initialFilters || {});
  var matchMethodLabels = {};
  var identifierSearch = createIdentifierSearchAdapter();
  var searchRequestController = null;
  var searchRequestSequence = 0;
  var summaryBinding = null;
  var lastRenderedPayload = null;
  var lastRenderedZoom = null;
  var destroyed = false;

  function setStatus(kind, message, canRetry) {
    if (!statusElement || !statusTextElement) return;
    statusElement.classList.toggle('d-none', !message);
    statusElement.dataset.state = kind || '';
    statusTextElement.textContent = message || '';
    if (retryButton) retryButton.hidden = !canRetry;
  }

  function getViewportPolicy(zoom) {
    var policy = mapShared.getViewportZoomPolicy(zoom);
    var requestLimit = policy.limit == null ? 'all' : String(policy.limit);
    return Object.assign({}, policy, {
      requestLimit: requestLimit,
      identity: [
        'mode=' + policy.mode,
        'limit=' + requestLimit,
        'filters=' + filterAdapter.getCacheKey(),
        'search=' + identifierSearch.getCacheKey()
      ].join('&')
    });
  }

  function isPayloadCapped(rawPayload) {
    var meta = normalizePayload(rawPayload).meta;
    return !!(meta.gtfs_capped || meta.atlas_capped);
  }

  function prepareCompletenessStatus(policy) {
    if (policy.shouldShowBanner) {
      setStatus('zoom', '📍 Zoom in a bit more to see all markers in this area', false);
    } else {
      setStatus('', '', false);
    }
  }

  function updateCompletenessStatus(policy, meta) {
    var capped = !!(meta.gtfs_capped || meta.atlas_capped);
    if (!policy.isOverview && !capped) {
      setStatus('', '', false);
      return;
    }

    var message = '📍 Zoom in a bit more to see all markers in this area';
    if (capped) {
      message += '. Limited views can omit a matched stop’s counterpart.';
    }
    setStatus('zoom', message, false);
  }

  var defaultCenter = AppConstants.MAP.DEFAULT_CENTER;
  var defaultZoom = AppConstants.MAP.DEFAULT_ZOOM;
  var minZoom = AppConstants.MAP.MIN_ZOOM;
  var maxZoom = AppConstants.MAP.MAX_ZOOM;
  var maxBounds = AppConstants.MAP.MAX_BOUNDS;

  var mapCore = components.MapCore.create({
    container: mapElement,
    view: {
      center: defaultCenter,
      zoom: defaultZoom
    },
    mapOptions: {
      closePopupOnClick: false,
      preferCanvas: false,
      minZoom: minZoom,
      maxZoom: maxZoom,
      maxBounds: maxBounds,
      maxBoundsViscosity: 1,
      zoomControl: false
    },
    rendererPadding: 0.1,
    defaultBaseLayer: 'OpenStreetMap',
    layerGroups: {
      atlasMarkers: true,
      gtfsMarkers: true,
      lines: true
    },
    controls: {
      zoom: { position: 'bottomleft' },
      layers: { position: 'bottomleft' }
    },
    popupBehavior: true,
    invalidateOnResize: true
  });

  var map = mapCore.map;
  var atlasMarkersLayer = mapCore.layers.atlasMarkers;
  var gtfsMarkersLayer = mapCore.layers.gtfsMarkers;
  var linesLayer = mapCore.layers.lines;

  function renderPopup(payload) {
    return global.PopupRenderer.generateGtfsStopIdSloidPopupHtml(payload, {
      enableFilterLinks: false,
      enableRouteLinks: false
    });
  }

  function buildPopupUrl(entityType, identifier) {
    var params = new URLSearchParams({ entity_type: entityType });
    params.set(entityType === 'atlas' ? 'sloid' : 'stop_id', identifier);
    return config.popupUrl + '?' + params.toString();
  }

  var popupController = components.MapPopupController.create({
    cache: 'payload',
    createPopup: function (content) {
      return mapRenderer.createPopupWithOptions(content);
    },
    errorContent: '<div class="p-2 text-danger">Unable to load stop details. Click the marker to retry.</div>',
    onError: function (error, context) {
      console.error('Failed to load GTFS popup for ' + context.key, error);
    }
  });

  function popupOptions(descriptor) {
    return {
      key: descriptor.key,
      load: function (context) {
        return fetchJson(buildPopupUrl(descriptor.entity.entityType, descriptor.entity.identifier), {
          signal: context.signal
        });
      },
      render: renderPopup
    };
  }

  function attachPopup(marker, descriptor) {
    popupController.attach(marker, popupOptions(descriptor));
  }

  function updateMarker(marker, descriptor) {
    if (typeof marker.setLatLng === 'function') marker.setLatLng(descriptor.displayPosition);
    marker._routesGtfsDescriptor = descriptor;
    attachPopup(marker, descriptor);
  }

  function handleMarkerRemoval(marker, _descriptor, details) {
    if (details && details.reason === 'replace' && details.replacementLayer &&
        typeof popupController.transfer === 'function') {
      popupController.transfer(marker, details.replacementLayer).catch(function (error) {
        console.error('Failed to preserve an open popup while replacing a GTFS map marker', error);
      });
      return;
    }
    popupController.detach(marker);
  }

  var atlasRegistry = components.MapLayerRegistry.create({
    layerGroup: atlasMarkersLayer,
    create: function (descriptor) {
      var marker = mapRenderer.createEntityMarker(descriptor);
      marker._routesGtfsDescriptor = descriptor;
      attachPopup(marker, descriptor);
      return marker;
    },
    update: updateMarker,
    onRemove: handleMarkerRemoval
  });

  var gtfsRegistry = components.MapLayerRegistry.create({
    layerGroup: gtfsMarkersLayer,
    create: function (descriptor) {
      var marker = mapRenderer.createEntityMarker(descriptor);
      marker._routesGtfsDescriptor = descriptor;
      attachPopup(marker, descriptor);
      return marker;
    },
    update: updateMarker,
    onRemove: handleMarkerRemoval
  });

  function renderPayload(rawPayload, context) {
    var payload = normalizePayload(rawPayload);
    var policy = getViewportPolicy(context.zoom);
    updateCompletenessStatus(policy, payload.meta);

    if (context.cacheHit && rawPayload === lastRenderedPayload && context.zoom === lastRenderedZoom) {
      return;
    }

    var snapshot = global.MapEntityAdapters.gtfs(payload);
    var layout = mapRenderer.layoutEntities(snapshot.entities, {
      map: map, zoom: context.zoom, sourcePositionsByKey: snapshot.sourcePositionsByKey
    });

    atlasRegistry.reconcile(layout.descriptors.filter(item => item.entity.entityType === 'atlas'), context);
    gtfsRegistry.reconcile(layout.descriptors.filter(item => item.entity.entityType === 'gtfs'), context);
    if (context.zoom < AppConstants.MAP.ZOOM_LINE_THRESHOLD) {
      linesLayer.clearLayers();
    } else {
      linesLayer.clearLayers();
      global.LineRenderer.drawRelationships(snapshot.relationships, linesLayer, layout.displayPositionsByKey);
    }
    lastRenderedPayload = rawPayload;
    lastRenderedZoom = context.zoom;
  }

  function buildMapRequestUrl(context) {
    var bounds = context.requestBounds;
    var policy = getViewportPolicy(context.zoom);
    var params = new URLSearchParams({
      min_lat: String(bounds.getSouth()),
      min_lon: String(bounds.getWest()),
      max_lat: String(bounds.getNorth()),
      max_lon: String(bounds.getEast()),
      zoom: String(context.zoom),
      limit: policy.requestLimit,
      include_matches: policy.isOverview ? '0' : '1'
    });
    filterAdapter.appendRequestParams(params);
    identifierSearch.appendRequestParams(params);
    return config.mapUrl + '?' + params.toString();
  }

  var viewportLoader = components.MapViewportLoader.create({
    map: map,
    events: ['moveend', 'zoomend'],
    debounceMs: AppConstants.DATA_LOADING.VIEW_DEBOUNCE_MS,
    buildRequestBounds: function (context) {
      var policy = getViewportPolicy(context.zoom);
      return context.bounds.pad(policy.isOverview ? 0.5 : 0.35);
    },
    getRequestIdentity: function (context) {
      return getViewportPolicy(context.zoom).identity;
    },
    shouldReuse: function (cached, context) {
      var sameZoom = cached.zoom === context.zoom;
      var safeZoomIn = context.zoom > cached.zoom && !isPayloadCapped(cached.data);
      if (!sameZoom && !safeZoomIn) return false;

      try {
        return cached.requestBounds.contains(context.bounds.pad(-0.05));
      } catch (error) {
        return false;
      }
    },
    load: function (context) {
      prepareCompletenessStatus(getViewportPolicy(context.zoom));
      return fetchJson(buildMapRequestUrl(context), { signal: context.signal });
    },
    onData: renderPayload,
    onError: function (error) {
      console.error('Failed to refresh GTFS stop_id/SLOID map', error);
      setStatus('error', 'The map could not be refreshed. The last successful result is still shown.', true);
    }
  });

  function arrayValue(value) {
    if (Array.isArray(value)) return value;
    return value == null || value === '' ? [] : [String(value)];
  }

  function getMatchMethodCheckboxes() {
    return matchMethodsContainer
      ? Array.from(matchMethodsContainer.querySelectorAll('.routes-gtfs-match-method'))
      : [];
  }

  function syncMatchedMasterFromMethods() {
    if (!matchedAllCheckbox) return;
    var methodCheckboxes = getMatchMethodCheckboxes();
    var selectedCount = methodCheckboxes.filter(function (checkbox) { return checkbox.checked; }).length;
    matchedAllCheckbox.checked = methodCheckboxes.length > 0 && selectedCount === methodCheckboxes.length;
    matchedAllCheckbox.indeterminate = selectedCount > 0 && selectedCount < methodCheckboxes.length;
  }

  function syncFilterControlsFromState(state) {
    state = state || filterAdapter.getState();
    var statuses = arrayValue(state.status);
    var methods = arrayValue(state.match_method);
    var allMatched = statuses.indexOf('matched') !== -1;

    if (matchedAllCheckbox) {
      matchedAllCheckbox.checked = allMatched;
      matchedAllCheckbox.indeterminate = false;
    }
    if (unmatchedGtfsCheckbox) unmatchedGtfsCheckbox.checked = statuses.indexOf('gtfs_unmatched') !== -1;
    if (unmatchedAtlasCheckbox) unmatchedAtlasCheckbox.checked = statuses.indexOf('atlas_unmatched') !== -1;
    getMatchMethodCheckboxes().forEach(function (checkbox) {
      checkbox.checked = allMatched || methods.indexOf(checkbox.value) !== -1;
    });
    if (!allMatched) syncMatchedMasterFromMethods();
  }

  function buildFilterStateFromControls() {
    var statuses = [];
    var methods = [];
    if (matchedAllCheckbox && matchedAllCheckbox.checked) {
      statuses.push('matched');
    } else {
      getMatchMethodCheckboxes().forEach(function (checkbox) {
        if (checkbox.checked) methods.push(checkbox.value);
      });
    }
    if (unmatchedGtfsCheckbox && unmatchedGtfsCheckbox.checked) statuses.push('gtfs_unmatched');
    if (unmatchedAtlasCheckbox && unmatchedAtlasCheckbox.checked) statuses.push('atlas_unmatched');

    var state = {};
    if (statuses.length > 0) state.status = statuses;
    if (methods.length > 0) state.match_method = methods;
    return state;
  }

  function renderMatchingMethodOptions(methods) {
    if (!matchMethodsContainer || !matchMethodsSection) return;
    matchMethodsContainer.replaceChildren();
    matchMethodLabels = {};

    (Array.isArray(methods) ? methods : []).forEach(function (method, index) {
      if (!method || !method.value) return;
      var value = String(method.value);
      var label = String(method.label || value.replace(/_/g, ' '));
      matchMethodLabels[value] = label;

      var wrapper = document.createElement('div');
      wrapper.className = 'form-check';
      var checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.className = 'form-check-input routes-gtfs-match-method';
      checkbox.id = 'routesGtfsMatchMethod' + String(index);
      checkbox.value = value;
      var labelElement = document.createElement('label');
      labelElement.className = 'form-check-label';
      labelElement.htmlFor = checkbox.id;
      labelElement.append(document.createTextNode(label + ' '));
      if (method.count != null) {
        var count = document.createElement('span');
        count.className = 'badge filter-count-badge ms-1';
        count.textContent = String(method.count);
        labelElement.append(count);
      }
      wrapper.append(checkbox, labelElement);
      matchMethodsContainer.append(wrapper);
    });

    matchMethodsSection.classList.toggle('d-none', getMatchMethodCheckboxes().length === 0);
    syncFilterControlsFromState();
  }

  function renderSummary(summary) {
    if (destroyed) return;
    renderMatchingMethodOptions(summary.match_methods);
    if (!summaryElement) return;
    summaryElement.innerHTML = [
      '<div class="header-summary__stat"><strong>' + String(summary.total_gtfs_stops || 0) + '</strong> <span>GTFS (<span style="color:#2f9e44;font-weight:bold;">' + String(summary.gtfs_coverage_percent || 0) + '% matched</span>)</span></div>',
      '<div class="header-summary__stat"><strong>' + String(summary.total_atlas_stops || 0) + '</strong> <span>ATLAS (<span style="color:#174092;font-weight:bold;">' + String(summary.atlas_coverage_percent || 0) + '% matched</span>)</span></div>'
    ].join('');
  }

  var summaryRequestController = typeof global.AbortController === 'function'
    ? new global.AbortController()
    : null;

  function loadSummary() {
    var options = summaryRequestController ? { signal: summaryRequestController.signal } : {};
    fetchJson(config.summaryUrl, options)
      .then(renderSummary)
      .catch(function (error) {
        if (destroyed || (error && error.name === 'AbortError')) return;
        console.error('Failed to load GTFS summary', error);
        if (summaryElement) {
          summaryElement.innerHTML = '<div class="header-summary__stat">Failed to load GTFS summary.</div>';
        }
      });
  }

  function getActiveMapFilterCount() {
    return filterAdapter.getActiveCount() + (identifierSearch.getState() ? 1 : 0);
  }

  function renderActiveFilterChips() {
    var search = identifierSearch.getState();
    var state = filterAdapter.getState();
    var chips = [];
    arrayValue(state.status).forEach(function (status) {
      chips.push(global.FilterChipUtils.buildRemovableChip({
        label: FILTER_STATUS_LABELS[status] || status,
        badgeClass: status === 'matched' ? 'filter-chip-matched' : 'filter-chip-unmatched',
        removeClass: 'remove-gtfs-map-filter',
        data: { filterType: 'status', filterValue: status },
        closeChar: '×',
        removeLabel: 'Remove ' + (FILTER_STATUS_LABELS[status] || status) + ' filter'
      }));
    });
    arrayValue(state.match_method).forEach(function (method) {
      chips.push(global.FilterChipUtils.buildRemovableChip({
        label: 'Matched: ' + (matchMethodLabels[method] || method.replace(/_/g, ' ')),
        badgeClass: 'filter-chip-matched',
        removeClass: 'remove-gtfs-map-filter',
        data: { filterType: 'match_method', filterValue: method },
        closeChar: '×',
        removeLabel: 'Remove matching method filter'
      }));
    });
    if (search) {
      chips.push(global.FilterChipUtils.buildRemovableChip({
        label: SEARCH_KIND_LABELS[search.kind] + ': ' + search.value,
        badgeClass: 'filter-chip-secondary',
        removeClass: 'remove-gtfs-identifier-search',
        closeChar: '×',
        removeLabel: 'Clear identifier search'
      }));
    }
    if (activeFiltersElement) {
      activeFiltersElement.innerHTML = chips.length > 0
        ? chips.join('')
        : '<span class="badge filter-chip-badge filter-chip-secondary">All entries</span>';
    }
    if (summaryBinding) {
      summaryBinding.syncFilters({ activeFilterCount: getActiveMapFilterCount() });
    }
  }

  function setSearchBusy(busy) {
    if (searchForm) searchForm.setAttribute('aria-busy', busy ? 'true' : 'false');
    if (searchButton) searchButton.disabled = !!busy;
  }

  function setSearchError(message) {
    if (!searchFeedback) return;
    searchFeedback.textContent = message || '';
    searchFeedback.classList.toggle('d-none', !message);
    if (searchInput) searchInput.setAttribute('aria-invalid', message ? 'true' : 'false');
    if (message && searchHint) searchHint.classList.add('d-none');
  }

  function cancelIdentifierLookup() {
    searchRequestSequence += 1;
    if (searchRequestController) {
      try { searchRequestController.abort(); } catch (error) { /* sequence checks remain authoritative */ }
      searchRequestController = null;
    }
    setSearchBusy(false);
  }

  function focusIdentifierTargets(targets) {
    var positions = (targets || []).map(function (target) {
      var lat = finiteCoordinate(target.lat);
      var lon = finiteCoordinate(target.lon);
      return lat == null || lon == null ? null : [lat, lon];
    }).filter(Boolean);

    if (positions.length === 0) {
      return Promise.reject(new Error('No mappable stop found for this identifier.'));
    }

    var resume = typeof viewportLoader.pause === 'function'
      ? viewportLoader.pause()
      : function () {};
    if (positions.length === 1 && typeof map.setView === 'function') {
      map.setView(positions[0], Math.max(Number(map.getZoom()) || 0, 16), { animate: false });
    } else if (typeof map.fitBounds === 'function') {
      map.fitBounds(positions, { padding: [36, 36], maxZoom: 16, animate: false });
    }
    viewportLoader.invalidate();
    resume();
    return viewportLoader.reload({ force: true, reason: 'identifier-search' });
  }

  function applyIdentifierSearch(parsed, targets) {
    identifierSearch.replace({
      kind: parsed.kind,
      value: parsed.value,
      targets: targets
    });
    if (searchInput) searchInput.value = '';
    renderActiveFilterChips();
    return focusIdentifierTargets(targets);
  }

  function submitIdentifierSearch(rawValue) {
    var parsed = parseIdentifierSearch(rawValue == null && searchInput ? searchInput.value : rawValue);
    if (parsed.error) {
      setSearchError(parsed.error);
      return Promise.resolve({ status: 'invalid', error: parsed.error });
    }

    cancelIdentifierLookup();
    setSearchError('');
    setSearchBusy(true);
    var requestSequence = searchRequestSequence;
    searchRequestController = typeof global.AbortController === 'function'
      ? new global.AbortController()
      : null;
    var params = new URLSearchParams({ kind: parsed.kind, value: parsed.value });
    var options = searchRequestController ? { signal: searchRequestController.signal } : {};

    return fetchJson(config.searchUrl + '?' + params.toString(), options)
      .then(function (payload) {
        if (destroyed || requestSequence !== searchRequestSequence) return { status: 'stale' };
        var targets = Array.isArray(payload.targets) ? payload.targets : [];
        return applyIdentifierSearch(parsed, targets).then(function () {
          if (destroyed || requestSequence !== searchRequestSequence) return { status: 'stale' };
          return { status: 'found', search: identifierSearch.getState() };
        });
      })
      .catch(function (error) {
        if (destroyed || requestSequence !== searchRequestSequence || (error && error.name === 'AbortError')) {
          return { status: 'stale' };
        }
        var message = error && error.status === 404
          ? 'No mappable stop found for this identifier.'
          : 'The identifier search could not be completed.';
        setSearchError(message);
        return { status: 'error', error: error };
      })
      .then(function (result) {
        if (requestSequence === searchRequestSequence) {
          searchRequestController = null;
          setSearchBusy(false);
        }
        return result;
      });
  }

  function resetIdentifierSearchState() {
    cancelIdentifierLookup();
    setSearchError('');
    if (searchInput) searchInput.value = '';
    return identifierSearch.clear();
  }

  function clearIdentifierSearch() {
    var changed = resetIdentifierSearchState();
    renderActiveFilterChips();
    if (!changed) return Promise.resolve({ status: 'unchanged' });
    viewportLoader.invalidate();
    return viewportLoader.reload({ force: true, reason: 'identifier-search-clear' });
  }

  function clearAllMapFilters() {
    var searchChanged = resetIdentifierSearchState();
    var filtersChanged = filterAdapter.replace({});
    syncFilterControlsFromState({});
    renderActiveFilterChips();
    if (!searchChanged && !filtersChanged) return Promise.resolve({ status: 'unchanged' });
    viewportLoader.invalidate();
    return viewportLoader.reload({ force: true, reason: 'all-filters-clear' });
  }

  function handleSearchSubmit(event) {
    event.preventDefault();
    submitIdentifierSearch();
  }

  function handleSearchInput() {
    setSearchError('');
    if (searchHint) searchHint.classList.toggle('d-none', !!searchInput.value.trim());
  }

  function handleSearchFocus() {
    if (searchHint && searchInput && !searchInput.value.trim() && (!searchFeedback || searchFeedback.classList.contains('d-none'))) {
      searchHint.classList.remove('d-none');
    }
  }

  function handleSearchBlur() {
    global.setTimeout(function () {
      if (searchHint) searchHint.classList.add('d-none');
    }, 150);
  }

  function handleSearchKeydown(event) {
    if (event.key !== 'Escape') return;
    event.preventDefault();
    if (searchInput && searchInput.value) {
      searchInput.value = '';
      setSearchError('');
      if (searchHint) searchHint.classList.remove('d-none');
      return;
    }
    clearIdentifierSearch();
  }

  function handleActiveFiltersClick(event) {
    var removeLink = event.target.closest('.remove-gtfs-identifier-search, .remove-gtfs-map-filter');
    if (!removeLink) return;
    event.preventDefault();
    if (removeLink.classList.contains('remove-gtfs-identifier-search')) {
      clearIdentifierSearch();
      return;
    }

    var filterType = removeLink.dataset.filterType;
    var filterValue = removeLink.dataset.filterValue;
    var nextState = filterAdapter.getState();
    var values = arrayValue(nextState[filterType]).filter(function (value) {
      return value !== filterValue;
    });
    if (values.length > 0) nextState[filterType] = values;
    else delete nextState[filterType];
    setFilters(nextState);
  }

  function handleFilterControlsChange(event) {
    var target = event.target;
    if (!target || target.type !== 'checkbox') return;
    if (target === matchedAllCheckbox) {
      getMatchMethodCheckboxes().forEach(function (checkbox) {
        checkbox.checked = matchedAllCheckbox.checked;
      });
      matchedAllCheckbox.indeterminate = false;
    } else if (target.classList.contains('routes-gtfs-match-method')) {
      syncMatchedMasterFromMethods();
    } else if (target !== unmatchedGtfsCheckbox && target !== unmatchedAtlasCheckbox) {
      return;
    }
    setFilters(buildFilterStateFromControls());
  }

  function isMobileViewport() {
    return global.matchMedia('(max-width: 768px)').matches;
  }

  summaryBinding = global.HeaderSummary && typeof global.HeaderSummary.bind === 'function'
    ? global.HeaderSummary.bind({
      collapsed: isMobileViewport(),
      isMobileViewport: isMobileViewport,
      getActiveFilterCount: getActiveMapFilterCount,
      onClearAll: clearAllMapFilters
    })
    : null;

  function syncSummaryLayout() {
    if (summaryBinding) {
      summaryBinding.setCollapsed(isMobileViewport(), 'viewport');
    } else if (global.HeaderSummary && typeof global.HeaderSummary.setCollapsed === 'function') {
      global.HeaderSummary.setCollapsed(isMobileViewport());
    }
  }

  function handleResize() {
    syncSummaryLayout();
  }

  function retryViewport() {
    viewportLoader.reload({ force: true, reason: 'retry' });
  }

  function setFilters(filters) {
    if (!filterAdapter.replace(filters)) {
      return Promise.resolve({ status: 'unchanged' });
    }
    syncFilterControlsFromState();
    renderActiveFilterChips();
    viewportLoader.invalidate();
    return viewportLoader.reload({ force: true, reason: 'filters-change' });
  }

  function destroy() {
    if (destroyed) return;
    destroyed = true;
    cancelIdentifierLookup();
    global.removeEventListener('resize', handleResize);
    global.removeEventListener('beforeunload', destroy);
    if (retryButton) retryButton.removeEventListener('click', retryViewport);
    if (searchForm) searchForm.removeEventListener('submit', handleSearchSubmit);
    if (searchInput) {
      searchInput.removeEventListener('input', handleSearchInput);
      searchInput.removeEventListener('focus', handleSearchFocus);
      searchInput.removeEventListener('blur', handleSearchBlur);
      searchInput.removeEventListener('keydown', handleSearchKeydown);
    }
    if (filterControls) filterControls.removeEventListener('change', handleFilterControlsChange);
    if (activeFiltersElement) activeFiltersElement.removeEventListener('click', handleActiveFiltersClick);
    if (summaryRequestController) summaryRequestController.abort();
    if (summaryBinding) summaryBinding.destroy();
    viewportLoader.destroy();
    atlasRegistry.destroy();
    gtfsRegistry.destroy();
    popupController.destroy();
    mapCore.destroy();
  }

  global.addEventListener('resize', handleResize);
  global.addEventListener('beforeunload', destroy);
  if (retryButton) retryButton.addEventListener('click', retryViewport);
  if (searchForm) searchForm.addEventListener('submit', handleSearchSubmit);
  if (searchInput) {
    searchInput.addEventListener('input', handleSearchInput);
    searchInput.addEventListener('focus', handleSearchFocus);
    searchInput.addEventListener('blur', handleSearchBlur);
    searchInput.addEventListener('keydown', handleSearchKeydown);
  }
  if (filterControls) filterControls.addEventListener('change', handleFilterControlsChange);
  if (activeFiltersElement) activeFiltersElement.addEventListener('click', handleActiveFiltersClick);

  global.RoutesGtfsStopIdSloidMap = Object.freeze({
    setFilters: setFilters,
    clearFilters: function () { return setFilters({}); },
    clearAllFilters: clearAllMapFilters,
    getFilters: filterAdapter.getState,
    getFilterCacheKey: filterAdapter.getCacheKey,
    getActiveFilterCount: getActiveMapFilterCount,
    search: submitIdentifierSearch,
    clearSearch: clearIdentifierSearch,
    getSearch: identifierSearch.getState,
    reload: function () { return viewportLoader.reload({ force: true, reason: 'api' }); },
    destroy: destroy
  });

  syncSummaryLayout();
  syncFilterControlsFromState();
  renderActiveFilterChips();
  loadSummary();
  viewportLoader.reload({ reason: 'initial' });
})(window);
