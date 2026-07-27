const fs = require('fs');
const path = require('path');

describe('HeaderSummary filter visibility', () => {
  const controllers = [];

  beforeAll(() => {
    const scriptPath = path.join(__dirname, '../../static/js/components/header-summary.js');
    const scriptContent = fs.readFileSync(scriptPath, 'utf8');

    window.eval(scriptContent);
  });

  beforeEach(() => {
    document.body.innerHTML = `
      <div id="headerSummaryInfo">
        <button type="button" id="headerSummaryMobileToggle" aria-expanded="true"></button>
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

  afterEach(() => {
    controllers.splice(0).forEach((controller) => controller.destroy());
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

  test('preserves the existing global API and publishes the shared namespace', () => {
    expect(window.HeaderSummary.getCountText(1)).toBe('1 filter active');
    expect(window.HeaderSummary.getCountText(2)).toBe('2 filters active');
    expect(window.MapComponents.HeaderSummary).toBe(window.HeaderSummary);

    window.HeaderSummary.setCollapsed(true);

    expect(document.getElementById('headerSummaryInfo').classList.contains('header-summary--collapsed')).toBe(true);
    expect(document.getElementById('headerSummaryMobileToggle').getAttribute('aria-expanded')).toBe('false');
  });

  test('binds configurable controls and reports state changes', () => {
    document.body.innerHTML = `
      <section id="customSummary">
        <button id="customMobileToggle" aria-expanded="true"></button>
        <div id="customFiltersRow">
          <button id="customFiltersToggle" aria-expanded="false">
            <span id="customFiltersLabel"></span>
            <i class="header-summary__filters-toggle-icon"></i>
          </button>
          <a id="customClearAll" href="#clear">Clear</a>
        </div>
        <div id="customFiltersPanel" class="d-none"></div>
      </section>
    `;

    const onCollapsedChange = jest.fn();
    const onFiltersExpandedChange = jest.fn();
    const onClearAll = jest.fn();
    const controller = window.HeaderSummary.bind({
      activeFilterCount: 3,
      isMobileViewport: () => true,
      onCollapsedChange,
      onFiltersExpandedChange,
      onClearAll,
      elements: {
        summary: '#customSummary',
        mobileToggle: document.getElementById('customMobileToggle'),
        filtersToggle: '#customFiltersToggle',
        filtersLabel: '#customFiltersLabel',
        clearAll: '#customClearAll',
        filtersPanel: '#customFiltersPanel',
        filtersRow: '#customFiltersRow'
      }
    });
    controllers.push(controller);

    expect(document.getElementById('customFiltersLabel').textContent).toBe('Filters: 3 filters active');
    expect(document.getElementById('customFiltersPanel').classList.contains('d-none')).toBe(true);

    document.getElementById('customFiltersToggle').click();

    expect(controller.getState().filtersExpanded).toBe(true);
    expect(document.getElementById('customFiltersPanel').classList.contains('d-none')).toBe(false);
    expect(onFiltersExpandedChange).toHaveBeenCalledWith(
      true,
      expect.objectContaining({ source: 'filters-toggle', event: expect.any(Event) })
    );

    document.getElementById('customMobileToggle').click();

    expect(document.getElementById('customSummary').classList.contains('header-summary--collapsed')).toBe(true);
    expect(onCollapsedChange).toHaveBeenCalledWith(
      true,
      expect.objectContaining({ source: 'mobile-toggle', event: expect.any(Event) })
    );

    document.getElementById('customClearAll').click();
    expect(onClearAll).toHaveBeenCalledTimes(1);
  });

  test('supports server-rendered filter state without requiring a count', () => {
    const controller = window.HeaderSummary.bind();
    controllers.push(controller);

    document.getElementById('headerSummaryFiltersToggle').click();

    expect(controller.getState().activeFilterCount).toBeNull();
    expect(controller.getState().filtersExpanded).toBe(true);
    expect(document.getElementById('headerSummaryFiltersPanel').classList.contains('d-none')).toBe(false);
  });

  test('ignores mobile collapse clicks outside the configured viewport', () => {
    const onCollapsedChange = jest.fn();
    const controller = window.HeaderSummary.bind({
      isMobileViewport: () => false,
      onCollapsedChange
    });
    controllers.push(controller);

    document.getElementById('headerSummaryMobileToggle').click();

    expect(controller.getState().collapsed).toBe(false);
    expect(onCollapsedChange).not.toHaveBeenCalled();
  });

  test('destroy removes every listener owned by the binding', () => {
    const onCollapsedChange = jest.fn();
    const onFiltersExpandedChange = jest.fn();
    const onClearAll = jest.fn();
    const controller = window.HeaderSummary.bind({
      activeFilterCount: 3,
      isMobileViewport: () => true,
      onCollapsedChange,
      onFiltersExpandedChange,
      onClearAll
    });

    controller.destroy();
    document.getElementById('headerSummaryFiltersToggle').click();
    document.getElementById('headerSummaryMobileToggle').click();
    document.getElementById('clearAllFilters').click();

    expect(controller.getState()).toEqual({
      collapsed: false,
      filtersExpanded: false,
      activeFilterCount: 3
    });
    expect(onCollapsedChange).not.toHaveBeenCalled();
    expect(onFiltersExpandedChange).not.toHaveBeenCalled();
    expect(onClearAll).not.toHaveBeenCalled();
  });
});
