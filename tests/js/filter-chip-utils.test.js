const fs = require('fs');
const path = require('path');

describe('FilterChipUtils', () => {
  beforeAll(() => {
    window.eval(fs.readFileSync(path.join(__dirname, '../../static/js/shared/utils.js'), 'utf8'));
    window.eval(fs.readFileSync(path.join(__dirname, '../../static/js/components/filter-chip-utils.js'), 'utf8'));
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
