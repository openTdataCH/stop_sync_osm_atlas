// Draggable and Resizable popup implementation for map stops
(function() {
    // Check if Leaflet is available
    if (typeof L === 'undefined') {
        console.error('Leaflet not found. DraggablePopup requires Leaflet.');
        return;
    }

    // Create a custom popup class extending Leaflet's Popup
    L.DraggablePopup = L.Popup.extend({
        options: {
            minWidth: 150,
            minHeight: 100,
            initialWidth: 'auto', // Default initial width auto-fit
            initialHeight: 'auto', // Default initial height
            resizeMargin: 10, // Pixels around the edge to trigger resize
            autoPan: false, // Disable autoPan to prevent popup from moving when opened
            closeOnClick: false, // Prevent closing when clicking on the map
            autoClose: false, // Prevent closing when clicking elsewhere
            className: 'customPopup permanent-popup' // Add classes for styling and persistence
        },

        initialize: function(options) {
            L.Util.setOptions(this, options);
            L.Popup.prototype.initialize.call(this, options);
            this._marker = null;
            this._line = null;
            this._isDragging = false;
            this._isResizing = false;
            this._resizeMode = null; // e.g., 'n', 's', 'e', 'w', 'nw', 'ne', 'sw', 'se'
            this._startPos = { x: 0, y: 0 };
            this._startSize = { width: 0, height: 0 };
            this._popupStartPos = { left: 0, top: 0 };
            this._boundMouseMove = this._onMouseMove.bind(this);
            this._boundMouseUp = this._onMouseUp.bind(this);
            // Store the explicit size set by the user
            this._currentWidth = null;
            this._currentHeight = null;
            this._maxContentWidth = null;
            this._interactionsInitialized = false;

            // When Leaflet updates the content, it wipes our handle, so we need to re-init.
            this.on('contentupdate', this._onContentUpdate, this);
        },

        onAdd: function(map) {
            L.Popup.prototype.onAdd.call(this, map);
            this._marker = this._source;

            // Apply initial or previously set dimensions
            this._applyDimensions();
            
            // Initialize interactions after a short delay
            setTimeout(() => {
                this._initInteractions();
                this._createLine();
                
                // Ensure the drag handle is created and at the top
                this._ensureDragHandleAtTop();
                
                // Reposition close button
                this._repositionCloseButton();
                
                // Make this popup persist on map
                this._makePersistent();
            }, 100);
            
            return this;
        },
        
        onRemove: function(map) {
            // Clean up our custom event listener
            this.off('contentupdate', this._onContentUpdate, this);
            
            this._removeLine();
            this._removeInteractionListeners(); // Clean up listeners
            L.Popup.prototype.onRemove.call(this, map);
        },
        
        _makePersistent: function() {
            if (!this._map) return;
            
            // Store a reference to this popup in the map
            if (!this._map._persistentPopups) {
                this._map._persistentPopups = [];
                
                // Override the map's _moveEnd method to reopen popups
                const originalMoveEnd = this._map._moveEnd;
                this._map._moveEnd = function(e) {
                    originalMoveEnd.call(this, e);
                    
                    // Update popup lines after map movement
                    if (window.updateAllPopupLines) {
                        window.updateAllPopupLines();
                    }
                };
            }
            
            // Add this popup to the persistent popups list if not already there
            if (this._map._persistentPopups.indexOf(this) === -1) {
                this._map._persistentPopups.push(this);
            }
        },
        
        // This is our new handler for when Leaflet resets the popup content
        _onContentUpdate: function() {
            // The content has been reset by setContent(), which wipes out the drag handle.
            // We need to re-initialize to add it back.
            // A timeout ensures the DOM is ready.
            setTimeout(() => {
                if (this._container) { // Check if popup is still on map
                    this._initInteractions();
                    this._ensureDragHandleAtTop();
                }
            }, 10);
        },
        
        _repositionCloseButton: function() {
            if (!this._container) return;
            
            const closeButton = this._container.querySelector('.leaflet-popup-close-button');
            if (closeButton) {
                // Make sure the close button is in the content wrapper for proper positioning
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
                contentNode.style.width = typeof appliedWidth === 'number' 
                    ? `${appliedWidth}px` 
                    : appliedWidth;
            }
            if (appliedHeight && appliedHeight !== 'auto') {
                contentNode.style.height = typeof appliedHeight === 'number' 
                    ? `${appliedHeight}px` 
                    : appliedHeight;
            } else {
                contentNode.style.height = 'auto';
            }
            contentNode.style.overflow = 'auto';
        },

        // Ensure the drag handle is at the top of content
        _ensureDragHandleAtTop: function() {
            if (!this._container || !this._contentNode) return;
            
            // Only proceed if interactions are initialized to avoid interference
            if (!this._interactionsInitialized) return;
            
            // Get the drag handle specifically from this popup's content
            const dragHandle = this._contentNode.querySelector('.popup-drag-handle');
            if (!dragHandle) return;
            
            // Make sure the handle is the first child of content
            const firstChild = this._contentNode.firstChild;
            if (firstChild !== dragHandle) {
                // Only move if the drag handle is actually a child of this content node
                if (this._contentNode.contains(dragHandle)) {
                    this._contentNode.insertBefore(dragHandle, firstChild);
                }
            }
        },

        _initInteractions: function() {
            if (!this._container) return;

            const container = this._container;
            const popup = this;

            // --- Create or Reuse Drag Handle (Header) ---
            let dragHandle = this._contentNode.querySelector('.popup-drag-handle');
            if (!dragHandle) {
                dragHandle = L.DomUtil.create('div', 'popup-drag-handle', this._contentNode);
                dragHandle.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M10 9h4V6h3l-5-5-5 5h3v3zm-1 1H6V7l-5 5 5 5v-3h3v-4zm14 2l-5-5v3h-3v4h3v3l5-5zm-9 3h-4v3H7l5 5 5-5h-3v-3z"/></svg> Move';
            }
            
            // Ensure the drag handle is the first child
            if (this._contentNode.firstChild !== dragHandle) {
                this._contentNode.insertBefore(dragHandle, this._contentNode.firstChild);
            }
            
            // --- Event Listeners (only bind if not already bound) ---
            if (!this._interactionsInitialized) {
                this._onMouseDown = this._onMouseDown.bind(this);
                this._onMouseMove = this._onMouseMove.bind(this);
                this._onMouseUp = this._onMouseUp.bind(this);
                this._onMouseHover = this._onMouseHover.bind(this);

                L.DomEvent.on(container, 'mousedown', this._onMouseDown);
                L.DomEvent.on(container, 'mousemove', this._onMouseHover); // For cursor changes
                
                this._interactionsInitialized = true;
            }
            
            container._leaflet_popup_instance = this;
        },

        _removeInteractionListeners: function() {
            if (!this._container) return;
            L.DomEvent.off(this._container, 'mousedown', this._onMouseDown);
            L.DomEvent.off(this._container, 'mousemove', this._onMouseHover);
            // Remove potential global listeners just in case
            L.DomEvent.off(document, 'mousemove', this._onMouseMove);
            L.DomEvent.off(document, 'mouseup', this._onMouseUp);
            
            // Clear instance ref
            if (this._container._leaflet_popup_instance === this) {
                delete this._container._leaflet_popup_instance;
            }
            
            // Remove from persistent popups list
            if (this._map && this._map._persistentPopups) {
                const index = this._map._persistentPopups.indexOf(this);
                if (index !== -1) {
                    this._map._persistentPopups.splice(index, 1);
                }
            }
            
            // Reset initialization flag for proper cleanup
            this._interactionsInitialized = false;
        },

        // --- Combined Mouse Down Logic ---
        _onMouseDown: function(e) {
            // If clicking the close button, let Leaflet handle it and do nothing here
            if (this._closeButton && (e.target === this._closeButton || e.target.parentNode === this._closeButton)) {
                return; 
            }
            
            // Prevent starting new action if already active
            if (this._isDragging || this._isResizing) return;
            
            const target = e.target;
            const container = this._container;
            
            // Check if clicking on the drag handle
            if (container.querySelector('.popup-drag-handle').contains(target)) {
                L.DomEvent.stopPropagation(e); // Stop only if starting drag
                L.DomEvent.preventDefault(e);
                this._startDragging(e);
            } else {
                // Check if clicking near an edge for resizing
                this._resizeMode = this._getResizeMode(e);
                if (this._resizeMode) {
                    L.DomEvent.stopPropagation(e); // Stop only if starting resize
                    L.DomEvent.preventDefault(e);
                    this._startResizing(e);
                } 
                // Otherwise, allow default browser/Leaflet behavior (text selection, etc.)
                // NO stopPropagation here
            }
        },

        // --- Dragging Logic ---
        _startDragging: function(e) {
            this._isDragging = true;
            this._startPos = { x: e.clientX, y: e.clientY };
            this._popupStartPos = { left: this._container.offsetLeft, top: this._container.offsetTop };

            L.DomUtil.addClass(this._container, 'leaflet-popup-dragging');
            L.DomEvent.on(document, 'mousemove', this._onMouseMove);
            L.DomEvent.on(document, 'mouseup', this._onMouseUp);
        },

        // --- Resizing Logic ---
        _startResizing: function(e) {
            this._isResizing = true;
            this._startPos = { x: e.clientX, y: e.clientY };
            const contentNode = this._contentNode;
            if (!contentNode) { // Safety check
                 this._isResizing = false;
                 return;
             }
            this._startSize = { width: contentNode.offsetWidth, height: contentNode.offsetHeight };
            this._popupStartPos = { left: this._container.offsetLeft, top: this._container.offsetTop };

            // --- Calculate Max Content Width --- 
            this._maxContentWidth = null; // Reset first
            // Basic constants (should match CSS)
            const bubbleBasis = 200; 
            const gap = 8; 
            const paddingLeft = 8;
            const paddingRight = 8;
            const singleBubbleBuffer = 25;
            const multiBubbleBuffer = 80; // Extra padding for multi-bubble layouts
            
            // Check if it's a multi-bubble container or a single bubble
            const matchesContainer = contentNode.querySelector('.matches-container');
            const singleBubble = contentNode.querySelector('.atlas-match, .osm-match');

            if (matchesContainer) { // Multi-bubble case
                const bubbles = matchesContainer.children;
                const numBubbles = bubbles.length;
                if (numBubbles > 0) {
                    this._maxContentWidth = (bubbleBasis * numBubbles) + (gap * Math.max(0, numBubbles - 1)) + paddingLeft + paddingRight + multiBubbleBuffer;
                }
            } else if (singleBubble) { // Single bubble case (unmatched)
                 this._maxContentWidth = bubbleBasis + paddingLeft + paddingRight + singleBubbleBuffer;
            }
            // --- End Calculate Max Content Width ---

            // Only proceed if resizing is possible
            if (this._maxContentWidth === null || this._maxContentWidth >= this.options.minWidth) {
                 L.DomUtil.addClass(this._container, 'leaflet-popup-resizing');
                 L.DomEvent.on(document, 'mousemove', this._onMouseMove);
                 L.DomEvent.on(document, 'mouseup', this._onMouseUp);
             } else {
                 // Cannot resize further (max width is less than min width allowed)
                 this._isResizing = false; 
             }
        },
        
        // --- Combined Mouse Move Logic ---
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

            // Adjust width based on resize mode
            if (this._resizeMode.includes('e')) {
                newWidth = this._startSize.width + dx;
            }
            if (this._resizeMode.includes('w')) {
                newWidth = this._startSize.width - dx;
                // Left position calculation will happen after width constraints
            }

            // --- Apply Max Width Constraint ---
            if (this._maxContentWidth !== null && newWidth > this._maxContentWidth) {
                newWidth = this._maxContentWidth;
            }
            // --- End Apply Max Width Constraint ---

            // Apply min width constraint (AFTER max width check)
            const minW = this.options.minWidth;
             if (newWidth < minW) {
                newWidth = minW;
            }

            // Now calculate final left position if resizing from 'w'
            if (this._resizeMode.includes('w')) {
                 newLeft = this._popupStartPos.left + (this._startSize.width - newWidth);
            }

            // Adjust height based on resize mode
            if (this._resizeMode.includes('s')) {
                newHeight = this._startSize.height + dy;
            }
            if (this._resizeMode.includes('n')) {
                newHeight = this._startSize.height - dy;
                // Top position calculation will happen after height constraints
            }

            // Apply min height constraint
            const minH = this.options.minHeight; // Use Leaflet's option
            if (newHeight < minH) {
                newHeight = minH;
            }

            // Now calculate final top position if resizing from 'n'
            if (this._resizeMode.includes('n')) {
                newTop = this._popupStartPos.top + (this._startSize.height - newHeight);
            }

            // Update styles
            contentNode.style.width = `${newWidth}px`;
            contentNode.style.height = `${newHeight}px`; // Apply height during resize
            contentNode.style.overflow = 'auto';

            // Adjust container position for top/left resize
            if (this._resizeMode.includes('n') || this._resizeMode.includes('w')) {
                this._container.style.left = `${newLeft}px`;
                this._container.style.top = `${newTop}px`;
            }

            this._updatePosition();
            this._updateLine();
        },

        // --- Combined Mouse Up Logic ---
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
                    // Set height to auto ON MOUSE UP to minimize blank space
                    this._contentNode.style.height = 'auto';
                }
                // Reset max width cache after resize is complete
                this._maxContentWidth = null;
            }

            L.DomEvent.off(document, 'mousemove', this._onMouseMove);
            L.DomEvent.off(document, 'mouseup', this._onMouseUp);
            this._updateLine();
            this._updateCursor();
        },
        
        // --- Cursor and Edge Detection ---
        _onMouseHover: function(e) {
             if (this._isDragging || this._isResizing) return; // Don't change cursor while active
             this._updateCursor(this._getResizeMode(e));
        },
        
        _getResizeMode: function(e) {
            const container = this._container;
            const contentNode = this._contentNode;
            if (!container || !contentNode || e.target === container.querySelector('.popup-drag-handle') || container.querySelector('.popup-drag-handle').contains(e.target)) {
                return null; // Don't resize if on drag handle
            }
            
            const rect = contentNode.getBoundingClientRect(); // Use content node rect for edge check
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
            let cursor = 'auto'; // Default cursor for content area
            
            // Set cursor based on resize mode, prioritizing corners
            switch (mode) {
                case 'n': cursor = 'ns-resize'; break;
                case 's': cursor = 'ns-resize'; break;
                case 'e': cursor = 'ew-resize'; break;
                case 'w': cursor = 'ew-resize'; break;
                case 'ne': cursor = 'nesw-resize'; break;
                case 'sw': cursor = 'nesw-resize'; break;
                case 'nw': cursor = 'nwse-resize'; break;
                case 'se': cursor = 'nwse-resize'; break;
                default: cursor = 'auto'; // Default
            }
            
            // Apply cursor to the container, allowing content to potentially override
            if (container.style.cursor !== cursor) {
                 container.style.cursor = cursor;
            }
             // Ensure drag handle always shows grab/grabbing cursor
            const dragHandle = container.querySelector('.popup-drag-handle');
            if (dragHandle) {
                dragHandle.style.cursor = this._isDragging ? 'grabbing' : 'grab';
            }
        },

        // --- Connection Line Logic (similar to previous version) ---
        _createLine: function() {
            if (!this._map || !this._marker) return;
            let svg = this._map._pathRoot || (this._map._renderer && this._map._renderer._container);
            if (!svg) return; // Cannot find SVG container
            
            // Ensure SVG is the direct child if using _renderer._container
            if (svg.nodeName.toLowerCase() !== 'svg') {
                 svg = svg.querySelector('svg');
            }
            if (!svg) return; // Still no SVG found

            this._line = L.SVG.create('line');
            this._line.setAttribute('class', 'popup-connection-line');
            svg.appendChild(this._line);
            this._updateLine(); // Initial draw
        },
        
        _updateLine: function() {
            if (!this._line || !this._marker || !this._map || !this._container) return;

            const markerPoint = this._map.latLngToLayerPoint(this._marker.getLatLng());

            // Get the popup's tip anchor point (bottom-center of the popup container)
            const popupTipPoint = this._getPopupTipPoint(); 
            const popupPoint = this._map.layerPointToContainerPoint(popupTipPoint);
           
            // Convert container point back to layer point for SVG coordinates
            const svgPopupPoint = this._map.containerPointToLayerPoint(popupPoint);

            // Update line attributes
            this._line.setAttribute('x1', markerPoint.x);
            this._line.setAttribute('y1', markerPoint.y);
            this._line.setAttribute('x2', svgPopupPoint.x);
            this._line.setAttribute('y2', svgPopupPoint.y);
        },

        // Helper to get the popup tip point (for connection line)
        _getPopupTipPoint: function() {
            if (!this._container || !this._map) return [0, 0];
            
            // Get popup container rectangle
            const popupRect = this._container.getBoundingClientRect();
            const mapRect = this._map.getContainer().getBoundingClientRect();
            
            // Find the tip container
            const tipContainer = this._container.querySelector('.leaflet-popup-tip-container');
            let tipPoint;
            
            if (tipContainer) {
                // Get the position of the tip
                const tipRect = tipContainer.getBoundingClientRect();
                // Use the center-bottom of the tip container
                tipPoint = L.point(
                    tipRect.left + (tipRect.width / 2) - mapRect.left,
                    tipRect.bottom - mapRect.top
                );
            } else {
                // Fallback to center-bottom of popup
                tipPoint = L.point(
                    popupRect.left + (popupRect.width / 2) - mapRect.left,
                    popupRect.bottom - mapRect.top
                );
            }
            
            // Convert to layer point
            return this._map.containerPointToLayerPoint(tipPoint);
        },
        
        _removeLine: function() {
            if (this._line) {
                try {
                    if (this._line.parentNode) {
                        this._line.parentNode.removeChild(this._line);
                    }
                } catch (e) {
                    console.warn("Error removing popup connection line:", e);
                }
                this._line = null;
            }
        },
        
        // Override updatePosition to also update our line
        _updatePosition: function () {
            L.Popup.prototype._updatePosition.call(this);
            this._updateLine();
            
            // Ensure the drag handle is at the top
            this._ensureDragHandleAtTop();
            
            // Ensure close button stays in the right position
            this._repositionCloseButton();
        },

        // Override Leaflet's internal update layout method
        _updateLayout: function () {
            // Apply our stored dimensions *before* calling the original method
            this._applyDimensions(); 
            
            // Now call the original Leaflet layout update
            L.Popup.prototype._updateLayout.call(this);
        }
    });

    // Factory function
    L.draggablePopup = function(options) {
        return new L.DraggablePopup(options);
    };
    
    // Utility function to update all popup lines (e.g., on map move/zoom)
    window.updateAllPopupLines = function() {
        document.querySelectorAll('.leaflet-popup').forEach(function(container) {
            const popup = container._leaflet_popup_instance;
            if (popup instanceof L.DraggablePopup && popup._updateLine) {
                popup._updateLine();
            }
        });
    };
    
})();
