/**
 * CRUD table column resize + wrap mode.
 *
 * Works on any `<table class="crud-table" data-table-key="…">` rendered by the
 * `{% crud_table %}` tag. Each data header (`th[data-field]`) carries a
 * `.col-resizer` handle (role="separator") on its right edge:
 *
 *   - drag            → resize that column (pointer events; touch included)
 *   - double-click    → fit the column to its widest cell
 *   - Arrow ←/→       → ±16px (Shift: ±64px); Enter → fit; Home → minimum
 *
 * The table uses `table-layout: fixed`, so a header's width IS the column
 * width. On the first resize every data column is pinned to its current px
 * width and the table gets a `min-width` equal to the sum, so widening one
 * column grows the table (the wrapper scrolls) instead of squeezing the rest.
 * When the table is narrower than its container the browser distributes the
 * slack proportionally, so a resized table still fills the card.
 *
 * Widths persist in localStorage per `data-table-key` (the view's url_base +
 * its field list, so a changed `list_fields` never replays stale widths).
 * Everything re-initialises after an htmx swap — sort/search/filter/paginate
 * all replace the table — and is idempotent per table element.
 *
 * Progressive enhancement: with the script absent the handles are
 * `display: none` and the tools row stays `hidden`.
 */
(function () {
    'use strict';

    var MIN_WIDTH = 48;
    var MAX_FIT_WIDTH = 640;
    var STEP = 16;
    var BIG_STEP = 64;
    var WIDTHS_PREFIX = 'ss_colwidths_';
    var WRAP_PREFIX = 'ss_colwrap_';

    // ---- storage ---------------------------------------------------------

    function storageKey(prefix, table) {
        return prefix + (table.getAttribute('data-table-key') || window.location.pathname);
    }

    function loadWidths(table) {
        try {
            var raw = window.localStorage.getItem(storageKey(WIDTHS_PREFIX, table));
            var parsed = raw ? JSON.parse(raw) : null;
            return parsed && typeof parsed === 'object' ? parsed : {};
        } catch (e) {
            return {};
        }
    }

    function saveWidths(table, widths) {
        try {
            var key = storageKey(WIDTHS_PREFIX, table);
            if (widths && Object.keys(widths).length) {
                window.localStorage.setItem(key, JSON.stringify(widths));
            } else {
                window.localStorage.removeItem(key);
            }
        } catch (e) { /* private mode / blocked storage — resize still works for this page view */ }
    }

    function loadWrap(table) {
        try {
            return window.localStorage.getItem(storageKey(WRAP_PREFIX, table)) === '1';
        } catch (e) {
            return false;
        }
    }

    function saveWrap(table, on) {
        try {
            var key = storageKey(WRAP_PREFIX, table);
            if (on) {
                window.localStorage.setItem(key, '1');
            } else {
                window.localStorage.removeItem(key);
            }
        } catch (e) { /* ignore */ }
    }

    // ---- geometry --------------------------------------------------------

    function dataHeaders(table) {
        return Array.prototype.slice.call(table.querySelectorAll('thead th[data-field]'));
    }

    function allHeaders(table) {
        return Array.prototype.slice.call(table.querySelectorAll('thead th'));
    }

    function clamp(px) {
        return Math.max(MIN_WIDTH, Math.round(px));
    }

    /** Sum of every header's current rendered width — the table's natural min-width once columns are pinned. */
    function totalWidth(table) {
        return allHeaders(table).reduce(function (sum, th) {
            return sum + th.getBoundingClientRect().width;
        }, 0);
    }

    /** Pin every data column to its current px width so later edits only move the dragged column. */
    function pinAll(table) {
        var widths = {};
        dataHeaders(table).forEach(function (th) {
            var w = clamp(th.getBoundingClientRect().width);
            th.style.width = w + 'px';
            widths[th.getAttribute('data-field')] = w;
        });
        return widths;
    }

    function setColumnWidth(table, th, px) {
        px = clamp(px);
        th.style.width = px + 'px';
        var handle = th.querySelector('.col-resizer');
        if (handle) {
            handle.setAttribute('aria-valuenow', String(px));
        }
        table.style.minWidth = Math.round(totalWidth(table)) + 'px';
        return px;
    }

    /** Widest content in the column (header label + every cell), capped. */
    function fitWidth(table, th) {
        var index = Array.prototype.indexOf.call(th.parentNode.children, th);
        var widest = 0;
        var label = th.querySelector('.th-sort span') || th;
        widest = Math.max(widest, measureText(label) + 40); // header padding + sort glyph
        var rows = table.tBodies.length ? table.tBodies[0].rows : [];
        Array.prototype.forEach.call(rows, function (row) {
            var cell = row.children[index];
            if (!cell) {
                return;
            }
            // scrollWidth includes the cell's padding but not an overflowing
            // ellipsis, so it is the natural nowrap width of the content.
            widest = Math.max(widest, cell.scrollWidth + 2);
        });
        return Math.min(MAX_FIT_WIDTH, clamp(widest));
    }

    function measureText(el) {
        var range = document.createRange();
        range.selectNodeContents(el);
        var rect = range.getBoundingClientRect();
        return rect.width;
    }

    // ---- apply / reset / wrap -------------------------------------------

    function applySaved(table) {
        var saved = loadWidths(table);
        var any = false;
        dataHeaders(table).forEach(function (th) {
            var w = saved[th.getAttribute('data-field')];
            var handle = th.querySelector('.col-resizer');
            if (typeof w === 'number' && w >= MIN_WIDTH) {
                th.style.width = w + 'px';
                any = true;
            }
            if (handle) {
                handle.setAttribute('aria-valuenow', String(Math.round(th.getBoundingClientRect().width)));
            }
        });
        table.classList.toggle('is-resized', any);
        table.style.minWidth = any ? Math.round(totalWidth(table)) + 'px' : '';
        syncResetButton(table);
    }

    function persist(table) {
        var widths = {};
        dataHeaders(table).forEach(function (th) {
            widths[th.getAttribute('data-field')] = clamp(th.getBoundingClientRect().width);
        });
        saveWidths(table, widths);
        table.classList.add('is-resized');
        syncResetButton(table);
    }

    function resetWidths(table) {
        saveWidths(table, null);
        dataHeaders(table).forEach(function (th) {
            // Restore whatever the server emitted (column_widths / type default), else free.
            th.style.width = th.getAttribute('data-server-width') || '';
        });
        table.style.minWidth = '';
        table.classList.remove('is-resized');
        dataHeaders(table).forEach(function (th) {
            var handle = th.querySelector('.col-resizer');
            if (handle) {
                handle.setAttribute('aria-valuenow', String(Math.round(th.getBoundingClientRect().width)));
            }
        });
        syncResetButton(table);
    }

    function toolsFor(table) {
        var wrap = table.closest('.crud-table-wrap');
        var tools = wrap && wrap.nextElementSibling;
        return tools && tools.classList.contains('crud-table-tools') ? tools : null;
    }

    function syncResetButton(table) {
        var tools = toolsFor(table);
        var btn = tools && tools.querySelector('.crud-table-reset-widths');
        if (btn) {
            btn.hidden = !table.classList.contains('is-resized');
        }
    }

    function setWrap(table, on) {
        table.classList.toggle('is-wrapping', on);
        var tools = toolsFor(table);
        var btn = tools && tools.querySelector('.crud-table-wrap-toggle');
        if (btn) {
            btn.setAttribute('aria-pressed', on ? 'true' : 'false');
        }
    }

    // ---- interaction -----------------------------------------------------

    function startDrag(table, th, handle, event) {
        event.preventDefault();
        if (!table.classList.contains('is-resized')) {
            pinAll(table);
            table.style.minWidth = Math.round(totalWidth(table)) + 'px';
        }
        var startX = event.clientX;
        var startWidth = th.getBoundingClientRect().width;
        var pointerId = event.pointerId;

        handle.classList.add('is-dragging');
        table.classList.add('is-dragging');
        try {
            handle.setPointerCapture(pointerId);
        } catch (e) { /* older engines */ }

        function onMove(ev) {
            if (ev.pointerId !== pointerId) {
                return;
            }
            setColumnWidth(table, th, startWidth + (ev.clientX - startX));
        }

        function onEnd(ev) {
            if (ev.pointerId !== pointerId) {
                return;
            }
            handle.removeEventListener('pointermove', onMove);
            handle.removeEventListener('pointerup', onEnd);
            handle.removeEventListener('pointercancel', onEnd);
            handle.classList.remove('is-dragging');
            table.classList.remove('is-dragging');
            try {
                handle.releasePointerCapture(pointerId);
            } catch (e) { /* ignore */ }
            persist(table);
        }

        handle.addEventListener('pointermove', onMove);
        handle.addEventListener('pointerup', onEnd);
        handle.addEventListener('pointercancel', onEnd);
    }

    function nudge(table, th, delta) {
        if (!table.classList.contains('is-resized')) {
            pinAll(table);
        }
        setColumnWidth(table, th, th.getBoundingClientRect().width + delta);
        persist(table);
    }

    function fit(table, th) {
        if (!table.classList.contains('is-resized')) {
            pinAll(table);
        }
        setColumnWidth(table, th, fitWidth(table, th));
        persist(table);
    }

    function bindHandle(table, th, handle) {
        handle.addEventListener('pointerdown', function (event) {
            if (event.button !== 0 && event.pointerType === 'mouse') {
                return;
            }
            startDrag(table, th, handle, event);
        });
        handle.addEventListener('dblclick', function (event) {
            event.preventDefault();
            fit(table, th);
        });
        // A click on the handle must never bubble into the sort button.
        handle.addEventListener('click', function (event) {
            event.stopPropagation();
        });
        handle.addEventListener('keydown', function (event) {
            var delta = event.shiftKey ? BIG_STEP : STEP;
            switch (event.key) {
                case 'ArrowRight':
                    event.preventDefault();
                    nudge(table, th, delta);
                    break;
                case 'ArrowLeft':
                    event.preventDefault();
                    nudge(table, th, -delta);
                    break;
                case 'Home':
                    event.preventDefault();
                    nudge(table, th, MIN_WIDTH - th.getBoundingClientRect().width);
                    break;
                case 'Enter':
                    event.preventDefault();
                    fit(table, th);
                    break;
                default:
                    break;
            }
        });
    }

    function initTable(table) {
        if (table.dataset.resizeInit === '1') {
            return;
        }
        table.dataset.resizeInit = '1';

        dataHeaders(table).forEach(function (th) {
            // Remember the server-emitted width so "Reset columns" can restore it.
            if (th.style.width && !th.hasAttribute('data-server-width')) {
                th.setAttribute('data-server-width', th.style.width);
            }
            var handle = th.querySelector('.col-resizer');
            if (handle) {
                bindHandle(table, th, handle);
            }
        });

        table.classList.add('is-resizable');
        applySaved(table);
        setWrap(table, loadWrap(table));

        var tools = toolsFor(table);
        if (tools) {
            tools.hidden = false;
            var wrapBtn = tools.querySelector('.crud-table-wrap-toggle');
            if (wrapBtn) {
                wrapBtn.addEventListener('click', function () {
                    var on = !table.classList.contains('is-wrapping');
                    setWrap(table, on);
                    saveWrap(table, on);
                });
            }
            var resetBtn = tools.querySelector('.crud-table-reset-widths');
            if (resetBtn) {
                resetBtn.addEventListener('click', function () {
                    resetWidths(table);
                });
            }
        }
    }

    function initAll(root) {
        var scope = root && root.querySelectorAll ? root : document;
        var tables = scope.querySelectorAll('table.crud-table[data-table-key]');
        Array.prototype.forEach.call(tables, initTable);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () { initAll(document); });
    } else {
        initAll(document);
    }
    document.body.addEventListener('htmx:afterSwap', function (event) {
        initAll(event.target);
    });
    // Out-of-band and settled content (e.g. related tabs) can land outside event.target.
    document.body.addEventListener('htmx:afterSettle', function () {
        initAll(document);
    });

    window.SmallStackTableResize = { init: initAll, reset: resetWidths };
})();
