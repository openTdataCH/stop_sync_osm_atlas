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
   *  - badgeClass: additional badge classes (e.g., 'badge-primary')
   *  - removeClass: anchor class to hook removal handler (default: 'remove-filter')
   *  - data: object of data-* attributes for the anchor (e.g., { type: 'nodeType', filter: 'atlas' })
   *  - closeChar: character for the close button (default: 'x')
   */
  function buildRemovableChip(options) {
    options = options || {};
    const label = escapeHtml(options.label || '');
    const extraBadgeClass = options.badgeClass || '';
    const removeClass = options.removeClass || 'remove-filter';
    const data = options.data || {};
    const closeChar = (options.closeChar == null ? 'x' : String(options.closeChar));

    let dataAttrs = '';
    Object.keys(data).forEach(function(key) {
      const attrName = 'data-' + key.replace(/([A-Z])/g, function(m){ return '-' + m.toLowerCase(); });
      const val = data[key];
      // Allow raw strings (like '#selector') to pass; still escape to be safe
      dataAttrs += ' ' + attrName + '="' + escapeHtml(val) + '"';
    });

    return '<span class="' + FILTER_CHIP_BADGE_CLASS + ' ' + extraBadgeClass + '">' + label +
           ' <a href="#" class="text-dark ' + removeClass + '"' + dataAttrs + '>' + escapeHtml(closeChar) + '</a></span>';
  }

  function generateOperatorChipsHtml(operators, options = {}) {
    const context = options.context || 'index';
    const chips = [];
    (operators || []).forEach(function(operator) {
      if (context === 'index') {
        chips.push(buildRemovableChip({
          label: 'Operator: ' + operator,
          badgeClass: 'badge-info',
          removeClass: 'remove-filter',
          data: { type: 'atlasOperator', filter: operator }
        }));
      } else {
        chips.push(buildRemovableChip({
          label: 'Operator: ' + operator,
          badgeClass: 'badge-info',
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
    const hasOperators = Array.isArray(operators) && operators.length > 0;

    selectedTypes.forEach(function(problemType) {
      const displayType = String(problemType || '').replace(/_/g, ' ').replace(/\b\w/g, function(l){return l.toUpperCase();});
      typeChips.push('<span class="' + FILTER_CHIP_BADGE_CLASS + ' badge-primary">' + escapeHtml(displayType) +
                 ' <a href="#" class="text-dark remove-type-chip" data-type="' + escapeHtml(problemType) + '">x</a></span>');
    });

    selectedPriorities.forEach(function(prio) {
      priorityChips.push('<span class="' + FILTER_CHIP_BADGE_CLASS + ' badge-light border">Priority P' + escapeHtml(prio) +
                 ' <a href="#" class="text-dark remove-priority-chip" data-priority="' + escapeHtml(prio) + '">x</a></span>');
    });

    const typeGroup = buildOrGroupHtml(typeChips);
    if (typeGroup) groups.push(typeGroup);

    const priorityGroup = buildOrGroupHtml(priorityChips);
    if (priorityGroup) groups.push(priorityGroup);

    if (groups.length === 0 && !hasOperators) {
      groups.push('<span class="' + FILTER_CHIP_BADGE_CLASS + ' badge-secondary">All entries</span>');
    }

    return groups;
  }

  function renderProblemChips(containerSelector, options = {}) {
    const container = $(containerSelector);
    if (container.length === 0) return;
    const problemTypes = options.problemTypes || [];
    const operators = options.operators || [];
    const priorities = options.priorities || [];
    const groups = generateProblemChipGroups(problemTypes, operators, priorities);
    const operatorsGroup = generateOperatorChipsHtml(operators, { context: 'problems' });
    if (operatorsGroup) groups.push(operatorsGroup);
    if (groups.length === 0) {
      container.html('<span class="' + FILTER_CHIP_BADGE_CLASS + ' badge-secondary">All entries</span>');
    } else {
      container.html(joinWithAndHtml(groups));
    }
    container.off('click.filterchips');
    container.on('click.filterchips', 'a.remove-type-chip', function(e) { e.preventDefault(); const type = $(this).data('type'); if (typeof options.onRemoveType === 'function') { options.onRemoveType(type); } });
    container.on('click.filterchips', 'a.remove-priority-chip', function(e) { e.preventDefault(); const priority = $(this).data('priority'); if (typeof options.onRemovePriority === 'function') { options.onRemovePriority(String(priority)); } });
    container.on('click.filterchips', 'a.remove-operator-chip', function(e) { e.preventDefault(); const op = $(this).data('operator'); if (typeof options.onRemoveOperator === 'function') { options.onRemoveOperator(op); } });
    container.on('click.filterchips', 'a.clear-all-problem-chips', function(e) { e.preventDefault(); if (typeof options.onClearAll === 'function') { options.onClearAll(); } });
  }

  global.FilterChipUtils = { generateOperatorChipsHtml, generateProblemChipGroups, renderProblemChips, buildOrGroupHtml, joinWithAndHtml, buildRemovableChip };
})(window);


