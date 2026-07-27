// problems.js - Main JavaScript for the Problem Identification Page

$(document).ready(function () {
    var headerSummaryFiltersExpanded = false;
    var headerSummaryCollapsed = false;
    var headerSummaryController = null;
    var mobileFiltersController = null;

    function setMainLayoutHeights() {
        const root = $('.problems-page-root');
        if (root.length === 0) return;
        const viewportH = window.innerHeight || document.documentElement.clientHeight;
        const rootTop = root.offset() ? root.offset().top : 0;
        const desiredHeight = Math.max(300, viewportH - rootTop);
        root.css('height', desiredHeight + 'px');

        setTimeout(() => {
            if (window.ProblemsMap && window.ProblemsMap.invalidateMapSize) {
                try { window.ProblemsMap.invalidateMapSize(); } catch (e) { }
            } else if (typeof L !== 'undefined' && ProblemsState.getProblemMap()) {
                try { ProblemsState.getProblemMap().invalidateSize(); } catch (e) { }
            }
        }, 0);
    }

    function getActiveProblemsFilterCount() {
        return (ProblemsState.getSelectedProblemTypes() || []).length
            + (ProblemsState.getSelectedPriorities() || []).length
            + (ProblemsState.getSelectedAtlasOperators() || []).length;
    }

    function isMobileViewport() {
        if (window.MobileFilters && typeof window.MobileFilters.isMobileViewport === 'function') {
            return window.MobileFilters.isMobileViewport();
        }
        return window.matchMedia('(max-width: 768px)').matches;
    }

    function updateSummaryStats() {
        const statsContainer = $('#headerSummaryStats');
        const totalCount = ProblemsState.getTotalProblems() || 0;

        if (!statsContainer.length) return;

        statsContainer.html(
            '<div><i class="fas fa-exclamation-triangle"></i> ' + totalCount + ' problems</div>'
        );
    }

    function applyHeaderSummaryLayoutState() {
        headerSummaryCollapsed = isMobileViewport();
        if (headerSummaryController) {
            headerSummaryController.setCollapsed(headerSummaryCollapsed, 'viewport');
        }
    }

    function refreshProblemsAfterFilterChange(options = {}) {
        if (options.syncOperatorDropdown && window.operatorDropdownProblems && window.operatorDropdownProblems.setSelection) {
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

        if (window.operatorDropdownProblems && window.operatorDropdownProblems.setSelection) {
            window.operatorDropdownProblems.setSelection([]);
        }

        refreshProblemsAfterFilterChange();
    }

    function renderFiltersSummary() {
        window.FilterChipUtils.renderProblemChips('#activeFilters', {
            problemTypes: ProblemsState.getSelectedProblemTypes(),
            priorities: ProblemsState.getSelectedPriorities(),
            operators: ProblemsState.getSelectedAtlasOperators(),
            onClearAll: clearAllProblemFilters,
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
        $(document).on('change.problemsPage', '.filter-problem-type', function () {
            const type = String($(this).val() || '');
            const isChecked = $(this).is(':checked');
            ProblemsData.updateProblemTypeFilter(type, isChecked);
            renderFiltersSummary();
        });

        $(document).on('click.problemsPage', '#priorityFilterProblems .priority-option', function (e) {
            e.preventDefault();
            const priority = String($(this).data('priority'));
            ProblemsData.updatePriorityFilter(priority);
            renderFiltersSummary();
        });

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
        collapsed: isMobileViewport(),
        isMobileViewport: isMobileViewport,
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
            if (open && isMobileViewport()) {
                headerSummaryCollapsed = true;
                headerSummaryController.setCollapsed(true, 'mobile-filters');
            }
        }
    });

    bindFilterEvents();
    applyHeaderSummaryLayoutState();

    ProblemsData.initializeProblemTypeFilter();
    ProblemsData.fetchProblems();
    renderFiltersSummary();

    ProblemsMap.initializeResize();

    setTimeout(() => {
        ProblemsUI.showKeyboardHint();
    }, 2000);

    $(window).on('resize.problemsPage', function () {
        setMainLayoutHeights();
        applyHeaderSummaryLayoutState();
    });

    window.addEventListener('pagehide', function (event) {
        if (event.persisted) return;
        if (headerSummaryController) headerSummaryController.destroy();
        if (mobileFiltersController) mobileFiltersController.destroy();
        if (window.operatorDropdownProblems && window.operatorDropdownProblems.destroy) {
            window.operatorDropdownProblems.destroy();
        }
        if (window.ProblemsMap) window.ProblemsMap.destroyProblemMap();
        $(document).off('.problemsPage');
        $(window).off('.problemsPage');
        $('#prevProblemBtn, #nextProblemBtn, #toggleContextBtn').off('.problemsPage');
        $('#activeFilters').off('.filterchips');
    }, { once: true });

    setTimeout(function () {
        setMainLayoutHeights();
    }, 300);

    $('#prevProblemBtn').on('click.problemsPage', function () {
        const currentIndex = ProblemsState.getCurrentProblemIndex();
        if (currentIndex > 0) {
            ProblemsState.setCurrentProblemIndex(currentIndex - 1);
            ProblemsState.setCurrentEntryProblemIndex(0);
            ProblemsUI.displayProblem(ProblemsState.getCurrentProblemIndex());
            ProblemsUI.updateNavButtons();
        }
    });

    $('#nextProblemBtn').on('click.problemsPage', function () {
        ProblemsData.navigateToNextProblem();
    });

    $('#toggleContextBtn').on('click.problemsPage', ProblemsMap.toggleContext);

    $(document).on('keydown.problemsPage', function (e) {
        if (!$(e.target).is('input, textarea, select')) {
            ProblemsUI.hideKeyboardHint();

            switch (e.key) {
                case 'ArrowRight':
                case ' ':
                    e.preventDefault();
                    ProblemsData.navigateToNextProblem();
                    break;
                case 'ArrowLeft':
                    e.preventDefault();
                    $('#prevProblemBtn').click();
                    break;
                case 'ArrowUp':
                    e.preventDefault();
                    $('#actionButtonsContent').animate({ scrollTop: '-=150' }, 200);
                    break;
                case 'ArrowDown':
                    e.preventDefault();
                    $('#actionButtonsContent').animate({ scrollTop: '+=150' }, 200);
                    break;
                case '?':
                    e.preventDefault();
                    if ($('#keyboardHint').hasClass('show')) {
                        ProblemsUI.hideKeyboardHint();
                    } else {
                        ProblemsUI.showKeyboardHint();
                    }
                    break;
            }
        }
    });
});
