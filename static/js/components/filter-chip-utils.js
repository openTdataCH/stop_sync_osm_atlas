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
          badgeClass: 'filter-chip-operator',
          removeClass: 'remove-filter',
          data: { type: 'atlasOperator', filter: operator }
        }));
      } else {
        chips.push(buildRemovableChip({
          label: 'Operator: ' + operator,
          badgeClass: 'filter-chip-operator',
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
      typeChips.push('<span class="' + FILTER_CHIP_BADGE_CLASS + ' filter-chip-problem-type">' + escapeHtml(displayType) +
                 ' <a href="#" class="text-dark remove-type-chip" data-type="' + escapeHtml(problemType) + '">x</a></span>');
    });

    selectedPriorities.forEach(function(prio) {
      priorityChips.push('<span class="' + FILTER_CHIP_BADGE_CLASS + ' text-bg-light border">Priority P' + escapeHtml(prio) +
                 ' <a href="#" class="text-dark remove-priority-chip" data-priority="' + escapeHtml(prio) + '">x</a></span>');
    });

    const typeGroup = buildOrGroupHtml(typeChips);
    if (typeGroup) groups.push(typeGroup);

    const priorityGroup = buildOrGroupHtml(priorityChips);
    if (priorityGroup) groups.push(priorityGroup);

    if (groups.length === 0 && !hasOperators) {
      groups.push('<span class="' + FILTER_CHIP_BADGE_CLASS + ' filter-chip-secondary">All entries</span>');
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
      container.html('<span class="' + FILTER_CHIP_BADGE_CLASS + ' filter-chip-secondary">All entries</span>');
    } else {
      container.html(joinWithAndHtml(groups));
    }
    container.off('click.filterchips');
    container.on('click.filterchips', 'a.remove-type-chip', function(e) { e.preventDefault(); const type = $(this).data('type'); if (typeof options.onRemoveType === 'function') { options.onRemoveType(type); } });
    container.on('click.filterchips', 'a.remove-priority-chip', function(e) { e.preventDefault(); const priority = $(this).data('priority'); if (typeof options.onRemovePriority === 'function') { options.onRemovePriority(String(priority)); } });
    container.on('click.filterchips', 'a.remove-operator-chip', function(e) { e.preventDefault(); const op = $(this).data('operator'); if (typeof options.onRemoveOperator === 'function') { options.onRemoveOperator(op); } });
    container.on('click.filterchips', 'a.clear-all-problem-chips', function(e) { e.preventDefault(); if (typeof options.onClearAll === 'function') { options.onClearAll(); } });
  }

  function buildDirectionDropdownHtml(options) {
    let direction = options.direction || '';
    // Handle comma-separated directions (common in matched routes where multiple IDs are filtered together)
    if (typeof direction === 'string' && direction.indexOf(',') !== -1) {
      const parts = direction.split(',').map(function(s) { return s.trim(); });
      direction = parts.find(function(p) { return p !== ''; }) || '';
    }
    const mapIndex = options.mapIndex || '';
    const routeLabel = options.routeLabel || '';
    const showClose = options.showClose || false;
    const directionDisplay = direction === '' ? 'Both' : 'Dir: ' + direction;
    
    const dropdownHtml = '<span class="direction-dropdown" data-index="' + escapeHtml(String(mapIndex)) + '" data-current="' + escapeHtml(direction) + '">' +
        '<span class="direction-current">' + escapeHtml(directionDisplay) + '</span><i class="fas fa-chevron-down direction-arrow"></i>' +
        '<div class="direction-options" style="display: none;">' +
        '<div class="direction-option" data-direction="">Both</div>' +
        '<div class="direction-option" data-direction="0">Dir: 0</div>' +
        '<div class="direction-option" data-direction="1">Dir: 1</div>' +
        '</div></span>';
    
    let chipContent = (routeLabel ? escapeHtml(routeLabel) + ' ' : '') + dropdownHtml;
    if (showClose) {
        chipContent += ' <a href="#" class="remove-filter text-dark text-decoration-none ms-1" data-type="station" data-index="' + escapeHtml(String(mapIndex)) + '">×</a>';
    }
        
    return '<span class="' + FILTER_CHIP_BADGE_CLASS + ' filter-chip-secondary shadow-sm" style="pointer-events: auto;">' + chipContent + '</span>';
  }

  function bindDirectionDropdownEvents(onChangeCallback) {
    $(document).off('click.directionDropdownToggle').on('click.directionDropdownToggle', '.direction-dropdown', function (e) {
        if ($(e.target).closest('.direction-option').length) return;
        var dropdown = $(this);
        var options = dropdown.find('.direction-options');
        var arrow = dropdown.find('.direction-arrow');
        
        $('.direction-dropdown.open').not(dropdown).each(function () {
            $(this).find('.direction-options').slideUp(200);
            $(this).find('.direction-arrow').removeClass('rotated');
            $(this).removeClass('open');
        });
        
        if (dropdown.hasClass('open')) {
            options.slideUp(200);
            arrow.removeClass('rotated');
            dropdown.removeClass('open');
        } else {
            options.slideDown(200);
            arrow.addClass('rotated');
            dropdown.addClass('open');
        }
    });

    $(document).off('click.directionDropdownOption').on('click.directionDropdownOption', '.direction-option', function (e) {
        e.stopPropagation();
        var option = $(this);
        var direction = option.data('direction');
        var dropdown = option.closest('.direction-dropdown');
        var mapIndex = dropdown.data('index');
        
        dropdown.attr('data-current', direction);
        var display = direction === '' ? 'Both' : 'Dir: ' + direction;
        dropdown.find('.direction-current').text(display);
        
        dropdown.find('.direction-options').slideUp(200);
        dropdown.find('.direction-arrow').removeClass('rotated');
        dropdown.removeClass('open');
        
        if (typeof onChangeCallback === 'function') {
            onChangeCallback(mapIndex, String(direction));
        }
    });

    $(document).off('click.directionDropdownOutside').on('click.directionDropdownOutside', function (e) {
        if (!$(e.target).closest('.direction-dropdown').length) {
            $('.direction-dropdown.open').each(function () {
                $(this).find('.direction-options').slideUp(200);
                $(this).find('.direction-arrow').removeClass('rotated');
                $(this).removeClass('open');
            });
        }
    });
  }

  global.FilterChipUtils = { generateOperatorChipsHtml, generateProblemChipGroups, renderProblemChips, buildOrGroupHtml, joinWithAndHtml, buildRemovableChip, buildDirectionDropdownHtml, bindDirectionDropdownEvents };
})(window);


