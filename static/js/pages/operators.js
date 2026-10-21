(function () {
  'use strict';

  // Rows and bar segments share one order, so a row highlights the segment at its own index.
  document.querySelectorAll('.operator-breakdown').forEach(function (breakdown) {
    var segments = breakdown.querySelectorAll('.operator-breakdown__segment');

    breakdown.querySelectorAll('.operator-breakdown__row').forEach(function (row, index) {
      var segment = segments[index];
      if (!segment) {
        return;
      }

      function setHighlighted(highlighted) {
        breakdown.classList.toggle('is-highlighting', highlighted);
        segment.classList.toggle('is-highlighted', highlighted);
      }

      row.addEventListener('mouseenter', function () { setHighlighted(true); });
      row.addEventListener('mouseleave', function () { setHighlighted(false); });
      row.addEventListener('focusin', function () { setHighlighted(true); });
      row.addEventListener('focusout', function () { setHighlighted(false); });
    });
  });

  var form = document.getElementById('operatorsToolbarForm');
  if (!form) {
    return;
  }

  form.querySelectorAll('.filter-auto-submit').forEach(function (element) {
    element.addEventListener('change', function () {
      form.submit();
    });
  });

  var searchInput = document.getElementById('operatorsSearchInput');
  if (!searchInput) {
    return;
  }

  searchInput.addEventListener('keypress', function (event) {
    if (event.key === 'Enter') {
      event.preventDefault();
      form.submit();
    }
  });
})();
