/* SPDX-License-Identifier: Apache-2.0 */
(function () {
    'use strict';

    var COLLAPSED_CLASS = 'detail-panel-collapsed';

    function bind(wrapperSelector, mainAreaSelector, panelSelector, activeClass, syncOnPanelClose) {
        var wrapper = document.querySelector(wrapperSelector);
        if (!wrapper) return;

        var collapseBtn = wrapper.querySelector('.detail-panel-collapse-btn');
        var restoreBtn = wrapper.querySelector('.detail-panel-restore-btn');
        var mainArea = mainAreaSelector ? wrapper.querySelector(mainAreaSelector) : null;
        var panel = panelSelector ? wrapper.querySelector(panelSelector) : null;

        if (collapseBtn) {
            collapseBtn.addEventListener('click', function (e) {
                e.stopPropagation();
                wrapper.classList.add(COLLAPSED_CLASS);
            });
        }

        if (restoreBtn) {
            restoreBtn.addEventListener('click', function (e) {
                e.stopPropagation();
                wrapper.classList.remove(COLLAPSED_CLASS);
            });
        }

        // Auto-restore only when the user clicks an actual item (anything
        // with a data-event-id), so casual scrolling/clicking in the list
        // doesn't pop the panel back open. Use the capture phase so we run
        // before per-item handlers that call e.stopPropagation() (e.g. the
        // calendar's event-block click handler).
        if (mainArea) {
            mainArea.addEventListener('click', function (e) {
                if (!wrapper.classList.contains(COLLAPSED_CLASS)) return;
                if (e.target.closest('[data-event-id]')) {
                    wrapper.classList.remove(COLLAPSED_CLASS);
                }
            }, true);
        }

        // For panels that visually disappear when nothing is selected (calendar),
        // clear the collapsed flag once the panel closes — otherwise the floating
        // restore circle would linger with nothing to restore to.
        if (syncOnPanelClose && panel && activeClass && typeof MutationObserver !== 'undefined') {
            var observer = new MutationObserver(function () {
                if (!panel.classList.contains(activeClass)) {
                    wrapper.classList.remove(COLLAPSED_CLASS);
                }
            });
            observer.observe(panel, { attributes: true, attributeFilter: ['class'] });
        }
    }

    function init() {
        // Schedule/Inbox: panel always shows something (empty state if no event),
        // so the collapsed flag is purely a UX preference — don't auto-clear it.
        bind('.schedule-list-detail-wrapper', '.schedule-main-area', '.schedule-detail-panel', 'has-event', false);
        // Calendar: panel is width:0 when nothing is selected; clear collapse on close.
        bind('.calendar-content-area', '.calendar-view-container', '.calendar-detail-panel', 'open', true);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
