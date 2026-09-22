const loadBrowserScript = require('./load-browser-script');
const path = require('path');

describe('FilterChipUtils', () => {
  beforeAll(() => {
    loadBrowserScript(path.join(__dirname, '../../static/js/shared/utils.js'));
    loadBrowserScript(path.join(__dirname, '../../static/js/components/filter-chip-utils.js'));
  });

  test('supports an accessible label on removable chip actions', () => {
    const container = document.createElement('div');
    container.innerHTML = window.FilterChipUtils.buildRemovableChip({
      label: 'UIC: 8507000',
      removeClass: 'remove-search',
      closeChar: '×',
      removeLabel: 'Clear identifier search'
    });

    const remove = container.querySelector('.remove-search');
    expect(remove.textContent).toBe('×');
    expect(remove.getAttribute('aria-label')).toBe('Clear identifier search');
    expect(remove.getAttribute('title')).toBe('Clear identifier search');
  });
});
