// problems.js - Main JavaScript for the Problem Identification Page

$(document).ready(function () {
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

    function syncInlineClearAllVisibility() {
        const clearBtn = $('#clearAllFilters');
        if (!clearBtn.length) return;
        if (getActiveProblemsFilterCount() > 0) {
            clearBtn.removeClass('d-none');
        } else {
            clearBtn.addClass('d-none');
        }
    }

    function updateSummaryStats() {
        const statsContainer = $('#headerSummaryStats');
        const totalCount = ProblemsState.getTotalProblems() || 0;

        if (!statsContainer.length) return;

        statsContainer.html(
            '<div><i class="fas fa-exclamation-triangle"></i> ' + totalCount + ' problems</div>'
        );
    }

    function updateSummaryFilterLabel() {
        const count = getActiveProblemsFilterCount();
        const label = $('#headerSummaryFiltersLabel');
        const toggle = $('#headerSummaryFiltersToggle');
        const panel = $('#headerSummaryFiltersPanel');
        const row = $('#headerSummaryFiltersRow');
        const icon = toggle.find('.header-summary__filters-toggle-icon');

        if (!label.length || !toggle.length) return;

        if (count === 1) {
            row.removeClass('d-none');
            label.text('Filters: 1 active');
            toggle.prop('disabled', true);
            icon.addClass('d-none');
            panel.removeClass('d-none');
        } else if (count > 1) {
            row.removeClass('d-none');
            label.text('Filters: ' + count + ' active');
            toggle.prop('disabled', false);
            icon.removeClass('d-none');
        } else {
            row.removeClass('d-none');
            label.text('Filters: None (All entries)');
            toggle.prop('disabled', true);
            icon.addClass('d-none');
            panel.addClass('d-none');
        }
    }

    function clearAllProblemFilters() {
        ProblemsState.setSelectedProblemTypes([]);
        ProblemsState.setSelectedPriorities([]);
        ProblemsState.setSelectedAtlasOperators([]);

        if (window.operatorDropdownProblems && window.operatorDropdownProblems.setSelection) {
            window.operatorDropdownProblems.setSelection([]);
        }

        ProblemsState.resetPaginationState();
        ProblemsData.initializeProblemTypeFilter();
        ProblemsData.fetchProblems();
        renderFiltersSummary();
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
                ProblemsState.resetPaginationState();
                ProblemsData.initializeProblemTypeFilter();
                ProblemsData.fetchProblems();
                renderFiltersSummary();
            },
            onRemovePriority: function (priority) {
                const next = (ProblemsState.getSelectedPriorities() || []).filter(p => p !== String(priority));
                ProblemsState.setSelectedPriorities(next);
                ProblemsState.resetPaginationState();
                ProblemsData.initializeProblemTypeFilter();
                ProblemsData.fetchProblems();
                renderFiltersSummary();
            },
            onRemoveOperator: function (op) {
                const next = (ProblemsState.getSelectedAtlasOperators() || []).filter(o => o !== op);
                ProblemsState.setSelectedAtlasOperators(next);
                if (window.operatorDropdownProblems && window.operatorDropdownProblems.setSelection) {
                    window.operatorDropdownProblems.setSelection(next);
                }
                ProblemsState.resetPaginationState();
                ProblemsData.initializeProblemTypeFilter();
                ProblemsData.fetchProblems();
                renderFiltersSummary();
            }
        });
        updateSummaryStats();
        updateSummaryFilterLabel();
        syncInlineClearAllVisibility();
    }

    window.ProblemsPage = {
        renderFiltersSummary
    };

    function bindFilterEvents() {
        $('#mobileFiltersToggleProblems').on('click', function () {
            const overlay = document.querySelector('.top-filters-overlay');
            const currentlyOpen = overlay ? overlay.classList.contains('is-mobile-open') : false;
            const nextOpen = !currentlyOpen;
            if (window.MobileFilters && typeof window.MobileFilters.setMobileFiltersOpen === 'function') {
                window.MobileFilters.setMobileFiltersOpen({
                    overlaySelector: '.top-filters-overlay',
                    toggleId: 'mobileFiltersToggleProblems',
                    isOpen: nextOpen
                });
            }
        });

        $(document).on('click', '#typeFilterMenuProblems .custom-control', function (e) {
            e.stopPropagation();
        });

        $(document).on('change', '.filter-problem-type', function () {
            const type = String($(this).val() || '');
            const isChecked = $(this).is(':checked');
            ProblemsData.updateProblemTypeFilter(type, isChecked);
            renderFiltersSummary();
        });

        $(document).on('click', '#priorityFilterProblems .priority-option', function (e) {
            e.preventDefault();
            const priority = String($(this).data('priority'));
            ProblemsData.updatePriorityFilter(priority);
            renderFiltersSummary();
        });

        $(document).on('click', '#clearAllFilters', function (e) {
            e.preventDefault();
            clearAllProblemFilters();
        });

        $(document).on('click', '#headerSummaryFiltersToggle', function (e) {
            e.preventDefault();
            const panel = $('#headerSummaryFiltersPanel');
            if (!panel.length || $(this).prop('disabled')) return;

            const nextExpanded = panel.hasClass('d-none');
            panel.toggleClass('d-none', !nextExpanded);
            $(this).attr('aria-expanded', nextExpanded ? 'true' : 'false');
        });

    }

    ProblemsState.initializeSettings();
    ProblemsMap.initProblemMap();
    ProblemsUI.setupIntersectionObserver();

    window.operatorDropdownProblems = new OperatorDropdown('#atlasOperatorFilterProblems', {
        placeholder: 'Select operators...',
        multiple: true,
        onSelectionChange: function (selectedOperators) {
            ProblemsState.setSelectedAtlasOperators(selectedOperators);
            ProblemsState.resetPaginationState();
            ProblemsData.initializeProblemTypeFilter();
            ProblemsData.fetchProblems();
            renderFiltersSummary();
        }
    });

    bindFilterEvents();

    ProblemsData.initializeProblemTypeFilter();
    ProblemsData.fetchProblems();
    renderFiltersSummary();

    ProblemsMap.initializeResize();

    setTimeout(() => {
        ProblemsUI.showKeyboardHint();
    }, 2000);

    $(window).on('resize', function () {
        setMainLayoutHeights();
    });

    setTimeout(function () {
        setMainLayoutHeights();
    }, 300);

    $('#prevProblemBtn').on('click', function () {
        const currentIndex = ProblemsState.getCurrentProblemIndex();
        if (currentIndex > 0) {
            ProblemsState.setCurrentProblemIndex(currentIndex - 1);
            ProblemsState.setCurrentEntryProblemIndex(0);
            ProblemsUI.displayProblem(ProblemsState.getCurrentProblemIndex());
            ProblemsUI.updateNavButtons();
        }
    });

    $('#nextProblemBtn').on('click', function () {
        ProblemsData.navigateToNextProblem();
    });

    $('#toggleContextBtn').on('click', ProblemsMap.toggleContext);

    $(document).on('keydown', function (e) {
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
