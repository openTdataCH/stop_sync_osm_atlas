const fs = require('fs');
const path = require('path');

describe('HeaderSummary filter visibility', () => {
  beforeAll(() => {
    const scriptPath = path.join(__dirname, '../../static/js/components/header-summary.js');
    const scriptContent = fs.readFileSync(scriptPath, 'utf8');

    window.eval(scriptContent);
  });

  beforeEach(() => {
    document.body.innerHTML = `
      <div id="headerSummaryInfo">
        <button type="button" id="headerSummaryFiltersToggle">
          <span id="headerSummaryFiltersLabel">Filters: None (All entries)</span>
          <i class="header-summary__filters-toggle-icon"></i>
        </button>
        <a href="#" id="clearAllFilters"></a>
        <div id="headerSummaryFiltersRow"></div>
        <div id="headerSummaryFiltersPanel" class="d-none"></div>
      </div>
    `;
  });

  test('shows the chip panel inline for a single active filter', () => {
    window.HeaderSummary.syncFilters({ activeFilterCount: 1 });

    expect(document.getElementById('headerSummaryFiltersRow').classList.contains('d-none')).toBe(true);
    expect(document.getElementById('headerSummaryFiltersPanel').classList.contains('d-none')).toBe(false);
    expect(document.getElementById('headerSummaryFiltersToggle').disabled).toBe(true);
  });

  test('hides the chip panel when there are no active filters', () => {
    window.HeaderSummary.syncFilters({ activeFilterCount: 0 });

    expect(document.getElementById('headerSummaryFiltersLabel').textContent).toBe('Filters: None (All entries)');
    expect(document.getElementById('headerSummaryFiltersPanel').classList.contains('d-none')).toBe(true);
    expect(document.getElementById('headerSummaryFiltersToggle').disabled).toBe(true);
  });
});