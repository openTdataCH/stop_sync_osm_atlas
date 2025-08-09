// filter-chip-utils.js - Shared utilities to render filter chips across pages
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

  // Generate operator chips HTML for different contexts
  // context: 'index' (uses existing remove-filter convention), 'problems' (custom handler)
  function generateOperatorChipsHtml(operators, options = {}) {
    const context = options.context || 'index';
    const chips = [];
    (operators || []).forEach(function(operator) {
      const safeOp = escapeHtml(operator);
      if (context === 'index') {
        // Match existing markup to keep existing remove handlers working
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

  // Build problem filter chips according to rules:
  // - If problemType === 'all' and solutionFilter === 'all':
  //   - Show 'All Problems' chip (no X) unless operators are selected, in which case show nothing
  // - If problemType === 'all' and solutionFilter in {'solved','unsolved'}:
  //   - Show only 'Solved'/'Unsolved' chip (with X to clear solution)
  // - If problemType !== 'all':
  //   - Show type chip (with X) and, if solutionFilter != 'all', also a separate 'Solved'/'Unsolved' chip
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

    // Priority chip (shown when not 'all')
    if (prio !== 'all') {
      chips.push('<span class="badge badge-light border mr-1 mb-1">Priority P' + escapeHtml(prio) +
                 ' <a href="#" class="text-dark clear-priority-chip">x</a></span>');
    }
    return chips;
  }

  // Render chips for the problems page into a container
  // options: { problemType, solutionFilter, operators, onClearProblemType, onRemoveOperator }
  function renderProblemChips(containerSelector, options = {}) {
    const container = $(containerSelector);
    if (container.length === 0) return;

    const problemType = options.problemType || 'all';
    const solutionFilter = options.solutionFilter || 'all';
    const operators = options.operators || [];
    const priority = options.priority || 'all';

    const chips = [];
    // Problem chips (may be 0, 1, or 2 depending on rules)
    const problemChips = generateProblemChips(problemType, solutionFilter, operators, priority);
    problemChips.forEach(c => chips.push(c));
    const operatorsGroup = generateOperatorChipsHtml(operators, { context: 'problems' });
    if (operatorsGroup) chips.push(operatorsGroup);

    if (chips.length === 0) {
      container.html('<span class="badge badge-secondary mr-1 mb-1">All Problems</span>');
    } else {
      container.html(chips.join(' <span class="filter-chip-operator">AND</span> '));
    }

    // Bind events (delegated within the container)
    container.off('click.filterchips');
    container.on('click.filterchips', 'a.clear-problem-type-chip', function(e) {
      e.preventDefault();
      if (typeof options.onClearProblemType === 'function') {
        options.onClearProblemType();
      }
    });
    container.on('click.filterchips', 'a.clear-solution-chip', function(e) {
      e.preventDefault();
      if (typeof options.onClearSolution === 'function') {
        options.onClearSolution();
      }
    });
    container.on('click.filterchips', 'a.clear-priority-chip', function(e) {
      e.preventDefault();
      if (typeof options.onClearPriority === 'function') {
        options.onClearPriority();
      }
    });
    container.on('click.filterchips', 'a.remove-operator-chip', function(e) {
      e.preventDefault();
      const op = $(this).data('operator');
      if (typeof options.onRemoveOperator === 'function') {
        options.onRemoveOperator(op);
      }
    });
  }

  global.FilterChipUtils = {
    generateOperatorChipsHtml,
    generateProblemChips,
    renderProblemChips
  };

})(window);


