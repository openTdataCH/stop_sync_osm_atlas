/**
 * Configurable lazy popup loading for Leaflet markers.
 *
 * Transport, URL construction, payload interpretation, and popup presentation
 * are injected by page adapters. This component owns request deduplication,
 * marker lifetime checks, optional caching, retry, and cleanup.
 */
(function (global) {
    'use strict';

    var namespace = global.MapComponents = global.MapComponents || {};

    function copyOptions(base, overrides) {
        var result = {};
        Object.keys(base || {}).forEach(function (key) { result[key] = base[key]; });
        Object.keys(overrides || {}).forEach(function (key) { result[key] = overrides[key]; });
        return result;
    }

    function cacheMode(value) {
        if (value === false || value === null) return false;
        if (value === 'content') return 'content';
        return 'payload';
    }

    function makeAbortController() {
        if (typeof global.AbortController === 'function') {
            return new global.AbortController();
        }
        return {
            signal: undefined,
            abort: function () {}
        };
    }

    function isAbort(error, controller) {
        return !!(
            (error && error.name === 'AbortError') ||
            (controller && controller.signal && controller.signal.aborted)
        );
    }

    function validateMarker(marker) {
        if (!marker || typeof marker.on !== 'function' || typeof marker.off !== 'function' ||
                typeof marker.bindPopup !== 'function' || typeof marker.openPopup !== 'function') {
            throw new Error('MapPopupController requires a Leaflet marker with popup and event methods.');
        }
    }

    function validateBindingOptions(options) {
        if (!options || options.key == null || options.key === '') {
            throw new Error('MapPopupController.attach() requires a stable entity key.');
        }
        if (typeof options.load !== 'function') {
            throw new Error('MapPopupController requires a load() callback for key "' + options.key + '".');
        }
        if (typeof options.render !== 'function') {
            throw new Error('MapPopupController requires a render() callback for key "' + options.key + '".');
        }
    }

    function create(defaultOptions) {
        defaultOptions = copyOptions({
            cache: 'payload',
            event: 'click',
            retainCacheOnDetach: false,
            errorContent: 'Unable to load details. Click the marker to retry.'
        }, defaultOptions || {});

        var bindings = new Map();
        var bindingsByKey = new Map();
        var requests = new Map();
        var cache = new Map();
        var destroyed = false;

        function assertActive() {
            if (destroyed) {
                throw new Error('MapPopupController has been destroyed.');
            }
        }

        function getKeyBindings(key) {
            var keyBindings = bindingsByKey.get(key);
            if (!keyBindings) {
                keyBindings = new Set();
                bindingsByKey.set(key, keyBindings);
            }
            return keyBindings;
        }

        function isCurrent(binding, generation) {
            return !destroyed && binding.active && binding.generation === generation &&
                bindings.get(binding.marker) === binding;
        }

        function popupContext(binding) {
            return {
                key: binding.key,
                marker: binding.marker
            };
        }

        function bindContent(binding, content, generation) {
            if (!isCurrent(binding, generation)) return false;
            var popup = typeof binding.options.createPopup === 'function'
                ? binding.options.createPopup(content, popupContext(binding))
                : content;
            if (popup == null) {
                throw new Error('MapPopupController createPopup() returned no popup for key "' + binding.key + '".');
            }
            if (!isCurrent(binding, generation)) return false;
            if (binding.marker.closePopup && binding.marker.getPopup && binding.marker.getPopup()) binding.marker.closePopup();
            binding.marker.bindPopup(popup);
            binding.loaded = true;
            binding.content = content;
            binding.marker.openPopup();
            return true;
        }

        function hasLoadedPopup(binding) {
            return binding.loaded && (
                typeof binding.marker.getPopup !== 'function' ||
                binding.marker.getPopup()
            );
        }

        function showTransientContent(binding, content, generation) {
            if (content == null || content === false || !isCurrent(binding, generation)) return;
            try {
                var rendered = typeof content === 'function'
                    ? content(popupContext(binding))
                    : content;
                if (rendered == null || rendered === false) return;
                var popup = typeof binding.options.createPopup === 'function'
                    ? binding.options.createPopup(rendered, popupContext(binding))
                    : rendered;
                if (!isCurrent(binding, generation)) return;
                if (binding.marker.closePopup && binding.marker.getPopup && binding.marker.getPopup()) binding.marker.closePopup();
                binding.marker.bindPopup(popup);
                binding.marker.openPopup();
            } catch (error) {
                if (global.console && typeof global.console.error === 'function') {
                    global.console.error('Failed to render popup state.', error);
                }
            }
        }

        function startRequest(binding) {
            var existing = requests.get(binding.key);
            if (existing) return existing;

            var controller = makeAbortController();
            var request = {
                key: binding.key,
                controller: controller,
                promise: null
            };
            requests.set(binding.key, request);

            var result;
            try {
                result = binding.options.load({
                    key: binding.key,
                    marker: binding.marker,
                    signal: controller.signal
                });
            } catch (error) {
                result = Promise.reject(error);
            }

            request.promise = Promise.resolve(result).then(function (payload) {
                if (requests.get(binding.key) === request && !destroyed) {
                    if (cacheMode(binding.options.cache) === 'payload') {
                        cache.set(binding.key, { kind: 'payload', value: payload });
                    }
                    requests.delete(binding.key);
                }
                return payload;
            }).catch(function (error) {
                if (requests.get(binding.key) === request) {
                    requests.delete(binding.key);
                }
                throw error;
            });

            return request;
        }

        function resolveContent(binding, generation) {
            var cached = cache.get(binding.key);
            if (cached && cached.kind === 'content') {
                return Promise.resolve(cached.value);
            }

            var payloadPromise;
            if (cached && cached.kind === 'payload') {
                payloadPromise = Promise.resolve(cached.value);
            } else {
                payloadPromise = startRequest(binding).promise;
            }

            return payloadPromise.then(function (payload) {
                return Promise.resolve(binding.options.render(payload, popupContext(binding)));
            }).then(function (content) {
                if (cacheMode(binding.options.cache) === 'content' && isCurrent(binding, generation)) {
                    cache.set(binding.key, { kind: 'content', value: content });
                }
                return content;
            });
        }

        function openBinding(binding) {
            if (!binding || !binding.active || destroyed) {
                return Promise.resolve({ status: 'removed' });
            }
            if (hasLoadedPopup(binding)) {
                binding.marker.openPopup();
                return Promise.resolve({ status: 'opened' });
            }
            if (binding.openingPromise) return binding.openingPromise;

            var generation = binding.generation;

            var promise = resolveContent(binding, generation).then(function (content) {
                if (!isCurrent(binding, generation)) {
                    return { status: 'removed' };
                }
                bindContent(binding, content, generation);
                return { status: 'loaded', content: content };
            }).catch(function (error) {
                if (!isCurrent(binding, generation)) {
                    return { status: 'removed', error: error };
                }
                var request = requests.get(binding.key);
                if (isAbort(error, request && request.controller)) {
                    return { status: 'aborted', error: error };
                }
                if (typeof binding.options.onError === 'function') {
                    binding.options.onError(error, popupContext(binding));
                }
                showTransientContent(binding, binding.options.errorContent, generation);
                return { status: 'error', error: error };
            });

            var trackedPromise = promise.then(function (result) {
                if (binding.openingPromise === trackedPromise) {
                    binding.openingPromise = null;
                }
                return result;
            });
            binding.openingPromise = trackedPromise;
            return trackedPromise;
        }

        function makeHandle(binding) {
            return {
                marker: binding.marker,
                key: binding.key,
                open: function () { return openBinding(binding); },
                detach: function () { detach(binding.marker); },
                update: function (options) { return attach(binding.marker, options); }
            };
        }

        function attach(marker, bindingOptions) {
            assertActive();
            validateMarker(marker);
            var existing = bindings.get(marker);
            var merged;

            if (existing && String(bindingOptions && bindingOptions.key) === existing.key) {
                merged = copyOptions(existing.options, bindingOptions || {});
                validateBindingOptions(merged);
                var nextEvent = merged.event || 'click';
                if (nextEvent !== existing.event) {
                    marker.off(existing.event, existing.handler);
                    existing.event = nextEvent;
                    marker.on(existing.event, existing.handler);
                }
                existing.options = merged;
                return makeHandle(existing);
            }

            if (existing) detach(marker);
            merged = copyOptions(defaultOptions, bindingOptions || {});
            validateBindingOptions(merged);

            var binding = {
                marker: marker,
                key: String(merged.key),
                options: merged,
                event: merged.event || 'click',
                handler: null,
                active: true,
                loaded: false,
                content: null,
                openingPromise: null,
                generation: 0
            };
            binding.handler = function () {
                // bindPopup() installs Leaflet's own click handler after this
                // lazy-loading handler. Once content is loaded, let Leaflet own
                // click-to-open/toggle behavior; opening here first would make
                // Leaflet immediately interpret the same click as a close.
                if (binding.event === 'click' && hasLoadedPopup(binding)) return;
                openBinding(binding);
            };

            bindings.set(marker, binding);
            getKeyBindings(binding.key).add(binding);
            marker.on(binding.event, binding.handler);
            return makeHandle(binding);
        }

        function abortRequestForKey(key) {
            var request = requests.get(key);
            if (!request) return;
            requests.delete(key);
            try {
                request.controller.abort();
            } catch (error) {
                // The lifetime check still prevents a late result from opening.
            }
        }

        function detach(marker) {
            var binding = bindings.get(marker);
            if (!binding) return false;

            binding.active = false;
            binding.generation += 1;
            binding.openingPromise = null;
            marker.off(binding.event, binding.handler);
            if (typeof marker.closePopup === 'function') marker.closePopup();
            if (typeof marker.unbindPopup === 'function') marker.unbindPopup();
            bindings.delete(marker);

            var keyBindings = bindingsByKey.get(binding.key);
            if (keyBindings) {
                keyBindings.delete(binding);
                if (keyBindings.size === 0) {
                    bindingsByKey.delete(binding.key);
                    abortRequestForKey(binding.key);
                    if (!binding.options.retainCacheOnDetach) {
                        cache.delete(binding.key);
                    }
                }
            }
            return true;
        }

        function transfer(oldMarker, replacementMarker) {
            assertActive();
            var oldBinding = bindings.get(oldMarker);
            var replacementBinding = bindings.get(replacementMarker);
            if (!oldBinding || !replacementBinding || oldBinding.key !== replacementBinding.key) {
                throw new Error('MapPopupController.transfer() requires two attached markers with the same entity key.');
            }

            var wasOpen = typeof oldMarker.isPopupOpen === 'function' && oldMarker.isPopupOpen();
            detach(oldMarker);
            if (wasOpen) return openBinding(replacementBinding);
            return Promise.resolve({ status: 'transferred' });
        }

        function remove(key) {
            key = String(key);
            var keyBindings = bindingsByKey.get(key);
            if (keyBindings) {
                Array.from(keyBindings).forEach(function (binding) {
                    detach(binding.marker);
                });
            }
            abortRequestForKey(key);
            cache.delete(key);
        }

        function resetBinding(binding) {
            binding.generation += 1;
            binding.loaded = false;
            binding.content = null;
            binding.openingPromise = null;
            if (typeof binding.marker.closePopup === 'function') binding.marker.closePopup();
            if (typeof binding.marker.unbindPopup === 'function') binding.marker.unbindPopup();
        }

        function invalidate(key) {
            if (key != null) {
                key = String(key);
                abortRequestForKey(key);
                cache.delete(key);
                var keyBindings = bindingsByKey.get(key);
                if (keyBindings) Array.from(keyBindings).forEach(resetBinding);
                return;
            }

            Array.from(requests.keys()).forEach(abortRequestForKey);
            cache.clear();
            Array.from(bindings.values()).forEach(resetBinding);
        }

        function destroy() {
            if (destroyed) return;
            Array.from(bindings.keys()).forEach(detach);
            Array.from(requests.keys()).forEach(abortRequestForKey);
            cache.clear();
            destroyed = true;
        }

        return {
            attach: attach,
            open: function (marker) { return openBinding(bindings.get(marker)); },
            transfer: transfer,
            detach: detach,
            remove: remove,
            invalidate: invalidate,
            destroy: destroy,
            has: function (marker) { return bindings.has(marker); },
            isLoading: function (key) { return requests.has(String(key)); }
        };
    }

    namespace.MapPopupController = {
        create: create
    };
})(window);
