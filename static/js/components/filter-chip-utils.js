(function(global) {
  'use strict';

  // Use shared escapeHtml utility
  const escapeHtml = SharedUtils.escapeHtml;
  const FILTER_CHIP_BADGE_CLASS = 'badge filter-chip-badge';

  function buildSeparatorChip(label) {
    return '<span class="filter-chip-separator">' + escapeHtml(label) + '</span>';
  }

  function buildOrGroupHtml(chipsArray) {
    if (!chipsArray || chipsArray.length === 0) return '';
    if (chipsArray.length === 1) return chipsArray[0];
    return buildSeparatorChip('(') + chipsArray.join(buildSeparatorChip('OR')) + buildSeparatorChip(')');
  }

  function joinWithAndHtml(items) {
    if (!items || items.length === 0) return '';
    if (items.length === 1) return items[0];
    return items.join(buildSeparatorChip('AND'));
  }

  /**
   * Build a removable filter chip with a consistent style
   * @param {object} options
   *  - label: string visible text inside the chip
   *  - badgeClass: additional badge classes (e.g., 'text-bg-primary')
   *  - removeClass: anchor class to hook removal handler (default: 'remove-filter')
   *  - data: object of data-* attributes for the anchor (e.g., { type: 'nodeType', filter: 'atlas' })
   *  - closeChar: character for the close button (default: 'x')
   *  - removeLabel: optional accessible label for the remove action
   */
  function buildRemovableChip(options) {
    options = options || {};
    const label = escapeHtml(options.label || '');
    const extraBadgeClass = options.badgeClass || '';
    const removeClass = options.removeClass || 'remove-filter';
    const data = options.data || {};
    const closeChar = (options.closeChar == null ? 'x' : String(options.closeChar));
    const removeLabel = options.removeLabel ? String(options.removeLabel) : '';

    let dataAttrs = '';
    Object.keys(data).forEach(function(key) {
      const attrName = 'data-' + key.replace(/([A-Z])/g, function(m){ return '-' + m.toLowerCase(); });
      const val = data[key];
      // Allow raw strings (like '#selector') to pass; still escape to be safe
      dataAttrs += ' ' + attrName + '="' + escapeHtml(val) + '"';
    });

    const accessibilityAttrs = removeLabel
      ? ' aria-label="' + escapeHtml(removeLabel) + '" title="' + escapeHtml(removeLabel) + '"'
      : '';

    return '<span class="' + FILTER_CHIP_BADGE_CLASS + ' ' + extraBadgeClass + '">' + label +
           ' <a href="#" class="text-body ' + removeClass + '"' + dataAttrs + accessibilityAttrs + '>' + escapeHtml(closeChar) + '</a></span>';
  }

  function generateOperatorChipsHtml(operators, options = {}) {
    const context = options.context || 'index';
    const labelPrefix = options.labelPrefix || 'Operator';
    const chipType = options.chipType || 'atlasOperator';
    const chipBadgeClass = options.badgeClass || 'filter-chip-operator';
    const chips = [];
    (operators || []).forEach(function(operator) {
      if (context === 'index') {
        chips.push(buildRemovableChip({
          label: labelPrefix + ': ' + operator,
          badgeClass: chipBadgeClass,
          removeClass: 'remove-filter',
          data: { type: chipType, filter: operator }
        }));
      } else {
        chips.push(buildRemovableChip({
          label: labelPrefix + ': ' + operator,
          badgeClass: chipBadgeClass,
          removeClass: 'remove-operator-chip',
          data: { operator: operator }
        }));
      }
    });
    return buildOrGroupHtml(chips);
  }

  function generateProblemChipGroups(problemTypes, operators, priorities) {
    const groups = [];
    const typeChips = [];
    const priorityChips = [];
    const selectedTypes = Array.isArray(problemTypes) ? problemTypes : [];
    const selectedPriorities = Array.isArray(priorities) ? priorities : [];

    selectedTypes.forEach(function(problemType) {
      const displayType = problemType === 'identifier'
        ? 'OSM ' + SharedUtils.sourceIdLabel()
        : String(problemType || '').replace(/_/g, ' ').replace(/\b\w/g, function(l){return l.toUpperCase();});
      typeChips.push('<span class="' + FILTER_CHIP_BADGE_CLASS + ' filter-chip-problem-type">' + escapeHtml(displayType) +
                 ' <a href="#" class="text-body remove-type-chip" data-type="' + escapeHtml(problemType) + '">x</a></span>');
    });

    selectedPriorities.forEach(function(prio) {
      priorityChips.push('<span class="' + FILTER_CHIP_BADGE_CLASS + ' bg-body-tertiary text-body border">Priority P' + escapeHtml(prio) +
                 ' <a href="#" class="text-body remove-priority-chip" data-priority="' + escapeHtml(prio) + '">x</a></span>');
    });

    const typeGroup = buildOrGroupHtml(typeChips);
    if (typeGroup) groups.push(typeGroup);

    const priorityGroup = buildOrGroupHtml(priorityChips);
    if (priorityGroup) groups.push(priorityGroup);

    return groups;
  }

  // One click listener per chip container, replaced on every render.
  const chipClickHandlers = new WeakMap();

  function renderProblemChips(containerSelector, options = {}) {
    const container = document.querySelector(containerSelector);
    if (!container) return;
    const problemTypes = options.problemTypes || [];
    const operators = options.operators || [];
    const priorities = options.priorities || [];
    const groups = generateProblemChipGroups(problemTypes, operators, priorities);
    const operatorsGroup = generateOperatorChipsHtml(operators, { context: 'problems' });
    if (operatorsGroup) groups.push(operatorsGroup);
    if (options.area) {
      groups.push(buildRemovableChip({ label: 'Drawn area', badgeClass: 'filter-chip-secondary', removeClass: 'remove-area-chip' }));
    }
    if (groups.length === 0) {
      container.innerHTML = '<span class="' + FILTER_CHIP_BADGE_CLASS + ' filter-chip-secondary">All entries</span>';
    } else {
      container.innerHTML = joinWithAndHtml(groups);
    }
    const previous = chipClickHandlers.get(container);
    if (previous) container.removeEventListener('click', previous);
    const handler = function(e) {
      const link = e.target.closest('a.remove-type-chip, a.remove-priority-chip, a.remove-operator-chip, a.remove-area-chip');
      if (!link || !container.contains(link)) return;
      e.preventDefault();
      if (link.classList.contains('remove-type-chip')) {
        if (typeof options.onRemoveType === 'function') options.onRemoveType(link.dataset.type);
      } else if (link.classList.contains('remove-priority-chip')) {
        if (typeof options.onRemovePriority === 'function') options.onRemovePriority(String(link.dataset.priority));
      } else if (link.classList.contains('remove-operator-chip')) {
        if (typeof options.onRemoveOperator === 'function') options.onRemoveOperator(link.dataset.operator);
      } else if (typeof options.onRemoveArea === 'function') {
        options.onRemoveArea();
      }
    };
    container.addEventListener('click', handler);
    chipClickHandlers.set(container, handler);
  }

  function buildDirectionDropdownHtml(options) {
    let direction = options.direction || '';
    // Handle comma-separated directions (common in matched routes where multiple IDs are filtered together)
    if (typeof direction === 'string' && direction.indexOf(',') !== -1) {
      const parts = direction.split(',').map(function(s) { return s.trim(); });
      direction = parts.find(function(p) { return p !== ''; }) || '';
    }
    // 0 is the first route filter, not "no index".
    const mapIndex = options.mapIndex != null ? options.mapIndex : '';
    const routeLabel = options.routeLabel || '';
    const showClose = options.showClose || false;
    // A route filter narrowed to variants shows them instead of a direction;
    // options.routeId adds the route's variants to the options, loaded on opening.
    const variantLabel = options.variantLabel || '';
    const current = variantLabel ? 'variant' : direction;
    const display = variantLabel || (direction === '' ? 'Both' : 'Dir: ' + direction);
    const routeAttribute = options.routeId ? ' data-route-id="' + escapeHtml(options.routeId) + '"' : '';

    const dropdownHtml = '<span class="direction-dropdown" data-index="' + escapeHtml(String(mapIndex)) + '" data-current="' + escapeHtml(current) + '"' + routeAttribute + '>' +
        '<span class="direction-current" title="' + escapeHtml(options.variantTitle || display) + '">' + escapeHtml(display) + '</span><i class="fas fa-chevron-down direction-arrow"></i>' +
        '<div class="direction-options" style="display: none;">' +
        (options.routeId
          // One list: the whole line, then each direction followed by its
          // variants (filled in on opening, see loadRouteVariantOptions).
          ? '<div class="direction-option" data-direction="">Both directions</div>' +
            '<div class="direction-variants">' +
            '<div class="direction-option direction-option--direction" data-direction="0">Direction 0</div>' +
            '<div class="direction-option direction-option--direction" data-direction="1">Direction 1</div>' +
            '</div>'
          : '<div class="direction-option" data-direction="">Both</div>' +
            '<div class="direction-option" data-direction="0">Dir: 0</div>' +
            '<div class="direction-option" data-direction="1">Dir: 1</div>') +
        '</div></span>';
    
    let chipContent = (routeLabel ? escapeHtml(routeLabel) + ' ' : '') + dropdownHtml;
    if (showClose) {
        chipContent += ' <a href="#" class="remove-filter text-body text-decoration-none ms-1" data-type="station" data-index="' + escapeHtml(String(mapIndex)) + '">×</a>';
    }
        
    return '<span class="' + FILTER_CHIP_BADGE_CLASS + ' filter-chip-secondary shadow-sm' + (options.routeId ? ' filter-chip-route' : '') +
        '" style="pointer-events: auto;">' + chipContent + '</span>';
  }

  global.FilterChipUtils = { generateOperatorChipsHtml, generateProblemChipGroups, renderProblemChips, buildOrGroupHtml, joinWithAndHtml, buildRemovableChip, buildDirectionDropdownHtml };
})(window);

