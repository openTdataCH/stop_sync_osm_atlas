const loadBrowserScript = require('./load-browser-script');
const path = require('path');

function createEmptyFilters() {
  return {
    station: [],
    stationTypes: [],
    routeDirections: [],
    stopType: [],
    matchMethods: [],
    atlasOperators: [],
    osmOperators: [],
    matchedOptions: {
      allSelected: true,
      methods: { two_sided_stop: false, reference: false, name: false },
      distanceMatching: {
        allSelected: false, group_distance: false, group_long_distance: false,
        local_ref_distance: false, distance_only_candidate: false, distance_ratio: false
      },
      routeMatching: { allSelected: false, gtfs_shared_route: false, gtfs_shared_direction: false }
    },
    unmatchedOptions: {
      allSelected: true,
      reasons: { noNearbyOSM: false, osmNearby: false }
    },
    transportTypes: [],
    osmEntityTypes: [],
    topN: null,
    showDuplicatesOnly: false,
    osmGroups: []
  };
}

describe('filters active count', () => {
  beforeAll(() => {
    const scriptPath = path.join(__dirname, '../../static/js/pages/filters.js');

    loadBrowserScript(scriptPath);
  });

  beforeEach(() => {
    global.activeFilters = createEmptyFilters();
  });

  test('counts OSM entity filters so the chip panel stays visible', () => {
    activeFilters.osmEntityTypes = ['way'];

    expect(getActiveFilterCount()).toBe(1);
  });

  test('counts route method subfilters using the live routeMatching keys', () => {
    activeFilters.matchedOptions = {
      allSelected: false,
      methods: { two_sided_stop: false, reference: false, name: false },
      distanceMatching: {
        allSelected: false, group_distance: false, group_long_distance: false,
        local_ref_distance: false, distance_only_candidate: false, distance_ratio: false
      },
      routeMatching: { allSelected: false, gtfs_shared_route: true, gtfs_shared_direction: false }
    };

    expect(getActiveFilterCount()).toBe(1);
  });

  test('sends rule keys and match types as the selected match methods', () => {
    activeFilters.matchedOptions = createEmptyFilters().matchedOptions;
    activeFilters.matchedOptions.allSelected = false;
    activeFilters.matchedOptions.methods.reference = true;
    activeFilters.matchedOptions.distanceMatching.local_ref_distance = true;
    activeFilters.matchedOptions.routeMatching.gtfs_shared_direction = true;

    expect(window.getSelectedMatchedMethodFiltersFromState()).toEqual(['reference', 'local_ref_distance', 'gtfs_shared_direction']);
  });
});