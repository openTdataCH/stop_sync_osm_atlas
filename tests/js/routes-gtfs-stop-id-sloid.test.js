const fs = require('fs');
const path = require('path');

const SCRIPT_PATH = path.join(__dirname, '../../static/js/pages/routes-gtfs-stop-id-sloid.js');

function response(payload) {
  return Promise.resolve({
    ok: true,
    status: 200,
    json: () => Promise.resolve(payload)
  });
}

function errorResponse(status, payload) {
  return Promise.resolve({
    ok: false,
    status,
    json: () => Promise.resolve(payload)
  });
}

function createLayerGroup() {
  const layers = [];
  return {
    layers,
    addLayer: jest.fn((layer) => {
      layers.push(layer);
      return layer;
    }),
    removeLayer: jest.fn((layer) => {
      const index = layers.indexOf(layer);
      if (index !== -1) layers.splice(index, 1);
    }),
    clearLayers: jest.fn(() => {
      layers.length = 0;
    }),
    eachLayer: jest.fn((callback) => {
      layers.slice().forEach(callback);
    })
  };
}

function createMarker(position, type) {
  return {
    type,
    position,
    setLatLng: jest.fn(function (nextPosition) {
      this.position = nextPosition;
      return this;
    }),
    on: jest.fn(),
    off: jest.fn(),
    bindPopup: jest.fn(),
    openPopup: jest.fn(),
    closePopup: jest.fn(),
    unbindPopup: jest.fn()
  };
}

function createRegistryFactory(registries) {
  return jest.fn((options) => {
    const entries = new Map();
    const registry = {
      options,
      entries,
      reconcile: jest.fn((descriptors, context) => {
        const nextKeys = new Set();
        descriptors.forEach((descriptor) => {
          nextKeys.add(descriptor.key);
          const current = entries.get(descriptor.key);
          if (!current) {
            const layer = options.create(descriptor, context);
            options.layerGroup.addLayer(layer);
            entries.set(descriptor.key, { layer, descriptor });
            return;
          }
          if (current.descriptor.renderSignature !== descriptor.renderSignature) {
            const replacement = options.create(descriptor, context);
            options.layerGroup.addLayer(replacement);
            if (options.onRemove) options.onRemove(current.layer, current.descriptor, {
              reason: 'replace',
              replacementLayer: replacement,
              replacementDescriptor: descriptor
            });
            options.layerGroup.removeLayer(current.layer);
            entries.set(descriptor.key, { layer: replacement, descriptor });
            return;
          }
          options.update(current.layer, descriptor, current.descriptor, context);
          current.descriptor = descriptor;
        });
        Array.from(entries.entries()).forEach(([key, current]) => {
          if (nextKeys.has(key)) return;
          if (options.onRemove) options.onRemove(current.layer, current.descriptor, { reason: 'reconcile-remove' });
          options.layerGroup.removeLayer(current.layer);
          entries.delete(key);
        });
      }),
      destroy: jest.fn(() => {
        Array.from(entries.values()).forEach((current) => {
          if (options.onRemove) options.onRemove(current.layer, current.descriptor, { reason: 'destroy' });
        });
        entries.clear();
      })
    };
    registries.push(registry);
    return registry;
  });
}

