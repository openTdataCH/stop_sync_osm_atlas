const fs = require('fs');
const path = require('path');

describe('MobileFilters', () => {
  const controllers = [];

  beforeAll(() => {
    const scriptPath = path.join(__dirname, '../../static/js/components/mobile-filters.js');
    const scriptContent = fs.readFileSync(scriptPath, 'utf8');

    window.eval(scriptContent);
  });

  beforeEach(() => {
    document.body.innerHTML = `
      <div class="top-filters-overlay">
        <button id="mobileFiltersToggle" aria-expanded="false">Filters</button>
        <div class="mobile-filters-panel"></div>
      </div>
      <button id="outside">Outside</button>
    `;
  });

  afterEach(() => {
    controllers.splice(0).forEach((controller) => controller.destroy());
  });

  test('preserves the existing setter API', () => {
    window.MobileFilters.setMobileFiltersOpen({
      overlaySelector: '.top-filters-overlay',
      toggleId: 'mobileFiltersToggle',
      isOpen: true
    });

    expect(document.querySelector('.top-filters-overlay').classList.contains('is-mobile-open')).toBe(true);
    expect(document.getElementById('mobileFiltersToggle').getAttribute('aria-expanded')).toBe('true');

    window.MobileFilters.setMobileFiltersOpen({
      overlaySelector: '.top-filters-overlay',
      toggleId: 'mobileFiltersToggle',
      isOpen: false
    });

    expect(document.querySelector('.top-filters-overlay').classList.contains('is-mobile-open')).toBe(false);
    expect(document.getElementById('mobileFiltersToggle').getAttribute('aria-expanded')).toBe('false');
  });

  test('publishes the same component through MapComponents', () => {
    expect(window.MapComponents.MobileFilters).toBe(window.MobileFilters);
  });

  test('binds configurable elements and emits open-state changes', () => {
    const onOpenChange = jest.fn();
    const controller = window.MobileFilters.bind({
      elements: {
        overlay: document.querySelector('.top-filters-overlay'),
        toggle: '#mobileFiltersToggle'
      },
      onOpenChange
    });
    controllers.push(controller);

    document.getElementById('mobileFiltersToggle').click();

    expect(controller.isOpen()).toBe(true);
    expect(document.querySelector('.top-filters-overlay').classList.contains('is-mobile-open')).toBe(true);
    expect(document.getElementById('mobileFiltersToggle').getAttribute('aria-expanded')).toBe('true');
    expect(onOpenChange).toHaveBeenCalledWith(
      true,
      expect.objectContaining({ source: 'toggle', event: expect.any(Event) })
    );

    controller.setOpen(false);

    expect(controller.isOpen()).toBe(false);
    expect(onOpenChange).toHaveBeenLastCalledWith(
      false,
      expect.objectContaining({ source: 'api', event: null })
    );
  });

  test('can close on outside click and Escape without owning summary controls', () => {
    const onOpenChange = jest.fn();
    const controller = window.MobileFilters.bind({
      toggleId: 'mobileFiltersToggle',
      closeOnOutsideClick: true,
      closeOnEscape: true,
      onOpenChange
    });
    controllers.push(controller);

    controller.setOpen(true);
    document.getElementById('outside').click();

    expect(controller.isOpen()).toBe(false);
    expect(onOpenChange).toHaveBeenLastCalledWith(
      false,
      expect.objectContaining({ source: 'outside-click' })
    );

    controller.setOpen(true);
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));

    expect(controller.isOpen()).toBe(false);
    expect(onOpenChange).toHaveBeenLastCalledWith(
      false,
      expect.objectContaining({ source: 'escape' })
    );
  });

  test('destroy removes toggle and document listeners', () => {
    const onOpenChange = jest.fn();
    const controller = window.MobileFilters.bind({
      toggleId: 'mobileFiltersToggle',
      isOpen: true,
      closeOnOutsideClick: true,
      closeOnEscape: true,
      onOpenChange
    });

    controller.destroy();
    document.getElementById('mobileFiltersToggle').click();
    document.getElementById('outside').click();
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));

    expect(controller.isOpen()).toBe(true);
    expect(document.querySelector('.top-filters-overlay').classList.contains('is-mobile-open')).toBe(true);
    expect(onOpenChange).not.toHaveBeenCalled();
  });

  test('fails clearly when the configured pair is incomplete', () => {
    expect(() => window.MobileFilters.bind({
      elements: { overlay: '#missing-overlay', toggle: '#mobileFiltersToggle' }
    })).toThrow('MobileFilters.bind requires an overlay element');

    expect(() => window.MobileFilters.bind({
      elements: { overlay: '.top-filters-overlay', toggle: '#missing-toggle' }
    })).toThrow('MobileFilters.bind requires a toggle element');
  });
});
