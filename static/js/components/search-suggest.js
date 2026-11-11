// Suggestions under the map's search box: source stations and OSM elements
// whose name or number matches the typed text, from /api/search/suggest.
// Picking one adds the same search filter as typing its number.
// See documentation/2.2 Filter and search logic.md#names-and-suggestions.
(function (global) {
    'use strict';

    const DEBOUNCE_MS = 150;
    const MIN_LENGTH = 2;

    function fetchSuggestions(query) {
        return SharedUtils.fetchJson('/api/search/suggest', { q: query })
            .then(function (data) {
                return Array.isArray(data.results) ? data.results : [];
            });
    }

    // "ATLAS · 24 platforms", "OSM · no match", "OSM · disused"
    function describe(item) {
        if (item.side === 'osm') return item.stop_type === 'osm_disused' ? 'OSM · disused' : 'OSM · no match';
        const label = SharedUtils.sourceLabel();
        return label + ' · ' + item.stops + (item.stops === 1 ? ' platform' : ' platforms');
    }

    const element = SharedUtils.element;

    function renderItem(item, id, isActive) {
        const option = element('li', 'search-suggestion' + (isActive ? ' is-active' : ''));
        option.id = id;
        option.setAttribute('role', 'option');
        option.setAttribute('aria-selected', String(isActive));
        const main = element('span', 'search-suggestion__main');
        main.appendChild(element('span', 'search-suggestion__name', item.name));
        main.appendChild(element('span', 'search-suggestion__ref', item.ref));
        option.appendChild(main);
        const meta = element('span', 'search-suggestion__meta', describe(item));
        if (item.matched_name) meta.appendChild(element('span', 'search-suggestion__other', 'OSM name: ' + item.matched_name));
        option.appendChild(meta);
        return option;
    }

    /**
     * Attach suggestions to a text input.
     * @param {object} options
     *  - input: the text input
     *  - list: an empty <ul> with an id, shown under the input
     *  - onPick(item): called with the picked suggestion
     *  - preselectFirst(query): whether Enter should pick the first suggestion
     *  - fetch(query): optional, resolves to the suggestions
     */
    function attach(options) {
        const input = options.input;
        const list = options.list;
        const load = options.fetch || fetchSuggestions;
        const preselectFirst = options.preselectFirst || function () { return true; };
        let items = [];
        let active = -1;
        let timer = null;
        let latest = 0;

        input.setAttribute('role', 'combobox');
        input.setAttribute('aria-autocomplete', 'list');
        input.setAttribute('aria-expanded', 'false');
        input.setAttribute('aria-controls', list.id);
        list.setAttribute('role', 'listbox');

        function optionId(index) {
            return list.id + '-' + index;
        }

        function render() {
            list.textContent = '';
            items.forEach(function (item, index) {
                list.appendChild(renderItem(item, optionId(index), index === active));
            });
            const open = items.length > 0;
            list.classList.toggle('d-none', !open);
            input.setAttribute('aria-expanded', String(open));
            if (active >= 0) input.setAttribute('aria-activedescendant', optionId(active));
            else input.removeAttribute('aria-activedescendant');
        }

        function close() {
            clearTimeout(timer);
            latest += 1;  // a response still on its way must not reopen the list
            items = [];
            active = -1;
            render();
        }

        // Resolves to the suggestions, or to null when newer text replaced the query.
        function request(query) {
            clearTimeout(timer);
            latest += 1;
            const id = latest;
            return load(query).then(function (results) {
                if (id !== latest) return null;
                items = results;
                active = results.length > 0 && preselectFirst(query) ? 0 : -1;
                render();
                return results;
            });
        }

        function refresh() {
            const query = input.value.trim();
            if (query.length < MIN_LENGTH) {
                close();
                return;
            }
            if (active >= 0) {
                // The list is for older text: Enter must not pick from it.
                active = -1;
                render();
            }
            clearTimeout(timer);
            timer = setTimeout(function () {
                request(query).catch(close);
            }, DEBOUNCE_MS);
        }

        function pick(index) {
            const item = items[index];
            if (!item) return;
            close();
            options.onPick(item);
        }

        // Returns true when the key was for the list, so the caller skips it.
        function handleKeydown(event) {
            if (items.length === 0 || event.isComposing) return false;
            if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
                event.preventDefault();
                const step = event.key === 'ArrowDown' ? 1 : -1;
                active = active < 0 && step < 0 ? items.length - 1 : (active + step + items.length) % items.length;
                render();
                return true;
            }
            if (event.key === 'Escape') {
                close();
                return true;
            }
            if (event.key === 'Enter' && active >= 0) {
                event.preventDefault();
                pick(active);
                return true;
            }
            return false;
        }

        // mousedown, not click: it comes before the input loses focus.
        list.addEventListener('mousedown', function (event) {
            const option = event.target.closest ? event.target.closest('[role="option"]') : null;
            if (!option) return;
            event.preventDefault();
            pick(Number(option.id.slice(list.id.length + 1)));
        });
        input.addEventListener('input', refresh);
        input.addEventListener('focus', refresh);
        input.addEventListener('blur', function () {
            setTimeout(close, DEBOUNCE_MS);
        });

        return { close: close, request: request, handleKeydown: handleKeydown };
    }

    global.SearchSuggest = { attach: attach, describe: describe, fetchSuggestions: fetchSuggestions };
})(window);