function installPage() {
  document.body.innerHTML = `
    <div id="headerSummaryInfo">
      <button id="headerSummaryMobileToggle"></button>
      <div id="headerSummaryStats"></div>
      <div id="headerSummaryFiltersRow">
        <button id="headerSummaryFiltersToggle"></button>
        <a id="clearAllFilters" href="#">Clear all</a>
      </div>
      <div id="headerSummaryFiltersPanel"><div id="activeFilters"></div></div>
    </div>
    <form id="routesGtfsStopIdSloidSearchForm">
      <button id="routesGtfsStopIdSloidSearchButton" type="submit">Search</button>
      <input id="routesGtfsStopIdSloidSearchInput">
      <div id="routesGtfsStopIdSloidSearchHint" class="d-none"></div>
      <div id="routesGtfsStopIdSloidSearchFeedback" class="d-none"></div>
    </form>
    <div id="routesGtfsStopIdSloidStatus" class="zoom-banner d-none">
      <span id="routesGtfsStopIdSloidStatusText"></span>
      <button id="routesGtfsStopIdSloidRetry" hidden>Retry</button>
    </div>
    <div id="routesGtfsStopIdSloidMap"></div>
    <script type="application/json" id="routesGtfsStopIdSloidConfig">
      {"summaryUrl":"/summary","mapUrl":"/map","searchUrl":"/search","popupUrl":"/popup"}
    </script>
  `;

  const bounds = {
    getSouth: () => 46,
    getWest: () => 7,
    getNorth: () => 47,
    getEast: () => 8,
    pad: jest.fn(function () { return this; }),
    contains: jest.fn(() => true)
  };
  const map = {
    getBounds: jest.fn(() => bounds),
    getZoom: jest.fn(() => 12),
    setView: jest.fn(),
    fitBounds: jest.fn()
  };
  const layers = {
    atlasMarkers: createLayerGroup(),
    gtfsMarkers: createLayerGroup(),
    lines: createLayerGroup()
  };
  const mapCore = {
    map,
    layers,
    destroy: jest.fn()
  };
  const viewportController = {
    reload: jest.fn(() => Promise.resolve({ status: 'loaded' })),
    invalidate: jest.fn(),
    pause: jest.fn(() => jest.fn()),
    destroy: jest.fn()
  };
  const popupController = {
    attach: jest.fn(),
    detach: jest.fn(),
    transfer: jest.fn(() => Promise.resolve({ status: 'transferred' })),
    destroy: jest.fn()
  };
  const registries = [];
  let viewportOptions;

  class ClusterManager {
    constructor() {
      this.entries = [];
    }

    addMarker(lat, lon, markerData) {
      this.entries.push({ lat, lon, markerData });
    }

    getClusteredData() {
      return this.entries.map((entry) => {
        const offset = entry.markerData.entityType === 'atlas' ? 0.001 : -0.001;
        return {
          lat: entry.lat + offset,
          lon: entry.lon + offset,
          markerData: entry.markerData
        };
      });
    }
  }

  window.L = {
    circleMarker: jest.fn((position) => createMarker(position, 'gtfs')),
    layerGroup: jest.fn(createLayerGroup)
  };
  window.AppConstants = {
    MAP: {
      DEFAULT_CENTER: [46.8, 8.2],
      DEFAULT_ZOOM: 8,
      MIN_ZOOM: 8,
      MAX_ZOOM: 20,
      ZOOM_MARKER_THRESHOLD: 13,
      ZOOM_LINE_THRESHOLD: 13,
      ADDITIONAL_BANNER_ZOOM_LEVELS: 2,
      MAX_BOUNDS: [[45.5, 5.5], [48, 11]]
    },
    DATA_LOADING: {
      GENERAL_LIMIT: 1800,
      VIEW_DEBOUNCE_MS: 150
    }
  };
  window.MapRenderer = {
    MarkerClusterManager: ClusterManager,
    createAtlasMarker: jest.fn((lat, lon) => createMarker([lat, lon], 'atlas')),
    getMarkerRenderSignature: jest.fn((type, color, data, zoom) => [type, color, data.hasAtlasDuplicate, zoom < 18 ? 'circle' : 'label'].join('|')),
    createPopupWithOptions: jest.fn((content) => ({ content }))
  };
  window.MapShared = {
    createEntityKey: jest.fn((type, stop) => `${type}:${type === 'atlas' ? stop.sloid : stop.stop_id}`),
    getViewportZoomPolicy: jest.fn((zoom) => ({
      zoom,
      isOverview: zoom < 13,
      isFullDetail: zoom >= 15,
      shouldShowBanner: zoom < 15,
      limit: zoom < 15 ? 1800 : null,
      mode: zoom < 13 ? 'overview' : (zoom < 15 ? 'limited' : 'full')
    }))
  };
  window.PopupRenderer = {
    generateGtfsStopIdSloidPopupHtml: jest.fn((payload) => `<p>${payload.entity_type}</p>`)
  };
  window.LineRenderer = {
    drawLine: jest.fn((layer, atlasLat, atlasLon, gtfsLat, gtfsLon) => {
      const line = { atlasLat, atlasLon, gtfsLat, gtfsLon };
      layer.addLayer(line);
      return line;
    })
  };
  const summaryController = {
      setCollapsed: jest.fn(),
      syncFilters: jest.fn(),
      destroy: jest.fn()
  };
  window.HeaderSummary = {
    bind: jest.fn(() => summaryController)
  };
  window.FilterChipUtils = {
    buildRemovableChip: jest.fn((options) => (
      `<span class="filter-chip-badge ${options.badgeClass || ''}">${options.label}` +
      ` <a href="#" class="${options.removeClass || 'remove-filter'}">${options.closeChar || 'x'}</a></span>`
    ))
  };
  window.matchMedia = jest.fn(() => ({ matches: false }));
  window.fetch = jest.fn((url) => {
    if (url === '/summary') return response({ total_gtfs_stops: 1, total_atlas_stops: 1 });
    return response({});
  });

  const registryFactory = createRegistryFactory(registries);
  window.MapComponents = {
    MapCore: { create: jest.fn(() => mapCore) },
    MapViewportLoader: {
      create: jest.fn((options) => {
        viewportOptions = options;
        return viewportController;
      })
    },
    MapLayerRegistry: { create: registryFactory },
    MapPopupController: { create: jest.fn(() => popupController) }
  };

  window.eval(fs.readFileSync(SCRIPT_PATH, 'utf8'));

  return {
    bounds,
    layers,
    mapCore,
    map,
    popupController,
    registries,
    summaryController,
    viewportController,
    getViewportOptions: () => viewportOptions
  };
}

