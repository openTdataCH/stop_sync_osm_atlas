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

    /**
     * Setup CSRF token for AJAX requests
     * Should be called once on page load
     */
    SharedUtils.setupCSRFToken = function() {
        const csrfToken = (document.cookie.match(/\bcsrf_token=([^;]+)/) || [])[1];
        if (!csrfToken) return;

        if (global.$ && typeof global.$.ajaxSetup === 'function') {
            global.$.ajaxSetup({
                headers: {
                    'X-CSRFToken': csrfToken
                }
            });
        }
    };

    /**
     * Build a clear error message based on HTTP status and response body
     * @param {object} xhr - jQuery XHR object
     * @param {string} fallbackMessage - Default message if no specific error is found
     * @param {string} context - Context of the error: 'persist', 'bulk', 'owner', etc.
     * @returns {string} Error message
     */
    SharedUtils.buildErrorMessage = function(xhr, fallbackMessage, context) {
        try {
            const status = xhr && xhr.status;
            const body = (xhr && xhr.responseJSON) ? xhr.responseJSON : null;
            const serverMsg = body && (body.error || body.message);
            
            if (status === 401) {
                if (context === 'persist') return 'Please log in to make data persistent.';
                if (context === 'bulk') return 'Please log in to perform this action.';
                return 'Please log in to continue.';
            }
            
            if (status === 403) {
                if (context === 'owner') return 'Not authorized: only the author or an admin can modify or delete this item.';
                if (context === 'bulk') return 'Not authorized: only admins can perform this action.';
                if (context === 'persist') return 'Not authorized: only the author or an admin can update existing persistent items.';
                return 'Not authorized to perform this action.';
            }
            
            return serverMsg || fallbackMessage;
        } catch (e) {
            return fallbackMessage;
        }
    };

    // Export to global scope
    global.SharedUtils = SharedUtils;

})(window);

