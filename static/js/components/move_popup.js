// Draggable and Resizable popup implementation for map stops
(function() {
    if (typeof L === 'undefined') { return; }
    const POPUP_BUBBLE_SELECTOR = '.atlas-match, .osm-match, .gtfs-match';
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
            // Professional width control settings
            fitBubblesSingleRow: true,
            singleBubbleMaxWidthPx: AppConstants.POPUP.SINGLE_BUBBLE_MAX_WIDTH_PX,
            multiBubbleOptimalWidth: AppConstants.POPUP.MULTI_BUBBLE_OPTIMAL_WIDTH,
            multiBubbleMaxWidthPx: AppConstants.POPUP.MULTI_BUBBLE_MAX_WIDTH_PX || 420,
            multiBubbleResizeMaxWidthPx: AppConstants.POPUP.MULTI_BUBBLE_RESIZE_MAX_WIDTH_PX || 900,
            multiBubbleMaxColumns: AppConstants.POPUP.MULTI_BUBBLE_MAX_COLUMNS || 2,
            bubbleExpansionBuffer: AppConstants.POPUP.BUBBLE_EXPANSION_BUFFER,
            strictWidthControl: true // enable strict width limits
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
            this._popupStartPos = { left: 0, top: 0 };
            this._currentWidth = null;
            this._maxContentWidth = null;
            this._interactionsInitialized = false;
            this._mapEventHandlersBound = false;
            this._boundMapUpdate = null;
            this._bubbleCount = 0;
            this._isSingleBubbleMode = true;
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
            this._bubbleCount = 0;
            this._isSingleBubbleMode = true;
            
            setTimeout(() => {
                if (this._container) {
                    this._initInteractions();
                    this._ensureDragHandleAtTop();
                    this._analyzeBubbleLayout();
                    this._applyOptimalWidth();
                    this._updateLine();
                }
            }, 10);
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
        },
        _analyzeBubbleLayout: function() {
            if (!this._contentNode) return;
            
            const contentNode = this._contentNode;
            const unifiedView = contentNode.querySelector('.popup-unified-view');
            const initialView = contentNode.querySelector('.popup-initial-view');
            const isUnifiedVisible = unifiedView && getComputedStyle(unifiedView).display !== 'none';
            
            // Count bubbles accurately
            let bubbleElements = [];
            
            if (isUnifiedVisible) {
                const matchesContainer = unifiedView.querySelector('.matches-container');
                if (matchesContainer) {
                    // Count actual ATLAS and OSM bubbles in matches container
                    bubbleElements = Array.from(matchesContainer.children).map(wrapper => 
                        wrapper.querySelector('.atlas-match, .osm-match')
                    ).filter(Boolean);
                }
            } else if (initialView && getComputedStyle(initialView).display !== 'none') {
                // Single bubble in initial view
                const singleBubble = initialView.querySelector(POPUP_BUBBLE_SELECTOR);
                if (singleBubble) {
                    bubbleElements = [singleBubble];
                }
            } else {
                // Standalone popup content (no initial/unified wrappers).
                const directBubble = contentNode.querySelector(POPUP_BUBBLE_SELECTOR);
                if (directBubble) {
                    bubbleElements = [directBubble];
                }
            }
            
            this._bubbleCount = bubbleElements.length;
            this._isSingleBubbleMode = this._bubbleCount <= 1;
            
            // Store reference to current bubble container for width calculations
            this._currentBubbleElements = bubbleElements;
            this._currentMatchesContainer = isUnifiedVisible ? 
                unifiedView.querySelector('.matches-container') : null;
        },
        _applyOptimalWidth: function() {
            if (!this._map || !this._contentNode || !this.options.strictWidthControl) return;
            
            this._analyzeBubbleLayout();
            
            if (this._isSingleBubbleMode) {
                this._applySingleBubbleWidth();
            } else {
                this._applyMultiBubbleWidth();
            }
        },
        _applySingleBubbleWidth: function() {
            if (!this._currentBubbleElements || this._currentBubbleElements.length === 0) return;
            
            const bubble = this._currentBubbleElements[0];
            
            // Calculate natural width of the bubble content
            const originalStyle = bubble.style.width;
            bubble.style.width = 'auto';
            bubble.offsetHeight; // Force reflow
            const naturalWidth = bubble.offsetWidth;
            bubble.style.width = originalStyle;

            const buttonRow = bubble.querySelector('.bubble-btn-row');
            const buttonRowWidth = buttonRow ? buttonRow.scrollWidth : 0;
            const requiredContentWidth = Math.max(naturalWidth, buttonRowWidth + 6);
            
            // Keep single-bubble sizing simple and predictable.
            const containerPadding = 16;
            const bufferSpace = 12;
            const optimalWidth = requiredContentWidth + containerPadding + bufferSpace;

            const viewportCap = this._map
                ? Math.max(this.options.minWidth, Math.floor(this._map.getSize().x * 0.6))
                : this.options.singleBubbleMaxWidthPx;
            const maxWidth = Math.min(this.options.singleBubbleMaxWidthPx, viewportCap);

            this._currentWidth = Math.max(this.options.minWidth, Math.min(optimalWidth, maxWidth));
            this._applyDimensions();
            this._updatePosition();
        },
        _applyMultiBubbleWidth: function() {
            if (!this._currentMatchesContainer || !this._currentBubbleElements || this._currentBubbleElements.length === 0) {
                return;
            }

            this._currentWidth = this._calculateMultiBubbleWidth();
            this._applyDimensions();
            this._updatePosition();
        },
        _calculateMultiBubbleWidth: function() {
            const bubbleCount = this._currentBubbleElements ? this._currentBubbleElements.length : 1;
            const viewportWidth = this._map ? this._map.getSize().x : this.options.singleBubbleMaxWidthPx;
            const compactColumns = viewportWidth <= 900 ? 1 : this.options.multiBubbleMaxColumns;
            const columns = Math.max(1, Math.min(compactColumns, bubbleCount));

            const gap = 6;
            const containerPadding = 10;
            const outerPadding = 14;
            const perBubbleWidth = this.options.multiBubbleOptimalWidth;
            const desiredWidth = (columns * perBubbleWidth) + (Math.max(0, columns - 1) * gap) + containerPadding + outerPadding + this.options.bubbleExpansionBuffer;

            const viewportCap = Math.max(this.options.minWidth, Math.floor(viewportWidth * 0.9));
            const hardCap = this.options.multiBubbleMaxWidthPx;
            return Math.max(this.options.minWidth, Math.min(desiredWidth, viewportCap, hardCap));
        },
        _calculateResizeMaxWidth: function() {
            const viewportWidth = this._map ? this._map.getSize().x : this.options.multiBubbleResizeMaxWidthPx;
            const viewportCap = Math.max(this.options.minWidth, Math.floor(viewportWidth * 0.95));
            return Math.max(this.options.minWidth, Math.min(this.options.multiBubbleResizeMaxWidthPx, viewportCap));
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
            this._popupStartPos = { left: this._container.offsetLeft, top: this._container.offsetTop };
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
            this._popupStartPos = { left: this._container.offsetLeft, top: this._container.offsetTop };

            // Calculate professional width limits based on content
            this._analyzeBubbleLayout();
            
            if (this._isSingleBubbleMode) {
                // Single bubble: keep resize cap aligned with simplified width logic.
                this._maxContentWidth = this.options.singleBubbleMaxWidthPx;
            } else {
                // Multiple bubbles: allow wider manual resize than auto layout width.
                this._maxContentWidth = this._calculateResizeMaxWidth();
            }
            
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
            this._container.style.left = `${this._popupStartPos.left + dx}px`;
            this._container.style.top = `${this._popupStartPos.top + dy}px`;
            this._updateLine();
        },
        _onResizing: function(e) {
            const dx = e.clientX - this._startPos.x;
            const contentNode = this._contentNode;
            let newWidth = this._startSize.width;
            let newLeft = this._popupStartPos.left;
            
            if (this._resizeMode.includes('e')) { newWidth = this._startSize.width + dx; }
            if (this._resizeMode.includes('w')) { newWidth = this._startSize.width - dx; }
            
            // Apply professional width limits
            if (this._maxContentWidth !== null && newWidth > this._maxContentWidth) { 
                newWidth = this._maxContentWidth; 
            }
            const minW = this.options.minWidth;
            if (newWidth < minW) { newWidth = minW; }
            
            if (this._resizeMode.includes('w')) { newLeft = this._popupStartPos.left + (this._startSize.width - newWidth); }
            
            contentNode.style.width = `${newWidth}px`;
            contentNode.style.overflow = 'auto';
            
            if (this._resizeMode.includes('w')) {
                this._container.style.left = `${newLeft}px`;
            }
            
            this._updatePosition();
            this._updateLine();
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
                    this._currentWidth = this._contentNode.offsetWidth;
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
            L.Popup.prototype._updatePosition.call(this);
            this._updateLine();
            this._ensureDragHandleAtTop();
            this._repositionCloseButton();
        },
        _updateLayout: function () {
            this._applyOptimalWidth();
            this._applyDimensions(); 
            L.Popup.prototype._updateLayout.call(this);
        }
    });
    L.draggablePopup = function(options) { return new L.DraggablePopup(options); };
    window.updateAllPopupLines = function() {
        document.querySelectorAll('.leaflet-popup').forEach(function(container) {
            const popup = container._leaflet_popup_instance;
            if (popup instanceof L.DraggablePopup && popup._updateLine) { popup._updateLine(); }
        });
    };
})();