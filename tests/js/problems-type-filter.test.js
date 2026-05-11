const fs = require('fs');
const path = require('path');

function createMiniDollar() {
  return function $(selector) {
    const element = document.querySelector(selector);
    return {
      text(value) {
        if (!element) return value === undefined ? '' : this;
        if (value === undefined) return element.textContent;
        element.textContent = value;
        return this;
      },
      prop(name, value) {
        if (!element) return value === undefined ? undefined : this;
        if (value === undefined) return element[name];
        element[name] = value;
        return this;
      },
      is(expr) {
        if (!element) return false;
        if (expr === ':checked') return !!element.checked;
        return false;
      }
    };
  };
}

describe('problems type filter sync', () => {
  beforeAll(() => {
    global.$ = createMiniDollar();
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
    const scriptContent = fs.readFileSync(scriptPath, 'utf8');
    window.eval(scriptContent);
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
  });

  test('unchecking one type from the all state expands to the remaining explicit selection', () => {
    const next = window.ProblemsData.computeNextProblemTypeSelection([], 'distance', false);

    expect(next).toEqual([
      'attributes',
      'contradicts_route_matching',
      'duplicates',
      'unmatched'
    ]);
  });

  test('checking the last missing type collapses back to the all state', () => {
    const next = window.ProblemsData.computeNextProblemTypeSelection(
      ['attributes', 'contradicts_route_matching', 'duplicates', 'unmatched'],
      'distance',
      true
    );

    expect(next).toEqual([]);
  });
});
