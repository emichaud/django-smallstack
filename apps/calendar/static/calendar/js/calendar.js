/* Calendar — select a day without losing your place.
 *
 * Every grid cell, board day heading and the day column's × are ordinary
 * links to the same page with ?day= changed, so the page works with no
 * script at all. With script, a plain click on one of them fetches that URL
 * and swaps in only the regions marked data-cal-region ("main" — the grid or
 * board, whose selected-day highlight moves; "day" — the right-hand column),
 * so the page never reloads and the scroll position stays where it is. The
 * address bar follows (replaceState) so the URL is still shareable, and any
 * failure falls back to the normal navigation.
 */
(function () {
    'use strict';
    var SELECTOR = 'a.cal-cell, a.cal-dayhead, a.cal-day-close';
    var busy = false;

    function regions(root) {
        var out = {};
        root.querySelectorAll('[data-cal-region]').forEach(function (el) {
            out[el.getAttribute('data-cal-region')] = el;
        });
        return out;
    }

    function swap(href) {
        var here = regions(document);
        if (!here.day) return Promise.reject(new Error('no day region'));
        return fetch(href, { credentials: 'same-origin', headers: { 'X-Requested-With': 'fetch' } })
            .then(function (resp) {
                if (!resp.ok) throw new Error('HTTP ' + resp.status);
                return resp.text();
            })
            .then(function (html) {
                var doc = new DOMParser().parseFromString(html, 'text/html');
                var there = regions(doc);
                if (!there.day) throw new Error('no day region in response');
                Object.keys(here).forEach(function (name) {
                    if (there[name]) here[name].replaceWith(there[name]);
                });
                if (doc.title) document.title = doc.title;
                window.history.replaceState(null, '', href);
            });
    }

    document.addEventListener('click', function (event) {
        if (event.defaultPrevented || event.button !== 0) return;
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        var link = event.target.closest(SELECTOR);
        if (!link || !link.href || link.target || busy) return;
        var url = new URL(link.href, window.location.href);
        if (url.origin !== window.location.origin || url.pathname !== window.location.pathname) return;
        event.preventDefault();
        busy = true;
        swap(url.href)
            .catch(function () { window.location.assign(url.href); })
            .then(function () { busy = false; });
    });

    var sel = document.getElementById('cal-view-select');
    if (sel) sel.addEventListener('change', function () { if (this.value) window.location.assign(this.value); });
})();
