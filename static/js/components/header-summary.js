(function (window) {
    'use strict';

    function getCountText(count) {
        return count + ' filter' + (count !== 1 ? 's' : '') + ' active';
    }

    function setCollapsed(collapsed) {
        var summary = document.getElementById('headerSummaryInfo');
        var toggle = document.getElementById('headerSummaryMobileToggle');
        if (!summary || !toggle) return;

        summary.classList.toggle('header-summary--collapsed', !!collapsed);
        toggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    }

    function syncFilters(options) {
        options = options || {};

        var activeFilterCount = options.activeFilterCount || 0;
        var expanded = !!options.expanded;
        var inlineLimit = options.inlineLimit || 2;
        var toggle = document.getElementById('headerSummaryFiltersToggle');
        var label = document.getElementById('headerSummaryFiltersLabel');
        var clearAll = document.getElementById('clearAllFilters');
        var panel = document.getElementById('headerSummaryFiltersPanel');
        var row = document.getElementById('headerSummaryFiltersRow');
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

    window.HeaderSummary = {
        getCountText: getCountText,
        setCollapsed: setCollapsed,
        syncFilters: syncFilters
    };
})(window);