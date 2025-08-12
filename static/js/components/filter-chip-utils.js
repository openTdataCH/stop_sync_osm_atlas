(function(global) {
  'use strict';

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text == null ? '' : String(text);
    return div.innerHTML;
  }

  function buildOrGroupHtml(chipsArray) {
    if (!chipsArray || chipsArray.length === 0) return '';
    if (chipsArray.length === 1) return chipsArray[0];
    return '(' + chipsArray.join(' <span class="filter-chip-operator">OR</span> ') + ')';
  }

  function generateOperatorChipsHtml(operators, options = {}) {
    const context = options.context || 'index';
    const chips = [];
    (operators || []).forEach(function(operator) {
      const safeOp = escapeHtml(operator);
      if (context === 'index') {
        const chip = '<span class="badge badge-info mr-1 mb-1">Operator: ' + safeOp +
          ' <a href="#" class="text-dark remove-filter" data-type="atlasOperator" data-filter="' + safeOp + '">x</a></span>';
        chips.push(chip);
      } else {
        const chip = '<span class="badge badge-info mr-1 mb-1">Operator: ' + safeOp +
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
      chips.push('<span class="badge badge-secondary mr-1 mb-1">All Problems</span>');
        }
      } else {
        const solLabel = sol.replace(/\b\w/g, function(l){return l.toUpperCase();});
        chips.push('<span class="badge badge-secondary mr-1 mb-1">' + escapeHtml(solLabel) +
                   ' <a href="#" class="text-dark clear-solution-chip">x</a></span>');
      }
    } else {
      const displayType = (problemType || 'all').replace(/_/g, ' ').replace(/\b\w/g, function(l){return l.toUpperCase();});
      chips.push('<span class="badge badge-primary mr-1 mb-1">' + escapeHtml(displayType) +
                 ' <a href="#" class="text-dark clear-problem-type-chip">x</a></span>');
      if (sol !== 'all') {
        const solLabel = sol.replace(/\b\w/g, function(l){return l.toUpperCase();});
        chips.push('<span class="badge badge-secondary mr-1 mb-1">' + escapeHtml(solLabel) +
                   ' <a href="#" class="text-dark clear-solution-chip">x</a></span>');
      }
    }

    if (prio !== 'all') {
      chips.push('<span class="badge badge-light border mr-1 mb-1">Priority P' + escapeHtml(prio) +
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
      container.html('<span class="badge badge-secondary mr-1 mb-1">All Problems</span>');
    } else {
      container.html(chips.join(' <span class="filter-chip-operator">AND</span> '));
    }
    container.off('click.filterchips');
    container.on('click.filterchips', 'a.clear-problem-type-chip', function(e) { e.preventDefault(); if (typeof options.onClearProblemType === 'function') { options.onClearProblemType(); } });
    container.on('click.filterchips', 'a.clear-solution-chip', function(e) { e.preventDefault(); if (typeof options.onClearSolution === 'function') { options.onClearSolution(); } });
    container.on('click.filterchips', 'a.clear-priority-chip', function(e) { e.preventDefault(); if (typeof options.onClearPriority === 'function') { options.onClearPriority(); } });
    container.on('click.filterchips', 'a.remove-operator-chip', function(e) { e.preventDefault(); const op = $(this).data('operator'); if (typeof options.onRemoveOperator === 'function') { options.onRemoveOperator(op); } });
  }

  global.FilterChipUtils = { generateOperatorChipsHtml, generateProblemChips, renderProblemChips };
})(window);


