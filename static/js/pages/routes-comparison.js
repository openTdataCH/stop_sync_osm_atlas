(function (global) {
  'use strict';

  // Long runs of matching stops fold like diff hunks: keep FOLD_CONTEXT rows
  // at each end and fold the rest when that hides at least FOLD_MINIMUM stops.
  var FOLD_CONTEXT = 2;
  var FOLD_MINIMUM = 5;
  var PER_PAGE = 30;
  var controllers = new Map();

  function element(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function percentage(value) {
    return value == null || value === '' ? '—' : Number(value).toLocaleString(undefined, { maximumFractionDigits: 1 }) + '%';
  }

  function unique(parts) {
    return parts.filter(function (part, index) {
      return part != null && part !== '' && parts.indexOf(part) === index;
    });
  }

  // A candidate reads as its line ("S10 (Uetlibergbahn)") and its own name
  // ("Uetliberg -> Selnau"); the stored best overlap only has a joined label.
  function routeLine(route) {
    return route.route_name || route.route_id || '';
  }

  function routeName(route) {
    var name = route.display_name !== routeLine(route) ? route.display_name : null;
    return name || route.label || routeLine(route) || 'Itinerary ' + route.id;
  }

  function routeMeta(route, parts) {
    if (route.direction_id != null && route.direction_id !== '') parts.push('Direction ' + route.direction_id);
    if (route.matched_stop_count) parts.push(route.matched_stop_count + ' shared stop' + (route.matched_stop_count === 1 ? '' : 's'));
    return unique(parts).join(' · ');
  }

  function counterpartName(route) {
    return unique([routeLine(route), routeName(route)]).join(' · ');
  }

  // Panels of the route card highlighted by a score strip, to release on re-render.
  var linkedPanels = new WeakMap();

  function setHighlight(panels, on) {
    panels.forEach(function (panel) { panel.classList.toggle('is-counterpart-highlighted', on); });
  }

  function releaseHighlights(container) {
    setHighlight(linkedPanels.get(container) || [], false);
    linkedPanels.delete(container);
  }

  function revealPanel(panel) {
    panel.open = true;
    var summary = panel.querySelector('summary') || panel;
    if (summary.scrollIntoView) summary.scrollIntoView({ behavior: 'smooth', block: 'center' });
    summary.focus({ preventScroll: true });
    // Restart the flash when the same panel is revealed again.
    panel.classList.remove('is-counterpart-flash');
    void panel.offsetWidth;
    panel.classList.add('is-counterpart-flash');
  }

  /**
   * Names the saved counterparts of a candidate. One shown on the same route
   * card is highlighted while the badge is hovered, and opened on click.
   */
  function renderTaken(container, options) {
    var badge = element('span', 'comparison-badge comparison-badge--taken');
    var counterparts = options.counterparts || [];
    if (!counterparts.length) {
      badge.textContent = options.candidateLabel + ' variant is the saved match of another ' + options.fixedLabel + ' variant';
      badge.title = 'The matcher already paired this ' + options.candidateLabel + ' variant with a different ' + options.fixedLabel + ' variant.';
      return badge;
    }
    badge.appendChild(document.createTextNode('Already matched to ' + options.fixedLabel + ' '));
    var panels = [];
    counterparts.forEach(function (counterpart, index) {
      if (index) badge.appendChild(document.createTextNode(', '));
      var panel = counterpart.panel;
      var name = counterpartName(counterpart.route);
      var target = element(panel ? 'button' : 'strong', 'comparison-badge__target', name);
      target.title = (counterpart.route.label || name) + (panel ? ' · Show it on this route card' : '');
      if (panel) {
        panels.push(panel);
        target.type = 'button';
        target.addEventListener('click', function () { revealPanel(panel); });
        target.addEventListener('focus', function () { setHighlight([panel], true); });
        target.addEventListener('blur', function () { setHighlight([panel], false); });
      }
      badge.appendChild(target);
    });
    if (panels.length) {
      badge.classList.add('comparison-badge--linked');
      linkedPanels.set(container, panels);
      badge.addEventListener('mouseenter', function () { setHighlight(panels, true); });
      badge.addEventListener('mouseleave', function () { setHighlight(panels, false); });
    }
    return badge;
  }

  function readVariant(section) {
    var script = document.getElementById(section.dataset.variantData);
    if (!script) return null;
    try {
      return JSON.parse(script.textContent);
    } catch (error) {
      console.error('Invalid variant data', error);
      return null;
    }
  }

  function stopPoint(stop) {
    if (!stop || stop.lat == null || stop.lon == null) return null;
    var point = [Number(stop.lat), Number(stop.lon)];
    return isFinite(point[0]) && isFinite(point[1]) ? point : null;
  }

  function renderStop(stop, source, missingText) {
    var cell = element('div', 'comparison-stop comparison-stop--' + source);
    if (!stop) {
      cell.classList.add('comparison-stop--missing');
      if (missingText) cell.appendChild(element('span', 'comparison-stop__missing', missingText));
      return cell;
    }
    var position = element('span', 'comparison-stop__position', stop.position != null ? stop.position : stop.stop_sequence);
    if (stop.stop_sequence != null) position.title = 'Stop sequence ' + stop.stop_sequence;
    var body = element('div', 'comparison-stop__body');
    body.appendChild(element('span', 'comparison-stop__name', stop.stop_label || 'Unnamed stop'));
    var identifiers = Array.isArray(stop.stop_ids) ? stop.stop_ids.join(', ') : '';
    if (stop.uic_ref) identifiers += (identifiers ? ' · ' : '') + 'UIC ' + stop.uic_ref;
    if (identifiers) {
      var id = element('span', 'comparison-stop__id', identifiers);
      id.title = identifiers;
      body.appendChild(id);
    }
    cell.appendChild(position);
    cell.appendChild(body);
    return cell;
  }

  function renderLink(row) {
    var link = element('span', 'comparison-link');
    if (!row.match_type || !row.atlas || !row.osm) {
      link.setAttribute('aria-hidden', 'true');
      return link;
    }
    var uic = row.match_type === 'uic_match';
    link.classList.add(uic ? 'comparison-link--uic' : 'comparison-link--stop');
    link.title = uic ? 'Same UIC number' : 'Same stop';
    var mark = element('span', 'comparison-link__mark', uic ? 'UIC' : '');
    mark.setAttribute('aria-hidden', 'true');
    link.appendChild(mark);
    link.appendChild(element('span', 'visually-hidden', uic ? 'matched by UIC' : 'matched by stop'));
    return link;
  }

  function rowKind(row) {
    if (row.atlas && row.osm) return row.match_type ? 'matched' : 'unlinked';
    return row.atlas ? 'atlas-only' : 'osm-only';
  }

  function foldMatchedRuns(list, items) {
    var start = 0;
    while (start < items.length) {
      if (items[start].kind !== 'matched') { start += 1; continue; }
      var end = start;
      while (end + 1 < items.length && items[end + 1].kind === 'matched') end += 1;
      var hidden = items.slice(start + FOLD_CONTEXT, end - FOLD_CONTEXT + 1);
      if (hidden.length >= FOLD_MINIMUM) foldRows(list, hidden.map(function (item) { return item.node; }));
      start = end + 1;
    }
  }

  function foldRows(list, nodes) {
    var fold = element('li', 'comparison-fold');
    var button = element('button', 'comparison-fold__button', 'Show ' + nodes.length + ' matching stops');
    button.type = 'button';
    button.addEventListener('click', function () {
      nodes.forEach(function (node) { node.hidden = false; });
      fold.remove();
    }, { once: true });
    fold.appendChild(button);
    nodes.forEach(function (node) { node.hidden = true; });
    list.insertBefore(fold, nodes[0]);
  }

  /**
   * Rows of an alignment. "single" lists one variant on its own: nothing is
   * missing, so rows are neither tinted nor folded.
   */
  function renderRows(list, rows, sourceLabel, single) {
    list.replaceChildren();
    list.classList.toggle('comparison-rows--single', Boolean(single));
    var items = (rows || []).map(function (row) {
      var kind = rowKind(row);
      var node = element('li', 'comparison-row comparison-row--' + kind);
      node.appendChild(renderStop(row.atlas, 'atlas', single ? '' : 'Not in ' + sourceLabel));
      node.appendChild(renderLink(row));
      node.appendChild(renderStop(row.osm, 'osm', single ? '' : 'Not in OSM'));
      var points = [stopPoint(row.atlas), stopPoint(row.osm)].filter(Boolean);
      if (points.length) node.dataset.points = JSON.stringify(points);
      list.appendChild(node);
      return { kind: kind, node: node };
    });
    if (!single) foldMatchedRuns(list, items);
  }

  function renderScore(container, data, options) {
    releaseHighlights(container);
    container.replaceChildren();
    container.hidden = false;
    var value = element('span', 'comparison-score__value', percentage(data.percentage));
    value.title = 'Stops shared in route order, divided by the stop count of the longer variant';
    container.appendChild(value);
    var text = element('span', 'comparison-score__text');
    var longer = Math.max(data.atlas_stop_count || 0, data.osm_stop_count || 0);
    text.appendChild(element('strong', '', data.matched_stop_count + ' of ' + longer + ' stops match in order'));
    text.appendChild(element('span', '', (data.atlas_stop_count - data.matched_stop_count) + ' only in ' + options.sourceLabel +
      ' · ' + (data.osm_stop_count - data.matched_stop_count) + ' only in OSM'));
    container.appendChild(text);
    var badges = element('span', 'comparison-score__badges');
    if (options.saved) badges.appendChild(element('span', 'comparison-badge comparison-badge--saved', 'Saved match'));
    var directions = { match: 'Directions agree', conflict: 'Direction conflict', unknown: 'Direction unknown' };
    badges.appendChild(element('span', 'comparison-badge' + (data.direction_status === 'match' ? '' : ' comparison-badge--warning'),
      directions[data.direction_status] || directions.unknown));
    if (options.candidateMatched) badges.appendChild(renderTaken(container, options));
    container.appendChild(badges);
    if (options.relationId && /^\d+$/.test(String(options.relationId))) {
      var link = element('a', 'comparison-score__link', 'OSM relation ' + options.relationId);
      link.href = 'https://www.openstreetmap.org/relation/' + options.relationId;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.appendChild(element('i', 'fas fa-external-link-alt'));
      container.appendChild(link);
    }
  }

  function retryButton(callback) {
    var button = element('button', 'btn btn-sm btn-outline-secondary comparison-retry', 'Try again');
    button.type = 'button';
    button.addEventListener('click', callback, { once: true });
    return button;
  }

  async function fetchJson(url, controller) {
    var response = await global.fetch(url.toString(), { signal: controller.signal });
    if (!response.ok) throw new Error('Request failed (' + response.status + ')');
    return response.json();
  }

  function emit(section, name, detail) {
    section.dispatchEvent(new CustomEvent(name, { bubbles: true, detail: detail }));
  }

  /** Row hover and click tell the variant map which stops to highlight. */
  function bindRowEvents(section, list, listen) {
    var current = null;
    function points(row) { return row && row.dataset.points ? JSON.parse(row.dataset.points) : null; }
    listen(list, 'mouseover', function (event) {
      var row = event.target.closest('.comparison-row');
      if (row === current) return;
      current = row;
      emit(section, 'routecomparisonhover', points(row));
    });
    listen(list, 'mouseleave', function () {
      current = null;
      emit(section, 'routecomparisonhover', null);
    });
    listen(list, 'click', function (event) {
      var row = event.target.closest('.comparison-row');
      if (row && row.dataset.points && !String(global.getSelection ? global.getSelection() : '')) {
        emit(section, 'routecomparisonfocus', points(row));
      }
    });
  }

  function createSavedController(section) {
    var panel = section.closest('details');
    var sourceLabel = section.dataset.sourceLabel || 'ATLAS';
    var list = section.querySelector('[data-comparison-results]');
    var summary = section.querySelector('[data-comparison-summary]');
    var empty = section.querySelector('[data-comparison-empty]');
    var rendered = false;
    var listeners = [];

    function listen(target, event, callback) {
      target.addEventListener(event, callback);
      listeners.push(function () { target.removeEventListener(event, callback); });
    }

    function activate() {
      if (rendered || !panel.open) return;
      rendered = true;
      var variant = readVariant(section);
      var comparison = variant && variant.stop_comparison;
      if (!comparison) {
        empty.hidden = false;
        empty.textContent = 'No stop sequence is available for these variants.';
        return;
      }
      renderScore(summary, comparison, { sourceLabel: sourceLabel, saved: true, relationId: variant.osm_relation_id });
      renderRows(list, comparison.rows, sourceLabel, false);
      if (!comparison.rows.length) {
        empty.hidden = false;
        empty.textContent = 'No stop sequence is available for these variants.';
      }
    }

    listen(panel, 'toggle', activate);
    bindRowEvents(section, list, listen);
    activate();
    return { section: section, destroy: function () { listeners.forEach(function (remove) { remove(); }); } };
  }

  function createExploreController(section) {
    function find(name) { return section.querySelector('[data-comparison-' + name + ']'); }
    var panel = section.closest('details');
    var sourceLabel = section.dataset.sourceLabel || 'ATLAS';
    var fixedSource = section.dataset.fixedSource;
    var fixedId = section.dataset.fixedItineraryId;
    var candidateSource = fixedSource === 'atlas' ? 'osm' : 'atlas';
    var candidateLabel = candidateSource === 'atlas' ? sourceLabel : 'OSM';
    var fixedLabel = fixedSource === 'atlas' ? sourceLabel : 'OSM';
    var picker = find('picker'), trigger = find('trigger'), popover = find('popover');
    var search = find('search'), optionsList = find('options'), more = find('more');
    var prev = find('prev'), next = find('next'), position = find('position');
    var value = find('value'), valueMeta = find('value-meta'), valueScore = find('value-score');
    var status = find('status'), summary = find('summary'), results = find('results'), empty = find('empty');
    var variant = null;
    var items = [], page = 0, pages = 0, total = 0, query = '';
    var selectedId = '', selectedRoute = null, activeIndex = -1;
    var optionsReady = false, optionsLoading = false, optionsError = false, hasChosen = false;
    var comparisonDirty = false, comparisonShown = false, activated = false, destroyed = false;
    var optionsVersion = 0, comparisonVersion = 0;
    var optionsController = null, comparisonController = null, searchTimer = null;
    var listeners = [];

    function listen(target, event, callback) {
      target.addEventListener(event, callback);
      listeners.push(function () { target.removeEventListener(event, callback); });
    }

    function candidateIndex() {
      return items.findIndex(function (item) { return String(item.id) === selectedId; });
    }

    function optionId(item) {
      return optionsList.id + '-' + item.id;
    }

    // The saved pair of a counterpart and the candidate, if this route card shows it.
    function counterpartPanel(route, candidateId) {
      var card = section.closest('.route-card');
      var ids = [String(route.id), String(candidateId)];
      if (!card || !ids.every(function (id) { return /^\d+$/.test(id); })) return null;
      return card.querySelector('.route-card__panel[data-' + fixedSource + '-itinerary-id="' + ids[0] + '"]' +
        '[data-' + candidateSource + '-itinerary-id="' + ids[1] + '"]');
    }

    function renderTrigger() {
      if (selectedRoute) {
        value.textContent = routeName(selectedRoute);
        valueMeta.textContent = routeMeta(selectedRoute, [routeLine(selectedRoute)]);
        valueScore.textContent = selectedRoute.percentage != null ? percentage(selectedRoute.percentage) : '';
      } else {
        value.textContent = optionsLoading && !optionsReady ? 'Finding the highest overlap…'
          : optionsError ? 'Could not load ' + candidateLabel + ' variants'
          : 'Choose a variant to compare';
        valueMeta.textContent = '';
        valueScore.textContent = '';
      }
      var index = candidateIndex();
      var busy = optionsLoading || optionsError || !items.length;
      prev.disabled = busy || index <= 0;
      next.disabled = busy || (index >= items.length - 1 && page >= pages);
    }

    function renderPosition() {
      position.replaceChildren();
      if (optionsLoading && !items.length) {
        position.textContent = query ? 'Searching ' + candidateLabel + ' routes…' : 'Ranking ' + candidateLabel + ' variants by stop overlap…';
      } else if (optionsError) {
        position.appendChild(element('span', '', 'Could not load ' + candidateLabel + ' variants. '));
        position.appendChild(retryButton(function () { loadOptions(1); }));
      } else if (!total) {
        position.textContent = query ? 'No ' + candidateLabel + ' route matches “' + query + '”.'
          : 'No ' + candidateLabel + ' variant shares a stop with this one. Search to compare with any route.';
      } else if (query) {
        position.textContent = total + (total === 1 ? ' route matches' : ' routes match') + ' “' + query + '” · highest overlap first';
      } else {
        position.textContent = total + ' ' + candidateLabel + ' variant' + (total === 1 ? ' shares' : 's share') +
          ' stops with this one · highest overlap first';
      }
    }

    function renderOptions() {
      optionsList.replaceChildren();
      items.forEach(function (item, index) {
        var option = element('li', 'comparison-option' + (index === activeIndex ? ' is-active' : ''));
        option.id = optionId(item);
        option.setAttribute('role', 'option');
        option.setAttribute('aria-selected', String(String(item.id) === selectedId));
        option.dataset.index = String(index);
        var score = element('span', 'comparison-option__score');
        score.appendChild(element('span', 'comparison-option__percent', percentage(item.percentage)));
        var bar = element('span', 'comparison-option__bar');
        var fill = element('span', 'comparison-option__fill');
        fill.style.width = Math.max(0, Math.min(100, Number(item.percentage) || 0)) + '%';
        bar.appendChild(fill);
        score.appendChild(bar);
        option.appendChild(score);
        var main = element('span', 'comparison-option__main');
        var title = element('span', 'comparison-option__title');
        if (routeLine(item) && routeLine(item) !== routeName(item)) title.appendChild(element('span', 'comparison-option__line', routeLine(item)));
        title.appendChild(document.createTextNode(routeName(item)));
        main.appendChild(title);
        var meta = routeMeta(item, [item.route_id !== routeLine(item) ? item.route_id : null]);
        if (meta) main.appendChild(element('span', 'comparison-option__meta', meta));
        option.appendChild(main);
        if (item.is_matched) {
          var flag = element('span', 'comparison-option__flag', 'Already matched');
          var names = (item.matched_with || []).map(counterpartName);
          flag.title = names.length ? 'Saved match of ' + fixedLabel + ' ' + names.join(', ')
            : 'Saved match of another ' + fixedLabel + ' variant';
          option.appendChild(flag);
        }
        optionsList.appendChild(option);
      });
      if (optionsLoading && items.length) optionsList.appendChild(element('li', 'comparison-options__loading', 'Loading…'));
      more.hidden = optionsLoading || optionsError || page >= pages;
      search.setAttribute('aria-activedescendant', activeIndex >= 0 && items[activeIndex] ? optionId(items[activeIndex]) : '');
      renderPosition();
      renderTrigger();
    }

    function setActive(index) {
      if (!items.length) return;
      activeIndex = Math.max(0, Math.min(items.length - 1, index));
      Array.prototype.forEach.call(optionsList.querySelectorAll('.comparison-option'), function (option) {
        option.classList.toggle('is-active', Number(option.dataset.index) === activeIndex);
      });
      var active = document.getElementById(optionId(items[activeIndex]));
      search.setAttribute('aria-activedescendant', active ? active.id : '');
      if (active && active.scrollIntoView) active.scrollIntoView({ block: 'nearest' });
    }

    function showFixedStops() {
      if (!variant || !variant.stop_comparison) return;
      renderRows(results, variant.stop_comparison.rows, sourceLabel, true);
    }

    function clearComparison() {
      releaseHighlights(summary);
      summary.replaceChildren();
      summary.hidden = true;
      if (comparisonShown) {
        comparisonShown = false;
        showFixedStops();
        emit(section, 'routecomparisonchange', null);
      }
    }

    function renderComparison(data) {
      if (data[candidateSource] && String(data[candidateSource].id) === selectedId) {
        selectedRoute = Object.assign({}, selectedRoute, data[candidateSource],
          { percentage: data.percentage, matched_stop_count: data.matched_stop_count });
        renderTrigger();
      }
      status.replaceChildren();
      var candidate = data[candidateSource];
      renderScore(summary, data, {
        sourceLabel: sourceLabel,
        candidateLabel: candidateLabel,
        fixedLabel: fixedLabel,
        candidateMatched: Boolean(candidate && candidate.is_matched),
        counterparts: ((candidate && candidate.matched_with) || []).map(function (route) {
          return { route: route, panel: counterpartPanel(route, candidate.id) };
        }),
        relationId: data.osm ? data.osm.source_itinerary_id : null
      });
      renderRows(results, data.rows, sourceLabel, false);
      comparisonShown = true;
      empty.hidden = Boolean(data.rows && data.rows.length);
      if (!empty.hidden) empty.textContent = 'The selected variants contain no stops to compare.';
      emit(section, 'routecomparisonchange', data);
    }

    async function loadComparison() {
      if (comparisonController) comparisonController.abort();
      var version = ++comparisonVersion;
      comparisonDirty = false;
      if (!selectedId) return;
      var controller = new AbortController();
      comparisonController = controller;
      section.setAttribute('aria-busy', 'true');
      status.textContent = 'Comparing stops…';
      var url = new URL(section.dataset.comparisonUrl, global.location.href);
      url.searchParams.set(fixedSource + '_itinerary_id', fixedId);
      url.searchParams.set(candidateSource + '_itinerary_id', selectedId);
      try {
        var data = await fetchJson(url, controller);
        if (version !== comparisonVersion || destroyed) return;
        section.setAttribute('aria-busy', 'false');
        renderComparison(data);
      } catch (error) {
        if (version !== comparisonVersion || destroyed || error.name === 'AbortError') return;
        comparisonDirty = true;
        section.setAttribute('aria-busy', 'false');
        clearComparison();
        status.replaceChildren(element('span', '', 'Could not compare these variants. '), retryButton(loadComparison));
      }
    }

    // The previous comparison stays visible, dimmed, until the next one arrives.
    function selectRoute(route) {
      selectedId = String(route.id);
      selectedRoute = route;
      hasChosen = true;
      empty.hidden = true;
      renderOptions();
      if (panel.open) loadComparison();
      else comparisonDirty = true;
    }

    async function loadOptions(requestPage, step) {
      if (destroyed) return;
      if (optionsController) optionsController.abort();
      clearTimeout(searchTimer);
      searchTimer = null;
      var version = ++optionsVersion;
      var controller = new AbortController();
      var append = requestPage > 1;
      optionsController = controller;
      optionsLoading = true;
      optionsError = false;
      if (!append) { items = []; activeIndex = -1; }
      renderOptions();
      var url = new URL(section.dataset.optionsUrl, global.location.href);
      url.searchParams.set('source', candidateSource);
      url.searchParams.set('fixed_itinerary_id', fixedId);
      url.searchParams.set('q', query);
      url.searchParams.set('unmatched', '0');
      // Without a search, list only variants sharing a stop; a search reaches every route.
      url.searchParams.set('shared_only', query ? '0' : '1');
      url.searchParams.set('page', String(requestPage));
      url.searchParams.set('per_page', String(PER_PAGE));
      try {
        var data = await fetchJson(url, controller);
        if (version !== optionsVersion || destroyed) return;
        var received = data.items || [];
        items = append ? items.concat(received) : received;
        page = data.page;
        pages = data.pages;
        total = data.total;
        optionsLoading = false;
        optionsReady = true;
        var index = candidateIndex();
        if (index >= 0) selectedRoute = Object.assign({}, selectedRoute, items[index]);
        renderOptions();
        if (step && received.length) selectRoute(received[0]);
        else if (!hasChosen && items.length) selectRoute(items[0]);
        else if (!hasChosen && !query) {
          empty.hidden = false;
          empty.textContent = 'No ' + candidateLabel + ' variant shares a stop with this one. ' +
            'Use the picker to search any ' + candidateLabel + ' route.';
          renderTrigger();
        }
      } catch (error) {
        if (version !== optionsVersion || destroyed || error.name === 'AbortError') return;
        optionsLoading = false;
        optionsError = true;
        renderOptions();
      }
    }

    function stepRoute(direction) {
      if (optionsLoading || optionsError || !items.length) return;
      var index = candidateIndex();
      var nextIndex = index + direction;
      if (nextIndex >= 0 && nextIndex < items.length) selectRoute(items[nextIndex]);
      else if (direction > 0 && page < pages) loadOptions(page + 1, true);
    }

    function openPopover() {
      if (!popover.hidden) return;
      popover.hidden = false;
      trigger.setAttribute('aria-expanded', 'true');
      if (!optionsReady && !optionsLoading) loadOptions(1);
      var index = candidateIndex();
      if (index >= 0) setActive(index);
      search.focus();
    }

    function closePopover(restoreFocus) {
      if (popover.hidden) return;
      popover.hidden = true;
      trigger.setAttribute('aria-expanded', 'false');
      if (restoreFocus) trigger.focus();
    }

    function choose(index) {
      var item = items[index];
      if (!item) return;
      closePopover(true);
      if (String(item.id) !== selectedId || comparisonDirty) selectRoute(item);
    }

    function preselectStoredBest() {
      var bestId = section.dataset.bestId;
      if (!bestId) return;
      // The importer stored the top candidate, so compare it while the ranking loads.
      selectRoute({
        id: bestId,
        label: section.dataset.bestLabel,
        percentage: section.dataset.bestPercentage === '' ? null : Number(section.dataset.bestPercentage),
        matched_stop_count: Number(section.dataset.bestMatchedStops) || 0
      });
    }

    function activate() {
      if (!panel.open || destroyed) return;
      if (!activated) {
        activated = true;
        variant = readVariant(section);
        showFixedStops();
        preselectStoredBest();
      }
      if (!optionsLoading && (!optionsReady || optionsError)) loadOptions(1);
      if (comparisonDirty) loadComparison();
    }

    function destroy() {
      destroyed = true;
      optionsVersion += 1;
      comparisonVersion += 1;
      if (optionsController) optionsController.abort();
      if (comparisonController) comparisonController.abort();
      clearTimeout(searchTimer);
      releaseHighlights(summary);
      listeners.forEach(function (remove) { remove(); });
    }

    listen(panel, 'toggle', activate);
    listen(trigger, 'click', function () {
      if (popover.hidden) openPopover();
      else closePopover(false);
    });
    listen(trigger, 'keydown', function (event) {
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        openPopover();
      }
    });
    listen(search, 'keydown', function (event) {
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        setActive(activeIndex + (event.key === 'ArrowDown' ? 1 : -1));
      } else if (event.key === 'Enter') {
        event.preventDefault();
        choose(activeIndex >= 0 ? activeIndex : 0);
      } else if (event.key === 'Escape') {
        event.preventDefault();
        closePopover(true);
      }
    });
    listen(search, 'input', function () {
      clearTimeout(searchTimer);
      optionsVersion += 1;
      if (optionsController) optionsController.abort();
      optionsLoading = true;
      query = search.value.trim();
      items = [];
      activeIndex = -1;
      renderOptions();
      searchTimer = setTimeout(function () { loadOptions(1); }, 250);
    });
    listen(popover, 'mousedown', function (event) {
      // Keep focus in the search box so the popover stays open.
      if (event.target.closest('.comparison-option, button')) event.preventDefault();
    });
    listen(optionsList, 'click', function (event) {
      var option = event.target.closest('.comparison-option');
      if (option) choose(Number(option.dataset.index));
    });
    listen(more, 'click', function () {
      loadOptions(page + 1);
      search.focus();
    });
    listen(picker, 'focusout', function (event) {
      if (!event.relatedTarget || !picker.contains(event.relatedTarget)) closePopover(false);
    });
    listen(document, 'pointerdown', function (event) {
      if (!popover.hidden && !picker.contains(event.target)) closePopover(false);
    });
    listen(prev, 'click', function () { stepRoute(-1); });
    listen(next, 'click', function () { stepRoute(1); });
    bindRowEvents(section, results, listen);
    renderTrigger();
    activate();
    return { section: section, id: fixedId, destroy: destroy };
  }

  function init() {
    document.querySelectorAll('.variant-comparison').forEach(function (section) {
      if (controllers.has(section)) return;
      controllers.set(section, section.dataset.mode === 'saved'
        ? createSavedController(section) : createExploreController(section));
    });
    return Array.from(controllers.values());
  }

  function destroy() {
    controllers.forEach(function (controller) { controller.destroy(); });
    controllers.clear();
  }

  global.RoutesComparison = { init: init, destroy: destroy };
  global.addEventListener('pagehide', function (event) { if (!event.persisted) destroy(); });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, { once: true });
  else init();
})(window);
