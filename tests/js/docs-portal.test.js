const loadBrowserScript = require('./load-browser-script');
const path = require('path');

function navLink(slug, number, title, extra = '') {
  const numberHtml = number ? `<span class="docs-nav-number">${number}</span> ` : '';
  return `<a class="docs-nav-link ${extra}" href="/docs/${slug}" data-doc-slug="${slug}">${numberHtml}<span class="docs-nav-title">${title}</span></a>`;
}

function section(key, root, items = []) {
  const toggle = items.length
    ? `<button class="docs-toggle" type="button" aria-expanded="false"><i></i></button>`
    : '';
  const subitems = items.length
    ? `<div class="docs-subitems collapse">${items.map((item) => navLink(...item)).join('')}</div>`
    : '';
  return `<div class="docs-section" data-section="${key}">
      <div class="docs-section-header">${navLink(...root, 'docs-section-link').replace('<a ', `<a data-section-link="${key}" `)}${toggle}</div>
      ${subitems}
    </div>`;
}

function sidebarHtml() {
  return `<nav id="docsSidebar">
    <input id="docsSidebarFilter">
    <div class="docs-collection" id="overview">
      ${section('overview-0', ['intro', '0', 'User guide'], [['working_through_problems', '0.1', 'Working through problems'], ['glossary', '0.4', 'Glossary']])}
    </div>
    <p class="docs-audience-heading" data-audience="For developers">For developers</p>
    <div class="docs-collection" id="engine" data-audience="For developers">
      <div class="docs-collection-heading"><span class="docs-collection-label">Matching engine</span></div>
      ${section('engine-2', ['matching_process', 'E.2', 'Matching process'], [
        ['reference_matching', 'E.2.1', 'Reference matching'],
        ['name_matching', 'E.2.2', 'Name matching'],
      ])}
      ${section('engine-3', ['routes', 'E.3', 'Routes'], [['route_pipeline_data_flow', 'E.3.1', 'Route pipeline data flow']])}
      ${section('engine-extra-changelog', ['engine_changelog', '', 'Matching engine changelog'])}
    </div>
    <p id="docsFilterEmpty" hidden>No pages match.</p>
  </nav>`;
}

const sectionEl = (key) => document.querySelector(`.docs-section[data-section="${key}"]`);
const header = (key) => sectionEl(key).querySelector('.docs-section-header');
const isOpen = (key) => sectionEl(key).querySelector('.docs-subitems').classList.contains('show');
const link = (slug) => document.querySelector(`[data-doc-slug="${slug}"]`);
const stored = () => JSON.parse(localStorage.getItem('docsSidebarExpanded') || '[]');
const visibleSections = () => Array.from(document.querySelectorAll('.docs-section'))
  .filter((el) => !el.hidden).map((el) => el.dataset.section);

