/**
 * Colour theme. Loaded in <head> before the stylesheets, so the page is
 * painted in its theme from the start: the stored choice, or the system
 * preference when the choice is "system", sets data-bs-theme on <html>.
 * Controls carrying data-theme-choice switch it; a "themechange" event on
 * the document tells canvases that draw their own colours to redraw.
 */
(function (global) {
    'use strict';

    var STORAGE_KEY = 'theme';
    var CHOICES = ['system', 'light', 'dark'];
    var ICONS = { system: 'fa-adjust', light: 'fa-sun', dark: 'fa-moon' };
    var root = document.documentElement;
    var media = typeof global.matchMedia === 'function' ? global.matchMedia('(prefers-color-scheme: dark)') : null;

    function storedChoice() {
        try {
            var value = global.localStorage.getItem(STORAGE_KEY);
            return CHOICES.indexOf(value) > 0 ? value : 'system';
        } catch (error) {
            return 'system';
        }
    }

    function resolve(choice) {
        if (choice === 'light' || choice === 'dark') return choice;
        return media && media.matches ? 'dark' : 'light';
    }

    function syncControls(choice) {
        document.querySelectorAll('[data-theme-choice]').forEach(function (control) {
            var selected = control.getAttribute('data-theme-choice') === choice;
            control.classList.toggle('active', selected);
            control.setAttribute('aria-checked', selected ? 'true' : 'false');
        });
        document.querySelectorAll('[data-theme-icon]').forEach(function (icon) {
            CHOICES.forEach(function (name) { icon.classList.remove(ICONS[name]); });
            icon.classList.add(ICONS[choice]);
        });
    }

    function apply(choice) {
        var theme = resolve(choice);
        if (root.getAttribute('data-bs-theme') !== theme) {
            root.setAttribute('data-bs-theme', theme);
            document.dispatchEvent(new CustomEvent('themechange', { detail: { theme: theme } }));
        }
        syncControls(choice);
    }

    function choose(choice) {
        var next = CHOICES.indexOf(choice) >= 0 ? choice : 'system';
        try {
            if (next === 'system') global.localStorage.removeItem(STORAGE_KEY);
            else global.localStorage.setItem(STORAGE_KEY, next);
        } catch (error) {
            // Without storage the choice lasts for this page only.
        }
        apply(next);
    }

    apply(storedChoice());

    if (media) {
        var followSystem = function () {
            if (storedChoice() === 'system') apply('system');
        };
        if (typeof media.addEventListener === 'function') media.addEventListener('change', followSystem);
        else if (typeof media.addListener === 'function') media.addListener(followSystem);
    }

    document.addEventListener('click', function (event) {
        var control = event.target.closest && event.target.closest('[data-theme-choice]');
        if (control) choose(control.getAttribute('data-theme-choice'));
    });
    document.addEventListener('DOMContentLoaded', function () { syncControls(storedChoice()); });

    global.Theme = {
        choose: choose,
        choice: storedChoice,
        current: function () { return root.getAttribute('data-bs-theme'); },
        resolve: resolve
    };
})(window);
