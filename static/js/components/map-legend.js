// The main map's legend: what the marker colours, rings, letters and lines mean.
// A Leaflet control above the layer switcher. It opens on a first visit on a
// wide screen, then stays as the viewer left it.
// See documentation/2.1 Map Data Loading and Rendering.md#legend.
(function (global) {
    'use strict';

    const STORAGE_KEY = 'mapLegendOpen';

    function readOpen(fallback) {
        try {
            const stored = global.localStorage.getItem(STORAGE_KEY);
            return stored === null ? fallback : stored === '1';
        } catch (error) {
            return fallback;
        }
    }

    function writeOpen(open) {
        try {
            global.localStorage.setItem(STORAGE_KEY, open ? '1' : '0');
        } catch (error) {
            // Private windows may refuse storage; the legend still works.
        }
    }

    function markerSwatch(kind, letter) {
        return '<svg class="map-legend__marker map-legend__marker--' + kind + '" viewBox="0 0 16 16" aria-hidden="true">'
            + '<circle cx="8" cy="8" r="6"/>'
            + (letter ? '<text x="8" y="11">' + letter + '</text>' : '')
            + '</svg>';
    }

    function lineSwatch(kind) {
        return '<svg class="map-legend__line map-legend__line--' + kind + '" viewBox="0 0 24 16" aria-hidden="true">'
            + '<line x1="2" y1="8" x2="22" y2="8"/></svg>';
    }

    function row(swatch, label, note) {
        return '<li class="map-legend__row">' + swatch + '<span>' + label
            + (note ? ' <span class="map-legend__note">' + note + '</span>' : '') + '</span></li>';
    }

    function contentHtml(sourceLabel) {
        const source = SharedUtils.escapeHtml(sourceLabel);
        return '<ul class="map-legend__list">'
            + row(markerSwatch('atlas-matched'), 'Matched ' + source + ' stop')
            + row(markerSwatch('osm-matched'), 'Matched OSM stop')
            + row(markerSwatch('atlas-unmatched'), source + ' stop without OSM match')
            + row(markerSwatch('osm-unmatched'), 'OSM stop without ' + source + ' match')
            + row(markerSwatch('disused', 'U'), 'OSM stop marked disused')
            + '</ul><ul class="map-legend__list">'
            + row(lineSwatch('match'), 'Match', 'zoom 13+')
            + row(lineSwatch('group'), 'Parts of one OSM stop', 'zoom 17+')
            + '</ul>'
            + '<p class="map-legend__letters">From zoom 18 letters mark: <b>D</b> ' + source + ' duplicate, '
            + '<b>P</b> OSM platform, <b>S</b> OSM station, <b>U</b> disused.</p>';
    }

    /**
     * Add the legend to a map.
     * @param {L.Map} map
     * @param {object} options - sourceLabel, position (default 'bottomleft')
     */
    function add(map, options) {
        options = options || {};
        const narrow = global.SharedUtils.isMobileViewport();
        const control = L.control({ position: options.position || 'bottomleft' });

        control.onAdd = function () {
            const container = L.DomUtil.create('div', 'leaflet-control map-legend');
            container.innerHTML = '<button type="button" class="map-legend__toggle" aria-expanded="false" aria-controls="mapLegendBody">'
                + '<i class="fas fa-list-ul" aria-hidden="true"></i> Legend</button>'
                + '<div class="map-legend__body" id="mapLegendBody">' + contentHtml(options.sourceLabel || 'ATLAS') + '</div>';
            L.DomEvent.disableClickPropagation(container);
            L.DomEvent.disableScrollPropagation(container);
            const toggle = container.querySelector('.map-legend__toggle');

            function setOpen(open) {
                container.classList.toggle('is-open', open);
                toggle.setAttribute('aria-expanded', String(open));
            }

            toggle.addEventListener('click', function () {
                const open = !container.classList.contains('is-open');
                setOpen(open);
                writeOpen(open);
            });
            setOpen(readOpen(!narrow));
            return container;
        };
        return control.addTo(map);
    }

    global.MapLegend = Object.freeze({ add: add, contentHtml: contentHtml });
})(window);
