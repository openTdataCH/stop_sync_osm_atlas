(function () {
  'use strict';

  var svgNamespace = 'http://www.w3.org/2000/svg';

  function appendSvgElement(parent, name, attributes) {
    var element = document.createElementNS(svgNamespace, name);
    Object.keys(attributes || {}).forEach(function (key) {
      element.setAttribute(key, attributes[key]);
    });
    parent.appendChild(element);
    return element;
  }

  function elbowPath(startX, startY, endX, endY) {
    var deltaY = endY - startY;
    if (Math.abs(deltaY) < 1) {
      return 'M ' + startX + ' ' + startY + ' H ' + endX;
    }

    var direction = deltaY > 0 ? 1 : -1;
    var middleX = startX + ((endX - startX) * 0.52);
    var radius = Math.min(12, Math.abs(deltaY) / 2, Math.max(6, (endX - startX) / 4));

    return [
      'M', startX, startY,
      'H', middleX - radius,
      'Q', middleX, startY, middleX, startY + (direction * radius),
      'V', endY - (direction * radius),
      'Q', middleX, endY, middleX + radius, endY,
      'H', endX
    ].join(' ');
  }

  function drawOperatorConnectors(card, cardIndex) {
    var mapping = card.querySelector('.operator-card__mapping');
    var svg = card.querySelector('.operator-card__connectors');
    var source = card.querySelector('.operator-node--atlas');
    var targets = card.querySelectorAll('.operator-node--osm, .operator-node--wikidata, .operator-node--empty');

    if (!mapping || !svg || !source || !targets.length) {
      return;
    }

    svg.replaceChildren();
    if (window.matchMedia('(max-width: 760px)').matches) {
      return;
    }

    var mappingRect = mapping.getBoundingClientRect();
    var sourceRect = source.getBoundingClientRect();
    var width = mapping.clientWidth;
    var height = mapping.clientHeight;
    var markerId = 'operator-connector-arrow-' + cardIndex;

    svg.setAttribute('viewBox', '0 0 ' + width + ' ' + height);

    var defs = appendSvgElement(svg, 'defs');
    var marker = appendSvgElement(defs, 'marker', {
      id: markerId,
      viewBox: '0 0 8 8',
      markerWidth: '8',
      markerHeight: '8',
      refX: '7',
      refY: '4',
      orient: 'auto',
      markerUnits: 'userSpaceOnUse'
    });
    appendSvgElement(marker, 'path', {
      d: 'M 0 0 L 8 4 L 0 8 Z',
      fill: '#a6a9ad'
    });

    var startX = sourceRect.right - mappingRect.left;
    var startY = sourceRect.top - mappingRect.top + (sourceRect.height / 2);

    targets.forEach(function (target) {
      var targetRect = target.getBoundingClientRect();
      var endX = targetRect.left - mappingRect.left - 2;
      var endY = targetRect.top - mappingRect.top + (targetRect.height / 2);
      appendSvgElement(svg, 'path', {
        'class': 'operator-card__connector',
        d: elbowPath(startX, startY, endX, endY),
        'marker-end': 'url(#' + markerId + ')'
      });
    });
  }

  var cards = Array.prototype.slice.call(document.querySelectorAll('.operator-card'));
  var redrawQueued = false;

  function drawAllConnectors() {
    cards.forEach(drawOperatorConnectors);
  }

  function queueConnectorRedraw() {
    if (redrawQueued) {
      return;
    }
    redrawQueued = true;
    window.requestAnimationFrame(function () {
      redrawQueued = false;
      drawAllConnectors();
    });
  }

  if (cards.length) {
    queueConnectorRedraw();
    window.addEventListener('resize', queueConnectorRedraw);

    if (document.fonts && document.fonts.ready) {
      document.fonts.ready.then(queueConnectorRedraw);
    }

    if ('ResizeObserver' in window) {
      var connectorResizeObserver = new ResizeObserver(queueConnectorRedraw);
      cards.forEach(function (card) {
        connectorResizeObserver.observe(card);
      });
    }
  }

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
