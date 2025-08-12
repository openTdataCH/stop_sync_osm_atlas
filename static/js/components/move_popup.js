// Draggable and Resizable popup implementation for map stops
(function() {
    if (typeof L === 'undefined') { return; }
    L.DraggablePopup = L.Popup.extend({
        options: {
            minWidth: 150,
            minHeight: 100,
            initialWidth: 'auto',
            initialHeight: 'auto',
            resizeMargin: 10,
            autoPan: false,
            closeOnClick: false,
            autoClose: false,
            className: 'customPopup permanent-popup'
        },
        initialize: function(options) {
            L.Util.setOptions(this, options);
            L.Popup.prototype.initialize.call(this, options);
            this._marker = null;
            this._line = null;
            this._isDragging = false;
            this._isResizing = false;
            this._resizeMode = null;
            this._startPos = { x: 0, y: 0 };
            this._startSize = { width: 0, height: 0 };
            this._popupStartPos = { left: 0, top: 0 };
            this._boundMouseMove = this._onMouseMove.bind(this);
            this._boundMouseUp = this._onMouseUp.bind(this);
            this._currentWidth = null;
            this._currentHeight = null;
            this._maxContentWidth = null;
            this._interactionsInitialized = false;
            this.on('contentupdate', this._onContentUpdate, this);
        },
        onAdd: function(map) {
            L.Popup.prototype.onAdd.call(this, map);
            this._marker = this._source;
            this._applyDimensions();
            setTimeout(() => {
                this._initInteractions();
                this._createLine();
                this._ensureDragHandleAtTop();
                this._repositionCloseButton();
                this._makePersistent();
            }, 100);
            return this;
        },
        onRemove: function(map) {
            this.off('contentupdate', this._onContentUpdate, this);
            this._removeLine();
            this._removeInteractionListeners();
            L.Popup.prototype.onRemove.call(this, map);
        },
        _makePersistent: function() {
            if (!this._map) return;
            if (!this._map._persistentPopups) {
                this._map._persistentPopups = [];
                const originalMoveEnd = this._map._moveEnd;
                this._map._moveEnd = function(e) {
                    originalMoveEnd.call(this, e);
                    if (window.updateAllPopupLines) { window.updateAllPopupLines(); }
                };
            }
            if (this._map._persistentPopups.indexOf(this) === -1) {
                this._map._persistentPopups.push(this);
            }
        },
        _onContentUpdate: function() {
            setTimeout(() => {
                if (this._container) {
                    this._initInteractions();
                    this._ensureDragHandleAtTop();
                }
            }, 10);
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
            let appliedHeight = this._currentHeight || this.options.initialHeight;
            if (appliedWidth) {
                contentNode.style.width = typeof appliedWidth === 'number' ? `${appliedWidth}px` : appliedWidth;
            }
            if (appliedHeight && appliedHeight !== 'auto') {
                contentNode.style.height = typeof appliedHeight === 'number' ? `${appliedHeight}px` : appliedHeight;
            } else {
                contentNode.style.height = 'auto';
            }
            contentNode.style.overflow = 'auto';
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
            if (this._map && this._map._persistentPopups) {
                const index = this._map._persistentPopups.indexOf(this);
                if (index !== -1) { this._map._persistentPopups.splice(index, 1); }
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
            this._startSize = { width: contentNode.offsetWidth, height: contentNode.offsetHeight };
            this._popupStartPos = { left: this._container.offsetLeft, top: this._container.offsetTop };
            this._maxContentWidth = null;
            const bubbleBasis = 200; 
            const gap = 8; 
            const paddingLeft = 8;
            const paddingRight = 8;
            const singleBubbleBuffer = 25;
            const multiBubbleBuffer = 80; 
            const matchesContainer = contentNode.querySelector('.matches-container');
            const singleBubble = contentNode.querySelector('.atlas-match, .osm-match');
            if (matchesContainer) {
                const bubbles = matchesContainer.children;
                const numBubbles = bubbles.length;
                if (numBubbles > 0) {
                    this._maxContentWidth = (bubbleBasis * numBubbles) + (gap * Math.max(0, numBubbles - 1)) + paddingLeft + paddingRight + multiBubbleBuffer;
                }
            } else if (singleBubble) {
                this._maxContentWidth = bubbleBasis + paddingLeft + paddingRight + singleBubbleBuffer;
            }
            if (this._maxContentWidth === null || this._maxContentWidth >= this.options.minWidth) {
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
            const dy = e.clientY - this._startPos.y;
            const contentNode = this._contentNode;
            let newWidth = this._startSize.width;
            let newHeight = this._startSize.height;
            let newLeft = this._popupStartPos.left;
            let newTop = this._popupStartPos.top;
            if (this._resizeMode.includes('e')) { newWidth = this._startSize.width + dx; }
            if (this._resizeMode.includes('w')) { newWidth = this._startSize.width - dx; }
            if (this._maxContentWidth !== null && newWidth > this._maxContentWidth) { newWidth = this._maxContentWidth; }
            const minW = this.options.minWidth;
            if (newWidth < minW) { newWidth = minW; }
            if (this._resizeMode.includes('w')) { newLeft = this._popupStartPos.left + (this._startSize.width - newWidth); }
            if (this._resizeMode.includes('s')) { newHeight = this._startSize.height + dy; }
            if (this._resizeMode.includes('n')) { newHeight = this._startSize.height - dy; }
            const minH = this.options.minHeight;
            if (newHeight < minH) { newHeight = minH; }
            if (this._resizeMode.includes('n')) { newTop = this._popupStartPos.top + (this._startSize.height - newHeight); }
            contentNode.style.width = `${newWidth}px`;
            contentNode.style.height = `${newHeight}px`;
            contentNode.style.overflow = 'auto';
            if (this._resizeMode.includes('n') || this._resizeMode.includes('w')) {
                this._container.style.left = `${newLeft}px`;
                this._container.style.top = `${newTop}px`;
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
                    this._contentNode.style.height = 'auto';
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
            if (!container || !contentNode || e.target === container.querySelector('.popup-drag-handle') || container.querySelector('.popup-drag-handle').contains(e.target)) {
                return null;
            }
            const rect = contentNode.getBoundingClientRect();
            const margin = this.options.resizeMargin;
            const x = e.clientX;
            const y = e.clientY;
            let mode = '';
            if (y >= rect.top && y <= rect.top + margin) mode += 'n';
            else if (y <= rect.bottom && y >= rect.bottom - margin) mode += 's';
            if (x >= rect.left && x <= rect.left + margin) mode += 'w';
            else if (x <= rect.right && x >= rect.right - margin) mode += 'e';
            return mode || null;
        },
        _updateCursor: function(mode) {
            const container = this._container;
            if (!container) return;
            let cursor = 'auto';
            switch (mode) {
                case 'n': cursor = 'ns-resize'; break;
                case 's': cursor = 'ns-resize'; break;
                case 'e': cursor = 'ew-resize'; break;
                case 'w': cursor = 'ew-resize'; break;
                case 'ne': cursor = 'nesw-resize'; break;
                case 'sw': cursor = 'nesw-resize'; break;
                case 'nw': cursor = 'nwse-resize'; break;
                case 'se': cursor = 'nwse-resize'; break;
                default: cursor = 'auto';
            }
            if (container.style.cursor !== cursor) { container.style.cursor = cursor; }
            const dragHandle = container.querySelector('.popup-drag-handle');
            if (dragHandle) { dragHandle.style.cursor = this._isDragging ? 'grabbing' : 'grab'; }
        },
        _createLine: function() {
            if (!this._map || !this._marker) return;
            let svg = this._map._pathRoot || (this._map._renderer && this._map._renderer._container);
            if (!svg) return;
            if (svg.nodeName.toLowerCase() !== 'svg') { svg = svg.querySelector('svg'); }
            if (!svg) return;
            this._line = L.SVG.create('line');
            this._line.setAttribute('class', 'popup-connection-line');
            svg.appendChild(this._line);
            this._updateLine();
        },
        _updateLine: function() {
            if (!this._line || !this._marker || !this._map || !this._container) return;
            const markerPoint = this._map.latLngToLayerPoint(this._marker.getLatLng());
            const popupTipPoint = this._getPopupTipPoint(); 
            const popupPoint = this._map.layerPointToContainerPoint(popupTipPoint);
            const svgPopupPoint = this._map.containerPointToLayerPoint(popupPoint);
            this._line.setAttribute('x1', markerPoint.x);
            this._line.setAttribute('y1', markerPoint.y);
            this._line.setAttribute('x2', svgPopupPoint.x);
            this._line.setAttribute('y2', svgPopupPoint.y);
        },
        _getPopupTipPoint: function() {
            if (!this._container || !this._map) return [0, 0];
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
            return this._map.containerPointToLayerPoint(tipPoint);
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


