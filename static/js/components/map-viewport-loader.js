/**
 * Coordinates bounds-driven map requests without knowing their URL or payload.
 */
(function (global) {
    'use strict';

    var namespace = global.MapComponents = global.MapComponents || {};

    function assertFunction(value, name) {
        if (typeof value !== 'function') {
            throw new Error('MapViewportLoader requires options.' + name + ' to be a function.');
        }
    }

    function normalizeEvents(events) {
        if (Array.isArray(events)) return events.slice();
        return String(events || 'moveend zoomend').split(/\s+/).filter(Boolean);
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

    function create(options) {
        options = options || {};
        var map = options.map;
        if (!map || typeof map.getBounds !== 'function' || typeof map.getZoom !== 'function' ||
                typeof map.on !== 'function' || typeof map.off !== 'function') {
            throw new Error('MapViewportLoader requires a Leaflet map with bounds, zoom, on(), and off().');
        }
        assertFunction(options.load, 'load');
        assertFunction(options.onData, 'onData');

        var events = normalizeEvents(options.events);
        var debounceMs = Math.max(0, Number(options.debounceMs) || 0);
        var timerId = null;
        var sequence = 0;
        var activeRequest = null;
        var cacheEntry = null;
        var pauseCount = 0;
        var destroyed = false;

        function clearTimer() {
            if (timerId != null) {
                global.clearTimeout(timerId);
                timerId = null;
            }
        }

        function abortActive() {
            if (!activeRequest) return;
            try {
                activeRequest.controller.abort();
            } catch (error) {
                // Aborting is best-effort. Sequence checks remain authoritative.
            }
            activeRequest = null;
        }

        function supersede() {
            sequence += 1;
            abortActive();
        }

        function buildContext(reason, force) {
            var bounds = map.getBounds();
            var zoom = map.getZoom();
            var requestBounds = bounds;
            var baseContext = {
                map: map,
                bounds: bounds,
                zoom: zoom,
                reason: reason,
                force: !!force
            };

            if (typeof options.buildRequestBounds === 'function') {
                requestBounds = options.buildRequestBounds(baseContext);
            } else if (options.bufferRatio != null && bounds && typeof bounds.pad === 'function') {
                requestBounds = bounds.pad(Number(options.bufferRatio) || 0);
            }

            baseContext.requestBounds = requestBounds;
            baseContext.identity = typeof options.getRequestIdentity === 'function'
                ? options.getRequestIdentity(baseContext)
                : null;
            return baseContext;
        }

        function reportError(error, context) {
            if (typeof options.onError === 'function') {
                options.onError(error, context);
            }
        }

        function commitCached(entry, context, requestSequence) {
            context.sequence = requestSequence;
            context.signal = null;
            context.cacheHit = true;
            try {
                options.onData(entry.data, context);
                return Promise.resolve({ status: 'cached', data: entry.data, context: context });
            } catch (error) {
                reportError(error, context);
                return Promise.resolve({ status: 'error', error: error, context: context });
            }
        }

        function execute(reason, force) {
            clearTimer();
            if (destroyed) {
                return Promise.resolve({ status: 'destroyed' });
            }
            if (pauseCount > 0) {
                return Promise.resolve({ status: 'paused' });
            }

            supersede();
            var requestSequence = sequence;
            var context;
            try {
                context = buildContext(reason || 'reload', force);
            } catch (error) {
                reportError(error, { map: map, reason: reason || 'reload', sequence: requestSequence });
                return Promise.resolve({ status: 'error', error: error });
            }

            if (!force && cacheEntry && cacheEntry.identity === context.identity &&
                    typeof options.shouldReuse === 'function' &&
                    options.shouldReuse(cacheEntry, context)) {
                return commitCached(cacheEntry, context, requestSequence);
            }

            var controller = makeAbortController();
            context.sequence = requestSequence;
            context.signal = controller.signal;
            context.cacheHit = false;
            activeRequest = {
                sequence: requestSequence,
                controller: controller
            };

            var loadPromise;
            try {
                loadPromise = Promise.resolve(options.load(context));
            } catch (error) {
                loadPromise = Promise.reject(error);
            }

            return loadPromise.then(function (data) {
                if (destroyed || requestSequence !== sequence) {
                    return { status: 'stale', data: data, context: context };
                }

                options.onData(data, context);
                if (destroyed || requestSequence !== sequence) {
                    return { status: 'stale', data: data, context: context };
                }

                cacheEntry = {
                    data: data,
                    bounds: context.bounds,
                    requestBounds: context.requestBounds,
                    zoom: context.zoom,
                    identity: context.identity
                };
                return { status: 'loaded', data: data, context: context };
            }).catch(function (error) {
                if (destroyed || requestSequence !== sequence || isAbort(error, controller)) {
                    return { status: 'stale', error: error, context: context };
                }
                reportError(error, context);
                return { status: 'error', error: error, context: context };
            }).then(function (result) {
                if (activeRequest && activeRequest.sequence === requestSequence) {
                    activeRequest = null;
                }
                return result;
            });
        }

        function shouldSchedule(event) {
            if (destroyed || pauseCount > 0) return false;
            if (typeof options.shouldLoad === 'function') {
                return options.shouldLoad({
                    map: map,
                    event: event,
                    reason: event && event.type ? event.type : 'map-event'
                }) !== false;
            }
            return true;
        }

        function schedule(event) {
            if (!shouldSchedule(event)) return;
            clearTimer();
            // A viewport event makes the in-flight request obsolete immediately,
            // rather than only after the debounce delay has elapsed.
            supersede();
            var reason = event && event.type ? event.type : 'map-event';
            timerId = global.setTimeout(function () {
                timerId = null;
                execute(reason, false);
            }, debounceMs);
        }

        events.forEach(function (eventName) {
            map.on(eventName, schedule);
        });

        function reload(reloadOptions) {
            reloadOptions = reloadOptions || {};
            if (typeof reloadOptions === 'boolean') {
                reloadOptions = { force: reloadOptions };
            }
            return execute(reloadOptions.reason || 'reload', !!reloadOptions.force);
        }

        function invalidate() {
            if (destroyed) return;
            clearTimer();
            cacheEntry = null;
            supersede();
        }

        function pause() {
            if (destroyed) {
                return function () {};
            }
            pauseCount += 1;
            var resumed = false;
            return function (resumeOptions) {
                if (resumed || destroyed) return;
                resumed = true;
                pauseCount = Math.max(0, pauseCount - 1);
                if (resumeOptions && resumeOptions.reload && pauseCount === 0) {
                    reload({
                        force: !!resumeOptions.force,
                        reason: resumeOptions.reason || 'resume'
                    });
                }
            };
        }

        function destroy() {
            if (destroyed) return;
            destroyed = true;
            clearTimer();
            supersede();
            cacheEntry = null;
            events.forEach(function (eventName) {
                map.off(eventName, schedule);
            });
        }

        return {
            reload: reload,
            invalidate: invalidate,
            pause: pause,
            destroy: destroy,
            getCache: function () { return cacheEntry; },
            isLoading: function () { return !!activeRequest; },
            isPaused: function () { return pauseCount > 0; }
        };
    }

    namespace.MapViewportLoader = {
        create: create
    };
})(window);
