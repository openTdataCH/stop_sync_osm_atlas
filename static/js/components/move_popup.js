// Draggable and Resizable popup implementation for map stops
(function() {
    if (typeof L === 'undefined') { return; }
    // Stop popups get a fixed width; other popups keep Leaflet's sizing.
    const STOP_CONTENT_SELECTOR = '.atlas-match, .osm-match, .gtfs-match, .popup-compare';
    L.DraggablePopup = L.Popup.extend({
        options: {
            minWidth: AppConstants.POPUP.MIN_WIDTH,
            minHeight: AppConstants.POPUP.MIN_HEIGHT,
            initialWidth: AppConstants.POPUP.INITIAL_WIDTH,
            initialHeight: AppConstants.POPUP.INITIAL_HEIGHT,
            resizeMargin: AppConstants.POPUP.RESIZE_MARGIN,
            autoPan: false,
            closeOnClick: false,
            autoClose: false,
            className: 'customPopup permanent-popup',
            stopPopupWidthPx: AppConstants.POPUP.WIDTH_PX,
            // Share of the map width a stop popup may take; small maps raise it.
            stopPopupMapShare: 0.6,
            resizeMaxWidthPx: AppConstants.POPUP.RESIZE_MAX_WIDTH_PX || 900
        },
        initialize: function(options) {
            L.Util.setOptions(this, options);
            L.Popup.prototype.initialize.call(this, options);
            this._marker = null;
            this._line = null;
            this._lineLayer = null;
            this._isDragging = false;
            this._isResizing = false;
            this._resizeMode = null;
            this._startPos = { x: 0, y: 0 };
            this._startSize = { width: 0 };
            // Where the user dragged the popup, relative to where Leaflet puts it.
            this._dragOffset = null;
            this._startOffset = { x: 0, y: 0 };
            this._currentWidth = null;
            this._resizedWidth = null;
            this._maxContentWidth = null;
            this._interactionsInitialized = false;
            this._mapEventHandlersBound = false;
            this._boundMapUpdate = null;
            this.on('contentupdate', this._onContentUpdate, this);
        },
        onAdd: function(map) {
            L.Popup.prototype.onAdd.call(this, map);
            this._marker = this._source;
            this._applyDimensions();
            setTimeout(() => {
                this._initInteractions();
                this._createLine();
                this._bindMapEventHandlers();
                this._ensureDragHandleAtTop();
                this._repositionCloseButton();
                // Leaflet panned for the size before the bubble layout above.
                this._panIntoView();
            }, 100);
            return this;
        },
        onRemove: function(map) {
            this.off('contentupdate', this._onContentUpdate, this);
            this._removeLine();
            this._unbindMapEventHandlers();
            this._removeInteractionListeners();
            L.Popup.prototype.onRemove.call(this, map);
        },
        _onContentUpdate: function() {
            setTimeout(() => {
                if (this._container) {
                    this._initInteractions();
                    this._ensureDragHandleAtTop();
                    this.refreshLayout();
                }
            }, 10);
        },
        // Lays the popup out again after its content changed in place (See Matches).
        refreshLayout: function() {
            if (!this._map || !this._container) return;
            this._updateLayout();
            this._updatePosition();
            this._panIntoView();
        },
        // Popups that pan into view (route maps) follow their own resizes.
        // Leaflet pans by the width it measured, before the bubble layout.
        _panIntoView: function() {
            if (!this._map || !this._container || !this.options.autoPan) return;
            this._containerWidth = this._container.offsetWidth;
            this._adjustPan();
        },
        _bindMapEventHandlers: function() {
            if (!this._map || this._mapEventHandlersBound) return;
            this._boundMapUpdate = this._updateLine.bind(this);
            this._map.on('move zoom resize', this._boundMapUpdate);
            this._mapEventHandlersBound = true;
        },
        _unbindMapEventHandlers: function() {
            if (!this._map || !this._mapEventHandlersBound || !this._boundMapUpdate) return;
            this._map.off('move zoom resize', this._boundMapUpdate);
            this._boundMapUpdate = null;
            this._mapEventHandlersBound = false;
        },
        _repositionCloseButton: function() {
            if (!this._container) return;
            const closeButton = this._container.querySelector('.leaflet-popup-close-button');
            if (closeButton) {
                const contentWrapper = this._container.querySelector('.leaflet-popup-content-wrapper');
                if (contentWrapper && closeButton.parentNode !== contentWrapper) {
                    contentWrapper.appendChild(closeButton);
                }
            }
        },
        _applyDimensions: function() {
            if (!this._container) return;
            const contentNode = this._contentNode;
            if (!contentNode) return;
            let appliedWidth = this._currentWidth || this.options.initialWidth;
            if (appliedWidth) {
                contentNode.style.width = typeof appliedWidth === 'number' ? `${appliedWidth}px` : appliedWidth;
            }
            contentNode.style.height = 'auto';
            contentNode.style.overflow = 'auto';
            // Leaflet's maxHeight sets a fixed height, which 'auto' above undoes.
            if (this.options.maxHeight) contentNode.style.maxHeight = `${this.options.maxHeight}px`;
        },
        _applyStopPopupWidth: function() {
            if (!this._map || !this._contentNode) return;
            if (!this._contentNode.querySelector(STOP_CONTENT_SELECTOR)) return;
            this._currentWidth = this._resizedWidth || this._calculateStopPopupWidth();
            this._applyDimensions();
        },
        // One fixed width for every stop popup and both of its views, so ATLAS and
        // OSM popups match and See Matches never changes the width. Small maps narrow it.
        _calculateStopPopupWidth: function() {
            const width = this.options.stopPopupWidthPx;
            if (!this._map) return width;
            const mapCap = Math.floor(this._map.getSize().x * this.options.stopPopupMapShare);
            return Math.max(this.options.minWidth, Math.min(width, mapCap));
        },
        _calculateResizeMaxWidth: function() {
            const viewportWidth = this._map ? this._map.getSize().x : this.options.resizeMaxWidthPx;
            const viewportCap = Math.max(this.options.minWidth, Math.floor(viewportWidth * 0.95));
            return Math.max(this.options.minWidth, Math.min(this.options.resizeMaxWidthPx, viewportCap));
        },
        _ensureDragHandleAtTop: function() {
            if (!this._container || !this._contentNode) return;
            if (!this._interactionsInitialized) return;
            const dragHandle = this._contentNode.querySelector('.popup-drag-handle');
            if (!dragHandle) return;
            const firstChild = this._contentNode.firstChild;
            if (firstChild !== dragHandle && this._contentNode.contains(dragHandle)) {
                this._contentNode.insertBefore(dragHandle, firstChild);
            }
        },
        _initInteractions: function() {
            if (!this._container) return;
            const container = this._container;
            let dragHandle = this._contentNode.querySelector('.popup-drag-handle');
            if (!dragHandle) {
                dragHandle = L.DomUtil.create('div', 'popup-drag-handle', this._contentNode);
                dragHandle.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M10 9h4V6h3l-5-5-5 5h3v3zm-1 1H6V7l-5 5 5 5v-3h3v-4zm14 2l-5-5v3h-3v4h3v3l5-5zm-9 3h-4v3H7l5 5 5-5h-3v-3z"/></svg> Move';
            }
            if (this._contentNode.firstChild !== dragHandle) {
                this._contentNode.insertBefore(dragHandle, this._contentNode.firstChild);
            }
            if (!this._interactionsInitialized) {
                this._onMouseDown = this._onMouseDown.bind(this);
                this._onMouseMove = this._onMouseMove.bind(this);
                this._onMouseUp = this._onMouseUp.bind(this);
                this._onMouseHover = this._onMouseHover.bind(this);
                L.DomEvent.on(container, 'mousedown', this._onMouseDown);
                L.DomEvent.on(container, 'mousemove', this._onMouseHover);
                this._interactionsInitialized = true;
            }
            container._leaflet_popup_instance = this;
        },
        _removeInteractionListeners: function() {
            if (!this._container) return;
            L.DomEvent.off(this._container, 'mousedown', this._onMouseDown);
            L.DomEvent.off(this._container, 'mousemove', this._onMouseHover);
            L.DomEvent.off(document, 'mousemove', this._onMouseMove);
            L.DomEvent.off(document, 'mouseup', this._onMouseUp);
            if (this._container._leaflet_popup_instance === this) {
                delete this._container._leaflet_popup_instance;
            }
            this._interactionsInitialized = false;
        },
        _onMouseDown: function(e) {
            if (this._closeButton && (e.target === this._closeButton || e.target.parentNode === this._closeButton)) { return; }
            if (this._isDragging || this._isResizing) return;
            const target = e.target;
            const container = this._container;
            if (container.querySelector('.popup-drag-handle').contains(target)) {
                L.DomEvent.stopPropagation(e);
                L.DomEvent.preventDefault(e);
                this._startDragging(e);
            } else {
                this._resizeMode = this._getResizeMode(e);
                if (this._resizeMode) {
                    L.DomEvent.stopPropagation(e);
                    L.DomEvent.preventDefault(e);
                    this._startResizing(e);
                }
            }
        },
        _startDragging: function(e) {
            this._isDragging = true;
            this._startPos = { x: e.clientX, y: e.clientY };
            this._startOffset = { ...(this._dragOffset || { x: 0, y: 0 }) };
            L.DomUtil.addClass(this._container, 'leaflet-popup-dragging');
            L.DomEvent.on(document, 'mousemove', this._onMouseMove);
            L.DomEvent.on(document, 'mouseup', this._onMouseUp);
        },
        _startResizing: function(e) {
            this._isResizing = true;
            this._startPos = { x: e.clientX, y: e.clientY };
            const contentNode = this._contentNode;
            if (!contentNode) { this._isResizing = false; return; }
            this._startSize = { width: contentNode.offsetWidth };
            this._startOffset = { ...(this._dragOffset || { x: 0, y: 0 }) };
            this._maxContentWidth = this._calculateResizeMaxWidth();

            if (this._maxContentWidth >= this.options.minWidth) {
                L.DomUtil.addClass(this._container, 'leaflet-popup-resizing');
                L.DomEvent.on(document, 'mousemove', this._onMouseMove);
                L.DomEvent.on(document, 'mouseup', this._onMouseUp);
            } else {
                this._isResizing = false; 
            }
        },
        _onMouseMove: function(e) {
             if (this._isDragging) {
                this._onDragging(e);
             } else if (this._isResizing) {
                this._onResizing(e);
             }
        },
        _onDragging: function(e) {
            const dx = e.clientX - this._startPos.x;
            const dy = e.clientY - this._startPos.y;
            this._dragOffset = { x: this._startOffset.x + dx, y: this._startOffset.y + dy };
            this._updatePosition();
        },
        _onResizing: function(e) {
            const dx = e.clientX - this._startPos.x;
            const contentNode = this._contentNode;
            let newWidth = this._startSize.width;

            if (this._resizeMode.includes('e')) { newWidth = this._startSize.width + dx; }
            if (this._resizeMode.includes('w')) { newWidth = this._startSize.width - dx; }
            
            // Apply professional width limits
            if (this._maxContentWidth !== null && newWidth > this._maxContentWidth) { 
                newWidth = this._maxContentWidth; 
            }
            const minW = this.options.minWidth;
            if (newWidth < minW) { newWidth = minW; }
            
            contentNode.style.width = `${newWidth}px`;
            contentNode.style.overflow = 'auto';

            // Leaflet centres the popup; shift it so the edge opposite the handle stays put.
            const shift = (newWidth - this._startSize.width) / 2;
            const x = this._startOffset.x + (this._resizeMode.includes('w') ? -shift : shift);
            this._dragOffset = { x, y: this._startOffset.y };
            this._updatePosition();
        },
        _onMouseUp: function(e) {
            if (this._isDragging) {
                L.DomUtil.removeClass(this._container, 'leaflet-popup-dragging');
                this._isDragging = false;
            } else if (this._isResizing) {
                L.DomUtil.removeClass(this._container, 'leaflet-popup-resizing');
                this._isResizing = false;
                this._resizeMode = null;
                if (this._contentNode) {
                    this._currentWidth = this._resizedWidth = this._contentNode.offsetWidth;
                    this._contentNode.style.width = `${this._currentWidth}px`;
                }
                this._maxContentWidth = null;
            }
            L.DomEvent.off(document, 'mousemove', this._onMouseMove);
            L.DomEvent.off(document, 'mouseup', this._onMouseUp);
            this._updateLine();
            this._updateCursor();
        },
        _onMouseHover: function(e) {
             if (this._isDragging || this._isResizing) return;
             this._updateCursor(this._getResizeMode(e));
        },
        _getResizeMode: function(e) {
            const container = this._container;
            const contentNode = this._contentNode;
            const dragHandle = container && container.querySelector('.popup-drag-handle');
            if (!container || !contentNode || !dragHandle || e.target === dragHandle || dragHandle.contains(e.target)) {
                return null;
            }

            // Horizontal-only resize to keep popup height stable.
            const outerRect = container.getBoundingClientRect();
            const margin = this.options.resizeMargin;
            const x = e.clientX;
            let mode = '';
            if (x >= outerRect.left && x <= outerRect.left + margin) mode += 'w';
            else if (x <= outerRect.right && x >= outerRect.right - margin) mode += 'e';
            return mode || null;
        },
        _updateCursor: function(mode) {
            const container = this._container;
            if (!container) return;
            let cursor = 'auto';
            switch (mode) {
                case 'e': cursor = 'ew-resize'; break;
                case 'w': cursor = 'ew-resize'; break;
                default: cursor = 'auto';
            }
            if (container.style.cursor !== cursor) { container.style.cursor = cursor; }
            const dragHandle = container.querySelector('.popup-drag-handle');
            if (dragHandle) { dragHandle.style.cursor = this._isDragging ? 'grabbing' : 'grab'; }
        },
        _syncLineLayerDimensions: function(svg) {
            if (!svg || !this._map) return;
            const mapSize = this._map.getSize();
            svg.setAttribute('width', String(mapSize.x));
            svg.setAttribute('height', String(mapSize.y));
            svg.setAttribute('viewBox', `0 0 ${mapSize.x} ${mapSize.y}`);
            svg.setAttribute('preserveAspectRatio', 'none');
        },
        _getOrCreateLineLayer: function() {
            if (!this._map) return null;
            if (this._map._popupConnectionSvg && this._map._popupConnectionSvg.isConnected) {
                this._lineLayer = this._map._popupConnectionSvg;
                this._syncLineLayerDimensions(this._lineLayer);
                return this._lineLayer;
            }

            const mapContainer = this._map.getContainer();
            let svg = mapContainer.querySelector('.popup-connection-layer');
            if (!svg) {
                svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
                svg.setAttribute('class', 'popup-connection-layer');
                mapContainer.appendChild(svg);
            }

            this._syncLineLayerDimensions(svg);
            this._map._popupConnectionSvg = svg;
            this._lineLayer = svg;
            return svg;
        },
        _createLine: function() {
            if (!this._map || !this._marker) return;
            let svg = this._getOrCreateLineLayer();
            if (!svg) return;

            this._line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
            this._line.setAttribute('class', 'popup-connection-line');
            svg.appendChild(this._line);
            this._updateLine();
        },
        _updateLine: function() {
            if (!this._line || !this._marker || !this._map || !this._container) return;
            this._syncLineLayerDimensions(this._lineLayer);
            const markerPoint = this._map.latLngToContainerPoint(this._marker.getLatLng());
            const popupTipPoint = this._getPopupTipPoint(); 
            if (!popupTipPoint) return;

            this._line.setAttribute('x1', markerPoint.x);
            this._line.setAttribute('y1', markerPoint.y);
            this._line.setAttribute('x2', popupTipPoint.x);
            this._line.setAttribute('y2', popupTipPoint.y);
        },
        _getPopupTipPoint: function() {
            if (!this._container || !this._map) return null;
            const popupRect = this._container.getBoundingClientRect();
            const mapRect = this._map.getContainer().getBoundingClientRect();
            const tipContainer = this._container.querySelector('.leaflet-popup-tip-container');
            let tipPoint;
            if (tipContainer) {
                const tipRect = tipContainer.getBoundingClientRect();
                tipPoint = L.point(
                    tipRect.left + (tipRect.width / 2) - mapRect.left,
                    tipRect.bottom - mapRect.top
                );
            } else {
                tipPoint = L.point(
                    popupRect.left + (popupRect.width / 2) - mapRect.left,
                    popupRect.bottom - mapRect.top
                );
            }
            return tipPoint;
        },
        _removeLine: function() {
            if (this._line) {
                try { if (this._line.parentNode) { this._line.parentNode.removeChild(this._line); } } catch (e) {}
                this._line = null;
            }
        },
        _updatePosition: function () {
            if (!this._map || !this._container) return;
            // Leaflet centres the popup on the width it last measured; use the current one.
            this._containerWidth = this._container.offsetWidth;
            L.Popup.prototype._updatePosition.call(this);
            if (this._dragOffset) {
                this._container.style.left = `${this._containerLeft + this._dragOffset.x}px`;
                this._container.style.bottom = `${this._containerBottom - this._dragOffset.y}px`;
            }
            this._updateLine();
            this._ensureDragHandleAtTop();
            this._repositionCloseButton();
        },
        // Leaflet sizes the popup to its content first; the fixed width then replaces
        // that in the same frame, so the popup never shows at Leaflet's width.
        _updateLayout: function () {
            L.Popup.prototype._updateLayout.call(this);
            this._applyStopPopupWidth();
            if (this._container) this._containerWidth = this._container.offsetWidth;
        }
    });
    L.draggablePopup = function(options) { return new L.DraggablePopup(options); };
    function updateAllPopupLines(mapInstance) {
        document.querySelectorAll('.leaflet-popup').forEach(function(container) {
            const popup = container._leaflet_popup_instance;
            if (
                popup instanceof L.DraggablePopup &&
                popup._updateLine &&
                (!mapInstance || popup._map === mapInstance)
            ) {
                popup._updateLine();
            }
        });
    }
    window.MapComponents = window.MapComponents || {};
    window.MapComponents.PopupLines = Object.freeze({
        updateAll: updateAllPopupLines
    });
})();
