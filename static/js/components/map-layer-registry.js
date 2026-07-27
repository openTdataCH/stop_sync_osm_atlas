/**
 * Reconciles Leaflet layers by stable entity key.
 *
 * Page controllers own descriptor construction and marker factories. The
 * registry only decides whether a layer can be reused, must be replaced, or
 * is no longer present.
 */
(function (global) {
    'use strict';

    var namespace = global.MapComponents = global.MapComponents || {};

    function assertFunction(value, name) {
        if (typeof value !== 'function') {
            throw new Error('MapLayerRegistry requires options.' + name + ' to be a function.');
        }
    }

    function assertLayerGroup(layerGroup) {
        if (!layerGroup || typeof layerGroup.addLayer !== 'function' || typeof layerGroup.removeLayer !== 'function') {
            throw new Error('MapLayerRegistry requires a Leaflet layerGroup with addLayer() and removeLayer().');
        }
    }

    function descriptorKey(descriptor, index) {
        if (!descriptor || descriptor.key == null || descriptor.key === '') {
            throw new Error('MapLayerRegistry descriptor at index ' + index + ' is missing a stable key.');
        }
        return String(descriptor.key);
    }

    function validateDescriptors(descriptors) {
        if (!Array.isArray(descriptors)) {
            throw new Error('MapLayerRegistry.reconcile() expects an array of descriptors.');
        }

        var keys = new Set();
        var normalized = descriptors.map(function (descriptor, index) {
            var key = descriptorKey(descriptor, index);
            if (!Object.prototype.hasOwnProperty.call(descriptor, 'renderSignature') ||
                    descriptor.renderSignature == null || descriptor.renderSignature === '') {
                throw new Error('MapLayerRegistry descriptor for key "' + key + '" is missing renderSignature.');
            }
            if (!Object.prototype.hasOwnProperty.call(descriptor, 'position') || descriptor.position == null) {
                throw new Error('MapLayerRegistry descriptor for key "' + key + '" is missing position.');
            }
            if (keys.has(key)) {
                throw new Error('MapLayerRegistry received duplicate key "' + key + '".');
            }
            keys.add(key);
            return { key: key, descriptor: descriptor };
        });

        return { items: normalized, keys: keys };
    }

    function create(options) {
        options = options || {};
        assertLayerGroup(options.layerGroup);
        assertFunction(options.create, 'create');

        var layerGroup = options.layerGroup;
        var entries = new Map();
        var destroyed = false;

        function assertActive() {
            if (destroyed) {
                throw new Error('MapLayerRegistry has been destroyed.');
            }
        }

        function createLayer(descriptor, context) {
            var layer = options.create(descriptor, context);
            if (!layer) {
                throw new Error('MapLayerRegistry create() did not return a layer for key "' + descriptor.key + '".');
            }
            return layer;
        }

        function notifyRemoval(entry, reason, context, replacement) {
            if (typeof options.onRemove === 'function') {
                options.onRemove(entry.layer, entry.descriptor, {
                    key: entry.key,
                    reason: reason,
                    context: context,
                    replacementLayer: replacement ? replacement.layer : null,
                    replacementDescriptor: replacement ? replacement.descriptor : null
                });
            }
        }

        function removeEntry(entry, reason, context) {
            var callbackError = null;
            try {
                notifyRemoval(entry, reason, context);
            } catch (error) {
                callbackError = error;
            }
            layerGroup.removeLayer(entry.layer);
            entries.delete(entry.key);
            if (callbackError) throw callbackError;
        }

        function reconcile(descriptors, context) {
            assertActive();
            var next = validateDescriptors(descriptors);
            var result = {
                created: [],
                updated: [],
                replaced: [],
                removed: []
            };

            next.items.forEach(function (item) {
                var current = entries.get(item.key);
                var descriptor = item.descriptor;

                if (!current) {
                    var newLayer = createLayer(descriptor, context);
                    layerGroup.addLayer(newLayer);
                    entries.set(item.key, {
                        key: item.key,
                        layer: newLayer,
                        descriptor: descriptor
                    });
                    result.created.push(item.key);
                    return;
                }

                if (current.descriptor.renderSignature !== descriptor.renderSignature) {
                    // Create and add the replacement before disturbing the valid layer.
                    // If creation fails, the current marker remains usable.
                    var replacement = createLayer(descriptor, context);
                    layerGroup.addLayer(replacement);
                    var callbackError = null;
                    try {
                        notifyRemoval(current, 'replace', context, {
                            layer: replacement,
                            descriptor: descriptor
                        });
                    } catch (error) {
                        callbackError = error;
                    }
                    layerGroup.removeLayer(current.layer);
                    entries.set(item.key, {
                        key: item.key,
                        layer: replacement,
                        descriptor: descriptor
                    });
                    result.replaced.push(item.key);
                    if (callbackError) throw callbackError;
                    return;
                }

                if (typeof options.update === 'function') {
                    options.update(current.layer, descriptor, current.descriptor, context);
                } else if (descriptor.position != null && typeof current.layer.setLatLng === 'function') {
                    current.layer.setLatLng(descriptor.position);
                }
                current.descriptor = descriptor;
                result.updated.push(item.key);
            });

            Array.from(entries.values()).forEach(function (entry) {
                if (!next.keys.has(entry.key)) {
                    removeEntry(entry, 'remove', context);
                    result.removed.push(entry.key);
                }
            });

            result.size = entries.size;
            return result;
        }

        function get(key) {
            var entry = entries.get(String(key));
            return entry ? entry.layer : null;
        }

        function getDescriptor(key) {
            var entry = entries.get(String(key));
            return entry ? entry.descriptor : null;
        }

        function has(key) {
            return entries.has(String(key));
        }

        function clear(reason, context) {
            if (destroyed) return [];
            var removed = [];
            var firstError = null;
            Array.from(entries.values()).forEach(function (entry) {
                try {
                    removeEntry(entry, reason || 'clear', context);
                    removed.push(entry.key);
                } catch (error) {
                    if (!firstError) firstError = error;
                    if (!entries.has(entry.key)) removed.push(entry.key);
                }
            });
            if (firstError) throw firstError;
            return removed;
        }

        function destroy() {
            if (destroyed) return;
            try {
                clear('destroy');
            } finally {
                destroyed = true;
            }
        }

        return {
            reconcile: reconcile,
            get: get,
            getDescriptor: getDescriptor,
            has: has,
            size: function () { return entries.size; },
            keys: function () { return Array.from(entries.keys()); },
            clear: clear,
            destroy: destroy
        };
    }

    namespace.MapLayerRegistry = {
        create: create
    };
})(window);
