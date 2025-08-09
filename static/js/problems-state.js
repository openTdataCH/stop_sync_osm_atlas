// problems-state.js - Global state management for the Problem Identification Page

/**
 * ProblemsState - Centralized state management for the problems page
 * Handles all global variables and state mutations
 */
window.ProblemsState = (function() {
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
    let selectedProblemType = 'all'; // Current problem type filter
    let selectedAtlasOperators = []; // Current operator filter
    let selectedPriority = 'all'; // Current priority filter (all | 1 | 2 | 3 | 4 | 5)
    let currentPage = 1;
    let totalProblems = 0;
    let isLoadingMore = false;
    let currentSolutionFilter = 'all';
    let currentSortBy = 'default';
    let currentSortOrder = 'asc';

    // UI state
    let showContext = false; // Toggle state for showing context
    let keyboardHintShown = false;
    let keyboardHintTimeout = null;

    // Auto-persistence state
    let autoPersistEnabled = false;
    let autoPersistNotesEnabled = false;

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
        getSelectedProblemType: () => selectedProblemType,
        setSelectedProblemType: (type) => { selectedProblemType = type; },

        getSelectedAtlasOperators: () => selectedAtlasOperators,
        setSelectedAtlasOperators: (operators) => { selectedAtlasOperators = operators; },

        getSelectedPriority: () => selectedPriority,
        setSelectedPriority: (priority) => { selectedPriority = priority; },

        getCurrentPage: () => currentPage,
        setCurrentPage: (page) => { currentPage = page; },

        getTotalProblems: () => totalProblems,
        setTotalProblems: (total) => { totalProblems = total; },

        getIsLoadingMore: () => isLoadingMore,
        setIsLoadingMore: (loading) => { isLoadingMore = loading; },

        getCurrentSolutionFilter: () => currentSolutionFilter,
        setCurrentSolutionFilter: (filter) => { currentSolutionFilter = filter; },

        getCurrentSortBy: () => currentSortBy,
        setCurrentSortBy: (sortBy) => { currentSortBy = sortBy; },

        getCurrentSortOrder: () => currentSortOrder,
        setCurrentSortOrder: (sortOrder) => { currentSortOrder = sortOrder; },

        // UI state getters/setters
        getShowContext: () => showContext,
        setShowContext: (show) => { showContext = show; },

        getKeyboardHintShown: () => keyboardHintShown,
        setKeyboardHintShown: (shown) => { keyboardHintShown = shown; },

        getKeyboardHintTimeout: () => keyboardHintTimeout,
        setKeyboardHintTimeout: (timeout) => { keyboardHintTimeout = timeout; },

        // Auto-persistence getters/setters
        getAutoPersistEnabled: () => autoPersistEnabled,
        setAutoPersistEnabled: (enabled) => { 
            autoPersistEnabled = enabled;
            localStorage.setItem('autoPersistEnabled', enabled);
        },

        getAutoPersistNotesEnabled: () => autoPersistNotesEnabled,
        setAutoPersistNotesEnabled: (enabled) => { 
            autoPersistNotesEnabled = enabled;
            localStorage.setItem('autoPersistNotesEnabled', enabled);
        },

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
            // Load auto-persist settings from localStorage
            autoPersistEnabled = localStorage.getItem('autoPersistEnabled') === 'true';
            autoPersistNotesEnabled = localStorage.getItem('autoPersistNotesEnabled') === 'true';
        },

        // Get state summary for debugging
        getStateSnapshot: () => ({
            problemsCount: allProblems.length,
            currentProblemIndex,
            currentEntryProblemIndex,
            selectedProblemType,
            currentPage,
            totalProblems,
            showContext,
            autoPersistEnabled,
            autoPersistNotesEnabled
        })
    };
})();
