(function (global) {
  'use strict';

  function isMobileViewport() {
    return window.matchMedia('(max-width: 768px)').matches;
  }

  function setMobileFiltersOpen(options) {
    options = options || {};
    var overlaySelector = options.overlaySelector || '.top-filters-overlay';
    var toggleId = options.toggleId;
    var isOpen = !!options.isOpen;

    var overlay = document.querySelector(overlaySelector);
    var toggle = toggleId ? document.getElementById(toggleId) : null;

    if (!overlay) return;

    overlay.classList.toggle('is-mobile-open', isOpen);
    if (toggle) {
      toggle.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
    }
  }

  global.MobileFilters = {
    isMobileViewport: isMobileViewport,
    setMobileFiltersOpen: setMobileFiltersOpen
  };
})(window);
