const fs = require('fs');
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
      methods: { exact: false, name: false },
      distanceMatching: { allSelected: false, trio: false, stage1: false, stage2: false, stage3a: false, stage3b: false },
      routeMatching: { allSelected: false, tokens: false, direction: false }
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
    const scriptContent = fs.readFileSync(scriptPath, 'utf8');

    window.eval(scriptContent);
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
      methods: { exact: false, name: false },
      distanceMatching: { allSelected: false, trio: false, stage1: false, stage2: false, stage3a: false, stage3b: false },
      routeMatching: { allSelected: false, tokens: true, direction: false }
    };

    expect(getActiveFilterCount()).toBe(1);
  });
});