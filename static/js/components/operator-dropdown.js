// Operator Dropdown Component (moved to components)
class OperatorDropdown {
    constructor(container, options = {}) {
        this.container = typeof container === 'string' ? document.querySelector(container) : container;
        this.options = {
            placeholder: 'Select operators...',
            multiple: true,
            allowClear: true,
            searchPlaceholder: 'Search operators...',
            apiUrl: '/api/atlas_operators',
            onSelectionChange: null,
            ...options
        };
        this.operators = [];
        this.selectedOperators = [];
        this.isOpen = false;
        // Aborting it removes every listener the dropdown added.
        this.listeners = new AbortController();
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
        this.container.innerHTML = html;
        this.button = this.container.querySelector('.operator-dropdown-button');
        this.menu = this.container.querySelector('.operator-dropdown-menu');
        this.searchInput = this.container.querySelector('.operator-dropdown-search');
        this.itemsContainer = this.container.querySelector('.operator-dropdown-items');
        this.clearOption = this.container.querySelector('.operator-dropdown-clear');
    }
    bindEvents() {
        const opts = { signal: this.listeners.signal };
        this.button.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); this.toggle(); }, opts);
        this.searchInput.addEventListener('input', (e) => { this.filterOperators(e.target.value); }, opts);
        if (this.clearOption) {
            this.clearOption.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); this.clearSelection(); }, opts);
        }
        document.addEventListener('click', (e) => {
            if (!this.container.contains(e.target)) this.close();
        }, opts);
        this.menu.addEventListener('click', (e) => { e.stopPropagation(); }, opts);
        this.itemsContainer.addEventListener('click', (e) => {
            const item = e.target.closest('.operator-dropdown-item');
            if (!item) return;
            e.preventDefault();
            this.toggleOperatorSelection(item.dataset.operator);
        }, opts);
    }
    async loadOperators() {
        try {
            const data = await SharedUtils.fetchJson(this.options.apiUrl);
            this.operators = data.operators || [];
            this.renderOperatorItems();
        } catch (error) { console.error('Failed to load operators:', error); }
    }
    renderOperatorItems() {
        this.itemsContainer.innerHTML = this.operators.map(operator => {
            const isSelected = this.selectedOperators.includes(operator);
            return `<div class="operator-dropdown-item ${isSelected ? 'selected' : ''}" data-operator="${this.escapeHtml(operator)}">${this.escapeHtml(operator)}</div>`;
        }).join('');
    }
    items() { return Array.from(this.itemsContainer.querySelectorAll('.operator-dropdown-item')); }
    filterOperators(searchTerm) {
        const safeSearchTerm = String(searchTerm || '');
        const lowerSearchTerm = safeSearchTerm.toLowerCase();
        let visibleCount = 0;
        this.items().forEach(item => {
            const matches = (item.dataset.operator || '').toLowerCase().includes(lowerSearchTerm);
            item.classList.toggle('hidden', !matches);
            if (matches) visibleCount++;
        });
        let noResultsMsg = this.itemsContainer.querySelector('.operator-dropdown-no-results');
        if (visibleCount === 0 && safeSearchTerm.trim() !== '') {
            if (!noResultsMsg) {
                noResultsMsg = SharedUtils.element('div', 'operator-dropdown-no-results', 'No operators found');
                this.itemsContainer.appendChild(noResultsMsg);
            }
            noResultsMsg.hidden = false;
        } else if (noResultsMsg) { noResultsMsg.hidden = true; }
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
        const text = this.container.querySelector('.dropdown-text');
        const count = this.selectedOperators.length;
        text.textContent = count === 0 ? this.options.placeholder
            : count === 1 ? this.selectedOperators[0]
                : `${count} operators selected`;
        text.classList.toggle('has-selection', count > 0);
    }
    updateItemStates() {
        this.items().forEach(item => {
            item.classList.toggle('selected', this.selectedOperators.includes(item.dataset.operator));
        });
    }
    clearSelection() { this.selectedOperators = []; this.updateDisplay(); this.updateItemStates(); this.notifyChange(); }
    setSelection(operators) { this.selectedOperators = Array.isArray(operators) ? [...operators] : [operators]; this.updateDisplay(); this.updateItemStates(); }
    getSelection() { return [...this.selectedOperators]; }
    toggle() { this.isOpen ? this.close() : this.open(); }
    open() {
        this.menu.classList.add('show'); this.button.classList.add('active'); this.isOpen = true;
        setTimeout(() => { this.searchInput.focus(); this.searchInput.value = ''; this.filterOperators(''); }, 50);
    }
    close() { this.menu.classList.remove('show'); this.button.classList.remove('active'); this.isOpen = false; }
    notifyChange() { if (typeof this.options.onSelectionChange === 'function') { this.options.onSelectionChange(this.getSelection()); } }
    getDropdownId() { return `operator-dropdown-${Math.random().toString(36).slice(2, 11)}`; }
    getMenuId() { return `operator-menu-${Math.random().toString(36).slice(2, 11)}`; }
    escapeHtml(text) { return SharedUtils.escapeHtml(text); }
    destroy() {
        this.listeners.abort();
        this.container.innerHTML = '';
    }
}
window.OperatorDropdown = OperatorDropdown;
