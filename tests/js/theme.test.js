const loadBrowserScript = require('./load-browser-script');
const path = require('path');

const scriptPath = path.join(__dirname, '../../static/js/shared/theme.js');

function mockSystemTheme(dark) {
  const listeners = [];
  const media = {
    matches: dark,
    addEventListener: (type, listener) => listeners.push(listener),
  };
  window.matchMedia = jest.fn(() => media);
  return {
    change(nextDark) {
      media.matches = nextDark;
      listeners.forEach((listener) => listener());
    },
  };
}

describe('Theme', () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.documentElement.removeAttribute('data-bs-theme');
    document.body.innerHTML = `
      <i data-theme-icon class="fas fa-adjust"></i>
      <button data-theme-choice="system"></button>
      <button data-theme-choice="light"></button>
      <button data-theme-choice="dark"></button>
    `;
  });

  afterEach(() => {
    delete window.matchMedia;
  });

  test('follows the system preference when nothing is stored', () => {
    mockSystemTheme(true);
    loadBrowserScript(scriptPath);

    expect(document.documentElement.getAttribute('data-bs-theme')).toBe('dark');
    expect(window.Theme.choice()).toBe('system');
  });

  test('a stored choice overrides the system preference', () => {
    mockSystemTheme(true);
    window.localStorage.setItem('theme', 'light');
    loadBrowserScript(scriptPath);

    expect(window.Theme.current()).toBe('light');
  });

  test('a theme control stores the choice, applies it and announces the change', () => {
    mockSystemTheme(false);
    loadBrowserScript(scriptPath);
    const changes = [];
    document.addEventListener('themechange', (event) => changes.push(event.detail.theme));

    document.querySelector('[data-theme-choice="dark"]').click();

    expect(window.localStorage.getItem('theme')).toBe('dark');
    expect(window.Theme.current()).toBe('dark');
    expect(changes).toEqual(['dark']);
    expect(document.querySelector('[data-theme-choice="dark"]').getAttribute('aria-checked')).toBe('true');
    expect(document.querySelector('[data-theme-choice="system"]').classList.contains('active')).toBe(false);
    expect(document.querySelector('[data-theme-icon]').className).toBe('fas fa-moon');
  });

  test('choosing system forgets the choice and follows later system changes', () => {
    const system = mockSystemTheme(false);
    window.localStorage.setItem('theme', 'dark');
    loadBrowserScript(scriptPath);

    window.Theme.choose('system');
    expect(window.localStorage.getItem('theme')).toBeNull();
    expect(window.Theme.current()).toBe('light');

    system.change(true);
    expect(window.Theme.current()).toBe('dark');
  });

  test('an unknown stored value or unavailable storage falls back to the system preference', () => {
    mockSystemTheme(false);
    window.localStorage.setItem('theme', 'sepia');
    loadBrowserScript(scriptPath);
    expect(window.Theme.choice()).toBe('system');

    const getItem = jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    expect(window.Theme.choice()).toBe('system');
    expect(window.Theme.resolve('light')).toBe('light');
    getItem.mockRestore();
  });
});
