// problems-area.js - The Problems page's area filter.
//
// "Area" opens a dialog with a map: two clicks set opposite corners of a
// rectangle (between them it follows the pointer; dragging still moves the
// map). Applying keeps the problems whose ATLAS or OSM position lies inside,
// sent to /api/problems as bbox=west,south,east,north. The Problems map shows
// the area as a dashed outline. See documentation/2.4 Problems Page.md#area.

window.ProblemsArea = (function () {
    'use strict';

    // The area is drawn in the map's navy, dashed once it filters the list.
    const color = () => AppConstants.COLORS.MATCHED;
    const outlineStyle = () => ({ color: color(), weight: 2, dashArray: '6,4', fill: false, interactive: false });
    const drawStyle = () => ({ color: color(), weight: 2, fillOpacity: 0.08, interactive: false });

    let picker = null;   // { modal, map, rectangle, corner, onApply }
    let outline = null;

    // [west, south, east, north], rounded to about one metre.
    function boundsToArea(bounds) {
        const round = value => Math.round(value * 1e5) / 1e5;
        return [bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()].map(round);
    }

    function areaToBounds(area) {
        return L.latLngBounds([area[1], area[0]], [area[3], area[2]]);
    }

    // "west,south,east,north" to an area, or null when it is not one.
    function parseArea(text) {
        const values = String(text || '').split(',').map(Number);
        if (values.length !== 4 || values.some(value => !Number.isFinite(value))) return null;
        const [west, south, east, north] = values;
        const valid = -180 <= west && west < east && east <= 180 && -90 <= south && south < north && north <= 90;
        return valid ? values : null;
    }

    function formatArea(area) {
        return area ? area.join(',') : '';
    }

    function setPending(bounds) {
        picker.pending = bounds;
        document.getElementById('areaApplyBtn').disabled = !bounds;
    }

    function startRectangle(latlng) {
        if (picker.rectangle) picker.rectangle.remove();
        picker.corner = latlng;
        picker.rectangle = L.rectangle(L.latLngBounds(latlng, latlng), drawStyle()).addTo(picker.map);
        setPending(null);
    }

    function finishRectangle(latlng) {
        const bounds = L.latLngBounds(picker.corner, latlng);
        picker.corner = null;
        if (bounds.getWest() === bounds.getEast() || bounds.getSouth() === bounds.getNorth()) {
            picker.rectangle.remove();
            picker.rectangle = null;
            return;
        }
        picker.rectangle.setBounds(bounds);
        setPending(bounds);
    }

    function onMapClick(event) {
        if (picker.corner) finishRectangle(event.latlng);
        else startRectangle(event.latlng);
    }

    function onMouseMove(event) {
        if (picker.corner) picker.rectangle.setBounds(L.latLngBounds(picker.corner, event.latlng));
    }

    function createPicker() {
        const element = document.getElementById('areaModal');
        const map = window.MapComponents.MapCore.create({
            container: 'areaMap',
            view: { center: AppConstants.MAP.DEFAULT_CENTER, zoom: AppConstants.MAP.DEFAULT_ZOOM },
            mapOptions: { maxZoom: AppConstants.MAP.MAX_ZOOM, doubleClickZoom: false },
            baseLayers: () => window.MapShared.createBaseTileLayers(),
            defaultBaseLayer: 'OpenStreetMap'
        }).map;
        picker = { modal: bootstrap.Modal.getOrCreateInstance(element), map, rectangle: null, corner: null, pending: null, onApply: null, view: null };
        map.on('click', onMapClick);
        map.on('mousemove', onMouseMove);
        // The map has its size only once the dialog is shown: set the view then.
        element.addEventListener('shown.bs.modal', () => {
            map.invalidateSize();
            if (picker.rectangle) map.fitBounds(picker.rectangle.getBounds(), { padding: [30, 30] });
            else if (picker.view) map.fitBounds(picker.view);
        });
        document.getElementById('areaApplyBtn').addEventListener('click', () => {
            if (!picker.pending) return;
            picker.modal.hide();
            picker.onApply(boundsToArea(picker.pending));
        });
        document.getElementById('areaRemoveBtn').addEventListener('click', () => {
            picker.modal.hide();
            picker.onApply(null);
        });
    }

    /**
     * Opens the dialog on the current area, or on the given view without one.
     * onApply(area) receives [west, south, east, north], or null to remove it.
     */
    function open(area, view, onApply) {
        if (!picker) createPicker();
        picker.onApply = onApply;
        picker.corner = null;
        if (picker.rectangle) picker.rectangle.remove();
        picker.rectangle = area ? L.rectangle(areaToBounds(area), drawStyle()).addTo(picker.map) : null;
        setPending(area ? areaToBounds(area) : null);
        document.getElementById('areaRemoveBtn').classList.toggle('d-none', !area);
        picker.view = view;
        picker.modal.show();
    }

    // The dashed outline of the area on the Problems map; none without an area.
    function showOutline(map, area) {
        if (outline) outline.remove();
        outline = map && area ? L.rectangle(areaToBounds(area), outlineStyle()).addTo(map) : null;
    }

    return { open, showOutline, parseArea, formatArea, boundsToArea };
})();
