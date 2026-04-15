/**
 * jQuery-lite compatibility shim.
 *
 * This removes the external jQuery runtime dependency while preserving
 * existing call sites during native migration.
 */
(function (global) {
    'use strict';

    var eventRegistry = new WeakMap();
    var ajaxDefaults = { headers: {} };

    function isElement(node) {
        return !!node && (node.nodeType === 1 || node === window || node === document);
    }

    function parseEventName(eventName) {
        var parts = String(eventName || '').split('.');
        return {
            type: parts[0] || '',
            namespace: parts.slice(1).join('.')
        };
    }

    function normalizeDataKey(key) {
        return String(key || '').replace(/-([a-z])/g, function (_m, c) {
            return c.toUpperCase();
        });
    }

    function toKebabCase(key) {
        return String(key || '').replace(/[A-Z]/g, function (m) {
            return '-' + m.toLowerCase();
        });
    }

    function isVisible(node) {
        if (!node || node.nodeType !== 1) return false;
        if (node.style && node.style.display === 'none') return false;
        if (node.hidden) return false;
        if (node.offsetWidth || node.offsetHeight || node.getClientRects().length) return true;
        return false;
    }

    function selectNodes(root, selector) {
        if (!root || !selector) return [];

        var sel = String(selector).trim();
        if (!sel) return [];

        // jQuery pseudo-classes used in this codebase that are not valid CSS selectors.
        if (sel.indexOf(':selected') >= 0) {
            sel = sel.replace(/:selected/g, ':checked');
        }

        var wantsVisible = sel.indexOf(':visible') >= 0;
        if (wantsVisible) {
            sel = sel.replace(/:visible/g, '');
        }

        var nodes = [];
        try {
            nodes = Array.prototype.slice.call(root.querySelectorAll(sel));
        } catch (e) {
            nodes = [];
        }

        if (wantsVisible) {
            nodes = nodes.filter(isVisible);
        }

        return nodes;
    }

    function parseHtml(html) {
        var template = document.createElement('template');
        template.innerHTML = String(html || '').trim();
        return Array.prototype.slice.call(template.content.childNodes).filter(function (n) {
            return n.nodeType === 1 || n.nodeType === 3;
        });
    }

    function uniqueNodes(nodes) {
        var seen = new Set();
        var out = [];
        (nodes || []).forEach(function (n) {
            if (!n || seen.has(n)) return;
            seen.add(n);
            out.push(n);
        });
        return out;
    }

    function normalizeNodes(input, context) {
        if (input instanceof JQueryLite) {
            return input.get();
        }

        if (input == null) {
            return [];
        }

        if (typeof input === 'function') {
            if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', input, { once: true });
            } else {
                input();
            }
            return [document];
        }

        if (typeof input === 'string') {
            var trimmed = input.trim();
            if (!trimmed) return [];

            if (trimmed.charAt(0) === '<' && trimmed.charAt(trimmed.length - 1) === '>') {
                return parseHtml(trimmed);
            }

            var root = context && context.nodeType ? context : document;
            return selectNodes(root, trimmed);
        }

        if (isElement(input)) {
            return [input];
        }

        if (Array.isArray(input)) {
            return input.filter(Boolean);
        }

        if (typeof NodeList !== 'undefined' && input instanceof NodeList) {
            return Array.prototype.slice.call(input);
        }

        if (typeof HTMLCollection !== 'undefined' && input instanceof HTMLCollection) {
            return Array.prototype.slice.call(input);
        }

        return [];
    }

    function getStoredHandlers(node) {
        if (!eventRegistry.has(node)) {
            eventRegistry.set(node, []);
        }
        return eventRegistry.get(node);
    }

    function JQueryLite(nodes) {
        this._nodes = uniqueNodes(nodes || []);
        this.length = this._nodes.length;
    }

    JQueryLite.prototype.get = function (index) {
        if (index === undefined) {
            return this._nodes.slice();
        }
        if (index < 0) {
            return this._nodes[this._nodes.length + index];
        }
        return this._nodes[index];
    };

    JQueryLite.prototype.first = function () {
        return $(this._nodes.length > 0 ? this._nodes[0] : null);
    };

    JQueryLite.prototype.each = function (callback) {
        this._nodes.forEach(function (node, index) {
            callback.call(node, index, node);
        });
        return this;
    };

    JQueryLite.prototype.map = function (callback) {
        var out = this._nodes.map(function (node, index) {
            return callback.call(node, index, node);
        });
        return {
            get: function (index) {
                if (index === undefined) return out.slice();
                return out[index];
            }
        };
    };

    JQueryLite.prototype.filter = function (selectorOrCallback) {
        if (typeof selectorOrCallback === 'function') {
            return $(this._nodes.filter(function (node, index) {
                return !!selectorOrCallback.call(node, index, node);
            }));
        }

        var selector = String(selectorOrCallback || '').trim();
        if (!selector) return $(this._nodes);

        if (selector === ':checked') {
            return $(this._nodes.filter(function (n) { return !!n.checked; }));
        }
        if (selector === ':visible') {
            return $(this._nodes.filter(isVisible));
        }
        if (selector === ':disabled') {
            return $(this._nodes.filter(function (n) { return !!n.disabled; }));
        }

        return $(this._nodes.filter(function (node) {
            return !!(node.matches && node.matches(selector));
        }));
    };

    JQueryLite.prototype.not = function (selectorOrElements) {
        if (typeof selectorOrElements === 'string') {
            var selector = selectorOrElements.trim();
            return $(this._nodes.filter(function (node) {
                return !(node.matches && node.matches(selector));
            }));
        }

        var excluded = new Set(normalizeNodes(selectorOrElements));
        return $(this._nodes.filter(function (node) {
            return !excluded.has(node);
        }));
    };

    JQueryLite.prototype.find = function (selector) {
        var out = [];
        this._nodes.forEach(function (node) {
            if (!node || !node.querySelectorAll) return;
            out = out.concat(selectNodes(node, selector));
        });
        return $(out);
    };

    JQueryLite.prototype.closest = function (selector) {
        return $(this._nodes.map(function (node) {
            return node && node.closest ? node.closest(selector) : null;
        }).filter(Boolean));
    };

    JQueryLite.prototype.prev = function (selector) {
        var out = this._nodes.map(function (node) {
            return node ? node.previousElementSibling : null;
        }).filter(Boolean);
        if (selector) {
            out = out.filter(function (node) {
                return node.matches && node.matches(selector);
            });
        }
        return $(out);
    };

    JQueryLite.prototype.has = function (target) {
        var targetNode = normalizeNodes(target)[0];
        if (!targetNode) return $([]);
        return $(this._nodes.filter(function (node) {
            return !!(node.contains && node.contains(targetNode));
        }));
    };

    JQueryLite.prototype.is = function (selectorOrElement) {
        if (this.length === 0) return false;
        var node = this._nodes[0];

        if (typeof selectorOrElement === 'string') {
            var selector = selectorOrElement.trim();
            if (selector === ':checked') return !!node.checked;
            if (selector === ':visible') return isVisible(node);
            if (selector === ':disabled') return !!node.disabled;
            if (selector === 'option:selected') return !!node.selected;
            return !!(node.matches && node.matches(selector));
        }

        var target = normalizeNodes(selectorOrElement)[0];
        return node === target;
    };

    JQueryLite.prototype.addClass = function (className) {
        var classes = String(className || '').split(/\s+/).filter(Boolean);
        return this.each(function () {
            if (!this.classList) return;
            classes.forEach(function (c) { this.classList.add(c); }, this);
        });
    };

    JQueryLite.prototype.removeClass = function (className) {
        var classes = String(className || '').split(/\s+/).filter(Boolean);
        return this.each(function () {
            if (!this.classList) return;
            classes.forEach(function (c) { this.classList.remove(c); }, this);
        });
    };

    JQueryLite.prototype.toggleClass = function (className, force) {
        return this.each(function () {
            if (!this.classList) return;
            if (force === undefined) {
                this.classList.toggle(className);
            } else {
                this.classList.toggle(className, !!force);
            }
        });
    };

    JQueryLite.prototype.hasClass = function (className) {
        if (this.length === 0) return false;
        return !!(this._nodes[0].classList && this._nodes[0].classList.contains(className));
    };

    JQueryLite.prototype.attr = function (name, value) {
        if (value === undefined) {
            if (this.length === 0) return undefined;
            return this._nodes[0].getAttribute(name);
        }
        return this.each(function () {
            this.setAttribute(name, value);
        });
    };

    JQueryLite.prototype.prop = function (name, value) {
        if (value === undefined) {
            if (this.length === 0) return undefined;
            return this._nodes[0][name];
        }
        return this.each(function () {
            this[name] = value;
        });
    };

    JQueryLite.prototype.data = function (key, value) {
        var dataKey = normalizeDataKey(key);
        var attrName = 'data-' + toKebabCase(dataKey);

        if (value === undefined) {
            if (this.length === 0) return undefined;
            var node = this._nodes[0];
            if (node.dataset && Object.prototype.hasOwnProperty.call(node.dataset, dataKey)) {
                return node.dataset[dataKey];
            }
            return node.getAttribute ? node.getAttribute(attrName) : undefined;
        }

        return this.each(function () {
            if (this.dataset) {
                this.dataset[dataKey] = value;
            } else if (this.setAttribute) {
                this.setAttribute(attrName, value);
            }
        });
    };

    JQueryLite.prototype.val = function (value) {
        if (value === undefined) {
            if (this.length === 0) return undefined;
            return this._nodes[0].value;
        }
        return this.each(function () {
            this.value = value;
        });
    };

    JQueryLite.prototype.text = function (value) {
        if (value === undefined) {
            if (this.length === 0) return undefined;
            return this._nodes[0].textContent;
        }
        return this.each(function () {
            this.textContent = value;
        });
    };

    JQueryLite.prototype.html = function (value) {
        if (value === undefined) {
            if (this.length === 0) return undefined;
            return this._nodes[0].innerHTML;
        }
        return this.each(function () {
            this.innerHTML = value;
        });
    };

    JQueryLite.prototype.css = function (prop, value) {
        if (typeof prop === 'string' && value === undefined) {
            if (this.length === 0) return undefined;
            return this._nodes[0].style[prop] || global.getComputedStyle(this._nodes[0])[prop];
        }

        if (typeof prop === 'object' && prop) {
            var self = this;
            Object.keys(prop).forEach(function (k) {
                self.css(k, prop[k]);
            });
            return this;
        }

        return this.each(function () {
            this.style[prop] = value;
        });
    };

    JQueryLite.prototype.show = function () {
        return this.each(function () {
            var prev = this.dataset ? this.dataset.jqPrevDisplay : '';
            this.style.display = prev || '';
            if (global.getComputedStyle(this).display === 'none') {
                this.style.display = 'block';
            }
        });
    };

    JQueryLite.prototype.hide = function () {
        return this.each(function () {
            if (this.dataset) {
                this.dataset.jqPrevDisplay = this.style.display || '';
            }
            this.style.display = 'none';
        });
    };

    JQueryLite.prototype.toggle = function (state) {
        if (state === undefined) {
            return this.each(function () {
                if (isVisible(this)) {
                    $(this).hide();
                } else {
                    $(this).show();
                }
            });
        }
        return state ? this.show() : this.hide();
    };

    JQueryLite.prototype.append = function (content) {
        var addNodes = normalizeNodes(content);
        if (addNodes.length === 0 && typeof content === 'string') {
            addNodes = parseHtml(content);
        }

        return this.each(function (parentIndex) {
            addNodes.forEach(function (node) {
                var toInsert = parentIndex === 0 ? node : node.cloneNode(true);
                this.appendChild(toInsert);
            }, this);
        });
    };

    JQueryLite.prototype.empty = function () {
        return this.each(function () {
            this.innerHTML = '';
        });
    };

    JQueryLite.prototype.remove = function () {
        return this.each(function () {
            if (this.parentNode) {
                this.parentNode.removeChild(this);
            }
        });
    };

    JQueryLite.prototype.width = function () {
        if (this.length === 0) return undefined;
        var node = this._nodes[0];
        if (node === global) return global.innerWidth;
        if (node.getBoundingClientRect) return node.getBoundingClientRect().width;
        return undefined;
    };

    JQueryLite.prototype.offset = function () {
        if (this.length === 0) return undefined;
        var node = this._nodes[0];
        if (!node.getBoundingClientRect) return undefined;
        var rect = node.getBoundingClientRect();
        return {
            top: rect.top + global.pageYOffset,
            left: rect.left + global.pageXOffset
        };
    };

    JQueryLite.prototype.trigger = function (eventOrName, extraParameters) {
        return this.each(function () {
            var evt;
            if (typeof eventOrName === 'object' && eventOrName !== null && eventOrName.type) {
                // Not ideal for multiple elements, but allow it for BS5 internal passes
                evt = eventOrName;
            } else {
                var fullName = String(eventOrName || '');
                var parsed = parseEventName(fullName);
                var type = fullName.indexOf('.') >= 0 ? fullName : (parsed.type || fullName);
                if (!type) return;
                try {
                    evt = new Event(type, { bubbles: true, cancelable: true });
                } catch (e) {
                    evt = document.createEvent('Event');
                    evt.initEvent(type, true, true);
                }
            }
            this.dispatchEvent(evt);
        });
    };

    JQueryLite.prototype.click = function (handler) {
        if (typeof handler === 'function') {
            return this.on('click', handler);
        }
        return this.trigger('click');
    };

    JQueryLite.prototype.ready = function (handler) {
        if (typeof handler !== 'function') return this;
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', handler, { once: true });
        } else {
            handler();
        }
        return this;
    };

    JQueryLite.prototype.animate = function (props, duration, complete) {
        var done = typeof complete === 'function' ? complete : null;
        var ms = typeof duration === 'number' ? duration : 0;

        this.each(function () {
            if (!props || props.scrollTop === undefined) return;
            var current = this.scrollTop || 0;
            var target = props.scrollTop;

            if (typeof target === 'string' && /^([+-])=\d+$/.test(target)) {
                var delta = parseInt(target.slice(2), 10);
                if (target.charAt(0) === '-') {
                    target = current - delta;
                } else {
                    target = current + delta;
                }
            }

            if (typeof target === 'number') {
                this.scrollTop = target;
            }
        });

        if (done) {
            setTimeout(done, ms);
        }
        return this;
    };

    JQueryLite.prototype.slideUp = function (_duration) {
        return this.hide();
    };

    JQueryLite.prototype.slideDown = function (_duration) {
        return this.show();
    };

    JQueryLite.prototype.on = function (events, selectorOrHandler, maybeHandler) {
        var selector = typeof selectorOrHandler === 'string' ? selectorOrHandler : null;
        var handler = selector ? maybeHandler : selectorOrHandler;
        if (typeof handler !== 'function') return this;

        var eventList = String(events || '').split(/\s+/).filter(Boolean);
        if (eventList.length === 0) return this;

        return this.each(function () {
            var node = this;
            var stored = getStoredHandlers(node);

            eventList.forEach(function (eventName) {
                var parsed = parseEventName(eventName);
                if (!parsed.type) return;

                var listenTypes = [parsed.type];
                // Bootstrap 5 emits events with dotted names (e.g. shown.bs.dropdown).
                // Register both base and full names so we support dotted native events
                // and jQuery-style namespaced events.
                if (eventName.indexOf('.') >= 0 && eventName !== parsed.type) {
                    listenTypes.push(eventName);
                }

                var wrapped = function (event) {
                    if (selector) {
                        var matched = event.target && event.target.closest ? event.target.closest(selector) : null;
                        if (!matched || !(node.contains ? node.contains(matched) : matched === node)) {
                            return;
                        }
                        event.delegateTarget = node;
                        handler.call(matched, event);
                        return;
                    }
                    handler.call(node, event);
                };

                listenTypes.forEach(function (listenType) {
                    node.addEventListener(listenType, wrapped);
                    stored.push({
                        type: parsed.type,
                        namespace: parsed.namespace,
                        selector: selector,
                        original: handler,
                        wrapped: wrapped,
                        listenType: listenType
                    });
                });
            });
        });
    };

    JQueryLite.prototype.off = function (events, handler) {
        var hasEvents = events !== undefined && events !== null && String(events).trim() !== '';
        var eventList = hasEvents ? String(events).split(/\s+/).filter(Boolean).map(parseEventName) : [];

        return this.each(function () {
            var node = this;
            var stored = getStoredHandlers(node);

            var keep = [];
            stored.forEach(function (entry) {
                var matchesEvent = !hasEvents;

                if (hasEvents) {
                    matchesEvent = eventList.some(function (ev) {
                        if (ev.type && entry.type !== ev.type) return false;
                        if (ev.namespace && entry.namespace !== ev.namespace) return false;
                        if (!ev.type && !ev.namespace) return true;
                        return true;
                    });
                }

                var matchesHandler = !handler || entry.original === handler;

                if (matchesEvent && matchesHandler) {
                    node.removeEventListener(entry.listenType || entry.type, entry.wrapped);
                } else {
                    keep.push(entry);
                }
            });

            eventRegistry.set(node, keep);
        });
    };

    function toQueryString(params) {
        if (!params || typeof params !== 'object') return '';
        var searchParams = new URLSearchParams();
        Object.keys(params).forEach(function (key) {
            var value = params[key];
            if (value === undefined || value === null || value === '') return;
            if (Array.isArray(value)) {
                value.forEach(function (item) {
                    searchParams.append(key, String(item));
                });
                return;
            }
            searchParams.append(key, String(value));
        });
        return searchParams.toString();
    }

    function createDeferredJqXHR() {
        var doneCbs = [];
        var failCbs = [];
        var alwaysCbs = [];
        var completed = false;
        var succeeded = false;
        var successArgs = null;
        var failArgs = null;

        var jqXHR = {
            readyState: 1,
            status: 0,
            responseText: '',
            responseJSON: null,
            aborted: false,
            done: function (cb) {
                if (typeof cb !== 'function') return jqXHR;
                if (completed && succeeded) {
                    cb.apply(null, successArgs || []);
                } else {
                    doneCbs.push(cb);
                }
                return jqXHR;
            },
            fail: function (cb) {
                if (typeof cb !== 'function') return jqXHR;
                if (completed && !succeeded) {
                    cb.apply(null, failArgs || []);
                } else {
                    failCbs.push(cb);
                }
                return jqXHR;
            },
            always: function (cb) {
                if (typeof cb !== 'function') return jqXHR;
                if (completed) {
                    cb.apply(null, succeeded ? (successArgs || []) : (failArgs || []));
                } else {
                    alwaysCbs.push(cb);
                }
                return jqXHR;
            }
        };

        return {
            jqXHR: jqXHR,
            resolve: function (args) {
                if (completed) return;
                completed = true;
                succeeded = true;
                jqXHR.readyState = 4;
                successArgs = args || [];
                doneCbs.forEach(function (cb) { cb.apply(null, successArgs); });
                alwaysCbs.forEach(function (cb) { cb.apply(null, successArgs); });
            },
            reject: function (args) {
                if (completed) return;
                completed = true;
                succeeded = false;
                jqXHR.readyState = 4;
                failArgs = args || [];
                failCbs.forEach(function (cb) { cb.apply(null, failArgs); });
                alwaysCbs.forEach(function (cb) { cb.apply(null, failArgs); });
            }
        };
    }

    function normalizeAjaxError(err) {
        if (!err) {
            return { status: 0, message: 'Request failed' };
        }
        if (err.status !== undefined) {
            return err;
        }
        return {
            status: 0,
            message: err.message || 'Request failed'
        };
    }

    function ajax(options) {
        options = options || {};
        var method = String(options.method || options.type || 'GET').toUpperCase();
        var url = options.url || '';
        var data = options.data;
        var headers = Object.assign({}, ajaxDefaults.headers, options.headers || {});

        var isGetLike = method === 'GET' || method === 'HEAD';

        if (isGetLike && data && typeof data === 'object') {
            var query = toQueryString(data);
            if (query) {
                url += (url.indexOf('?') >= 0 ? '&' : '?') + query;
            }
            data = null;
        }

        if (options.cache === false) {
            url += (url.indexOf('?') >= 0 ? '&' : '?') + '_ts=' + Date.now();
        }

        var body = null;
        if (!isGetLike && data !== undefined && data !== null) {
            if (typeof data === 'string') {
                body = data;
            } else {
                var contentType = options.contentType || headers['Content-Type'];
                if (!contentType) {
                    contentType = 'application/json';
                }
                headers['Content-Type'] = contentType;

                if (contentType.indexOf('application/json') >= 0) {
                    body = JSON.stringify(data);
                } else {
                    body = String(data);
                }
            }
        }

        var deferred = createDeferredJqXHR();
        var jqXHR = deferred.jqXHR;
        var controller = new AbortController();
        var timeoutHandle = null;

        jqXHR.abort = function () {
            if (jqXHR.readyState === 4) return jqXHR;
            jqXHR.aborted = true;
            controller.abort();
            return jqXHR;
        };

        if (options.timeout && Number(options.timeout) > 0) {
            timeoutHandle = setTimeout(function () {
                jqXHR.abort();
            }, Number(options.timeout));
        }

        fetch(url, {
            method: method,
            headers: headers,
            body: body,
            signal: controller.signal
        }).then(function (response) {
            jqXHR.status = response.status;
            return response.text().then(function (text) {
                jqXHR.responseText = text;
                var json = null;
                if (text) {
                    try {
                        json = JSON.parse(text);
                    } catch (e) {
                        json = null;
                    }
                }
                jqXHR.responseJSON = json;

                if (!response.ok) {
                    throw {
                        status: response.status,
                        responseText: text,
                        responseJSON: json,
                        message: (json && (json.error || json.message)) || ('Request failed with status ' + response.status)
                    };
                }

                var payload = json;
                if (payload === null) {
                    payload = text;
                }

                if (typeof options.success === 'function') {
                    options.success(payload, 'success', jqXHR);
                }
                if (typeof options.complete === 'function') {
                    options.complete(jqXHR, 'success');
                }
                deferred.resolve([payload, 'success', jqXHR]);
            });
        }).catch(function (rawErr) {
            var err = normalizeAjaxError(rawErr);
            var textStatus = jqXHR.aborted ? 'abort' : 'error';
            var errorThrown = jqXHR.aborted ? 'abort' : (err.message || 'error');

            if (err.status !== undefined) {
                jqXHR.status = err.status;
            }
            if (err.responseText !== undefined) {
                jqXHR.responseText = err.responseText;
            }
            if (err.responseJSON !== undefined) {
                jqXHR.responseJSON = err.responseJSON;
            }

            if (typeof options.error === 'function') {
                options.error(jqXHR, textStatus, errorThrown);
            }
            if (typeof options.complete === 'function') {
                options.complete(jqXHR, textStatus);
            }
            deferred.reject([jqXHR, textStatus, errorThrown]);
        }).finally(function () {
            if (timeoutHandle) {
                clearTimeout(timeoutHandle);
            }
        });

        return jqXHR;
    }

    function $(input, context) {
        return new JQueryLite(normalizeNodes(input, context));
    }



    $.ajaxSetup = function (config) {
        config = config || {};
        if (config.headers && typeof config.headers === 'object') {
            ajaxDefaults.headers = Object.assign({}, ajaxDefaults.headers, config.headers);
        }
    };

    $.ajax = ajax;

    $.getJSON = function (url, data, success) {
        if (typeof data === 'function') {
            success = data;
            data = undefined;
        }
        return ajax({
            url: url,
            method: 'GET',
            data: data,
            cache: false,
            success: success
        });
    };

    $.get = function (url, data, success) {
        if (typeof data === 'function') {
            success = data;
            data = undefined;
        }
        return ajax({
            url: url,
            method: 'GET',
            data: data,
            success: success
        });
    };

    $.post = function (url, data, success) {
        if (typeof data === 'function') {
            success = data;
            data = undefined;
        }
        return ajax({
            url: url,
            method: 'POST',
            data: data,
            success: success
        });
    };

    global.$ = $;
})(window);
