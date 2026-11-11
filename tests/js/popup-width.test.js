const loadBrowserScript = require('./load-browser-script');
const path = require('path');

describe('stop popup width and position', () => {
  beforeAll(() => {
    window.L = require('leaflet');
    window.AppConstants = global.AppConstants = {
      ...window.AppConstants,
      POPUP: { MIN_WIDTH: 130, WIDTH_PX: 260, RESIZE_MAX_WIDTH_PX: 900 }
    };
    loadBrowserScript(path.join(__dirname, '../../static/js/components/move_popup.js'));
  });

  function popupOnMap(mapWidth, options) {
    const popup = new window.L.DraggablePopup(options);
    popup._map = { getSize: () => ({ x: mapWidth }) };
    popup._contentNode = document.createElement('div');
    popup._contentNode.innerHTML = '<div class="atlas-match"></div>';
    popup._applyDimensions = jest.fn();
    return popup;
  }

  test('opens at the fixed width and keeps it when the layout runs again', () => {
    const popup = popupOnMap(1400);

    popup._applyStopPopupWidth();
    popup._applyStopPopupWidth();
    popup._applyStopPopupWidth();

    expect(popup._currentWidth).toBe(260);
  });

  test('the comparison view has the same width as a single card', () => {
    const popup = popupOnMap(1400);
    popup._contentNode.innerHTML = '<div class="popup-compare"></div>';

    popup._applyStopPopupWidth();

    expect(popup._currentWidth).toBe(260);
  });

  test('a width the user dragged to is kept when the content changes', () => {
    const popup = popupOnMap(1400);
    popup._resizedWidth = 410;

    popup._applyStopPopupWidth();

    expect(popup._currentWidth).toBe(410);
  });

  test('popups without stop content keep the width Leaflet gives them', () => {
    const popup = popupOnMap(1400);
    popup._contentNode.innerHTML = '<p>Note</p>';

    popup._applyStopPopupWidth();

    expect(popup._currentWidth).toBeNull();
  });

  test('a small map narrows it to its share of the map, never below the minimum', () => {
    expect(popupOnMap(300)._calculateStopPopupWidth()).toBe(180);
    expect(popupOnMap(300, { stopPopupMapShare: 0.9 })._calculateStopPopupWidth()).toBe(260);
    expect(popupOnMap(100)._calculateStopPopupWidth()).toBe(130);
  });

  test('a dragged popup keeps its offset from the marker when it is laid out again', () => {
    const popup = popupOnMap(1400);
    popup._container = document.createElement('div');
    Object.defineProperty(popup._container, 'offsetWidth', { value: 268 });
    popup._updateLine = jest.fn();
    popup._ensureDragHandleAtTop = jest.fn();
    popup._repositionCloseButton = jest.fn();
    jest.spyOn(window.L.Popup.prototype, '_updatePosition').mockImplementation(function () {
      this._containerLeft = -Math.round(this._containerWidth / 2);
      this._containerBottom = 20;
      this._container.style.left = `${this._containerLeft}px`;
      this._container.style.bottom = `${this._containerBottom}px`;
    });
    popup._dragOffset = { x: 40, y: -30 };

    popup._updatePosition();

    expect(popup._container.style.left).toBe('-94px');
    expect(popup._container.style.bottom).toBe('50px');
    window.L.Popup.prototype._updatePosition.mockRestore();
  });
});

describe('popup Move handle', () => {
  beforeAll(() => {
    window.L = require('leaflet');
    window.AppConstants = global.AppConstants = {
      ...window.AppConstants,
      POPUP: { MIN_WIDTH: 130, WIDTH_PX: 260, RESIZE_MAX_WIDTH_PX: 900 }
    };
    loadBrowserScript(path.join(__dirname, '../../static/js/components/move_popup.js'));
  });

  test('a closed and reopened popup keeps its Move handle when Leaflet rewrites its content', () => {
    jest.useFakeTimers();
    const container = document.createElement('div');
    document.body.appendChild(container);
    const map = window.L.map(container).setView([47, 8], 15);
    const popup = new window.L.DraggablePopup().setLatLng([47, 8]).setContent('<div class="atlas-match">Stop</div>');
    const handles = () => popup.getElement().querySelectorAll('.popup-drag-handle').length;

    popup.openOn(map);
    jest.advanceTimersByTime(200);
    expect(handles()).toBe(1);

    map.closePopup(popup);
    popup.openOn(map);
    jest.advanceTimersByTime(200);
    // Clicking the marker of an open popup makes Leaflet update it, which rewrites the content.
    popup.update();
    jest.advanceTimersByTime(50);
    expect(handles()).toBe(1);

    map.remove();
    container.remove();
    jest.useRealTimers();
  });

  test('moving an open popup to another marker keeps its view, content and drag offset', () => {
    jest.useFakeTimers();
    const container = document.createElement('div');
    document.body.appendChild(container);
    const map = window.L.map(container).setView([47, 8], 15);
    const popup = new window.L.DraggablePopup().setLatLng([47, 8])
      .setContent('<div class="atlas-match"><div class="card">Card</div></div>');
    popup.openOn(map);
    jest.advanceTimersByTime(200);
    const card = popup.getElement().querySelector('.card');
    card.style.display = 'none'; // as See Matches leaves it
    popup._dragOffset = { x: 40, y: -30 };
    const replacement = window.L.marker([47.001, 8.001]);

    popup.setSource(replacement);

    expect(popup.getElement().querySelector('.card')).toBe(card);
    expect(card.style.display).toBe('none');
    expect(popup._dragOffset).toEqual({ x: 40, y: -30 });
    expect(popup.getLatLng().equals(window.L.latLng(47.001, 8.001))).toBe(true);
    expect(popup._source).toBe(replacement);
    expect(popup.isOpen()).toBe(true);

    map.remove();
    container.remove();
    jest.useRealTimers();
  });
});

