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

  test('escapes quotes in HTML and data attributes so selectors round-trip intact', () => {
    expect(window.SharedUtils.escapeHtml(`<a title="x" data-k='y'>&</a>`))
      .toBe('&lt;a title=&quot;x&quot; data-k=&#39;y&#39;&gt;&amp;&lt;/a&gt;');

    const container = document.createElement('div');
    const selector = '.filter-problem-type[value="distance"]';
    container.innerHTML = window.FilterChipUtils.buildRemovableChip({
      label: 'Problem: "Distance"',
      data: { type: 'problem', target: selector }
    });

    const remove = container.querySelector('.remove-filter');
    expect(remove.dataset.type).toBe('problem');
    expect(remove.dataset.target).toBe(selector);
  });
});
