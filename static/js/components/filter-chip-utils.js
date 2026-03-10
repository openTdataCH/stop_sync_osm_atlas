(function(global) {
  'use strict';

  // Use shared escapeHtml utility
  const escapeHtml = SharedUtils.escapeHtml;
  const FILTER_CHIP_BADGE_CLASS = 'badge filter-chip-badge';
  const FILTER_CHIP_SEPARATOR_CLASS = 'badge filter-chip-badge filter-chip-separator';

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
      const safeOp = escapeHtml(operator);
      if (context === 'index') {
        const chip = '<span class="' + FILTER_CHIP_BADGE_CLASS + ' badge-info">Operator: ' + safeOp +
          ' <a href="#" class="text-dark remove-filter" data-type="atlasOperator" data-filter="' + safeOp + '">x</a></span>';
        chips.push(chip);
      } else {
        const chip = '<span class="' + FILTER_CHIP_BADGE_CLASS + ' badge-info">Operator: ' + safeOp +
          ' <a href="#" class="text-dark remove-operator-chip" data-operator="' + safeOp + '">x</a></span>';
        chips.push(chip);
      }
    });
    return buildOrGroupHtml(chips);
  }

  function generateProblemChips(problemType, solutionFilter, operators, priority) {
    const chips = [];
    const typeIsAll = (problemType === 'all');
    const hasOperators = Array.isArray(operators) && operators.length > 0;
    const sol = (solutionFilter || 'all');
    const prio = priority || 'all';

    if (typeIsAll) {
      if (sol === 'all') {
        if (!hasOperators) {
      chips.push('<span class="' + FILTER_CHIP_BADGE_CLASS + ' badge-secondary">All Problems</span>');
        }
      } else {
        const solLabel = sol.replace(/\b\w/g, function(l){return l.toUpperCase();});
        chips.push('<span class="' + FILTER_CHIP_BADGE_CLASS + ' badge-secondary">' + escapeHtml(solLabel) +
                   ' <a href="#" class="text-dark clear-solution-chip">x</a></span>');
      }
    } else {
      const displayType = (problemType || 'all').replace(/_/g, ' ').replace(/\b\w/g, function(l){return l.toUpperCase();});
      chips.push('<span class="' + FILTER_CHIP_BADGE_CLASS + ' badge-primary">' + escapeHtml(displayType) +
                 ' <a href="#" class="text-dark clear-problem-type-chip">x</a></span>');
      if (sol !== 'all') {
        const solLabel = sol.replace(/\b\w/g, function(l){return l.toUpperCase();});
        chips.push('<span class="' + FILTER_CHIP_BADGE_CLASS + ' badge-secondary">' + escapeHtml(solLabel) +
                   ' <a href="#" class="text-dark clear-solution-chip">x</a></span>');
      }
    }

    if (prio !== 'all') {
      chips.push('<span class="' + FILTER_CHIP_BADGE_CLASS + ' badge-light border">Priority P' + escapeHtml(prio) +
                 ' <a href="#" class="text-dark clear-priority-chip">x</a></span>');
    }
    return chips;
  }

  function renderProblemChips(containerSelector, options = {}) {
    const container = $(containerSelector);
    if (container.length === 0) return;
    const problemType = options.problemType || 'all';
    const solutionFilter = options.solutionFilter || 'all';
    const operators = options.operators || [];
    const priority = options.priority || 'all';
    const chips = [];
    const problemChips = generateProblemChips(problemType, solutionFilter, operators, priority);
    problemChips.forEach(c => chips.push(c));
    const operatorsGroup = generateOperatorChipsHtml(operators, { context: 'problems' });
    if (operatorsGroup) chips.push(operatorsGroup);
    if (chips.length === 0) {
      container.html('<span class="' + FILTER_CHIP_BADGE_CLASS + ' badge-secondary">All Problems</span>');
    } else {
      container.html(chips.join(buildSeparatorChip('AND')));
    }
    container.off('click.filterchips');
    container.on('click.filterchips', 'a.clear-problem-type-chip', function(e) { e.preventDefault(); if (typeof options.onClearProblemType === 'function') { options.onClearProblemType(); } });
    container.on('click.filterchips', 'a.clear-solution-chip', function(e) { e.preventDefault(); if (typeof options.onClearSolution === 'function') { options.onClearSolution(); } });
    container.on('click.filterchips', 'a.clear-priority-chip', function(e) { e.preventDefault(); if (typeof options.onClearPriority === 'function') { options.onClearPriority(); } });
    container.on('click.filterchips', 'a.remove-operator-chip', function(e) { e.preventDefault(); const op = $(this).data('operator'); if (typeof options.onRemoveOperator === 'function') { options.onRemoveOperator(op); } });
  }

  global.FilterChipUtils = { generateOperatorChipsHtml, generateProblemChips, renderProblemChips, buildOrGroupHtml, joinWithAndHtml, buildRemovableChip };
})(window);


