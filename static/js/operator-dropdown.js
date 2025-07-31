/**
 * Operator Dropdown Component
 * 
 * A reusable dropdown component for selecting Atlas operators with search functionality.
 * Supports multiple selection and provides clean UI for filtering by operators.
 */

class OperatorDropdown {
    constructor(container, options = {}) {
        this.container = $(container);
        this.options = {
            placeholder: 'Select operators...',
            multiple: true,
            allowClear: true,
            searchPlaceholder: 'Search operators...',
            onSelectionChange: null, // Callback function
            ...options
        };
        
        this.operators = [];
        this.selectedOperators = [];
        this.isOpen = false;
        
        this.init();
    }
    
    init() {
        this.createHTML();
        this.bindEvents();
        this.loadOperators();
    }
    
    createHTML() {
        const html = `
            <div class="operator-dropdown-container">
                <button type="button" class="operator-dropdown-button" id="${this.getDropdownId()}">
                    <span class="dropdown-text">${this.options.placeholder}</span>
                </button>
                <div class="operator-dropdown-menu" id="${this.getMenuId()}">
                    <input type="text" class="operator-dropdown-search" placeholder="${this.options.searchPlaceholder}">
                    ${this.options.allowClear ? '<div class="operator-dropdown-clear">Clear all</div>' : ''}
                    <div class="operator-dropdown-items"></div>
                </div>
            </div>
        `;
        
        this.container.html(html);
        
        this.button = this.container.find('.operator-dropdown-button');
        this.menu = this.container.find('.operator-dropdown-menu');
        this.searchInput = this.container.find('.operator-dropdown-search');
        this.itemsContainer = this.container.find('.operator-dropdown-items');
        this.clearOption = this.container.find('.operator-dropdown-clear');
    }
    
    bindEvents() {
        // Toggle dropdown
        this.button.on('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            this.toggle();
        });
        
        // Search functionality
        this.searchInput.on('input', (e) => {
            this.filterOperators(e.target.value);
        });
        
        // Clear all functionality
        this.clearOption.on('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            this.clearSelection();
        });
        
        // Close dropdown when clicking outside
        $(document).on('click', (e) => {
            if (!this.container.is(e.target) && this.container.has(e.target).length === 0) {
                this.close();
            }
        });
        
        // Prevent dropdown from closing when clicking inside the menu
        this.menu.on('click', (e) => {
            e.stopPropagation();
        });
        
        // Prevent search input from triggering button click
        this.searchInput.on('click', (e) => {
            e.stopPropagation();
        });
    }
    
    async loadOperators() {
        try {
            const response = await fetch('/api/operators');
            const data = await response.json();
            
            if (data.error) {
                console.error('Error loading operators:', data.error);
                return;
            }
            
            this.operators = data.operators || [];
            this.renderOperatorItems();
        } catch (error) {
            console.error('Failed to load operators:', error);
        }
    }
    
    renderOperatorItems() {
        const itemsHtml = this.operators.map(operator => {
            const isSelected = this.selectedOperators.includes(operator);
            return `
                <div class="operator-dropdown-item ${isSelected ? 'selected' : ''}" data-operator="${operator}">
                    ${this.escapeHtml(operator)}
                </div>
            `;
        }).join('');
        
        this.itemsContainer.html(itemsHtml);
        
        // Bind click events to operator items
        this.itemsContainer.find('.operator-dropdown-item').on('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            
            const operator = $(e.target).data('operator');
            this.toggleOperatorSelection(operator);
        });
    }
    
    filterOperators(searchTerm) {
        const lowerSearchTerm = searchTerm.toLowerCase();
        
        this.itemsContainer.find('.operator-dropdown-item').each((index, element) => {
            const $item = $(element);
            const operator = $item.data('operator').toLowerCase();
            
            if (operator.includes(lowerSearchTerm)) {
                $item.removeClass('hidden').show();
            } else {
                $item.addClass('hidden').hide();
            }
        });
        
        // Show "no results" message if no items are visible
        const visibleItems = this.itemsContainer.find('.operator-dropdown-item:visible');
        let noResultsMsg = this.itemsContainer.find('.operator-dropdown-no-results');
        
        if (visibleItems.length === 0 && searchTerm.trim() !== '') {
            if (noResultsMsg.length === 0) {
                noResultsMsg = $('<div class="operator-dropdown-no-results">No operators found</div>');
                this.itemsContainer.append(noResultsMsg);
            }
            noResultsMsg.show();
        } else {
            noResultsMsg.hide();
        }
    }
    
    toggleOperatorSelection(operator) {
        if (!this.options.multiple) {
            // Single selection mode
            this.selectedOperators = [operator];
            this.close();
        } else {
            // Multiple selection mode
            const index = this.selectedOperators.indexOf(operator);
            if (index > -1) {
                this.selectedOperators.splice(index, 1);
            } else {
                this.selectedOperators.push(operator);
            }
        }
        
        this.updateDisplay();
        this.updateItemStates();
        this.notifyChange();
    }
    
    updateDisplay() {
        const button = this.container.find('.dropdown-text');
        
        if (this.selectedOperators.length === 0) {
            button.text(this.options.placeholder);
            button.removeClass('has-selection');
        } else if (this.selectedOperators.length === 1) {
            button.text(this.selectedOperators[0]);
            button.addClass('has-selection');
        } else {
            button.text(`${this.selectedOperators.length} operators selected`);
            button.addClass('has-selection');
        }
    }
    
    updateItemStates() {
        this.itemsContainer.find('.operator-dropdown-item').each((index, element) => {
            const $item = $(element);
            const operator = $item.data('operator');
            
            if (this.selectedOperators.includes(operator)) {
                $item.addClass('selected');
            } else {
                $item.removeClass('selected');
            }
        });
    }
    
    clearSelection() {
        this.selectedOperators = [];
        this.updateDisplay();
        this.updateItemStates();
        this.notifyChange();
    }
    
    setSelection(operators) {
        this.selectedOperators = Array.isArray(operators) ? [...operators] : [operators];
        this.updateDisplay();
        this.updateItemStates();
    }
    
    getSelection() {
        return [...this.selectedOperators];
    }
    
    toggle() {
        if (this.isOpen) {
            this.close();
        } else {
            this.open();
        }
    }
    
    open() {
        this.menu.addClass('show');
        this.button.addClass('active');
        this.isOpen = true;
        
        // Focus search input and clear it
        setTimeout(() => {
            this.searchInput.focus();
            this.searchInput.val('');
            this.filterOperators(''); // Reset filter
        }, 50);
    }
    
    close() {
        this.menu.removeClass('show');
        this.button.removeClass('active');
        this.isOpen = false;
    }
    
    notifyChange() {
        if (this.options.onSelectionChange && typeof this.options.onSelectionChange === 'function') {
            this.options.onSelectionChange(this.getSelection());
        }
    }
    
    // Utility methods
    getDropdownId() {
        return `operator-dropdown-${Math.random().toString(36).substr(2, 9)}`;
    }
    
    getMenuId() {
        return `operator-menu-${Math.random().toString(36).substr(2, 9)}`;
    }
    
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
    
    // Public API methods
    destroy() {
        $(document).off('click');
        this.container.empty();
    }
    
    refresh() {
        this.loadOperators();
    }
    
    disable() {
        this.button.prop('disabled', true);
        this.button.addClass('disabled');
    }
    
    enable() {
        this.button.prop('disabled', false);
        this.button.removeClass('disabled');
    }
}

// Export for use in other files
window.OperatorDropdown = OperatorDropdown; 