describe('popup content', () => {
  beforeAll(() => {
    loadBrowserScript(path.join(__dirname, '../../static/js/components/popup-utils.js'));
    loadBrowserScript(path.join(__dirname, '../../static/js/components/popup-renderer.js'));
  });

  test('coordinates show at most 7 decimals, without trailing zeros', () => {
    const osm = window.PopupRenderer.generatePopupHtml({ stop_type: 'unmatched', osm_node_id: '1', osm_lat: 46.64345852229, osm_lon: 6.9 }, 'osm');
    const atlas = window.PopupRenderer.generatePopupHtml({ sloid: 'ch:1:sloid:1', atlas_lat: '47.123456789', atlas_lon: 8 }, 'atlas');

    expect(osm).toContain('(46.6434585, 6.9)');
    expect(atlas).toContain('(47.1234568, 8)');
  });

  function renderMatches(stop, viewType) {
    const container = document.createElement('div');
    container.innerHTML = window.PopupRenderer.generatePopupHtml(stop, viewType);
    return container;
  }

  function rowValues(page, label) {
    const row = [...page.querySelectorAll('tbody tr')].find(tr => tr.querySelector('th') && tr.querySelector('th').textContent === label);
    return row ? [...row.querySelectorAll('td')].map(td => td.textContent.trim()) : undefined;
  }

  test('a stop with one match compares the fields both sources have, the pair rows spanning both', () => {
    const stop = {
      id: 1, stop_type: 'matched', sloid: 'ch:1:sloid:7000', uic_ref: '8577673',
      atlas_designation_official: 'Vuisternens, forge', atlas_designation: 'A', atlas_business_org_abbr: 'TPF Auto',
      atlas_lat: 46.64345852229, atlas_lon: 6.93968950298,
      osm_node_id: '983850472', osm_name: 'Forge <old>', osm_uic_ref: '8577673', osm_local_ref: 'B', osm_operator: 'TPF',
      osm_network: 'Frimobil', osm_uic_name: 'Vuisternens', osm_public_transport: 'platform',
      osm_lat: 46.6434672, osm_lon: 6.9396533, distance_m: 2.94, match_type: 'uic_reference_one_osm'
    };
    const container = renderMatches(stop, 'atlas');
    const unified = container.querySelector('.popup-unified-view');
    const page = unified.querySelector('.popup-compare');

    expect(container.querySelector('.popup-initial-view').textContent).toContain('See Matches');
    expect(container.querySelector('.popup-initial-view').textContent).not.toContain('See Matches (');
    expect(unified.querySelector('.popup-view-back').textContent).toContain('Close Matches');
    expect(unified.querySelector('.popup-match-picker')).toBeNull();
    expect(unified.querySelector('.atlas-match, .osm-match')).toBeNull();
    expect(rowValues(page, 'Name')).toEqual(['Vuisternens, forge', 'Forge <old>']);
    expect(page.innerHTML).toContain('Forge &lt;old&gt;');
    expect(rowValues(page, 'Operator')).toEqual(['TPF Auto', 'TPF']);
    expect(rowValues(page, 'Coord')[0]).toBe('(46.6434585, 6.9396895)');
    expect(rowValues(page, 'Distance')).toEqual(['2.9 m']);
    expect(rowValues(page, 'Match Type')[0]).toContain('uic_reference_one_osm');
    ['Network', 'UIC Name', 'Type'].forEach(label => expect(rowValues(page, label)).toBeUndefined());
  });

  test('identifiers that differ between ATLAS and OSM are marked', () => {
    const stop = {
      id: 1, stop_type: 'matched', sloid: 'ch:1:sloid:7000', uic_ref: '8500001', atlas_designation: 'A',
      atlas_lat: 46.9, atlas_lon: 7.4, osm_node_id: '1', osm_uic_ref: '8500002', osm_local_ref: 'a',
      osm_lat: 46.9, osm_lon: 7.4
    };
    const rows = [...renderMatches(stop, 'atlas').querySelectorAll('.popup-unified-view tbody tr')];
    const marked = rows.filter(tr => tr.classList.contains('is-different')).map(tr => tr.querySelector('th').textContent);

    expect(marked).toEqual(['UIC Ref']);
  });

  test('routes and tags open one panel at a time, each named by its source', () => {
    const stop = {
      id: 1, stop_type: 'matched', sloid: 'ch:1:sloid:7000', atlas_lat: 46.9, atlas_lon: 7.4,
      routes_atlas: [{ route_id: '92-202-j26-1', route_short_name: '202', direction_id: 0 }],
      osm_node_id: '1', osm_lat: 46.9, osm_lon: 7.4, routes_osm: [], osm_tags: { highway: 'bus_stop' }
    };
    const hasCapability = jest.spyOn(window.SharedUtils, 'hasCapability').mockReturnValue(true);
    const container = renderMatches(stop, 'atlas');
    hasCapability.mockRestore();
    document.body.appendChild(container);
    const tabs = Object.fromEntries([...container.querySelectorAll('.popup-unified-view .popup-details-tab')]
      .map(tab => [tab.textContent.trim(), tab]));
    const panel = tab => document.getElementById(tab.getAttribute('aria-controls'));

    expect(Object.keys(tabs)).toEqual(['GTFS routes', 'OSM routes', 'Tags (1)']);
    expect(tabs['OSM routes'].disabled).toBe(true);

    window.PopupRenderer.toggleMatchDetail(tabs['GTFS routes']);
    expect(panel(tabs['GTFS routes']).hidden).toBe(false);
    expect(panel(tabs['GTFS routes']).dataset.source).toBe('atlas');

    window.PopupRenderer.toggleMatchDetail(tabs['Tags (1)']);
    expect(panel(tabs['GTFS routes']).hidden).toBe(true);
    expect(panel(tabs['Tags (1)']).hidden).toBe(false);

    window.PopupRenderer.toggleMatchDetail(tabs['Tags (1)']);
    expect(panel(tabs['Tags (1)']).hidden).toBe(true);
    container.remove();
  });

  test('an OSM node matched to two ATLAS stops picks the pair by tab, each with its own distance', () => {
    const stop = {
      id: 1, stop_type: 'matched', is_osm_node: true, osm_node_id: '1001103527', osm_name: 'Bahnhof',
      osm_lat: 46.9, osm_lon: 7.4, match_type: 'uic_reference_local_ref',
      atlas_matches: [
        { sloid: 'ch:1:sloid:1:0:1', atlas_designation: 'A', atlas_lat: 46.9, atlas_lon: 7.4, distance_m: 3.2, match_type: 'uic_reference_local_ref' },
        { sloid: 'ch:1:sloid:1:0:2', atlas_lat: 46.9, atlas_lon: 7.4, distance_m: 8.4, match_type: 'distance_only_candidate' }
      ]
    };
    const container = renderMatches(stop, 'osm');
    document.body.appendChild(container);
    const unified = container.querySelector('.popup-unified-view');
    const pages = [...unified.querySelectorAll('.popup-compare')];
    const tabs = [...unified.querySelectorAll('.popup-match-tab')];

    expect(container.querySelector('.popup-initial-view').textContent).toContain('See Matches (2)');
    expect(unified.querySelector('.popup-match-picker').dataset.source).toBe('atlas');
    expect(tabs.map(tab => [...tab.querySelectorAll('span')].map(span => span.textContent))).toEqual([['Platform A', '3.2 m'], ['1:0:2', '8.4 m']]);
    expect(pages.map(page => page.hidden)).toEqual([false, true]);
    expect(rowValues(pages[1], 'Distance')).toEqual(['8.4 m']);
    expect(rowValues(pages[1], 'ID')[0]).toBe('ch:1:sloid:1:0:2');

    window.PopupRenderer.selectMatch(tabs[1]);

    expect(pages.map(page => page.hidden)).toEqual([true, false]);
    expect(tabs.map(tab => tab.getAttribute('aria-selected'))).toEqual(['false', 'true']);
    container.remove();
  });
});
