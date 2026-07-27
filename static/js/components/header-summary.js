(function (global) {
    'use strict';

    var DEFAULT_SELECTORS = {
        summary: '#headerSummaryInfo',
        mobileToggle: '#headerSummaryMobileToggle',
        filtersToggle: '#headerSummaryFiltersToggle',
        filtersLabel: '#headerSummaryFiltersLabel',
        clearAll: '#clearAllFilters',
        filtersPanel: '#headerSummaryFiltersPanel',
        filtersRow: '#headerSummaryFiltersRow'
    };

    function hasOwn(object, key) {
        return Object.prototype.hasOwnProperty.call(object, key);
    }

    function resolveElement(reference, fallbackSelector) {
        var target = typeof reference === 'undefined' ? fallbackSelector : reference;
        if (!target) return null;
        if (typeof target === 'string') return document.querySelector(target);
        return target;
    }

    /**
     * Resolve the standard summary elements once so a binding can clean up the
     * exact nodes it subscribed to. Each value may be a selector or an element.
     */
    function resolveElements(overrides) {
        overrides = overrides || {};

        return {
            summary: resolveElement(overrides.summary, DEFAULT_SELECTORS.summary),
            mobileToggle: resolveElement(overrides.mobileToggle, DEFAULT_SELECTORS.mobileToggle),
            filtersToggle: resolveElement(overrides.filtersToggle, DEFAULT_SELECTORS.filtersToggle),
            filtersLabel: resolveElement(overrides.filtersLabel, DEFAULT_SELECTORS.filtersLabel),
            clearAll: resolveElement(overrides.clearAll, DEFAULT_SELECTORS.clearAll),
            filtersPanel: resolveElement(overrides.filtersPanel, DEFAULT_SELECTORS.filtersPanel),
            filtersRow: resolveElement(overrides.filtersRow, DEFAULT_SELECTORS.filtersRow)
        };
    }

    function getCountText(count) {
        return count + ' filter' + (count !== 1 ? 's' : '') + ' active';
    }

    function setCollapsed(collapsed, elementOverrides) {
        var elements = resolveElements(elementOverrides);
        if (!elements.summary || !elements.mobileToggle) return;

        elements.summary.classList.toggle('header-summary--collapsed', !!collapsed);
        elements.mobileToggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    }

    function syncFilters(options) {
        options = options || {};

        var activeFilterCount = Number(options.activeFilterCount) || 0;
        var expanded = !!options.expanded;
        var inlineLimit = options.inlineLimit == null ? 2 : Number(options.inlineLimit);
        var elements = resolveElements(options.elements);
        var toggle = elements.filtersToggle;
        var label = elements.filtersLabel;
        var clearAll = elements.clearAll;
        var panel = elements.filtersPanel;
        var row = elements.filtersRow;
        var icon = toggle ? toggle.querySelector('.header-summary__filters-toggle-icon') : null;

        if (!toggle || !label) return;

        if (activeFilterCount > 0 && activeFilterCount <= inlineLimit) {
            if (row) row.classList.add('d-none');
            if (panel) panel.classList.remove('d-none');
            if (clearAll) clearAll.classList.add('d-none');
            toggle.disabled = true;
            toggle.setAttribute('aria-expanded', 'false');
            if (icon) icon.classList.add('d-none');
            return;
        }

        if (row) row.classList.remove('d-none');

        if (activeFilterCount > 1) {
            label.textContent = 'Filters: ' + getCountText(activeFilterCount);
            toggle.disabled = false;
            toggle.setAttribute('aria-expanded', expanded ? 'true' : 'false');
            if (clearAll) clearAll.classList.remove('d-none');
            if (icon) icon.classList.remove('d-none');
            if (panel) panel.classList.toggle('d-none', !expanded);
            return;
        }

        label.textContent = 'Filters: None (All entries)';
        toggle.disabled = true;
        toggle.setAttribute('aria-expanded', 'false');
        if (clearAll) clearAll.classList.add('d-none');
        if (icon) icon.classList.add('d-none');
        if (panel) panel.classList.add('d-none');
    }

    /**
     * Bind the generic summary controls.
     *
     * `elements` accepts selectors or elements using the keys in
     * `DEFAULT_SELECTORS`. Page-specific filter meaning remains in callbacks.
     * The returned controller owns only the listeners it creates and must be
     * destroyed when its page/widget is removed.
     */
    function bind(options) {
        options = options || {};

        var elements = resolveElements(options.elements);
        var destroyed = false;
        var ownsFilterCount = hasOwn(options, 'activeFilterCount')
            || typeof options.getActiveFilterCount === 'function';
        var state = {
            collapsed: hasOwn(options, 'collapsed')
                ? !!options.collapsed
                : !!(elements.summary && elements.summary.classList.contains('header-summary--collapsed')),
            filtersExpanded: hasOwn(options, 'filtersExpanded')
                ? !!options.filtersExpanded
                : !!(elements.filtersToggle && elements.filtersToggle.getAttribute('aria-expanded') === 'true'),
            activeFilterCount: hasOwn(options, 'activeFilterCount')
                ? Number(options.activeFilterCount) || 0
                : null
        };

        function getActiveFilterCount() {
            if (typeof options.getActiveFilterCount === 'function') {
                return Number(options.getActiveFilterCount()) || 0;
            }
            return state.activeFilterCount == null ? 0 : state.activeFilterCount;
        }

        function applyCollapsed() {
            setCollapsed(state.collapsed, elements);
        }

        function applyFilters() {
            if (ownsFilterCount) {
                state.activeFilterCount = getActiveFilterCount();
                syncFilters({
                    activeFilterCount: state.activeFilterCount,
                    expanded: state.filtersExpanded,
                    inlineLimit: options.inlineLimit,
                    elements: elements
                });
                return;
            }

            // A server-rendered page may only need common toggle wiring and may
            // not expose a client-side count. Preserve its existing label/state.
            if (elements.filtersToggle) {
                elements.filtersToggle.setAttribute('aria-expanded', state.filtersExpanded ? 'true' : 'false');
            }
            if (elements.filtersPanel) {
                elements.filtersPanel.classList.toggle('d-none', !state.filtersExpanded);
            }
        }

        function changeMeta(source, event) {
            return {
                source: source || 'api',
                event: event || null
            };
        }

        function setCollapsedState(collapsed, source, event) {
            if (destroyed) return;
            var next = !!collapsed;
            var changed = state.collapsed !== next;
            state.collapsed = next;
            applyCollapsed();

            if (changed && typeof options.onCollapsedChange === 'function') {
                options.onCollapsedChange(next, changeMeta(source, event));
            }
        }

        function setFiltersExpanded(expanded, source, event) {
            if (destroyed) return;
            var next = !!expanded;
            var changed = state.filtersExpanded !== next;
            state.filtersExpanded = next;
            applyFilters();

            if (changed && typeof options.onFiltersExpandedChange === 'function') {
                options.onFiltersExpandedChange(next, changeMeta(source, event));
            }
        }

        function syncControllerFilters(next) {
            if (destroyed) return;
            next = next || {};

            if (hasOwn(next, 'activeFilterCount')) {
                ownsFilterCount = true;
                state.activeFilterCount = Number(next.activeFilterCount) || 0;
            }
            if (hasOwn(next, 'expanded')) {
                state.filtersExpanded = !!next.expanded;
            }
            applyFilters();
        }

        function handleFiltersToggle(event) {
            if (elements.filtersToggle && elements.filtersToggle.disabled) return;
            event.preventDefault();
            setFiltersExpanded(!state.filtersExpanded, 'filters-toggle', event);
        }

        function handleMobileToggle(event) {
            var isMobile = typeof options.isMobileViewport !== 'function'
                || options.isMobileViewport();
            if (!isMobile) return;

            event.preventDefault();
            setCollapsedState(!state.collapsed, 'mobile-toggle', event);
        }

        function handleClearAll(event) {
            event.preventDefault();
            options.onClearAll(event);
        }

        if (elements.filtersToggle) {
            elements.filtersToggle.addEventListener('click', handleFiltersToggle);
        }
        if (elements.mobileToggle) {
            elements.mobileToggle.addEventListener('click', handleMobileToggle);
        }
        if (elements.clearAll && typeof options.onClearAll === 'function') {
            elements.clearAll.addEventListener('click', handleClearAll);
        }

        if (hasOwn(options, 'collapsed')) applyCollapsed();
        if (ownsFilterCount || hasOwn(options, 'filtersExpanded')) applyFilters();

        return {
            setCollapsed: setCollapsedState,
            setFiltersExpanded: setFiltersExpanded,
            syncFilters: syncControllerFilters,
            getState: function () {
                return {
                    collapsed: state.collapsed,
                    filtersExpanded: state.filtersExpanded,
                    activeFilterCount: ownsFilterCount ? getActiveFilterCount() : null
                };
            },
            destroy: function () {
                if (destroyed) return;
                destroyed = true;

                if (elements.filtersToggle) {
                    elements.filtersToggle.removeEventListener('click', handleFiltersToggle);
                }
                if (elements.mobileToggle) {
                    elements.mobileToggle.removeEventListener('click', handleMobileToggle);
                }
                if (elements.clearAll && typeof options.onClearAll === 'function') {
                    elements.clearAll.removeEventListener('click', handleClearAll);
                }
            }
        };
    }

    var HeaderSummary = {
        getCountText: getCountText,
        setCollapsed: setCollapsed,
        syncFilters: syncFilters,
        bind: bind
    };

    global.HeaderSummary = HeaderSummary;
    global.MapComponents = global.MapComponents || {};
    global.MapComponents.HeaderSummary = HeaderSummary;
})(window);
