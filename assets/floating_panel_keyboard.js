/**
 * H.E.R.M.E.S. GCS v2.0
 * Floating Control Panel - Keyboard Controls
 * Handles: keyboard navigation (WASD + Arrow keys)
 */

(function() {
    'use strict';

    function init() {
        const floatingWindow = document.getElementById('floating-window');
        
        if (!floatingWindow) {
            setTimeout(init, 100);
            return;
        }

        if (window._floatingKeyboardInitialized) return;
        window._floatingKeyboardInitialized = true;

        let windowFocused = false;

        // Enable keyboard control when clicking inside the window
        floatingWindow.addEventListener('click', function() {
            windowFocused = true;
            floatingWindow.classList.add('keyboard-enabled');
        });

        // Disable keyboard control when clicking outside
        document.addEventListener('click', function(e) {
            if (!floatingWindow.contains(e.target)) {
                windowFocused = false;
                floatingWindow.classList.remove('keyboard-enabled');
            }
        });

        // Key mapping
        const keyMap = {
            'ArrowUp': 'forward',
            'ArrowDown': 'backward',
            'ArrowLeft': 'left',
            'ArrowRight': 'right',
            'w': 'forward',
            's': 'backward',
            'a': 'left',
            'd': 'right'
        };

        // Handle keydown
        document.addEventListener('keydown', function(e) {
            if (!windowFocused) return;

            const direction = keyMap[e.key];
            if (direction) {
                e.preventDefault();
                
                // Find the button by data-key attribute or by ID
                const btn = document.querySelector(`[data-key="${e.key}"]`) ||
                            document.querySelector(`button[id*="${direction}"]`);
                
                if (btn) {
                    btn.classList.add('key-pressed');
                    btn.click();
                }
            }
        });

        // Handle keyup
        document.addEventListener('keyup', function(e) {
            const direction = keyMap[e.key];
            if (direction) {
                const btn = document.querySelector(`[data-key="${e.key}"]`) ||
                            document.querySelector(`button[id*="${direction}"]`);
                
                if (btn) {
                    btn.classList.remove('key-pressed');
                }
            }
        });

        console.log('✅ Floating panel keyboard controls initialized');
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
