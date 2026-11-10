/**
 * Shareable page URLs.
 *
 * Pages keep what they show in the address bar, so the address bar is always
 * a permalink. Everything is written with history.replaceState, which fires no
 * map or hashchange events: keeping the URL current never reloads data and
 * never adds history entries.
 *
 * Map views follow openstreetmap.org: #map=<zoom>/<lat>/<lon>.
 * See documentation/2.9 Permalinks.md for every page's format.
 */
(function (global) {
    'use strict';

    var HASH_DEBOUNCE_MS = 300;
    var COPIED_FEEDBACK_MS = 1500;
    // Characters left unencoded in query values, as the server's
    // canonical_query_redirect does, so links stay readable and equal.
    var DEFAULT_SAFE = ',:/';

    var copyFeedback = null;  // { button, html, timer } while a button shows "Copied"

    function mapLimits(overrides) {
        var constants = global.AppConstants.MAP || {};
        return Object.assign({
            minZoom: constants.MIN_ZOOM,
            maxZoom: constants.MAX_ZOOM,
            maxBounds: constants.MAX_BOUNDS
        }, overrides || {});
    }

    function isInsideBounds(lat, lon, bounds) {
        if (!bounds) return Math.abs(lat) <= 90 && Math.abs(lon) <= 180;
        var south = Math.min(bounds[0][0], bounds[1][0]);
        var north = Math.max(bounds[0][0], bounds[1][0]);
        var west = Math.min(bounds[0][1], bounds[1][1]);
        var east = Math.max(bounds[0][1], bounds[1][1]);
        return lat >= south && lat <= north && lon >= west && lon <= east;
    }

    // Returns { center, zoom } for a usable #map= hash, or null. Other "&"
    // parts (osm.org adds e.g. &layers=T) are ignored.
    function parseMapHash(hash, limits) {
        limits = mapLimits(limits);
        var match = null;
        String(hash || '').replace(/^#/, '').split('&').some(function (part) {
            match = /^map=(\d{1,2})\/(-?\d{1,3}(?:\.\d+)?)\/(-?\d{1,3}(?:\.\d+)?)$/.exec(part);
            return !!match;
        });
        if (!match) return null;

        var zoom = Number(match[1]);
        var lat = Number(match[2]);
        var lon = Number(match[3]);
        if (zoom < limits.minZoom || zoom > limits.maxZoom) return null;
        if (!isInsideBounds(lat, lon, limits.maxBounds)) return null;
        return { center: [lat, lon], zoom: zoom };
    }

    function formatMapHash(zoom, lat, lon) {
        var round = function (value) { return String(Number(Number(value).toFixed(5))); };
        return '#map=' + Math.round(zoom) + '/' + round(lat) + '/' + round(lon);
    }

    function currentMapHash(map) {
        var center = map.getCenter();
        if (typeof center.wrap === 'function') center = center.wrap();
        return formatMapHash(map.getZoom(), center.lat, center.lng);
    }

    // The starting view: a usable #map= hash, otherwise the page default.
    function initialMapView(defaultView, limits) {
        return parseMapHash(global.location.hash, limits) || defaultView;
    }

    // Python's urlencode(quote_via=quote_plus, safe=...): spaces become "+".
    function encodeValue(value, safe) {
        return encodeURIComponent(String(value))
            .replace(/[!'()*]/g, function (c) { return '%' + c.charCodeAt(0).toString(16).toUpperCase(); })
            .replace(/%20/g, '+')
            .replace(/%([0-9A-F]{2})/g, function (escaped, hex) {
                var character = String.fromCharCode(parseInt(hex, 16));
                return safe.indexOf(character) === -1 ? escaped : character;
            });
    }

    // { key: value } to "key=value&...", in key order, skipping empty values.
    function encodeParams(params, safe) {
        safe = safe == null ? DEFAULT_SAFE : safe;
        return Object.keys(params || {}).filter(function (key) {
            var value = params[key];
            return value !== null && value !== undefined && value !== '';
        }).map(function (key) {
            return encodeValue(key, safe) + '=' + encodeValue(params[key], safe);
        }).join('&');
    }

    function decodeQueryKey(part) {
        var key = part.split('=')[0].replace(/\+/g, ' ');
        try {
            return decodeURIComponent(key);
        } catch (error) {
            return key;
        }
    }

    // Drops removeKeys from a query string and appends an encoded query. The
    // other parameters keep their exact text, so links built elsewhere (such
    // as the Operators page's filter links) survive every rewrite.
    function buildSearch(search, removeKeys, appendQuery) {
        var parts = String(search || '').replace(/^\?/, '').split('&').filter(function (part) {
            return part && (removeKeys || []).indexOf(decodeQueryKey(part)) === -1;
        });
        if (appendQuery) parts.push(appendQuery);
        return parts.length ? '?' + parts.join('&') : '';
    }

    // changes.search / changes.hash: the new text, or undefined to keep it.
    function replaceUrl(changes) {
        var current = global.location;
        var search = changes.search !== undefined ? changes.search : current.search;
        var hash = changes.hash !== undefined ? changes.hash : current.hash;
        if (search === current.search && hash === current.hash) return false;
        global.history.replaceState(global.history.state, '', current.pathname + search + hash);
        return true;
    }

    function pageUrl(search, hash) {
        var current = global.location;
        return current.origin + current.pathname + (search || '') + (hash || '');
    }

    // A stop side and stored id as the main map's stop parameters: ?sloid=
    // or ?osm=node|way/<id>. OSM ways are stored as "way_<id>".
    function stopParams(type, ref) {
        if (!ref) return null;
        if (type === 'atlas') return { sloid: String(ref) };
        if (type !== 'osm') return null;
        var element = /^(way_)?(\d+)$/.exec(String(ref));
        return element ? { osm: (element[1] ? 'way' : 'node') + '/' + element[2] } : null;
    }

    // Keeps the view in #map= while the map moves, and follows a hash edited
    // in the address bar: a link that differs only in its hash does not reload
    // the page. An unusable hash (such as a bare "#" from an href="#" link) is
    // replaced with the current view.
    function bindMapHash(map, limits) {
        var timer = null;

        function write() {
            timer = null;
            replaceUrl({ hash: currentMapHash(map) });
        }

        function schedule() {
            if (timer) clearTimeout(timer);
            timer = setTimeout(write, HASH_DEBOUNCE_MS);
        }

        function follow() {
            var view = parseMapHash(global.location.hash, limits);
            if (view) {
                map.setView(view.center, view.zoom);
            } else {
                replaceUrl({ hash: currentMapHash(map) });
            }
        }

        map.on('moveend', schedule);
        global.addEventListener('hashchange', follow);
        return {
            destroy: function () {
                map.off('moveend', schedule);
                global.removeEventListener('hashchange', follow);
                if (timer) clearTimeout(timer);
                timer = null;
            }
        };
    }

    // Several items (popups, variant panels) can be open at once. The URL names
    // the most recently opened one that is still open, through the given keys.
    function createSelectionTracker(keys) {
        var open = [];  // [{ item, query }], most recently opened last

        function write() {
            var latest = open[open.length - 1];
            replaceUrl({ search: buildSearch(global.location.search, keys, latest ? latest.query : '') });
        }

        return {
            open: function (item, query) {
                open = open.filter(function (entry) { return entry.item !== item; });
                if (!query) return false;
                open.push({ item: item, query: query });
                write();
                return true;
            },
            close: function (item) {
                var remaining = open.filter(function (entry) { return entry.item !== item; });
                if (remaining.length === open.length) return false;
                open = remaining;
                write();
                return true;
            },
            clear: function () {
                open = [];
            }
        };
    }

    // Follows Leaflet popups. queryFor(popup) returns the encoded query that
    // names the popup's item, or null for popups without one (loading, errors).
    function trackPopups(map, keys, queryFor) {
        var tracker = createSelectionTracker(keys);

        function onOpen(event) {
            tracker.open(event.popup, queryFor(event.popup));
        }

        function onClose(event) {
            tracker.close(event.popup);
        }

        map.on('popupopen', onOpen);
        map.on('popupclose', onClose);
        return {
            destroy: function () {
                map.off('popupopen', onOpen);
                map.off('popupclose', onClose);
                tracker.clear();
            }
        };
    }

    // The first "Copy link" button inside a popup: the side it was opened as.
    function popupCopyButton(popup) {
        var element = popup && typeof popup.getElement === 'function' ? popup.getElement() : null;
        return element && element.querySelector ? element.querySelector('.popup-copy-link') : null;
    }

    // Fallback for plain-HTTP deployments, where navigator.clipboard is missing.
    function copyTextWithSelection(text) {
        var field = document.createElement('textarea');
        field.value = text;
        field.setAttribute('readonly', '');
        field.style.position = 'fixed';
        field.style.opacity = '0';
        document.body.appendChild(field);
        field.select();
        var copied = false;
        try {
            copied = document.execCommand('copy');
        } catch (error) { }
        document.body.removeChild(field);
        return copied ? Promise.resolve() : Promise.reject(new Error('Copy command was refused.'));
    }

    function copyText(text) {
        var clipboard = global.navigator && global.navigator.clipboard;
        if (clipboard && typeof clipboard.writeText === 'function') {
            return clipboard.writeText(text).catch(function () {
                return copyTextWithSelection(text);
            });
        }
        return copyTextWithSelection(text);
    }

    function restoreCopyButton() {
        if (!copyFeedback) return;
        clearTimeout(copyFeedback.timer);
        copyFeedback.button.innerHTML = copyFeedback.html;
        copyFeedback.button.classList.remove('is-copied');
        copyFeedback = null;
    }

    function showCopied(button) {
        restoreCopyButton();
        copyFeedback = {
            button: button,
            html: button.innerHTML,
            timer: setTimeout(restoreCopyButton, COPIED_FEEDBACK_MS)
        };
        button.innerHTML = '<i class="fas fa-check" aria-hidden="true"></i> Copied';
        button.classList.add('is-copied');
    }

    // Copies url and confirms on the button; when copying is impossible, shows
    // the link so it can be copied by hand.
    function copyLink(button, url) {
        return copyText(url).then(function () {
            showCopied(button);
            return true;
        }, function () {
            global.SharedUtils.showTemporaryMessage(
                'Could not copy the link. Copy it from here: ' + global.SharedUtils.escapeHtml(url),
                'warning',
                8000
            );
            return false;
        });
    }

    global.Permalinks = Object.freeze({
        HASH_DEBOUNCE_MS: HASH_DEBOUNCE_MS,
        COPIED_FEEDBACK_MS: COPIED_FEEDBACK_MS,
        parseMapHash: parseMapHash,
        formatMapHash: formatMapHash,
        currentMapHash: currentMapHash,
        initialMapView: initialMapView,
        encodeParams: encodeParams,
        buildSearch: buildSearch,
        replaceUrl: replaceUrl,
        pageUrl: pageUrl,
        stopParams: stopParams,
        bindMapHash: bindMapHash,
        createSelectionTracker: createSelectionTracker,
        trackPopups: trackPopups,
        popupCopyButton: popupCopyButton,
        copyText: copyText,
        copyLink: copyLink,
        cancelCopyFeedback: restoreCopyButton
    });
})(window);
