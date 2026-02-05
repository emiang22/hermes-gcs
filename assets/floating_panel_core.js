/**
 * H.E.R.M.E.S. GCS v2.0
 * Floating Control Panel - Core Functionality
 * Handles: dragging, snapping, adaptive layout, position synchronization
 */

(function() {
    'use strict';

    // Constants
    const SNAP_THRESHOLD = parseInt(getComputedStyle(document.documentElement)
        .getPropertyValue('--floating-snap-threshold')) || 30;

    // State
    let isDragging = false;
    let dragTarget = null;
    let startX, startY, startLeft, startTop;
    let rafPending = false;
    let lastEvent = null;
    let snappedState = null; // 'left', 'right', 'top', 'bottom', or null
    
    // Percentage-based position storage (survives window resize)
    let positionPercent = {
        left: null,  // Percentage of viewport width (0-100)
        top: null    // Percentage of viewport height (0-100)
    };
    
    // Convert pixel position to percentage
    function pixelToPercent(pixelLeft, pixelTop) {
        return {
            left: (pixelLeft / window.innerWidth) * 100,
            top: (pixelTop / window.innerHeight) * 100
        };
    }
    
    // Convert percentage to pixel position
    function percentToPixel(percentLeft, percentTop) {
        return {
            left: (percentLeft / 100) * window.innerWidth,
            top: (percentTop / 100) * window.innerHeight
        };
    }

    function init() {
        const icon = document.getElementById('floating-minimized-icon');
        const floatingWindow = document.getElementById('floating-window');
        const titlebar = document.getElementById('floating-titlebar');
        const minimizeBtn = document.getElementById('floating-minimize-btn');
        const content = document.getElementById('floating-content');
        const buttonsContainer = document.getElementById('floating-buttons-container');

        if (!icon || !floatingWindow || !titlebar) {
            setTimeout(init, 100);
            return;
        }

        if (window._floatingPanelCoreInitialized) return;
        window._floatingPanelCoreInitialized = true;

        // ═══════════════════════════════════════════════════════════════
        // HELPER FUNCTIONS - Save/Restore Position
        // ═══════════════════════════════════════════════════════════════
        
        function savePosition() {
            // Save current position as percentage
            const left = parseFloat(floatingWindow.style.left) || 0;
            const top = parseFloat(floatingWindow.style.top) || 0;
            const percent = pixelToPercent(left, top);
            positionPercent.left = percent.left;
            positionPercent.top = percent.top;
        }
        
        function restorePosition() {
            // Restore position from percentage
            if (positionPercent.left !== null && positionPercent.top !== null) {
                const pixels = percentToPixel(positionPercent.left, positionPercent.top);
                floatingWindow.style.left = pixels.left + 'px';
                floatingWindow.style.top = pixels.top + 'px';
                floatingWindow.style.right = 'auto';
                floatingWindow.style.bottom = 'auto';
            }
        }

        // ═══════════════════════════════════════════════════════════════
        // INITIALIZE WINDOW POSITION (Convert bottom/right to left/top)
        // ═══════════════════════════════════════════════════════════════
        // Window starts with bottom: 20px, right: 20px - convert to left/top
        const viewportWidth = window.innerWidth;
        const viewportHeight = window.innerHeight;
        const windowWidth = floatingWindow.offsetWidth;
        const windowHeight = floatingWindow.offsetHeight;
        
        const initialLeft = viewportWidth - windowWidth - 20;
        const initialTop = viewportHeight - windowHeight - 20;
        
        floatingWindow.style.left = initialLeft + 'px';
        floatingWindow.style.top = initialTop + 'px';
        floatingWindow.style.right = 'auto';
        floatingWindow.style.bottom = 'auto';
        
        // Save initial position as percentage
        const initialPercent = pixelToPercent(initialLeft, initialTop);
        positionPercent.left = initialPercent.left;
        positionPercent.top = initialPercent.top;
        
        // Clear icon's initial bottom/right (will be positioned by updateIconPosition)
        icon.style.left = '';
        icon.style.right = 'auto';
        icon.style.top = '';
        icon.style.bottom = 'auto';

        // ═══════════════════════════════════════════════════════════════
        // INITIAL VISIBILITY STATE (Both always rendered, use opacity)
        // ═══════════════════════════════════════════════════════════════
        // Icon visible, window hidden by default
        icon.style.opacity = '1';
        icon.style.pointerEvents = 'auto';
        icon.style.transition = 'opacity 0.3s ease, all 0.3s ease';
        floatingWindow.style.opacity = '0';
        floatingWindow.style.pointerEvents = 'none';
        floatingWindow.style.transition = 'opacity 0.3s ease';

        // ═══════════════════════════════════════════════════════════════
        // POSITION SYNCHRONIZATION
        // Icon is always positioned relative to window (stuck to corner/center)
        // Uses style.left/top directly instead of getBoundingClientRect
        // ═══════════════════════════════════════════════════════════════

        function updateIconPosition() {
            const iconSize = 60; // Fixed size from CSS
            
            // Get window position from style properties (not getBoundingClientRect)
            const windowLeft = parseFloat(floatingWindow.style.left) || 0;
            const windowTop = parseFloat(floatingWindow.style.top) || 0;
            const windowWidth = floatingWindow.offsetWidth;
            const windowHeight = floatingWindow.offsetHeight;
            
            // Clear all positioning
            icon.style.right = 'auto';
            icon.style.bottom = 'auto';

            if (snappedState === 'left') {
                // Top-left corner
                icon.style.left = windowLeft + 'px';
                icon.style.top = windowTop + 'px';
            } else if (snappedState === 'right') {
                // Top-right corner (default)
                icon.style.left = (windowLeft + windowWidth - iconSize) + 'px';
                icon.style.top = windowTop + 'px';
            } else if (snappedState === 'top') {
                // Centered horizontally at top
                icon.style.left = (windowLeft + windowWidth / 2 - iconSize / 2) + 'px';
                icon.style.top = windowTop + 'px';
            } else if (snappedState === 'bottom') {
                // Centered horizontally at bottom
                icon.style.left = (windowLeft + windowWidth / 2 - iconSize / 2) + 'px';
                icon.style.top = (windowTop + windowHeight - iconSize) + 'px';
            } else {
                // Default: top-right corner
                icon.style.left = (windowLeft + windowWidth - iconSize) + 'px';
                icon.style.top = windowTop + 'px';
            }
        }

        // Initial positioning - wait for layout to complete
        requestAnimationFrame(() => {
            requestAnimationFrame(() => {
                updateIconPosition();
                console.log('Icon positioned:', {
                    windowLeft: floatingWindow.style.left,
                    windowTop: floatingWindow.style.top,
                    iconLeft: icon.style.left,
                    iconTop: icon.style.top,
                    snappedState
                });
            });
        });

        // ═══════════════════════════════════════════════════════════════
        // VIEWPORT BOUNDARY CHECK
        // ═══════════════════════════════════════════════════════════════

        function ensureInViewport(element) {
            const w = window.innerWidth;
            const h = window.innerHeight;

            let left = parseFloat(element.style.left) || 0;
            let top = parseFloat(element.style.top) || 0;
            const elementWidth = element.offsetWidth;
            const elementHeight = element.offsetHeight;
            let adjusted = false;

            // Check right edge
            if (left + elementWidth > w) {
                left = w - elementWidth;
                adjusted = true;
            }

            // Check left edge
            if (left < 0) {
                left = 0;
                adjusted = true;
            }

            // Check bottom edge
            if (top + elementHeight > h) {
                top = h - elementHeight;
                adjusted = true;
            }

            // Check top edge
            if (top < 0) {
                top = 0;
                adjusted = true;
            }

            if (adjusted) {
                element.style.left = left + 'px';
                element.style.top = top + 'px';
                element.style.right = 'auto';
                element.style.bottom = 'auto';
            }
        }

        // ═══════════════════════════════════════════════════════════════
        // TOGGLE VISIBILITY (Just fade in/out, no repositioning)
        // ═══════════════════════════════════════════════════════════════

        function togglePanel() {
            const isWindowOpen = floatingWindow.style.opacity === '1';

            if (isWindowOpen) {
                // Minimize: fade out window, fade in icon
                floatingWindow.style.opacity = '0';
                floatingWindow.style.pointerEvents = 'none';
                icon.style.opacity = '1';
                icon.style.pointerEvents = 'auto';
            } else {
                // Expand: fade out icon, fade in window
                icon.style.opacity = '0';
                icon.style.pointerEvents = 'none';
                floatingWindow.style.opacity = '1';
                floatingWindow.style.pointerEvents = 'auto';
            }
        }

        icon.addEventListener('click', togglePanel);
        minimizeBtn.addEventListener('click', togglePanel);

        // ═══════════════════════════════════════════════════════════════
        // ADAPTIVE LAYOUT - Switch between horizontal/vertical
        // ═══════════════════════════════════════════════════════════════

        function updateLayout() {
            if (!content || !buttonsContainer) return;
            
            const width = floatingWindow.offsetWidth;
            const height = floatingWindow.offsetHeight - 40; // Subtract titlebar height
            
            // Calculate aspect ratio
            const aspectRatio = width / height;
            
            if (aspectRatio > 1.3) {
                // Wide window: horizontal layout (camera left, buttons right)
                content.style.flexDirection = 'row';
                buttonsContainer.style.flexDirection = 'column';
                buttonsContainer.style.width = '90px';
                buttonsContainer.style.height = 'auto';
            } else {
                // Tall/square window: vertical layout (camera top, buttons bottom)
                content.style.flexDirection = 'column';
                buttonsContainer.style.flexDirection = 'row';
                buttonsContainer.style.flexWrap = 'wrap';
                buttonsContainer.style.width = '100%';
                buttonsContainer.style.height = 'auto';
            }
        }

        // ═══════════════════════════════════════════════════════════════
        // WINDOW RESIZE HANDLER - Keep panel in viewport
        // ═══════════════════════════════════════════════════════════════
        
        let resizeTimeout;
        function handleWindowResize() {
            // Debounce resize events
            clearTimeout(resizeTimeout);
            resizeTimeout = setTimeout(() => {
                // Restore position from percentage
                restorePosition();
                
                // Ensure it's still within viewport bounds
                ensureInViewport(floatingWindow);
                
                // Update saved percentage for new position
                savePosition();
                
                // Update icon to follow window
                updateIconPosition();
                
                console.log('Window resized, panel repositioned:', {
                    viewport: `${window.innerWidth}x${window.innerHeight}`,
                    position: `${floatingWindow.style.left}, ${floatingWindow.style.top}`,
                    percent: `${positionPercent.left.toFixed(1)}%, ${positionPercent.top.toFixed(1)}%`
                });
            }, 100);
        }
        
        window.addEventListener('resize', handleWindowResize);

        // ResizeObserver for adaptive layout and icon positioning
        const resizeObserver = new ResizeObserver(entries => {
            requestAnimationFrame(() => {
                updateLayout();
                updateIconPosition();
            });
        });
        resizeObserver.observe(floatingWindow);

        // Initial layout and icon position
        updateLayout();

        // ═══════════════════════════════════════════════════════════════
        // DRAGGING & SNAPPING
        // ═══════════════════════════════════════════════════════════════

        function detectSnap(element) {
            const w = window.innerWidth;
            const h = window.innerHeight;
            const left = parseFloat(element.style.left) || 0;
            const top = parseFloat(element.style.top) || 0;
            const right = left + element.offsetWidth;
            const bottom = top + element.offsetHeight;

            // Detect which edge we're snapped to
            if (left < SNAP_THRESHOLD) {
                return 'left';
            } else if (right > w - SNAP_THRESHOLD) {
                return 'right';
            } else if (top < SNAP_THRESHOLD) {
                return 'top';
            } else if (bottom > h - SNAP_THRESHOLD) {
                return 'bottom';
            }
            return null;
        }

        function startDrag(e, target) {
            if (e.target.id === 'floating-minimize-btn') return;
            
            isDragging = true;
            // Always drag the window, icon follows automatically
            dragTarget = floatingWindow;
            startX = e.clientX;
            startY = e.clientY;

            startLeft = parseFloat(floatingWindow.style.left) || 0;
            startTop = parseFloat(floatingWindow.style.top) || 0;

            floatingWindow.style.transition = 'none';
            icon.style.transition = 'none';

            if (target === icon) {
                icon.style.cursor = 'grabbing';
            } else {
                titlebar.style.cursor = 'grabbing';
            }

            e.preventDefault();
            e.stopPropagation();
        }

        function drag(e) {
            if (!isDragging || !dragTarget) return;

            lastEvent = e;
            if (rafPending) return;

            rafPending = true;
            requestAnimationFrame(() => {
                rafPending = false;
                if (!lastEvent || !dragTarget) return;

                const dx = lastEvent.clientX - startX;
                const dy = lastEvent.clientY - startY;

                let left = startLeft + dx;
                let top = startTop + dy;

                dragTarget.style.left = left + 'px';
                dragTarget.style.top = top + 'px';
                dragTarget.style.right = 'auto';
                dragTarget.style.bottom = 'auto';

                const w = window.innerWidth;
                const h = window.innerHeight;
                const tw = dragTarget.offsetWidth;
                const th = dragTarget.offsetHeight;

                let snapped = false;
                let newSnapState = null;

                // Right edge snap
                if (left + tw > w - SNAP_THRESHOLD) {
                    dragTarget.style.left = (w - tw) + 'px';
                    snapped = true;
                    newSnapState = 'right';
                }
                // Left edge snap
                else if (left < SNAP_THRESHOLD) {
                    dragTarget.style.left = '0px';
                    snapped = true;
                    newSnapState = 'left';
                }

                // Bottom edge snap
                if (top + th > h - SNAP_THRESHOLD) {
                    dragTarget.style.top = (h - th) + 'px';
                    snapped = true;
                    newSnapState = 'bottom';
                }
                // Top edge snap
                else if (top < SNAP_THRESHOLD) {
                    dragTarget.style.top = '0px';
                    snapped = true;
                    newSnapState = 'top';
                }

                snappedState = newSnapState;
                dragTarget.classList.toggle('snap-preview', snapped);
                
                // Update icon position to follow window
                updateIconPosition();
            });
        }

        function stopDrag() {
            if (!isDragging || !dragTarget) return;

            isDragging = false;
            dragTarget.classList.remove('snap-preview');

            // Save the new position as percentage after dragging
            savePosition();

            // Restore transitions on both elements
            icon.style.transition = 'opacity 0.3s ease, all 0.3s ease';
            icon.style.cursor = 'grab';
            floatingWindow.style.transition = 'opacity 0.3s ease';
            titlebar.style.cursor = 'grab';

            dragTarget = null;
        }

        icon.addEventListener('mousedown', e => startDrag(e, icon));
        titlebar.addEventListener('mousedown', e => startDrag(e, floatingWindow));
        document.addEventListener('mousemove', drag);
        document.addEventListener('mouseup', stopDrag);
        
        console.log('✅ Floating panel core initialized (responsive positioning enabled)');
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();