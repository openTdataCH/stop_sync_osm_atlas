// Operator Dropdown Component (moved to components)
class OperatorDropdown {
    constructor(container, options = {}) {
        this.container = $(container);
        this.options = {
            placeholder: 'Select operators...',
            multiple: true,
            allowClear: true,
            searchPlaceholder: 'Search operators...',
            onSelectionChange: null,
            ...options
        };
        this.operators = [];
        this.selectedOperators = [];
        this.isOpen = false;
        this.eventNamespace = '.operatorDropdown-' + Math.random().toString(36).slice(2, 9);
        this.boundDocumentClick = null;
        this.init();
    }
    init() { this.createHTML(); this.bindEvents(); this.loadOperators(); }
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
            </div>`;
        this.container.html(html);
        this.button = this.container.find('.operator-dropdown-button');
        this.menu = this.container.find('.operator-dropdown-menu');
        this.searchInput = this.container.find('.operator-dropdown-search');
        this.itemsContainer = this.container.find('.operator-dropdown-items');
        this.clearOption = this.container.find('.operator-dropdown-clear');
    }
    bindEvents() {
        const ns = this.eventNamespace;
        this.button.on('click' + ns, (e) => { e.preventDefault(); e.stopPropagation(); this.toggle(); });
        this.searchInput.on('input' + ns, (e) => { this.filterOperators(e.target.value); });
        this.clearOption.on('click' + ns, (e) => { e.preventDefault(); e.stopPropagation(); this.clearSelection(); });
        this.boundDocumentClick = (e) => {
            if (!this.container.is(e.target) && this.container.has(e.target).length === 0) this.close();
        };
        $(document).on('click' + ns, this.boundDocumentClick);
        this.menu.on('click' + ns, (e) => { e.stopPropagation(); });
        this.searchInput.on('click' + ns, (e) => { e.stopPropagation(); });
    }
    async loadOperators() {
        try {
            const response = await fetch('/api/operators');
            const data = await response.json();
            if (data.error) { console.error('Error loading operators:', data.error); return; }
            this.operators = data.operators || [];
            this.renderOperatorItems();
        } catch (error) { console.error('Failed to load operators:', error); }
    }
    renderOperatorItems() {
        const itemsHtml = this.operators.map(operator => {
            const isSelected = this.selectedOperators.includes(operator);
            return `<div class="operator-dropdown-item ${isSelected ? 'selected' : ''}" data-operator="${this.escapeHtml(operator)}">${this.escapeHtml(operator)}</div>`;
        }).join('');
        this.itemsContainer.html(itemsHtml);
        this.itemsContainer.find('.operator-dropdown-item').on('click' + this.eventNamespace, (e) => {
            e.preventDefault(); e.stopPropagation();
            const operator = $(e.target).data('operator');
            this.toggleOperatorSelection(operator);
        });
    }
    filterOperators(searchTerm) {
        const safeSearchTerm = String(searchTerm || '');
        const lowerSearchTerm = safeSearchTerm.toLowerCase();
        this.itemsContainer.find('.operator-dropdown-item').each((index, element) => {
            const $item = $(element);
            const operator = ($item.data('operator') || '').toLowerCase();
            if (operator.includes(lowerSearchTerm)) { $item.removeClass('hidden').show(); }
            else { $item.addClass('hidden').hide(); }
        });
        const visibleItems = this.itemsContainer.find('.operator-dropdown-item:visible');
        let noResultsMsg = this.itemsContainer.find('.operator-dropdown-no-results');
        if (visibleItems.length === 0 && safeSearchTerm.trim() !== '') {
            if (noResultsMsg.length === 0) {
                noResultsMsg = $('<div class="operator-dropdown-no-results">No operators found</div>');
                this.itemsContainer.append(noResultsMsg);
            }
            noResultsMsg.show();
        } else { noResultsMsg.hide(); }
    }
    toggleOperatorSelection(operator) {
        if (!this.options.multiple) { this.selectedOperators = [operator]; this.close(); }
        else {
            const index = this.selectedOperators.indexOf(operator);
            if (index > -1) { this.selectedOperators.splice(index, 1); }
            else { this.selectedOperators.push(operator); }
        }
        this.updateDisplay(); this.updateItemStates(); this.notifyChange();
    }
    updateDisplay() {
        const button = this.container.find('.dropdown-text');
        if (this.selectedOperators.length === 0) { button.text(this.options.placeholder).removeClass('has-selection'); }
        else if (this.selectedOperators.length === 1) { button.text(this.selectedOperators[0]).addClass('has-selection'); }
        else { button.text(`${this.selectedOperators.length} operators selected`).addClass('has-selection'); }
    }
    updateItemStates() {
        this.itemsContainer.find('.operator-dropdown-item').each((index, element) => {
            const $item = $(element);
            const operator = $item.data('operator');
            if (this.selectedOperators.includes(operator)) $item.addClass('selected');
            else $item.removeClass('selected');
        });
    }
    clearSelection() { this.selectedOperators = []; this.updateDisplay(); this.updateItemStates(); this.notifyChange(); }
    setSelection(operators) { this.selectedOperators = Array.isArray(operators) ? [...operators] : [operators]; this.updateDisplay(); this.updateItemStates(); }
    getSelection() { return [...this.selectedOperators]; }
    toggle() { this.isOpen ? this.close() : this.open(); }
    open() { this.menu.addClass('show'); this.button.addClass('active'); this.isOpen = true; setTimeout(() => { this.searchInput.focus().val(''); this.filterOperators(''); }, 50); }
    close() { this.menu.removeClass('show'); this.button.removeClass('active'); this.isOpen = false; }
    notifyChange() { if (this.options.onSelectionChange && typeof this.options.onSelectionChange === 'function') { this.options.onSelectionChange(this.getSelection()); } }
    getDropdownId() { return `operator-dropdown-${Math.random().toString(36).slice(2, 11)}`; }
    getMenuId() { return `operator-menu-${Math.random().toString(36).slice(2, 11)}`; }
    escapeHtml(text) { return SharedUtils.escapeHtml(text); }
    destroy() {
        const ns = this.eventNamespace;
        this.button.off(ns);
        this.searchInput.off(ns);
        this.clearOption.off(ns);
        this.menu.off(ns);
        this.itemsContainer.off(ns);
        if (this.boundDocumentClick) {
            $(document).off('click' + ns, this.boundDocumentClick);
            this.boundDocumentClick = null;
        }
        this.container.empty();
    }
    refresh() { this.loadOperators(); }
    disable() { this.button.prop('disabled', true).addClass('disabled'); }
    enable() { this.button.prop('disabled', false).removeClass('disabled'); }
}
window.OperatorDropdown = OperatorDropdown;


