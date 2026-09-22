(function (global) {
  'use strict';

  var controllers = new Map();
  var bestRequests = new Set();
  var batchGeneration = 0;

  function element(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function percentage(value) {
    return value == null ? '—' : Number(value).toLocaleString(undefined, { maximumFractionDigits: 1 }) + '%';
  }

  function routeLabel(route) {
    if (!route) return '';
    var parts = [route.route_id, route.route_name, route.display_name];
    if (route.direction_id != null && route.direction_id !== '') parts.push('Direction ' + route.direction_id);
    return parts.filter(function (part, index) {
      return part != null && part !== '' && parts.indexOf(part) === index;
    }).join(' · ') || 'Itinerary ' + route.id;
  }

  function optionLabel(route) {
    return percentage(route.percentage) + ' overlap · ' + routeLabel(route) + (route.is_matched ? ' · Already matched' : '');
  }

  async function fetchJson(url, controller) {
    var response = await global.fetch(url.toString(), { signal: controller.signal });
    if (!response.ok) throw new Error('Request failed (' + response.status + ')');
    return response.json();
  }

  function retryButton(callback) {
    var button = element('button', 'btn btn-sm btn-outline-secondary comparison-retry', 'Try again');
    button.type = 'button';
    button.addEventListener('click', callback, { once: true });
    return button;
  }

  function renderStop(stop) {
    var node = element('div', 'comparison-stop' + (stop ? '' : ' comparison-stop--missing'));
    if (!stop) {
      node.textContent = 'No corresponding stop';
      return node;
    }
    node.appendChild(element('span', 'comparison-stop__sequence', stop.stop_sequence));
    var body = element('div', 'comparison-stop__body');
    body.appendChild(element('span', 'comparison-stop__name', stop.stop_label || 'Unnamed stop'));
    var identifiers = Array.isArray(stop.stop_ids) ? stop.stop_ids.join(', ') : '';
    if (stop.uic_ref) identifiers += (identifiers ? ' · ' : '') + 'UIC ' + stop.uic_ref;
    if (identifiers) body.appendChild(element('span', 'comparison-stop__id', identifiers));
    node.appendChild(body);
    return node;
  }

  function createController(section) {
    function find(name) { return section.querySelector('[data-comparison-' + name + ']'); }
    var panel = section.closest('details');
    var sourceLabel = section.dataset.sourceLabel || 'ATLAS';
    var fixedSource = section.dataset.fixedSource;
    var fixedId = section.dataset.fixedItineraryId;
    var candidateSource = fixedSource === 'atlas' ? 'osm' : 'atlas';
    var candidateLabel = candidateSource === 'atlas' ? sourceLabel : 'OSM';
    var search = find('search'), select = find('select'), prev = find('prev'), next = find('next');
    var position = find('position'), status = find('status'), summary = find('summary');
    var results = find('results'), empty = find('empty'), fallback = find('fallback');
    var candidateName = find('candidate-name');
    var bestBadge = panel.querySelector('[data-best-overlap]');
    var items = [], page = 1, pages = 0, total = 0;
    var selectedId = '', selectedRoute = null;
    var optionsReady = false, optionsLoading = false, optionsError = false, hasChosen = false;
    var comparisonDirty = false, bestKnown = false, destroyed = false;
    var optionsVersion = 0, comparisonVersion = 0;
    var optionsController = null, comparisonController = null, searchTimer = null;
    var listeners = [];

    function listen(target, event, callback) {
      target.addEventListener(event, callback);
      listeners.push(function () { target.removeEventListener(event, callback); });
    }

    function setBest(best) {
      if (destroyed || !bestBadge) return;
      bestKnown = true;
      bestBadge.textContent = best ? 'Highest overlap: ' + percentage(best.percentage) : 'No candidate routes';
      bestBadge.title = best ? routeLabel(best) : 'No routes are available on the opposite side.';
    }

    function unavailable() {
      if (!destroyed && !bestKnown && bestBadge) bestBadge.textContent = 'Overlap unavailable';
    }

    function candidateIndex() {
      return items.findIndex(function (item) { return String(item.id) === selectedId; });
    }

    function renderOptions() {
      select.replaceChildren();
      var placeholder = element('option', '', 'Choose ' + candidateLabel + ' route…');
      placeholder.value = '';
      select.appendChild(placeholder);
      var index = candidateIndex();
      if (selectedId && index < 0) {
        var selected = element('option', '', optionLabel(selectedRoute || { id: selectedId }));
        selected.value = selectedId;
        select.appendChild(selected);
      }
      items.forEach(function (item) {
        var option = element('option', '', optionLabel(item));
        option.value = item.id;
        select.appendChild(option);
      });
      select.value = selectedId;
      select.disabled = optionsLoading;
      select.setAttribute('aria-busy', String(optionsLoading));
      prev.disabled = optionsLoading || optionsError || !items.length || (index <= 0 && page <= 1);
      next.disabled = optionsLoading || optionsError || !items.length || (index >= items.length - 1 && page >= pages);
      position.replaceChildren();
      if (optionsLoading) {
        position.textContent = 'Finding routes by stop overlap…';
      } else if (optionsError) {
        position.appendChild(element('span', '', 'Could not load ' + candidateLabel + ' routes. '));
        position.appendChild(retryButton(function () { loadOptions(page); }));
      } else if (!total) {
        position.textContent = 'No routes found.' + (search.value.trim() ? ' Try another search.' : '');
      } else {
        position.textContent = total + ' result' + (total === 1 ? '' : 's') +
          ' · highest overlap first · page ' + page + ' of ' + pages;
      }
      if (candidateName) candidateName.textContent = selectedRoute ? routeLabel(selectedRoute) : 'Choose a route to compare';
    }

    function clearComparison() {
      results.replaceChildren();
      summary.replaceChildren();
      summary.hidden = true;
      status.replaceChildren();
      if (fallback) fallback.hidden = false;
      section.dispatchEvent(new CustomEvent('routecomparisonchange', { bubbles: true, detail: null }));
    }

    function renderComparison(data) {
      summary.replaceChildren();
      summary.hidden = false;
      results.replaceChildren();
      if (fallback) fallback.hidden = true;
      results.setAttribute('role', 'list');
      if (data[candidateSource] && String(data[candidateSource].id) === selectedId) {
        selectedRoute = Object.assign({}, selectedRoute, data[candidateSource]);
        renderOptions();
      }
      var score = element('div', 'comparison-score');
      score.appendChild(element('span', 'comparison-score__value', percentage(data.percentage)));
      var detail = element('div', 'comparison-score__detail');
      var longer = Math.max(data.atlas_stop_count || 0, data.osm_stop_count || 0);
      detail.appendChild(element('strong', '', data.matched_stop_count + ' of ' + longer + ' stops match in sequence'));
      detail.appendChild(element('span', '', sourceLabel + ': ' + (data.atlas_stop_count - data.matched_stop_count) +
        ' only · OSM: ' + (data.osm_stop_count - data.matched_stop_count) + ' only'));
      score.appendChild(detail);
      summary.appendChild(score);
      summary.appendChild(element('span', 'comparison-badge', data.is_saved_match ? 'Saved match' : 'Exploratory comparison'));
      var directionText = { match: 'Directions agree', conflict: 'Direction conflict', unknown: 'Direction unknown' };
      summary.appendChild(element('span', 'comparison-badge' +
        (data.direction_status === 'match' ? '' : ' comparison-badge--warning'),
      directionText[data.direction_status] || directionText.unknown));
      (data.rows || []).forEach(function (row) {
        var matched = Boolean(row.atlas && row.osm && row.match_type);
        var node = element('div', 'comparison-stop-row' + (matched ? ' comparison-stop-row--matched' : ''));
        node.setAttribute('role', 'listitem');
        node.appendChild(renderStop(row.atlas));
        var link = element('div', 'comparison-link' + (matched ? ' comparison-link--matched' : ''));
        if (matched) {
          link.title = row.match_type === 'uic_match' ? 'Matched by UIC' : 'Matched through stop matching';
          var symbol = element('span', 'comparison-link__symbol', row.match_type === 'uic_match' ? 'UIC ↔' : 'Stop ↔');
          symbol.setAttribute('aria-hidden', 'true');
          link.appendChild(symbol);
          link.appendChild(element('span', 'visually-hidden', link.title));
        } else link.setAttribute('aria-hidden', 'true');
        node.appendChild(link);
        node.appendChild(renderStop(row.osm));
        results.appendChild(node);
      });
      empty.hidden = Boolean(data.rows && data.rows.length);
      if (!empty.hidden) empty.textContent = 'The selected routes contain no stops to compare.';
      status.textContent = data.matched_stop_count + ' matched stops. ' + (data.rows || []).length + ' aligned rows.';
      section.dispatchEvent(new CustomEvent('routecomparisonchange', { bubbles: true, detail: data }));
    }

    async function loadComparison() {
      if (comparisonController) comparisonController.abort();
      var version = ++comparisonVersion;
      comparisonDirty = false;
      clearComparison();
      if (!selectedId) {
        section.setAttribute('aria-busy', 'false');
        empty.hidden = false;
        empty.textContent = 'Choose a route from ' + candidateLabel + ' to compare.';
        return;
      }
      var controller = new AbortController();
      comparisonController = controller;
      section.setAttribute('aria-busy', 'true');
      empty.hidden = true;
      status.textContent = 'Comparing route stops…';
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
        status.replaceChildren(element('span', '', 'Could not compare these routes. '), retryButton(loadComparison));
      }
    }

    function selectRoute(route) {
      selectedId = route ? String(route.id) : '';
      selectedRoute = route || null;
      hasChosen = true;
      comparisonDirty = true;
      renderOptions();
      if (panel.open) loadComparison();
    }

    async function loadOptions(requestPage, step) {
      if (destroyed) return;
      if (optionsController) optionsController.abort();
      clearTimeout(searchTimer);
      searchTimer = null;
      var version = ++optionsVersion;
      var controller = new AbortController();
      optionsController = controller;
      optionsLoading = true;
      optionsError = false;
      renderOptions();
      var url = new URL(section.dataset.optionsUrl, global.location.href);
      url.searchParams.set('source', candidateSource);
      url.searchParams.set('fixed_itinerary_id', fixedId);
      url.searchParams.set('q', search.value.trim());
      url.searchParams.set('unmatched', '0');
      url.searchParams.set('page', String(requestPage));
      url.searchParams.set('per_page', '30');
      try {
        var data = await fetchJson(url, controller);
        if (version !== optionsVersion || destroyed) return;
        items = data.items || [];
        page = data.page;
        pages = data.pages;
        total = data.total;
        optionsLoading = false;
        optionsReady = true;
        setBest(data.best);
        renderOptions();
        if (items.length && (!hasChosen || step)) selectRoute(items[step < 0 ? items.length - 1 : 0]);
        else if (!selectedId && !items.length) {
          empty.hidden = false;
          empty.textContent = 'No candidate routes are available' + (search.value.trim() ? ' for this search.' : '.');
        }
      } catch (error) {
        if (version !== optionsVersion || destroyed || error.name === 'AbortError') return;
        optionsLoading = false;
        optionsError = true;
        items = [];
        renderOptions();
      }
    }

    function stepRoute(direction) {
      if (optionsLoading || optionsError || !items.length) return;
      var index = candidateIndex();
      var nextIndex = index < 0 && direction > 0 ? 0 : index + direction;
      if (nextIndex >= 0 && nextIndex < items.length) selectRoute(items[nextIndex]);
      else if (page + direction > 0 && page + direction <= pages) loadOptions(page + direction, direction);
    }

    function activate() {
      if (!panel.open || destroyed) return;
      if (!optionsLoading && (!optionsReady || optionsError)) loadOptions(1);
      else if (comparisonDirty) loadComparison();
    }

    function destroy() {
      destroyed = true;
      optionsVersion += 1;
      comparisonVersion += 1;
      if (optionsController) optionsController.abort();
      if (comparisonController) comparisonController.abort();
      clearTimeout(searchTimer);
      listeners.forEach(function (remove) { remove(); });
    }

    listen(panel, 'toggle', activate);
    listen(search, 'input', function () {
      clearTimeout(searchTimer);
      optionsVersion += 1;
      if (optionsController) optionsController.abort();
      optionsLoading = true;
      renderOptions();
      searchTimer = setTimeout(function () { loadOptions(1); }, 250);
    });
    listen(select, 'change', function () {
      var id = select.value;
      var route = items.find(function (item) { return String(item.id) === id; });
      selectRoute(id ? route || selectedRoute || { id: id } : null);
    });
    listen(prev, 'click', function () { stepRoute(-1); });
    listen(next, 'click', function () { stepRoute(1); });
    activate();
    return { section: section, id: fixedId, setBest: setBest, unavailable: unavailable, destroy: destroy };
  }

  function loadBestBadges(entries) {
    var groups = new Map();
    entries.forEach(function (entry) {
      var url = entry.section.dataset.bestUrl;
      if (!groups.has(url)) groups.set(url, []);
      groups.get(url).push(entry);
    });
    var jobs = [];
    groups.forEach(function (group, url) {
      for (var index = 0; index < group.length; index += 100) jobs.push({ url: url, entries: group.slice(index, index + 100) });
    });
    var generation = batchGeneration;
    async function worker() {
      while (jobs.length && generation === batchGeneration) {
        var job = jobs.shift();
        var controller = new AbortController();
        bestRequests.add(controller);
        try {
          var url = new URL(job.url, global.location.href);
          job.entries.forEach(function (entry) { url.searchParams.append('itinerary_id', entry.id); });
          var data = await fetchJson(url, controller);
          if (generation !== batchGeneration) return;
          job.entries.forEach(function (entry) { entry.setBest(data.items[entry.id]); });
        } catch (error) {
          if (generation === batchGeneration && error.name !== 'AbortError') job.entries.forEach(function (entry) { entry.unavailable(); });
        } finally {
          bestRequests.delete(controller);
        }
      }
    }
    var workerCount = Math.min(3, jobs.length);
    for (var workerIndex = 0; workerIndex < workerCount; workerIndex += 1) worker();
  }

  function init() {
    var added = [];
    document.querySelectorAll('.variant-comparison').forEach(function (section) {
      if (controllers.has(section)) return;
      var controller = createController(section);
      controllers.set(section, controller);
      added.push(controller);
    });
    loadBestBadges(added);
    return Array.from(controllers.values());
  }

  function destroy() {
    batchGeneration += 1;
    bestRequests.forEach(function (controller) { controller.abort(); });
    bestRequests.clear();
    controllers.forEach(function (controller) { controller.destroy(); });
    controllers.clear();
  }

  global.RoutesComparison = { init: init, destroy: destroy };
  global.addEventListener('pagehide', function (event) { if (!event.persisted) destroy(); });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, { once: true });
  else init();
})(window);
