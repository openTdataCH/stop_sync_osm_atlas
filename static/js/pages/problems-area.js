// problems-area.js - The Problems page's area filter.
//
// "Area" opens a dialog with a map: two clicks set opposite corners of a
// rectangle (between them it follows the pointer; dragging still moves the
// map). Applying keeps the problems whose ATLAS or OSM position lies inside,
// sent to /api/problems as bbox=west,south,east,north. The Problems map shows
// the area as a dashed outline. "Clear selection" wipes the rectangle; with
// an area already applied, applying nothing then removes it. See
// documentation/2.4 Problems Page.md#area.

window.ProblemsArea = (function () {
    'use strict';

    // The area is drawn in the map's navy, dashed once it filters the list.
    const color = () => AppConstants.COLORS.MATCHED;
    const outlineStyle = () => ({ color: color(), weight: 2, dashArray: '6,4', fill: false, interactive: false });
    const drawStyle = () => ({ color: color(), weight: 2, fillOpacity: 0.08, interactive: false });

    let picker = null;   // { modal, map, rectangle, corner, pending, applied, onApply, view }
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

    // Apply filters by the drawn rectangle; with none, it removes the applied
    // area, and does nothing when there is no area to remove.
    function refreshButtons() {
        const apply = document.getElementById('areaApplyBtn');
        const removing = !picker.pending && !!picker.applied;
        apply.disabled = !picker.pending && !removing;
        apply.textContent = removing ? 'Show all problems' : 'Filter problems in this area';
        document.getElementById('areaClearBtn').disabled = !picker.rectangle;
    }

    function setPending(bounds) {
        picker.pending = bounds;
        refreshButtons();
    }

    function clearSelection() {
        if (picker.rectangle) picker.rectangle.remove();
        picker.rectangle = null;
        picker.corner = null;
        setPending(null);
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
            clearSelection();
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
        picker = { modal: bootstrap.Modal.getOrCreateInstance(element), map, rectangle: null, corner: null, pending: null, applied: null, onApply: null, view: null };
        map.on('click', onMapClick);
        map.on('mousemove', onMouseMove);
        // The map has its size only once the dialog is shown: set the view then.
        element.addEventListener('shown.bs.modal', () => {
            map.invalidateSize();
            if (picker.rectangle) map.fitBounds(picker.rectangle.getBounds(), { padding: [30, 30] });
            else if (picker.view) map.fitBounds(picker.view);
        });
        document.getElementById('areaApplyBtn').addEventListener('click', () => {
            if (!picker.pending && !picker.applied) return;
            picker.modal.hide();
            picker.onApply(picker.pending ? boundsToArea(picker.pending) : null);
        });
        document.getElementById('areaClearBtn').addEventListener('click', clearSelection);
    }

    /**
     * Opens the dialog on the current area, or on the given view without one.
     * onApply(area) receives [west, south, east, north], or null to remove it.
     */
    function open(area, view, onApply) {
        if (!picker) createPicker();
        picker.onApply = onApply;
        picker.applied = area;
        clearSelection();
        if (area) {
            picker.rectangle = L.rectangle(areaToBounds(area), drawStyle()).addTo(picker.map);
            setPending(areaToBounds(area));
        }
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
