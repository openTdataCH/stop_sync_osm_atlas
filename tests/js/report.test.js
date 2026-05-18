const fs = require('fs');
const path = require('path');

function createMiniDollar() {
  return function $(selector) {
    if (selector === document) {
      return {
        ready(callback) {
          if (typeof callback === 'function') {
            callback();
          }
          return this;
        },
        on() {
          return this;
        }
      };
    }

    const element = typeof selector === 'string' ? document.querySelector(selector) : selector;

    return {
      val(value) {
        if (!element) return value === undefined ? undefined : this;
        if (value === undefined) return element.value;
        element.value = value;
        return this;
      },
      is(expr) {
        if (!element) return false;
        if (expr === ':checked') return !!element.checked;
        if (expr === ':disabled') return !!element.disabled;
        return false;
      },
      on() {
        return this;
      },
      prop(name, value) {
        if (!element) return value === undefined ? undefined : this;
        if (value === undefined) return element[name];
        element[name] = value;
        return this;
      },
      text(value) {
        if (!element) return value === undefined ? '' : this;
        if (value === undefined) return element.textContent;
        element.textContent = value;
        return this;
      },
      hide() {
        if (element) element.style.display = 'none';
        return this;
      },
      show() {
        if (element) element.style.display = '';
        return this;
      },
      toggle() {
        return this;
      },
      addClass() {
        return this;
      },
      removeClass() {
        return this;
      },
      css() {
        return this;
      },
      attr() {
        return this;
      },
      find() {
        return this;
      },
      length: element ? 1 : 0,
    };
  };
}

describe('report request params', () => {
  beforeAll(() => {
    global.$ = createMiniDollar();
    global.OperatorDropdown = function () {};

    const scriptPath = path.join(__dirname, '../../static/js/pages/report.js');
    const scriptContent = fs.readFileSync(scriptPath, 'utf8');
    window.eval(scriptContent);
  });

  beforeEach(() => {
    document.body.innerHTML = `
      <input type="radio" name="reportCategory" value="distance" id="categoryDistance">
      <input type="radio" name="reportCategory" value="unmatched" id="categoryUnmatched">
      <input type="radio" name="reportCategory" value="problems" id="categoryProblems" checked>
      <input type="radio" name="limitMode" value="all" id="limitAll" checked>
      <input type="radio" name="limitMode" value="upto" id="limitUpTo">
      <select id="sortOrderModal"><option value="priority_desc" selected>Priority</option></select>
      <select id="reportFormatModal"><option value="csv" selected>CSV</option></select>
      <input type="number" id="reportLimitModal" value="50">
      <input type="checkbox" id="includeAtlasCoords">
      <input type="checkbox" id="includeOsmCoords">
      <input type="checkbox" id="ptypeDistance" checked>
      <input type="checkbox" id="ptypeUnmatched" checked>
      <input type="checkbox" id="ptypeAttributes" checked>
      <input type="checkbox" id="ptypeContradictsRouteMatching" checked>
      <input type="checkbox" id="ptypeDuplicates" checked>
      <input type="checkbox" id="priority1" checked>
      <input type="checkbox" id="priority2" checked>
      <input type="checkbox" id="priority3" checked>
      <button id="cancelReportBtn"></button>
    `;
    window.operatorDropdownReports = null;
  });

  test('includes route contradiction problem type in problems export params', () => {
    const params = window.buildReportRequestParams();

    expect(params.report_type).toBe('problems');
    expect(params.problem_types.split(',')).toEqual([
      'distance',
      'unmatched',
      'attributes',
      'contradicts_route_matching',
      'duplicates'
    ]);
  });
});