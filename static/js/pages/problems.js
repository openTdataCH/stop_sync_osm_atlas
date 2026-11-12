// problems.js - Main JavaScript for the Problem Identification Page

document.addEventListener('DOMContentLoaded', function () {
    // Aborting it on pagehide removes the page's listeners.
    const pageListeners = new AbortController();
    const listen = { signal: pageListeners.signal };
    var headerSummaryFiltersExpanded = false;
    var headerSummaryCollapsed = false;
    var headerSummaryController = null;
    var mobileFiltersController = null;

    function setMainLayoutHeights() {
        const root = document.querySelector('.problems-page-root');
        if (!root) return;
        const viewportH = window.innerHeight || document.documentElement.clientHeight;
        const rootTop = root.getBoundingClientRect().top + window.pageYOffset;
        const desiredHeight = Math.max(300, viewportH - rootTop);
        root.style.height = desiredHeight + 'px';

        setTimeout(() => {
            ProblemsMap.invalidateMapSize();
        }, 0);
    }

    function getActiveProblemsFilterCount() {
        return (ProblemsState.getSelectedProblemTypes() || []).length
            + (ProblemsState.getSelectedPriorities() || []).length
            + (ProblemsState.getSelectedAtlasOperators() || []).length
            + (ProblemsState.getArea() ? 1 : 0);
    }

    function updateSummaryStats() {
        const statsContainer = document.getElementById('headerSummaryStats');
        const entries = ProblemsState.getTotalProblems() || 0;
        const problems = ProblemsState.getProblemCount() || 0;
        const types = ProblemsState.getSelectedProblemTypes() || [];
        // The duplicates-only view lists groups; every other view lists stops, each with all its problems.
        const unit = types.length === 1 && types[0] === 'duplicates'
            ? (entries === 1 ? ' group' : ' groups') : (entries === 1 ? ' stop' : ' stops');

        if (!statsContainer) return;

        statsContainer.innerHTML = '<div><i class="fas fa-exclamation-triangle"></i> '
            + SharedUtils.formatCount(problems) + (problems === 1 ? ' problem' : ' problems')
            + (unit.includes('group') ? ' in ' : ' at ') + SharedUtils.formatCount(entries) + unit + '</div>';
    }

    function applyHeaderSummaryLayoutState() {
        headerSummaryCollapsed = SharedUtils.isMobileViewport();
        if (headerSummaryController) {
            headerSummaryController.setCollapsed(headerSummaryCollapsed, 'viewport');
        }
    }

    function refreshProblemsAfterFilterChange(options = {}) {
        if (options.syncOperatorDropdown) {
            window.operatorDropdownProblems.setSelection(ProblemsState.getSelectedAtlasOperators() || []);
        }
        ProblemsState.resetPaginationState();
        ProblemsData.initializeProblemTypeFilter();
        ProblemsData.fetchProblems();
        renderFiltersSummary();
    }

    function clearAllProblemFilters() {
        ProblemsState.setSelectedProblemTypes([]);
        ProblemsState.setSelectedPriorities([]);
        ProblemsState.setSelectedAtlasOperators([]);
        ProblemsState.setArea(null);

        window.operatorDropdownProblems.setSelection([]);

        refreshProblemsAfterFilterChange();
    }

    function renderFiltersSummary() {
        window.FilterChipUtils.renderProblemChips('#activeFilters', {
            problemTypes: ProblemsState.getSelectedProblemTypes(),
            priorities: ProblemsState.getSelectedPriorities(),
            operators: ProblemsState.getSelectedAtlasOperators(),
            area: ProblemsState.getArea(),
            onRemoveArea: function () {
                ProblemsState.setArea(null);
                refreshProblemsAfterFilterChange();
            },
            onRemoveType: function (type) {
                const next = (ProblemsState.getSelectedProblemTypes() || []).filter(t => t !== type);
                ProblemsState.setSelectedProblemTypes(next);
                refreshProblemsAfterFilterChange();
            },
            onRemovePriority: function (priority) {
                const next = (ProblemsState.getSelectedPriorities() || []).filter(p => p !== String(priority));
                ProblemsState.setSelectedPriorities(next);
                refreshProblemsAfterFilterChange();
            },
            onRemoveOperator: function (op) {
                const next = (ProblemsState.getSelectedAtlasOperators() || []).filter(o => o !== op);
                ProblemsState.setSelectedAtlasOperators(next);
                refreshProblemsAfterFilterChange({ syncOperatorDropdown: true });
            }
        });
        updateSummaryStats();
        ProblemsArea.showOutline(ProblemsState.getProblemMap(), ProblemsState.getArea());
        const areaButton = document.getElementById('areaFilterButton');
        if (areaButton) areaButton.classList.toggle('is-active', !!ProblemsState.getArea());
        if (headerSummaryController) {
            headerSummaryController.syncFilters({
                activeFilterCount: getActiveProblemsFilterCount(),
                expanded: headerSummaryFiltersExpanded
            });
        }
    }

    window.ProblemsPage = {
        renderFiltersSummary
    };

    function bindFilterEvents() {
        document.addEventListener('change', function (e) {
            const box = e.target.closest('.filter-problem-type');
            if (!box) return;
            ProblemsData.updateProblemTypeFilter(String(box.value || ''), box.checked);
            renderFiltersSummary();
        }, listen);

        document.addEventListener('click', function (e) {
            const option = e.target.closest('#priorityFilterProblems .priority-option');
            if (!option) return;
            e.preventDefault();
            ProblemsData.updatePriorityFilter(String(option.dataset.priority));
            renderFiltersSummary();
        }, listen);

        const areaButton = document.getElementById('areaFilterButton');
        if (areaButton) areaButton.addEventListener('click', function () {
            const map = ProblemsState.getProblemMap();
            ProblemsArea.open(ProblemsState.getArea(), map ? map.getBounds() : null, function (area) {
                ProblemsState.setArea(area);
                refreshProblemsAfterFilterChange();
            });
        }, listen);
    }

    ProblemsMap.initProblemMap();
    ProblemsUI.setupIntersectionObserver();

    window.operatorDropdownProblems = new OperatorDropdown('#atlasOperatorFilterProblems', {
        placeholder: 'Select operators...',
        multiple: true,
        onSelectionChange: function (selectedOperators) {
            ProblemsState.setSelectedAtlasOperators(selectedOperators);
            refreshProblemsAfterFilterChange();
        }
    });

    headerSummaryController = window.HeaderSummary.bind({
        getActiveFilterCount: getActiveProblemsFilterCount,
        filtersExpanded: headerSummaryFiltersExpanded,
        collapsed: SharedUtils.isMobileViewport(),
        isMobileViewport: SharedUtils.isMobileViewport,
        onFiltersExpandedChange: function (expanded) {
            headerSummaryFiltersExpanded = expanded;
        },
        onCollapsedChange: function (collapsed, meta) {
            headerSummaryCollapsed = collapsed;
            if (meta.source === 'mobile-toggle' && mobileFiltersController) {
                mobileFiltersController.setOpen(false, 'summary-toggle');
            }
        },
        onClearAll: clearAllProblemFilters
    });
    mobileFiltersController = window.MobileFilters.bind({
        elements: {
            overlay: '.top-filters-overlay',
            toggle: '#mobileFiltersToggleProblems'
        },
        isOpen: false,
        closeOnOutsideClick: true,
        closeOnEscape: true,
        onOpenChange: function (open) {
            if (open && SharedUtils.isMobileViewport()) {
                headerSummaryCollapsed = true;
                headerSummaryController.setCollapsed(true, 'mobile-filters');
            }
        }
    });

    bindFilterEvents();
    applyHeaderSummaryLayoutState();

    // A permalink sets the filters and the entry to open (problems-permalink.js).
    const linked = ProblemsPermalink.parse(window.location.search);
    ProblemsState.setSelectedProblemTypes(linked.problemTypes);
    ProblemsState.setSelectedPriorities(linked.priorities);
    ProblemsState.setSelectedAtlasOperators(linked.atlasOperators);
    ProblemsState.setArea(linked.area);
    window.operatorDropdownProblems.setSelection(linked.atlasOperators);

    function warnLinkedStopMissing() {
        const params = new URLSearchParams(window.location.search);
        const named = ['sloid', 'osm'].filter(key => params.has(key))
            .map(key => key + '=' + params.get(key)).join(', ');
        SharedUtils.showTemporaryMessage(
            'No problem found for the linked stop (' + SharedUtils.escapeHtml(named) + ') with these filters. Showing the first entry.',
            'warning',
            6000
        );
    }

    if (linked.invalidStop) warnLinkedStopMissing();
    ProblemsData.initializeProblemTypeFilter();
    ProblemsData.fetchProblems(1, linked.focus ? { focus: linked.focus, onFocusMissing: warnLinkedStopMissing } : {});
    renderFiltersSummary();

    ProblemsMap.initializeResize();

    setTimeout(() => {
        ProblemsUI.showKeyboardHint();
    }, 2000);

    window.addEventListener('resize', function () {
        setMainLayoutHeights();
        applyHeaderSummaryLayoutState();
    }, listen);

    window.addEventListener('pagehide', function (event) {
        if (event.persisted) return;
        if (headerSummaryController) headerSummaryController.destroy();
        if (mobileFiltersController) mobileFiltersController.destroy();
        window.operatorDropdownProblems.destroy();
        ProblemsMap.destroyProblemMap();
        pageListeners.abort();
        Permalinks.cancelCopyFeedback();
    }, { once: true });

    setTimeout(function () {
        setMainLayoutHeights();
    }, 300);

    function onClick(id, handler) {
        const button = document.getElementById(id);
        if (button) button.addEventListener('click', handler, listen);
    }

    onClick('prevProblemBtn', function () {
        ProblemsData.navigateToPreviousProblem();
    });

    onClick('copyProblemLinkBtn', function () {
        ProblemsPermalink.copyCurrentLink(this);
    });

    onClick('nextProblemBtn', function () {
        ProblemsData.navigateToNextProblem();
    });

    onClick('toggleContextBtn', ProblemsMap.toggleContext);

    function scrollProblemContent(delta) {
        const content = document.getElementById('actionButtonsContent');
        if (content) content.scrollTop += delta;
    }

    document.addEventListener('keydown', function (e) {
        if (!(e.target.matches && e.target.matches('input, textarea, select'))) {
            ProblemsUI.hideKeyboardHint();

            switch (e.key) {
                case 'ArrowRight':
                case ' ':
                    e.preventDefault();
                    ProblemsData.navigateToNextProblem();
                    break;
                case 'ArrowLeft':
                    e.preventDefault();
                    ProblemsData.navigateToPreviousProblem();
                    break;
                case 'ArrowUp':
                    e.preventDefault();
                    scrollProblemContent(-150);
                    break;
                case 'ArrowDown':
                    e.preventDefault();
                    scrollProblemContent(150);
                    break;
                case '?':
                    e.preventDefault();
                    if (document.getElementById('keyboardHint').classList.contains('show')) {
                        ProblemsUI.hideKeyboardHint();
                    } else {
                        ProblemsUI.showKeyboardHint();
                    }
                    break;
            }
        }
    }, listen);
});
