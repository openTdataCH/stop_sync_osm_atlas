const loadBrowserScript = require('./load-browser-script');
const path = require('path');

describe('problems type filter sync', () => {
  beforeAll(() => {
    global.ProblemsState = {
      selectedProblemTypes: [],
      getSelectedProblemTypes() {
        return this.selectedProblemTypes;
      },
      setSelectedProblemTypes(types) {
        this.selectedProblemTypes = Array.isArray(types) ? types : [];
      }
    };

    const scriptPath = path.join(__dirname, '../../static/js/pages/problems-data.js');
    loadBrowserScript(scriptPath);
  });

  beforeEach(() => {
    document.body.innerHTML = `
      <button id="typeFilterButtonProblems"></button>
      <input type="checkbox" id="filterProblemTypeAll" />
      <input type="checkbox" id="filterProblemTypeAttributes" />
      <input type="checkbox" id="filterProblemTypeContradictsRouteMatching" />
      <input type="checkbox" id="filterProblemTypeDistance" />
      <input type="checkbox" id="filterProblemTypeDuplicates" />
      <input type="checkbox" id="filterProblemTypeUnmatched" />
      <input type="checkbox" id="filterProblemTypeDisused" />
      <input type="checkbox" id="filterProblemTypeIdentifier" />
    `;
    ProblemsState.setSelectedProblemTypes([]);
  });

  test('all state checks the master and all problem type checkboxes', () => {
    window.ProblemsData.updateTypeButtonDisplay();

    expect(document.querySelector('#typeFilterButtonProblems').textContent).toBe('Type: All');
    expect(document.querySelector('#filterProblemTypeAll').checked).toBe(true);
    expect(document.querySelector('#filterProblemTypeAttributes').checked).toBe(true);
    expect(document.querySelector('#filterProblemTypeContradictsRouteMatching').checked).toBe(true);
    expect(document.querySelector('#filterProblemTypeDistance').checked).toBe(true);
    expect(document.querySelector('#filterProblemTypeDuplicates').checked).toBe(true);
    expect(document.querySelector('#filterProblemTypeUnmatched').checked).toBe(true);
    expect(document.querySelector('#filterProblemTypeDisused').checked).toBe(true);
    expect(document.querySelector('#filterProblemTypeIdentifier').checked).toBe(true);
  });

  test('unchecking one type from the all state expands to the remaining explicit selection', () => {
    const next = window.ProblemsData.computeNextProblemTypeSelection([], 'distance', false);

    expect(next).toEqual([
      'attributes',
      'contradicts_route_matching',
      'duplicates',
      'unmatched',
      'disused',
      'identifier'
    ]);
  });

  test('checking the last missing type collapses back to the all state', () => {
    const next = window.ProblemsData.computeNextProblemTypeSelection(
      ['attributes', 'contradicts_route_matching', 'duplicates', 'unmatched', 'disused', 'identifier'],
      'distance',
      true
    );

    expect(next).toEqual([]);
  });
});