describe('DocsPage sidebar', () => {
  let sidebar;
  let input;

  function type(text) {
    input.value = text;
    input.dispatchEvent(new Event('input'));
  }

  function clickToggle(key) {
    sectionEl(key).querySelector('.docs-toggle').dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
  }

  beforeAll(() => {
    loadBrowserScript(path.join(__dirname, '../../static/js/docs/portal.js'));
  });

  beforeEach(() => {
    localStorage.clear();
    document.body.innerHTML = sidebarHtml();
    input = document.getElementById('docsSidebarFilter');
    sidebar = window.DocsPage.createSidebar({
      sidebar: document.getElementById('docsSidebar'),
      input,
      empty: document.getElementById('docsFilterEmpty'),
    });
  });

  afterEach(() => {
    sidebar.destroy();
    document.body.innerHTML = '';
  });

  test('marks the page being read and opens its section', () => {
    sidebar.markActive('reference_matching', 'engine-2');

    const current = Array.from(document.querySelectorAll('[aria-current="page"]'));
    expect(current).toEqual([link('reference_matching')]);
    expect(link('reference_matching').classList).toContain('active');
    expect(header('engine-2').classList).toContain('is-current');
    // Only the page is highlighted, not the section holding it.
    expect(header('engine-2').classList).not.toContain('active');
    expect(isOpen('engine-2')).toBe(true);
    expect(isOpen('engine-3')).toBe(false);
    expect(sectionEl('engine-2').querySelector('.docs-toggle').getAttribute('aria-expanded')).toBe('true');
    expect(stored()).toEqual(['engine-2']);

    // A section's own page highlights the section row.
    sidebar.markActive('routes', 'engine-3');
    expect(header('engine-3').classList).toContain('active');
    expect(header('engine-2').classList).not.toContain('is-current');
    expect(link('reference_matching').hasAttribute('aria-current')).toBe(false);
  });

  test('toggles open and close sections and remember them', () => {
    clickToggle('engine-3');
    expect(isOpen('engine-3')).toBe(true);
    expect(stored()).toEqual(['engine-3']);

    clickToggle('engine-3');
    expect(isOpen('engine-3')).toBe(false);
    expect(stored()).toEqual([]);
  });

  test('following a section page keeps its section open', () => {
    document.addEventListener('click', (event) => event.preventDefault(), { once: true });
    link('routes').click();
    expect(stored()).toEqual(['engine-3']);
  });

  test('the filter shows only matching pages, with their sections open', () => {
    type('  REFERENCE ');

    expect(visibleSections()).toEqual(['engine-2']);
    expect(isOpen('engine-2')).toBe(true);
    expect(link('reference_matching').hidden).toBe(false);
    expect(link('name_matching').hidden).toBe(true);
    expect(document.getElementById('overview').hidden).toBe(true);
    expect(document.getElementById('engine').hidden).toBe(false);
    expect(document.getElementById('docsFilterEmpty').hidden).toBe(true);
  });

  test('the filter matches page numbers', () => {
    type('e.2.2');
    expect(visibleSections()).toEqual(['engine-2']);
    expect(link('name_matching').hidden).toBe(false);
    expect(link('reference_matching').hidden).toBe(true);
  });

  test('a section found by its own title keeps its pages, collapsed', () => {
    type('routes');
    expect(visibleSections()).toEqual(['engine-3']);
    expect(isOpen('engine-3')).toBe(false);
    expect(link('route_pipeline_data_flow').hidden).toBe(false);
  });

  test('the developers heading hides with the collections below it', () => {
    const audience = document.querySelector('.docs-audience-heading');
    type('glossary');
    expect(audience.hidden).toBe(true);
    type('name matching');
    expect(audience.hidden).toBe(false);
  });

  test('without matches the filter says so', () => {
    type('zzz');
    expect(visibleSections()).toEqual([]);
    expect(document.getElementById('engine').hidden).toBe(true);
    expect(document.getElementById('docsFilterEmpty').hidden).toBe(false);
  });

  test('sections opened while filtering are not remembered', () => {
    type('routes');
    clickToggle('engine-3');
    expect(isOpen('engine-3')).toBe(true);
    expect(stored()).toEqual([]);
  });

  test('Escape clears the filter and restores the remembered sections', () => {
    clickToggle('engine-3');
    type('reference');
    expect(isOpen('engine-3')).toBe(false);

    const escape = new KeyboardEvent('keydown', { key: 'Escape', cancelable: true });
    input.dispatchEvent(escape);

    expect(escape.defaultPrevented).toBe(true);
    expect(input.value).toBe('');
    expect(visibleSections()).toHaveLength(4);
    expect(isOpen('engine-3')).toBe(true);
    expect(isOpen('engine-2')).toBe(false);
    expect(link('name_matching').hidden).toBe(false);
    expect(document.getElementById('docsFilterEmpty').hidden).toBe(true);
  });

  test('slash focuses the filter unless the reader is typing elsewhere', () => {
    const slash = () => new KeyboardEvent('keydown', { key: '/', bubbles: true, cancelable: true });

    const fromPage = slash();
    document.body.dispatchEvent(fromPage);
    expect(fromPage.defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(input);

    const other = document.createElement('textarea');
    document.body.appendChild(other);
    other.focus();
    const fromTextarea = slash();
    other.dispatchEvent(fromTextarea);
    expect(fromTextarea.defaultPrevented).toBe(false);
    expect(document.activeElement).toBe(other);

    const withModifier = new KeyboardEvent('keydown', { key: '/', ctrlKey: true, bubbles: true, cancelable: true });
    document.body.dispatchEvent(withModifier);
    expect(document.activeElement).toBe(other);
  });

  test('ignores unreadable stored sections', () => {
    localStorage.setItem('docsSidebarExpanded', '{"not": "a list"}');
    sidebar.markActive('', '');
    expect(visibleSections()).toHaveLength(4);
    expect(isOpen('engine-2')).toBe(false);

    localStorage.setItem('docsSidebarExpanded', 'not json');
    sidebar.markActive('', '');
    expect(isOpen('engine-2')).toBe(false);
  });
});

describe('DocsPage "On this page"', () => {
  let toc;
  let rail;
  let inline;
  let frames;

  function contentHtml(headings) {
    return headings.map(([tag, id, text]) => `<${tag} id="${id}">${text}</${tag}><p>Text</p>`).join('');
  }

  function setup(headings) {
    document.body.innerHTML = `
      <nav id="rail" hidden><ul class="docs-toc-list"></ul></nav>
      <details id="inline" hidden><summary>On this page</summary><ul class="docs-toc-list"></ul></details>
      <div id="content">${contentHtml(headings)}</div>`;
    rail = document.getElementById('rail');
    inline = document.getElementById('inline');
    toc = window.DocsPage.createToc({ content: document.getElementById('content'), containers: [rail, inline] });
  }

  function setTops(tops) {
    for (const [id, top] of Object.entries(tops)) {
      document.getElementById(id).getBoundingClientRect = () => ({ top });
    }
  }

  const entries = (container) => Array.from(container.querySelectorAll('li')).map((item) => [
    item.className, item.querySelector('a').getAttribute('href'), item.textContent,
  ]);
  const current = (container) => Array.from(container.querySelectorAll('a[aria-current="location"]'))
    .map((anchor) => anchor.getAttribute('href'));

  beforeAll(() => {
    loadBrowserScript(path.join(__dirname, '../../static/js/docs/portal.js'));
  });

  beforeEach(() => {
    frames = [];
    jest.spyOn(window, 'requestAnimationFrame').mockImplementation((callback) => frames.push(callback));
    jest.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => {});
  });

  afterEach(() => {
    toc.destroy();
    jest.restoreAllMocks();
    document.body.innerHTML = '';
  });

  test('lists the h2 and h3 sections in both places', () => {
    setup([['h2', 'setup', 'Set <code>up</code>\n  now'], ['h3', 'details', 'Details'], ['h4', 'deep', 'Deep'], ['h2', 'usage', 'Usage']]);
    toc.build();

    for (const container of [rail, inline]) {
      expect(container.hidden).toBe(false);
      expect(entries(container)).toEqual([
        ['docs-toc-item docs-toc-item--h2', '#setup', 'Set up now'],
        ['docs-toc-item docs-toc-item--h3', '#details', 'Details'],
        ['docs-toc-item docs-toc-item--h2', '#usage', 'Usage'],
      ]);
    }
  });

  test('stays hidden for pages with fewer than two sections', () => {
    setup([['h2', 'only', 'Only section'], ['h2', 'empty', ' ']]);
    toc.build();

    expect(rail.hidden).toBe(true);
    expect(inline.hidden).toBe(true);
    expect(entries(rail)).toEqual([]);
  });

  test('marks the last section that has scrolled under the navbar', () => {
    setup([['h2', 'setup', 'Setup'], ['h3', 'details', 'Details'], ['h2', 'usage', 'Usage']]);
    setTops({ setup: -200, details: 50, usage: 400 });
    toc.build();
    expect(current(rail)).toEqual(['#details']);
    expect(current(inline)).toEqual(['#details']);
    expect(rail.querySelector('a[href="#details"]').classList).toContain('active');

    setTops({ setup: 500, details: 700, usage: 900 });
    toc.update();
    expect(current(rail)).toEqual([]);
  });

  test('at the bottom of the page the last section is current', () => {
    setup([['h2', 'setup', 'Setup'], ['h2', 'usage', 'Usage']]);
    setTops({ setup: -50, usage: 600 });
    const body = document.body;
    Object.defineProperty(body, 'scrollTop', { configurable: true, value: 1000 });
    Object.defineProperty(body, 'scrollHeight', { configurable: true, value: 1800 });
    Object.defineProperty(body, 'clientHeight', { configurable: true, value: 800 });
    try {
      toc.build();
      expect(current(rail)).toEqual(['#usage']);
    } finally {
      delete body.scrollTop;
      delete body.scrollHeight;
      delete body.clientHeight;
    }
  });

  test('scrolling the page updates the current section once per frame', () => {
    setup([['h2', 'setup', 'Setup'], ['h2', 'usage', 'Usage']]);
    setTops({ setup: 300, usage: 600 });
    toc.build();
    expect(current(rail)).toEqual([]);

    // The page scrolls inside <body>, whose scroll events do not bubble.
    document.body.dispatchEvent(new Event('scroll'));
    document.body.dispatchEvent(new Event('scroll'));
    window.dispatchEvent(new Event('resize'));
    expect(frames).toHaveLength(1);

    setTops({ setup: 20, usage: 600 });
    frames.shift()();
    expect(current(rail)).toEqual(['#setup']);

    document.body.dispatchEvent(new Event('scroll'));
    expect(frames).toHaveLength(1);
  });

  test('destroy stops listening and cancels a pending frame', () => {
    setup([['h2', 'setup', 'Setup'], ['h2', 'usage', 'Usage']]);
    toc.build();
    document.body.dispatchEvent(new Event('scroll'));
    expect(frames).toHaveLength(1);

    toc.destroy();
    expect(window.cancelAnimationFrame).toHaveBeenCalledTimes(1);
    document.body.dispatchEvent(new Event('scroll'));
    expect(frames).toHaveLength(1);
  });

  test('choosing a section closes the list above the article', () => {
    setup([['h2', 'setup', 'Setup'], ['h2', 'usage', 'Usage']]);
    toc.build();
    inline.open = true;
    const stopNavigation = (event) => event.preventDefault();
    document.addEventListener('click', stopNavigation);
    try {
      inline.querySelector('a[href="#usage"]').click();
      expect(inline.open).toBe(false);
      rail.querySelector('a[href="#usage"]').click();
      expect(rail.hidden).toBe(false);
    } finally {
      document.removeEventListener('click', stopNavigation);
    }
  });
});

