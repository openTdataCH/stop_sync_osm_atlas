/**
 * Shared utility functions used across the application
 */
(function(global) {
    'use strict';

    const SharedUtils = {};

    /**
     * Escape HTML to prevent XSS attacks
     * @param {string|null} text - Text to escape
     * @returns {string} Escaped HTML string
     */
    SharedUtils.escapeHtml = function(text) {
        const div = document.createElement('div');
        div.textContent = text == null ? '' : String(text);
        return div.innerHTML;
    };

    // Presentation labels stay separate from the app's compatibility field names.
    SharedUtils.sourceLabel = () => String((global.ReviewConfig || {}).source_label || 'ATLAS');
    SharedUtils.sourceIdLabel = () => String((global.ReviewConfig || {}).source_id_label || 'SLOID');
    SharedUtils.sourceLabelHtml = () => SharedUtils.escapeHtml(SharedUtils.sourceLabel());
    SharedUtils.sourceIdLabelHtml = () => SharedUtils.escapeHtml(SharedUtils.sourceIdLabel());
    // 49452 -> "49,452": counts shown to people, grouped by thousands.
    SharedUtils.formatCount = value => Number(value || 0).toLocaleString('en-US');
    SharedUtils.hasCapability = name => (global.ReviewConfig || {}).capabilities?.[name] !== false;

    SharedUtils.sourceUrl = function(data) {
        const template = (global.ReviewConfig || {}).source_url_template;
        if (!template) return null;
        let complete = true;
        const url = template.replace(/\{(id|sloid|uic_ref)\}/g, (_, key) => {
            const value = key === 'id' ? (data.sloid ?? data.id) : data[key];
            if (value == null || value === '') complete = false;
            return encodeURIComponent(value ?? '');
        });
        return complete && /^https?:\/\//i.test(url) ? url : null;
    };

    /**
     * Display a temporary message to the user
     * @param {string} message - Message to display (can include HTML)
     * @param {string} type - Message type: 'success', 'error', 'warning', 'info'
     * @param {number} duration - Duration in milliseconds (default: 3000)
     */
    SharedUtils.showTemporaryMessage = function(message, type, duration) {
        type = type || 'info';
        duration = duration || 3000;
        
        const alertClass = type === 'success' ? 'alert-success' : 
                          type === 'error' ? 'alert-danger' : 
                          type === 'warning' ? 'alert-warning' : 'alert-info';
        
        const icon = type === 'success' ? 'fas fa-check-circle' : 
                    type === 'error' ? 'fas fa-exclamation-circle' : 
                    type === 'warning' ? 'fas fa-exclamation-triangle' : 'fas fa-info-circle';
        
        const messageContainer = document.createElement('div');
        messageContainer.className = 'temporary-message alert ' + alertClass;
        messageContainer.innerHTML = '<i class="' + icon + '"></i> ' + message;

        document.body.appendChild(messageContainer);

        // Align with existing toast CSS: show first, then animate out and remove.
        requestAnimationFrame(function () {
            messageContainer.classList.add('show');
        });

        setTimeout(function () {
            let removed = false;
            const remove = function () {
                if (removed) return;
                removed = true;
                if (messageContainer.parentNode) {
                    messageContainer.parentNode.removeChild(messageContainer);
                }
            };

            messageContainer.style.animation = 'toastSlideOut var(--transition-slow) ease-in forwards';
            messageContainer.addEventListener('animationend', remove, { once: true });
            // Fallback if animation is unavailable.
            setTimeout(remove, 500);
        }, duration);
    };

    // Tells the user something without blocking the page, as a toast: the app never
    // uses alert(). text is plain text; showTemporaryMessage takes HTML.
    SharedUtils.notify = function(text, type) {
        SharedUtils.showTemporaryMessage(SharedUtils.escapeHtml(text), type || 'warning', 4000);
    };

    /**
     * The server's error message from a failed request, or the fallback
     * @param {object} xhr - jQuery XHR object
     * @param {string} fallbackMessage - Message used when the response carries none
     * @returns {string} Error message
     */
    SharedUtils.buildErrorMessage = function(xhr, fallbackMessage) {
        const body = (xhr && xhr.responseJSON) ? xhr.responseJSON : null;
        return (body && (body.error || body.message)) || fallbackMessage;
    };

    // Export to global scope
    global.SharedUtils = SharedUtils;

})(window);
