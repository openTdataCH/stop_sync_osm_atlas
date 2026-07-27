/**
 * Small Leaflet map factory with explicit configuration and cleanup.
 */
(function (global) {
    'use strict';

    var namespace = global.MapComponents = global.MapComponents || {};

    function copyObject(source) {
        var result = {};
        Object.keys(source || {}).forEach(function (key) {
            result[key] = source[key];
        });
        return result;
    }

    function requireLeaflet() {
        if (!global.L || typeof global.L.map !== 'function' || typeof global.L.layerGroup !== 'function') {
            throw new Error('MapCore requires Leaflet to be loaded first.');
        }
        return global.L;
    }

    function normalizeControlOptions(value) {
        if (!value) return null;
        return value === true ? {} : copyObject(value);
    }

    function addLayerToMap(map, layer) {
        if (!layer) return;
        if (typeof layer.addTo === 'function') {
            layer.addTo(map);
        } else if (typeof map.addLayer === 'function') {
            map.addLayer(layer);
        } else {
            throw new Error('MapCore received a layer that cannot be added to the map.');
        }
    }

    function defaultBaseLayers() {
        if (!global.MapShared || typeof global.MapShared.createBaseTileLayers !== 'function') {
            throw new Error('MapCore requires MapShared.createBaseTileLayers() when options.baseLayers is omitted.');
        }
        var shared = global.MapShared.createBaseTileLayers();
        return {
            OpenStreetMap: shared.osm,
            'Transport Map': shared.transport,
            Satellite: shared.satellite
        };
    }

    function resolveBaseLayers(option, map) {
        if (option === false) return {};
        var layers = typeof option === 'function' ? option(map) : option;
        if (layers == null) return defaultBaseLayers();
        if (layers.osm && layers.transport && layers.satellite &&
                !layers.OpenStreetMap && !layers['Transport Map'] && !layers.Satellite) {
            return {
                OpenStreetMap: layers.osm,
                'Transport Map': layers.transport,
                Satellite: layers.satellite
            };
        }
        return copyObject(layers);
    }

    function resolvePadding(policy, zoom, map) {
        var value = typeof policy === 'function' ? policy(zoom, map) : policy;
        value = Number(value);
        if (!Number.isFinite(value) || value < 0) {
            throw new Error('MapCore rendererPadding must resolve to a non-negative number.');
        }
        return value;
    }

    function createPopupBehavior(map, option) {
        if (!option) return function () {};
        var config = option === true ? {} : option;
        var openPopups = new Set();

        function update() {
            var updateAll = config.updateAllLines;
            if (!updateAll && namespace.PopupLines && typeof namespace.PopupLines.updateAll === 'function') {
                updateAll = namespace.PopupLines.updateAll;
            }
            if (typeof updateAll === 'function') updateAll(map);
            openPopups.forEach(function (popup) {
                if (popup && typeof popup._updatePosition === 'function') {
                    popup._updatePosition();
                }
            });
        }

        function onOpen(event) {
            if (event && event.popup) openPopups.add(event.popup);
        }

        function onClose(event) {
            var popup = event && event.popup;
            if (!popup) return;
            openPopups.delete(popup);
            if (popup._line && typeof popup._removeLine === 'function') {
                try {
                    popup._removeLine();
                } catch (error) {
                    // Popup teardown should not prevent the map from closing it.
                }
            }
        }

        map.on('popupopen', onOpen);
        map.on('popupclose', onClose);
        map.on('move', update);
        map.on('zoom', update);

        return function () {
            map.off('popupopen', onOpen);
            map.off('popupclose', onClose);
            map.off('move', update);
            map.off('zoom', update);
            openPopups.forEach(function (popup) {
                if (popup && popup._line && typeof popup._removeLine === 'function') {
                    try {
                        popup._removeLine();
                    } catch (error) {
                        // Continue cleaning up the remaining popups.
                    }
                }
            });
            openPopups.clear();
        };
    }

    function create(options) {
        options = options || {};
        var L = requireLeaflet();
        var container = options.container || options.element;
        if (!container) {
            throw new Error('MapCore requires options.container.');
        }

        var view = options.view || {};
        var center = view.center != null ? view.center : options.center;
        var zoom = view.zoom != null ? view.zoom : options.zoom;
        var mapOptions = copyObject(options.mapOptions);
        var configuredControls = options.controls || {};

        // An explicitly configured zoom control replaces Leaflet's built-in
        // control; otherwise Leaflet would render two controls.
        if (configuredControls.zoom) {
            mapOptions.zoomControl = false;
        }

        if (options.rendererPadding != null && !mapOptions.renderer) {
            if (typeof L.svg !== 'function') {
                throw new Error('MapCore rendererPadding requires Leaflet SVG support.');
            }
            var initialPadding = options.initialRendererPadding != null
                ? resolvePadding(options.initialRendererPadding, zoom, null)
                : (typeof options.rendererPadding === 'function'
                    ? 0.1
                    : resolvePadding(options.rendererPadding, zoom, null));
            mapOptions.renderer = L.svg({
                padding: initialPadding
            });
        }

        var map = L.map(container, mapOptions);
        if (center != null && zoom != null) {
            map.setView(center, zoom);
        }

        var cleanup = [];
        var controls = {};
        var destroyed = false;
        var baseLayers = resolveBaseLayers(options.baseLayers, map);
        var baseLayerNames = Object.keys(baseLayers);
        var defaultBase = options.defaultBaseLayer;
        if (typeof defaultBase === 'string') {
            if (!Object.prototype.hasOwnProperty.call(baseLayers, defaultBase)) {
                throw new Error('MapCore defaultBaseLayer "' + defaultBase + '" does not exist.');
            }
            defaultBase = baseLayers[defaultBase];
        }
        if (!defaultBase && baseLayerNames.length > 0) defaultBase = baseLayers[baseLayerNames[0]];
        if (defaultBase) addLayerToMap(map, defaultBase);

        var layers = {};
        var overlayControlLayers = {};
        var layerConfigs = options.layerGroups || options.layers || {};
        Object.keys(layerConfigs).forEach(function (name) {
            var supplied = layerConfigs[name];
            var config = supplied === true ? {} : (supplied || {});
            var isLayer = supplied && typeof supplied.addTo === 'function' &&
                typeof supplied.addLayer === 'function';
            var layer;

            if (isLayer) {
                layer = supplied;
                config = {};
            } else if (config.layer) {
                layer = config.layer;
            } else if (typeof config.factory === 'function') {
                layer = config.factory({ map: map, name: name });
            } else {
                layer = L.layerGroup(config.initialLayers || [], config.options);
            }

            if (!layer) {
                throw new Error('MapCore could not create layer group "' + name + '".');
            }
            layers[name] = layer;
            if (config.visible !== false) addLayerToMap(map, layer);

            var label = config.controlLabel || config.label;
            if (label || config.showInControl) {
                overlayControlLayers[label || name] = layer;
            }
        });

        var zoomControlOptions = normalizeControlOptions(configuredControls.zoom);
        if (zoomControlOptions) {
            if (!L.control || typeof L.control.zoom !== 'function') {
                throw new Error('MapCore zoom control requires Leaflet L.control.zoom().');
            }
            controls.zoom = L.control.zoom(zoomControlOptions).addTo(map);
        }

        var layerControlOptions = normalizeControlOptions(configuredControls.layers);
        if (layerControlOptions) {
            if (!L.control || typeof L.control.layers !== 'function') {
                throw new Error('MapCore layer control requires Leaflet L.control.layers().');
            }
            controls.layers = L.control.layers(
                baseLayers,
                overlayControlLayers,
                layerControlOptions
            ).addTo(map);
        }

        if (options.rendererPadding != null) {
            var updateRendererPadding = function () {
                var renderer = typeof map.getRenderer === 'function' ? map.getRenderer(map) : mapOptions.renderer;
                if (renderer && renderer.options) {
                    renderer.options.padding = resolvePadding(options.rendererPadding, map.getZoom(), map);
                }
            };
            map.on('zoomend', updateRendererPadding);
            cleanup.push(function () { map.off('zoomend', updateRendererPadding); });
            updateRendererPadding();
        }

        cleanup.push(createPopupBehavior(map, options.popupBehavior));

        function invalidateSize() {
            if (!destroyed && typeof map.invalidateSize === 'function') {
                return map.invalidateSize.apply(map, arguments);
            }
        }

        if (options.invalidateOnResize) {
            var onResize = function () { invalidateSize(); };
            global.addEventListener('resize', onResize);
            cleanup.push(function () { global.removeEventListener('resize', onResize); });
        }

        function destroy() {
            if (destroyed) return;
            destroyed = true;
            cleanup.reverse().forEach(function (remove) { remove(); });
            Object.keys(controls).forEach(function (name) {
                if (controls[name] && typeof controls[name].remove === 'function') {
                    controls[name].remove();
                }
            });
            if (typeof map.remove === 'function') map.remove();
        }

        return {
            map: map,
            layers: layers,
            baseLayers: baseLayers,
            controls: controls,
            invalidateSize: invalidateSize,
            destroy: destroy
        };
    }

    namespace.MapCore = {
        create: create
    };
})(window);