describe('DocsPage PDF dialog', () => {
  let dialog;
  let modal;
  let submitted;

  function setup({ withPage = true } = {}) {
    const pageButton = withPage
      ? `<button data-pdf-scope="page" data-page-slug="reference_matching" data-page-section="engine-2"
           data-page-label="E.2.1 Reference matching">Download PDF</button>`
      : '';
    document.body.innerHTML = `
      <header id="docs-page-header">${pageButton}</header>
      <button id="sidebarDownload" data-pdf-scope="all">Download the documentation</button>
      <div id="docsPdfModal">
        <form>
          <label><input type="radio" name="scope" value="page"><span data-pdf-page-label></span></label>
          <label><input type="radio" name="scope" value="all"></label>
          <label><input type="radio" name="scope" value="sections"></label>
          <div data-pdf-sections hidden>
            <input type="checkbox" name="section" value="engine:1" data-section="engine-inputs-1">
            <input type="checkbox" name="section" value="engine:2" data-section="engine-2">
            <input type="checkbox" name="section" value="app:1" data-section="app-1">
          </div>
          <p data-pdf-error hidden>Choose at least one section.</p>
          <button type="submit">Download</button>
        </form>
      </div>`;
    modal = document.getElementById('docsPdfModal');
    submitted = [];
    dialog = window.DocsPage.createPdfDialog({
      modal,
      pageTrigger: '#docs-page-header [data-pdf-scope="page"]',
      onSubmit: (params) => submitted.push(params),
    });
  }

  // Bootstrap's show.bs.modal names the button that opened the dialog.
  function showFrom(trigger) {
    const event = new Event('show.bs.modal');
    event.relatedTarget = trigger;
    modal.dispatchEvent(event);
  }

  const scope = () => modal.querySelector('input[name="scope"]:checked').value;
  const scopeInput = (value) => modal.querySelector(`input[name="scope"][value="${value}"]`);
  const box = (value) => modal.querySelector(`input[name="section"][value="${value}"]`);
  const sectionList = () => modal.querySelector('[data-pdf-sections]');
  const error = () => modal.querySelector('[data-pdf-error]');

  function choose(value) {
    scopeInput(value).checked = true;
    scopeInput(value).dispatchEvent(new Event('change', { bubbles: true }));
  }

  function submit() {
    modal.querySelector('form').dispatchEvent(new Event('submit', { cancelable: true }));
  }

  beforeAll(() => {
    loadBrowserScript(path.join(__dirname, '../../static/js/docs/portal.js'));
  });

  afterEach(() => {
    dialog.destroy();
    document.body.innerHTML = '';
  });

  test('the page header opens it on the page being read', () => {
    setup();
    showFrom(document.querySelector('#docs-page-header button'));

    expect(scope()).toBe('page');
    expect(modal.querySelector('[data-pdf-page-label]').textContent).toBe('E.2.1 Reference matching');
    expect(sectionList().hidden).toBe(true);
    submit();
    expect(submitted).toEqual([{ included_pages: ['reference_matching'], include_cover: false, selected_only: true }]);
  });

  test('the sidebar opens it on the whole documentation', () => {
    setup();
    showFrom(document.getElementById('sidebarDownload'));

    expect(scope()).toBe('all');
    expect(scopeInput('page').disabled).toBe(false);
    submit();
    expect(submitted).toEqual([{ included_sections: null, include_cover: true, selected_only: false }]);
  });

  test('chosen sections start from the section being read', () => {
    setup();
    showFrom(document.getElementById('sidebarDownload'));
    choose('sections');

    expect(sectionList().hidden).toBe(false);
    expect([box('engine:1'), box('engine:2'), box('app:1')].map((input) => input.checked)).toEqual([false, true, false]);
    box('app:1').checked = true;
    submit();
    expect(submitted).toEqual([{ included_sections: ['engine:2', 'app:1'], include_cover: false, selected_only: true }]);
  });

  test('every section is the whole documentation', () => {
    setup();
    showFrom(null);
    choose('sections');
    ['engine:1', 'engine:2', 'app:1'].forEach((value) => { box(value).checked = true; });
    submit();
    expect(submitted).toEqual([{ included_sections: null, include_cover: true, selected_only: false }]);
  });

  test('without a section it says so instead of exporting', () => {
    setup();
    dialog.open('sections');
    box('engine:2').checked = false;
    submit();

    expect(submitted).toEqual([]);
    expect(error().hidden).toBe(false);
    // Changing the choice clears the message.
    box('app:1').checked = true;
    box('app:1').dispatchEvent(new Event('change', { bubbles: true }));
    expect(error().hidden).toBe(true);
  });

  test('without a page only the documentation can be chosen', () => {
    setup({ withPage: false });
    dialog.open('page');

    expect(scope()).toBe('all');
    expect(scopeInput('page').disabled).toBe(true);
    expect(modal.querySelectorAll('input[name="section"]:checked')).toHaveLength(0);
    expect(dialog.selection()).toEqual({ included_sections: null, include_cover: true, selected_only: false });
  });
});
