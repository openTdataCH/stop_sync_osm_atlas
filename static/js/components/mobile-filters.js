(function (global) {
  'use strict';

  function resolveElement(reference, fallbackSelector) {
    var target = reference == null ? fallbackSelector : reference;
    if (!target) return null;
    if (typeof target === 'string') return document.querySelector(target);
    return target;
  }

  function resolveElements(options) {
    options = options || {};
    var configured = options.elements || {};
    var overlayReference = configured.overlay != null
      ? configured.overlay
      : options.overlay;
    var toggleReference = configured.toggle != null
      ? configured.toggle
      : options.toggle;

    if (overlayReference == null && options.overlaySelector) {
      overlayReference = options.overlaySelector;
    }

    var overlay = resolveElement(overlayReference, '.top-filters-overlay');
    var toggle = resolveElement(toggleReference, null);
    if (!toggle && options.toggleId) {
      toggle = document.getElementById(options.toggleId);
    }

    return {
      overlay: overlay,
      toggle: toggle
    };
  }

  function isMobileViewport() {
    return global.matchMedia('(max-width: 768px)').matches;
  }

  function applyOpenState(elements, isOpen) {
    if (!elements.overlay) return;

    elements.overlay.classList.toggle('is-mobile-open', !!isOpen);
    if (elements.toggle) {
      elements.toggle.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
    }
  }

  function setMobileFiltersOpen(options) {
    options = options || {};
    applyOpenState(resolveElements(options), !!options.isOpen);
  }

  /**
   * Bind one configured mobile-filter overlay/toggle pair.
   *
   * `elements.overlay` and `elements.toggle` may be selectors or elements.
   * `overlaySelector` and `toggleId` remain supported for existing callers.
   * Use `onOpenChange` to coordinate other UI (for example, collapsing a
   * summary when filters open) rather than binding another listener here.
   */
  function bind(options) {
    options = options || {};

    var elements = resolveElements(options);
    if (!elements.overlay) {
      throw new Error('MobileFilters.bind requires an overlay element');
    }
    if (!elements.toggle) {
      throw new Error('MobileFilters.bind requires a toggle element');
    }

    var destroyed = false;
    var open = Object.prototype.hasOwnProperty.call(options, 'isOpen')
      ? !!options.isOpen
      : elements.overlay.classList.contains('is-mobile-open');

    function notify(source, event) {
      if (typeof options.onOpenChange === 'function') {
        options.onOpenChange(open, {
          source: source || 'api',
          event: event || null
        });
      }
    }

    function setOpen(nextOpen, source, event) {
      if (destroyed) return;
      var next = !!nextOpen;
      var changed = open !== next;
      open = next;
      applyOpenState(elements, open);
      if (changed) notify(source, event);
    }

    function toggle(source, event) {
      setOpen(!open, source || 'api', event);
    }

    function handleToggle(event) {
      event.preventDefault();
      toggle('toggle', event);
    }

    function handleOutsideClick(event) {
      if (!open || elements.overlay.contains(event.target) || elements.toggle.contains(event.target)) {
        return;
      }
      setOpen(false, 'outside-click', event);
    }

    function handleKeydown(event) {
      if (open && (event.key === 'Escape' || event.key === 'Esc')) {
        setOpen(false, 'escape', event);
      }
    }

    elements.toggle.addEventListener('click', handleToggle);
    if (options.closeOnOutsideClick) {
      document.addEventListener('click', handleOutsideClick);
    }
    if (options.closeOnEscape) {
      document.addEventListener('keydown', handleKeydown);
    }

    applyOpenState(elements, open);

    return {
      setOpen: setOpen,
      toggle: toggle,
      isOpen: function () {
        return open;
      },
      destroy: function () {
        if (destroyed) return;
        destroyed = true;

        elements.toggle.removeEventListener('click', handleToggle);
        if (options.closeOnOutsideClick) {
          document.removeEventListener('click', handleOutsideClick);
        }
        if (options.closeOnEscape) {
          document.removeEventListener('keydown', handleKeydown);
        }
      }
    };
  }

  var MobileFilters = {
    isMobileViewport: isMobileViewport,
    setMobileFiltersOpen: setMobileFiltersOpen,
    bind: bind
  };

  global.MobileFilters = MobileFilters;
  global.MapComponents = global.MapComponents || {};
  global.MapComponents.MobileFilters = MobileFilters;
})(window);
