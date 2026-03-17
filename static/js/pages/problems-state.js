// problems-state.js - Global state management for the Problem Identification Page

/**
 * ProblemsState - Centralized state management for the problems page
 * Handles all global variables and state mutations
 */
window.ProblemsState = (function () {
    'use strict';

    // Map-related state
    let problemMap = null;
    let osmLayerProblems = null;
    let problemMarkersLayer = null;
    let problemLinesLayer = null;
    let contextMarkersLayer = null;

    // Problem data state
    let allProblems = [];
    let filteredProblems = []; // This will now hold only the currently loaded problems
    let problemsByEntry = {}; // Group problems by entry ID
    let currentEntryProblems = []; // Current entry's problems

    // Navigation state
    let currentProblemIndex = -1;
    let currentEntryProblemIndex = 0; // Index within current entry's problems
    let currentProblem = null; // Store current problem for note saving

    // Filter and pagination state
    let selectedProblemTypes = []; // Current problem type filters
    let selectedAtlasOperators = []; // Current operator filter
    let selectedPriorities = []; // Current priority filters (1 | 2 | 3)
    let currentPage = 1;
    let totalProblems = 0;
    let isLoadingMore = false;

    // UI state
    let showContext = false; // Toggle state for showing context
    let keyboardHintShown = false;
    let keyboardHintTimeout = null;

    // Intersection observer for scroll navigation
    let observer = null;

    // Public API
    return {
        // Map getters/setters
        getProblemMap: () => problemMap,
        setProblemMap: (map) => { problemMap = map; },

        getOsmLayerProblems: () => osmLayerProblems,
        setOsmLayerProblems: (layer) => { osmLayerProblems = layer; },

        getProblemMarkersLayer: () => problemMarkersLayer,
        setProblemMarkersLayer: (layer) => { problemMarkersLayer = layer; },

        getProblemLinesLayer: () => problemLinesLayer,
        setProblemLinesLayer: (layer) => { problemLinesLayer = layer; },

        getContextMarkersLayer: () => contextMarkersLayer,
        setContextMarkersLayer: (layer) => { contextMarkersLayer = layer; },

        // Problem data getters/setters
        getAllProblems: () => allProblems,
        setAllProblems: (problems) => { allProblems = problems; },
        addProblems: (problems) => { allProblems = allProblems.concat(problems); },
        clearAllProblems: () => { allProblems = []; },

        getFilteredProblems: () => filteredProblems,
        setFilteredProblems: (problems) => { filteredProblems = problems; },

        getProblemsByEntry: () => problemsByEntry,
        setProblemsByEntry: (grouped) => { problemsByEntry = grouped; },

        getCurrentEntryProblems: () => currentEntryProblems,
        setCurrentEntryProblems: (problems) => { currentEntryProblems = problems; },

        // Navigation getters/setters
        getCurrentProblemIndex: () => currentProblemIndex,
        setCurrentProblemIndex: (index) => { currentProblemIndex = index; },

        getCurrentEntryProblemIndex: () => currentEntryProblemIndex,
        setCurrentEntryProblemIndex: (index) => { currentEntryProblemIndex = index; },

        getCurrentProblem: () => currentProblem,
        setCurrentProblem: (problem) => { currentProblem = problem; },

        // Filter and pagination getters/setters
        getSelectedProblemTypes: () => selectedProblemTypes,
        setSelectedProblemTypes: (types) => { selectedProblemTypes = Array.isArray(types) ? types : []; },

        getSelectedAtlasOperators: () => selectedAtlasOperators,
        setSelectedAtlasOperators: (operators) => { selectedAtlasOperators = operators; },

        getSelectedPriorities: () => selectedPriorities,
        setSelectedPriorities: (priorities) => { selectedPriorities = Array.isArray(priorities) ? priorities : []; },

        getCurrentPage: () => currentPage,
        setCurrentPage: (page) => { currentPage = page; },

        getTotalProblems: () => totalProblems,
        setTotalProblems: (total) => { totalProblems = total; },

        getIsLoadingMore: () => isLoadingMore,
        setIsLoadingMore: (loading) => { isLoadingMore = loading; },

        // UI state getters/setters
        getShowContext: () => showContext,
        setShowContext: (show) => { showContext = show; },

        getKeyboardHintShown: () => keyboardHintShown,
        setKeyboardHintShown: (shown) => { keyboardHintShown = shown; },

        getKeyboardHintTimeout: () => keyboardHintTimeout,
        setKeyboardHintTimeout: (timeout) => { keyboardHintTimeout = timeout; },

        // Observer getters/setters
        getObserver: () => observer,
        setObserver: (obs) => { observer = obs; },

        // Helper methods
        resetPaginationState: () => {
            allProblems = [];
            currentPage = 1;
            totalProblems = 0;
            currentProblemIndex = -1;
        },

        resetNavigationState: () => {
            currentProblemIndex = -1;
            currentEntryProblemIndex = 0;
            currentProblem = null;
        },

        initializeSettings: () => {
            // Reserved for future page-level settings
        },

        // Get state summary for debugging
        getStateSnapshot: () => ({
            problemsCount: allProblems.length,
            currentProblemIndex,
            currentEntryProblemIndex,
            selectedProblemTypes,
            currentPage,
            totalProblems,
            showContext
        })
    };
})();