function samplePayload(overrides) {
  return Object.assign({
    atlas_stops: [{
      sloid: 'ch:1:sloid:1',
      atlas_lat: 46.5,
      atlas_lon: 7.5,
      match_status: 'matched',
      has_atlas_duplicate: false
    }],
    gtfs_stops: [{
      stop_id: '8500:0:1',
      stop_lat: 46.6,
      stop_lon: 7.6,
      match_status: 'matched'
    }],
    matches: [{
      stop_id: '8500:0:1',
      sloid: 'ch:1:sloid:1',
      atlas_lat: 46.5,
      atlas_lon: 7.5,
      gtfs_stop_lat: 46.6,
      gtfs_stop_lon: 7.6
    }],
    meta: {}
  }, overrides || {});
}

describe('Routes GTFS stop_id/SLOID map adapter', () => {
  afterEach(() => {
    if (window.RoutesGtfsStopIdSloidMap) {
      window.RoutesGtfsStopIdSloidMap.destroy();
      delete window.RoutesGtfsStopIdSloidMap;
    }
  });

  test('uses shared primitives and preserves markers with stable keys', () => {
    const page = installPage();
    const viewportOptions = page.getViewportOptions();
    const context = { zoom: 17 };

    viewportOptions.onData(samplePayload(), context);
    const firstAtlasMarker = page.registries[0].entries.get('atlas:ch:1:sloid:1').layer;
    const firstGtfsMarker = page.registries[1].entries.get('gtfs:8500:0:1').layer;

    viewportOptions.onData(samplePayload({
      atlas_stops: [{
        sloid: 'ch:1:sloid:1',
        atlas_lat: 46.7,
        atlas_lon: 7.7,
        match_status: 'matched',
        has_atlas_duplicate: false
      }]
    }), context);

    expect(page.registries[0].entries.get('atlas:ch:1:sloid:1').layer).toBe(firstAtlasMarker);
    expect(page.registries[1].entries.get('gtfs:8500:0:1').layer).toBe(firstGtfsMarker);
    const updatedAtlasPosition = firstAtlasMarker.setLatLng.mock.calls[0][0];
    expect(updatedAtlasPosition[0]).toBeCloseTo(46.701);
    expect(updatedAtlasPosition[1]).toBeCloseTo(7.701);
    expect(page.popupController.attach).toHaveBeenCalledWith(
      firstAtlasMarker,
      expect.objectContaining({ key: 'atlas:ch:1:sloid:1' })
    );
    expect(page.layers.lines.clearLayers).toHaveBeenCalledTimes(2);
    expect(window.map).toBeUndefined();
    expect(window.MapComponents.MapCore.create).toHaveBeenCalledWith(
      expect.objectContaining({
        container: document.getElementById('routesGtfsStopIdSloidMap'),
        popupBehavior: true,
        invalidateOnResize: true
      })
    );
  });

  test('draws match lines between keyed display positions instead of raw snapshots', () => {
    const page = installPage();
    const viewportOptions = page.getViewportOptions();
    window.LineRenderer.drawLine.mockClear();

    viewportOptions.onData(samplePayload({
      matches: [{
        stop_id: '8500:0:1',
        sloid: 'ch:1:sloid:1',
        atlas_lat: null,
        atlas_lon: null,
        gtfs_stop_lat: null,
        gtfs_stop_lon: null
      }]
    }), { zoom: 20 });

    expect(window.LineRenderer.drawLine).toHaveBeenCalledTimes(1);
    const call = window.LineRenderer.drawLine.mock.calls[0];
    expect(call[1]).toBeCloseTo(46.501);
    expect(call[2]).toBeCloseTo(7.501);
    expect(call[3]).toBeCloseTo(46.599);
    expect(call[4]).toBeCloseTo(7.599);
  });

  test('uses a null-safe raw-coordinate fallback for legacy relationships without keys', () => {
    const page = installPage();
    const viewportOptions = page.getViewportOptions();
    window.LineRenderer.drawLine.mockClear();

    viewportOptions.onData(samplePayload({
      matches: [
        {
          atlas_lat: 46.51,
          atlas_lon: 7.51,
          gtfs_stop_lat: 46.61,
          gtfs_stop_lon: 7.61
        },
        {
          atlas_lat: null,
          atlas_lon: null,
          gtfs_stop_lat: 46.61,
          gtfs_stop_lon: 7.61
        }
      ]
    }), { zoom: 20 });

    expect(window.LineRenderer.drawLine).toHaveBeenCalledTimes(1);
    expect(window.LineRenderer.drawLine.mock.calls[0].slice(1, 5))
      .toEqual([46.51, 7.51, 46.61, 7.61]);
  });

  test('transfers popup state only when a zoom signature replaces a marker', () => {
    const page = installPage();
    const viewportOptions = page.getViewportOptions();

    viewportOptions.onData(samplePayload(), { zoom: 17 });
    const oldAtlasMarker = page.registries[0].entries.get('atlas:ch:1:sloid:1').layer;
    viewportOptions.onData(samplePayload(), { zoom: 19 });
    const replacement = page.registries[0].entries.get('atlas:ch:1:sloid:1').layer;

    expect(replacement).not.toBe(oldAtlasMarker);
    expect(page.popupController.transfer).toHaveBeenCalledWith(oldAtlasMarker, replacement);
    expect(page.popupController.detach).not.toHaveBeenCalledWith(oldAtlasMarker);

    viewportOptions.onData(samplePayload({ atlas_stops: [] }), { zoom: 19 });
    expect(page.popupController.detach).toHaveBeenCalledWith(replacement);
  });

  test('serializes filters into requests and cache identity, then invalidates once per change', async () => {
    const page = installPage();
    const viewportOptions = page.getViewportOptions();

    await window.RoutesGtfsStopIdSloidMap.setFilters({
      operator: ['tl', 'sbb', 'tl', ' tl '],
      matched: ' yes ',
      zoom: 99,
      search_kind: 'uic',
      search_value: '8503000',
      empty: ''
    });

    expect(window.RoutesGtfsStopIdSloidMap.getFilters()).toEqual({
      matched: 'yes',
      operator: ['sbb', 'tl']
    });
    expect(window.RoutesGtfsStopIdSloidMap.getActiveFilterCount()).toBe(3);
    expect(page.viewportController.invalidate).toHaveBeenCalledTimes(1);
    expect(page.viewportController.reload).toHaveBeenLastCalledWith({
      force: true,
      reason: 'filters-change'
    });

    const context = {
      requestBounds: page.bounds,
      zoom: 12,
      signal: { request: 1 }
    };
    expect(viewportOptions.getRequestIdentity(context)).toBe(
      'mode=overview&limit=1800&filters=matched=yes&operator=sbb&operator=tl&search='
    );

    window.fetch.mockClear();
    window.fetch.mockImplementation(() => response(samplePayload()));
    await viewportOptions.load(context);
    const requestUrl = new URL(window.fetch.mock.calls[0][0], 'https://example.test');
    expect(requestUrl.searchParams.get('min_lat')).toBe('46');
    expect(requestUrl.searchParams.get('zoom')).toBe('12');
    expect(requestUrl.searchParams.get('limit')).toBe('1800');
    expect(requestUrl.searchParams.get('include_matches')).toBe('0');
    expect(requestUrl.searchParams.get('matched')).toBe('yes');
    expect(requestUrl.searchParams.getAll('operator')).toEqual(['sbb', 'tl']);
    expect(requestUrl.searchParams.getAll('zoom')).toEqual(['12']);

    await window.RoutesGtfsStopIdSloidMap.setFilters({
      matched: 'yes',
      operator: ['tl', 'sbb']
    });
    expect(page.viewportController.invalidate).toHaveBeenCalledTimes(1);
  });

  test('shares the Index zoom budget and reuses contained buffered viewports', () => {
    const page = installPage();
    const viewportOptions = page.getViewportOptions();

    expect(viewportOptions.debounceMs).toBe(150);
    expect(viewportOptions.getRequestIdentity({ zoom: 12 }))
      .toBe('mode=overview&limit=1800&filters=&search=');
    expect(viewportOptions.getRequestIdentity({ zoom: 13 }))
      .toBe('mode=limited&limit=1800&filters=&search=');
    expect(viewportOptions.getRequestIdentity({ zoom: 14 }))
      .toBe('mode=limited&limit=1800&filters=&search=');
    expect(viewportOptions.getRequestIdentity({ zoom: 15 }))
      .toBe('mode=full&limit=all&filters=&search=');

    expect(viewportOptions.buildRequestBounds({ bounds: page.bounds, zoom: 12 })).toBe(page.bounds);
    expect(page.bounds.pad).toHaveBeenLastCalledWith(0.5);
    expect(viewportOptions.buildRequestBounds({ bounds: page.bounds, zoom: 14 })).toBe(page.bounds);
    expect(page.bounds.pad).toHaveBeenLastCalledWith(0.35);

    const cached = {
      zoom: 13,
      requestBounds: page.bounds,
      data: samplePayload({ meta: { atlas_capped: false, gtfs_capped: false } })
    };
    expect(viewportOptions.shouldReuse(cached, { zoom: 14, bounds: page.bounds })).toBe(true);
    expect(page.bounds.pad).toHaveBeenLastCalledWith(-0.05);

    cached.data = samplePayload({ meta: { atlas_capped: true } });
    expect(viewportOptions.shouldReuse(cached, { zoom: 14, bounds: page.bounds })).toBe(false);
    expect(viewportOptions.shouldReuse(cached, { zoom: 13, bounds: page.bounds })).toBe(true);
  });

  test('uses the shared zoom banner, hides low-zoom lines, and never says Updating map', async () => {
    const page = installPage();
    const viewportOptions = page.getViewportOptions();
    const status = document.getElementById('routesGtfsStopIdSloidStatus');
    const statusText = document.getElementById('routesGtfsStopIdSloidStatusText');

    window.fetch.mockClear();
    window.fetch.mockImplementation(() => response(samplePayload()));
    await viewportOptions.load({ requestBounds: page.bounds, zoom: 12, signal: {} });
    expect(status.classList.contains('d-none')).toBe(false);
    expect(statusText.textContent).toBe('📍 Zoom in a bit more to see all markers in this area');
    expect(statusText.textContent).not.toContain('Updating');

    window.LineRenderer.drawLine.mockClear();
    viewportOptions.onData(samplePayload(), { zoom: 12, cacheHit: false });
    expect(window.LineRenderer.drawLine).not.toHaveBeenCalled();
    expect(status.classList.contains('d-none')).toBe(false);

    viewportOptions.onData(samplePayload(), { zoom: 13, cacheHit: false });
    expect(window.LineRenderer.drawLine).toHaveBeenCalledTimes(1);
    expect(status.classList.contains('d-none')).toBe(true);

    viewportOptions.onData(samplePayload({ meta: { gtfs_capped: true } }), { zoom: 15, cacheHit: false });
    expect(status.classList.contains('d-none')).toBe(false);
    expect(statusText.textContent).toContain('matched stop’s counterpart');
  });

  test('does not reconcile an unchanged same-zoom cache hit', () => {
    const page = installPage();
    const viewportOptions = page.getViewportOptions();
    const payload = samplePayload();

    viewportOptions.onData(payload, { zoom: 14, cacheHit: false });
    const atlasCalls = page.registries[0].reconcile.mock.calls.length;
    const gtfsCalls = page.registries[1].reconcile.mock.calls.length;

    viewportOptions.onData(payload, { zoom: 14, cacheHit: true });

    expect(page.registries[0].reconcile).toHaveBeenCalledTimes(atlasCalls);
    expect(page.registries[1].reconcile).toHaveBeenCalledTimes(gtfsCalls);
  });

  test('keeps rendered layers on errors and exposes capped and retry states', () => {
    const consoleError = jest.spyOn(console, 'error').mockImplementation(() => {});
    const page = installPage();
    const viewportOptions = page.getViewportOptions();
    const status = document.getElementById('routesGtfsStopIdSloidStatus');
    const statusText = document.getElementById('routesGtfsStopIdSloidStatusText');
    const retry = document.getElementById('routesGtfsStopIdSloidRetry');

    viewportOptions.onData(samplePayload({
      meta: {
        atlas_capped: true,
        gtfs_capped: false,
        atlas_returned: 250
      }
    }), { zoom: 12 });
    const atlasMarker = page.registries[0].entries.get('atlas:ch:1:sloid:1').layer;
    const lineCount = page.layers.lines.layers.length;

    expect(status.classList.contains('d-none')).toBe(false);
    expect(status.dataset.state).toBe('zoom');
    expect(statusText.textContent).toContain('Zoom in a bit more');
    expect(statusText.textContent).toContain('matched stop’s counterpart');

    viewportOptions.onError(new Error('offline'));
    expect(page.registries[0].entries.get('atlas:ch:1:sloid:1').layer).toBe(atlasMarker);
    expect(page.layers.lines.layers).toHaveLength(lineCount);
    expect(status.dataset.state).toBe('error');
    expect(statusText.textContent).toContain('last successful result');
    expect(retry.hidden).toBe(false);

    retry.click();
    expect(page.viewportController.reload).toHaveBeenLastCalledWith({
      force: true,
      reason: 'retry'
    });
    expect(consoleError).toHaveBeenCalledWith(
      'Failed to refresh GTFS stop_id/SLOID map',
      expect.any(Error)
    );
    consoleError.mockRestore();
  });

  test('injects the GTFS popup URL and renderer into the popup controller', async () => {
    const page = installPage();
    expect(window.MapComponents.MapPopupController.create.mock.calls[0][0]).not.toHaveProperty('loadingContent');
    page.getViewportOptions().onData(samplePayload(), { zoom: 12 });
    const atlasBinding = page.popupController.attach.mock.calls.find((call) => call[1].key === 'atlas:ch:1:sloid:1')[1];
    const gtfsBinding = page.popupController.attach.mock.calls.find((call) => call[1].key === 'gtfs:8500:0:1')[1];

    window.fetch.mockClear();
    window.fetch.mockImplementation(() => response({ entity_type: 'atlas' }));
    const atlasPayload = await atlasBinding.load({ signal: { popup: true } });
    const atlasUrl = new URL(window.fetch.mock.calls[0][0], 'https://example.test');
    expect(atlasUrl.searchParams.get('entity_type')).toBe('atlas');
    expect(atlasUrl.searchParams.get('sloid')).toBe('ch:1:sloid:1');
    expect(atlasBinding.render(atlasPayload)).toBe('<p>atlas</p>');

    window.fetch.mockClear();
    window.fetch.mockImplementation(() => response({ entity_type: 'gtfs' }));
    await gtfsBinding.load({ signal: { popup: true } });
    const gtfsUrl = new URL(window.fetch.mock.calls[0][0], 'https://example.test');
    expect(gtfsUrl.searchParams.get('entity_type')).toBe('gtfs');
    expect(gtfsUrl.searchParams.get('stop_id')).toBe('8500:0:1');
  });

  test('searches exact identifiers, focuses all results, and serializes the active search', async () => {
    const page = installPage();
    const targets = [
      { entity_type: 'atlas', identifier: 'ch:1:sloid:92000', lat: 46.5, lon: 7.5 },
      { entity_type: 'gtfs', identifier: '8507000:0:1', lat: 46.5002, lon: 7.5002 }
    ];
    window.fetch.mockImplementation((url) => {
      if (url.startsWith('/search?')) return response({ targets });
      return response(samplePayload());
    });

    const result = await window.RoutesGtfsStopIdSloidMap.search('ch:1:sloid:92000');

    expect(result.status).toBe('found');
    expect(window.RoutesGtfsStopIdSloidMap.getSearch()).toEqual({
      kind: 'sloid',
      value: 'ch:1:sloid:92000',
      targets
    });
    expect(page.map.fitBounds).toHaveBeenCalledWith(
      [[46.5, 7.5], [46.5002, 7.5002]],
      expect.objectContaining({ maxZoom: 16, animate: false })
    );
    expect(document.getElementById('activeFilters').textContent).toContain('SLOID: ch:1:sloid:92000');
    expect(window.RoutesGtfsStopIdSloidMap.getActiveFilterCount()).toBe(1);

    const viewportOptions = page.getViewportOptions();
    const context = { requestBounds: page.bounds, zoom: 12, signal: {} };
    expect(viewportOptions.getRequestIdentity(context)).toBe(
      'mode=overview&limit=1800&filters=&search=search_kind=sloid&search_value=ch%3A1%3Asloid%3A92000'
    );
    window.fetch.mockClear();
    window.fetch.mockImplementation(() => response(samplePayload()));
    await viewportOptions.load(context);
    const requestUrl = new URL(window.fetch.mock.calls[0][0], 'https://example.test');
    expect(requestUrl.searchParams.get('search_kind')).toBe('sloid');
    expect(requestUrl.searchParams.get('search_value')).toBe('ch:1:sloid:92000');

    document.querySelector('.remove-gtfs-identifier-search').click();
    await Promise.resolve();
    expect(window.RoutesGtfsStopIdSloidMap.getSearch()).toBeNull();
    expect(page.viewportController.reload).toHaveBeenLastCalledWith({
      force: true,
      reason: 'identifier-search-clear'
    });
  });

  test.each([
    ['8503000', 'uic', '8503000'],
    ['uic: 8507000', 'uic', '8507000'],
    ['8507000:0:1', 'gtfs_stop_id', '8507000:0:1'],
    ['stop_id: custom-stop', 'gtfs_stop_id', 'custom-stop']
  ])('parses %s as %s and focuses a single result', async (query, kind, value) => {
    const page = installPage();
    window.fetch.mockImplementation((url) => {
      if (url.startsWith('/search?')) {
        return response({ targets: [{ entity_type: 'gtfs', identifier: value, lat: 47, lon: 8 }] });
      }
      return response({});
    });

    await window.RoutesGtfsStopIdSloidMap.search(query);

    const searchUrl = new URL(
      window.fetch.mock.calls.find((call) => call[0].startsWith('/search?'))[0],
      'https://example.test'
    );
    expect(searchUrl.searchParams.get('kind')).toBe(kind);
    expect(searchUrl.searchParams.get('value')).toBe(value);
    expect(page.map.setView).toHaveBeenCalledWith([47, 8], 16, { animate: false });
  });

  test('keeps the current search on a failed replacement and reports the error accessibly', async () => {
    installPage();
    window.fetch.mockImplementation((url) => {
      if (url.startsWith('/search?')) {
        return url.includes('existing')
          ? response({ targets: [{ entity_type: 'gtfs', identifier: 'existing', lat: 47, lon: 8 }] })
          : errorResponse(404, { error: 'Not found' });
      }
      return response({});
    });
    await window.RoutesGtfsStopIdSloidMap.search('stop_id:existing');

    const result = await window.RoutesGtfsStopIdSloidMap.search('stop_id:missing');

    expect(result.status).toBe('error');
    expect(window.RoutesGtfsStopIdSloidMap.getSearch().value).toBe('existing');
    const feedback = document.getElementById('routesGtfsStopIdSloidSearchFeedback');
    expect(feedback.textContent).toContain('No mappable stop');
    expect(document.getElementById('routesGtfsStopIdSloidSearchInput').getAttribute('aria-invalid')).toBe('true');
  });

  test('clear all resets both future domain filters and the identifier search in one reload', async () => {
    const page = installPage();
    window.fetch.mockImplementation((url) => {
      if (url.startsWith('/search?')) {
        return response({
          targets: [{ entity_type: 'gtfs', identifier: 'one', lat: 47, lon: 8 }]
        });
      }
      return response({});
    });
    await window.RoutesGtfsStopIdSloidMap.setFilters({ operator: ['SBB'] });
    await window.RoutesGtfsStopIdSloidMap.search('stop_id:one');
    page.viewportController.invalidate.mockClear();
    page.viewportController.reload.mockClear();

    await window.RoutesGtfsStopIdSloidMap.clearAllFilters();

    expect(window.RoutesGtfsStopIdSloidMap.getFilters()).toEqual({});
    expect(window.RoutesGtfsStopIdSloidMap.getSearch()).toBeNull();
    expect(window.RoutesGtfsStopIdSloidMap.getActiveFilterCount()).toBe(0);
    expect(page.viewportController.invalidate).toHaveBeenCalledTimes(1);
    expect(page.viewportController.reload).toHaveBeenCalledWith({
      force: true,
      reason: 'all-filters-clear'
    });
  });

  test('reports an older search as stale when it is superseded during map focus', async () => {
    const page = installPage();
    let finishFirstFocus;
    let markFirstFocusStarted;
    const firstFocusStarted = new Promise((resolve) => { markFirstFocusStarted = resolve; });
    page.viewportController.reload
      .mockImplementationOnce(() => {
        markFirstFocusStarted();
        return new Promise((resolve) => { finishFirstFocus = resolve; });
      })
      .mockResolvedValue({ status: 'loaded' });
    window.fetch.mockImplementation((url) => {
      if (url.startsWith('/search?')) {
        const value = new URL(url, 'https://example.test').searchParams.get('value');
        return response({
          targets: [{ entity_type: 'gtfs', identifier: value, lat: 47, lon: 8 }]
        });
      }
      return response({});
    });

    const first = window.RoutesGtfsStopIdSloidMap.search('stop_id:first');
    await firstFocusStarted;
    const second = await window.RoutesGtfsStopIdSloidMap.search('stop_id:second');
    finishFirstFocus({ status: 'loaded' });

    expect(second.status).toBe('found');
    expect((await first).status).toBe('stale');
    expect(window.RoutesGtfsStopIdSloidMap.getSearch().value).toBe('second');
  });
});
