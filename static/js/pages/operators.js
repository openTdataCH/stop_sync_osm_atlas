(function () {
  'use strict';

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