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
     * Requests url and resolves to its JSON answer.
     * params become the query string; empty values are left out and arrays
     * repeat their key. options: signal, method, headers, cache (the fetch
     * cache mode), and body, sent as JSON. A failed answer rejects with an Error carrying status and the
     * parsed body; an aborted request rejects with the browser's AbortError.
     */
    SharedUtils.fetchJson = function(url, params, options) {
        options = options || {};
        const query = new URLSearchParams();
        Object.keys(params || {}).forEach(key => {
            const value = params[key];
            if (value === undefined || value === null || value === '') return;
            (Array.isArray(value) ? value : [value]).forEach(item => query.append(key, String(item)));
        });
        const queryString = query.toString();
        const requestUrl = queryString ? url + (String(url).includes('?') ? '&' : '?') + queryString : url;
        const headers = Object.assign({ Accept: 'application/json' }, options.headers);
        const init = { method: options.method || 'GET', headers: headers, signal: options.signal };
        if (options.cache) init.cache = options.cache;
        if (options.body !== undefined) {
            headers['Content-Type'] = 'application/json';
            init.body = JSON.stringify(options.body);
        }
        return global.fetch(requestUrl, init).then(response => {
            if (response.ok) return response.json();
            return Promise.resolve()
                .then(() => response.json())
                .catch(() => null)
                .then(body => {
                    const serverMessage = body && (body.error || body.message);
                    const error = new Error(serverMessage || 'Request failed with status ' + response.status);
                    error.status = response.status;
                    error.body = body;
                    throw error;
                });
        });
    };

    SharedUtils.isAbortError = error => !!error && error.name === 'AbortError';

    /**
     * The server's error message from a failed request, or the fallback
     * @param {object} error - Error rejected by fetchJson (status, body)
     * @param {string} fallbackMessage - Message used when the response carries none
     * @returns {string} Error message
     */
    SharedUtils.buildErrorMessage = function(error, fallbackMessage) {
        const body = error && error.body;
        return (body && (body.error || body.message)) || fallbackMessage;
    };

    // The breakpoint below which map pages fold their filters into an overlay.
    SharedUtils.isMobileViewport = () => global.matchMedia('(max-width: 768px)').matches;

    // 3725 -> "1h 2m", 65 -> "1m 5s", 7 -> "7s"; "—" when unknown.
    SharedUtils.formatDuration = function(seconds) {
        if (typeof seconds !== 'number' || !Number.isFinite(seconds) || seconds < 0) return '—';
        const rounded = Math.round(seconds);
        const hours = Math.floor(rounded / 3600);
        const minutes = Math.floor((rounded % 3600) / 60);
        const remainder = rounded % 60;
        if (hours) return hours + 'h ' + minutes + 'm';
        if (minutes) return minutes + 'm ' + remainder + 's';
        return remainder + 's';
    };

    // The page scrolls in <body> (base.css) or, elsewhere, in the viewport.
    SharedUtils.isScrolledToBottom = function() {
        return [document.scrollingElement, document.body].some(element => !!element && element.scrollTop > 0
            && element.scrollHeight - element.scrollTop - element.clientHeight < 2);
    };

    // A new element with an optional class and text.
    SharedUtils.element = function(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text != null) node.textContent = text;
        return node;
    };

    // Export to global scope
    global.SharedUtils = SharedUtils;

})(window);
