(function () {
    'use strict';

    var tabs = document.querySelector('.c-page-tabs--sticky');
    var navbar = document.querySelector('.navbar');
    if (!tabs || !navbar) return;

    function updateOffsets() {
        document.documentElement.style.setProperty('--page-tabs-top', navbar.getBoundingClientRect().height + 'px');
        document.documentElement.style.setProperty('--page-tabs-height', tabs.getBoundingClientRect().height + 'px');
    }

    updateOffsets();
    if (typeof ResizeObserver !== 'undefined') {
        var observer = new ResizeObserver(updateOffsets);
        observer.observe(navbar);
        observer.observe(tabs);
    } else {
        window.addEventListener('resize', updateOffsets);
    }
})();
