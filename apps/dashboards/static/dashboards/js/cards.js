/**
 * Where a card's HTML lands, the page says so.
 *
 * A card type that draws with a script (a chart library) needs to mount on
 * every surface that shows cards, and those arrive in different ways: a
 * dashboard's cells and the components gallery over htmx, an embed eagerly
 * in the page, the builder's live preview and the Edit card dialog by hand.
 * This script, written by {% component_media %} ahead of every card type's
 * own files, turns all of them into one event:
 *
 *     document.addEventListener("dashboards:card-drawn", function (ev) {
 *         mountCharts(ev.target);   // the element that now holds the card's HTML
 *     });
 *
 * The event bubbles, fires once per drawn card, and never fires for a cell
 * that is still loading. SmallStackDashboards.cardDrawn(el) fires it for
 * HTML a script put somewhere itself.
 */
(function () {
    "use strict";
    var HOLDERS = ".dash-cell-body, .cc-preview, .cl-peek, #cb-preview";
    var PENDING = ".dash-cell-loading, .cc-ghost, .cc-loading";

    function drawn(el) {
        if (!el || !el.children.length || el.querySelector(PENDING)) return;
        el.dispatchEvent(new CustomEvent("dashboards:card-drawn", { bubbles: true }));
    }
    function drawnIn(root) {
        if (!root) return;
        if (root.matches && root.matches(HOLDERS)) { drawn(root); return; }
        if (!root.querySelectorAll) return;
        root.querySelectorAll(HOLDERS).forEach(drawn);
    }

    document.addEventListener("htmx:afterSettle", function (ev) {
        drawnIn((ev.detail && ev.detail.target) || ev.target);
    });
    function ready() { drawnIn(document); }   // cards already in the page (an eager embed)
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", ready);
    else ready();

    // -- choice widgets: a "choice" option with widget: "segmented" (pills in a
    // row, an icon for an alignment) or "swatches" (colour dots, each the
    // theme token its class names in dashboards.css). Both builders use this
    // in place of a select. Returns the group, or null for a plain choice.
    var ALIGN_ICONS = {
        start: "M3 5h18v2H3zm0 4h12v2H3zm0 4h18v2H3zm0 4h12v2H3z",
        center: "M3 5h18v2H3zm3 4h12v2H6zm-3 4h18v2H3zm3 4h12v2H6z",
        end: "M3 5h18v2H3zm6 4h12v2H9zm-6 4h18v2H3zm6 4h12v2H9z",
    };
    function choiceWidget(spec, current, onChange, idBase) {
        if (spec.widget !== "segmented" && spec.widget !== "swatches") return null;
        var swatches = spec.widget === "swatches";
        var group = document.createElement("div");
        group.className = swatches ? "cb-swatches" : "cb-seg";
        group.setAttribute("role", "radiogroup");
        group.setAttribute("aria-label", spec.label || spec.name);
        (spec.choices || []).forEach(function (c) {
            var pair = Array.isArray(c) ? c : [c, c];
            var value = String(pair[0]), label = String(pair[1]);
            var id = idBase + "-" + (value || "none");
            var input = document.createElement("input");
            input.type = "radio"; input.name = idBase; input.value = value; input.id = id;
            input.className = "sr-only cb-choice-radio";
            input.checked = value === String(current == null ? "" : current);
            input.addEventListener("change", function () { if (input.checked) onChange(value); });
            var lab = document.createElement("label");
            lab.setAttribute("for", id);
            lab.title = label;
            if (swatches) {
                lab.className = "cb-swatch cb-swatch--" + spec.name + "-" + (value || "none");
                var sr = document.createElement("span"); sr.className = "sr-only"; sr.textContent = label;
                lab.appendChild(sr);
            } else {
                lab.className = "cb-seg-item";
                var icon = spec.name === "align" ? ALIGN_ICONS[value] : null;
                if (icon) {
                    lab.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="' + icon + '"/></svg>';  // our own paths
                    var text = document.createElement("span"); text.className = "sr-only"; text.textContent = label;
                    lab.appendChild(text);
                } else lab.textContent = label;
            }
            group.appendChild(input);
            group.appendChild(lab);
        });
        return group;
    }

    // -- linked cards: a click on one narrows another --------------------------
    // A card whose cell says data-publish="<channel>" sends what's clicked in it
    // — the `narrow` filter its rows link already carries (a group, a bucket, a
    // day) — down that channel instead of opening the rows window. A card with
    // data-listen="<channel>" redraws from its own URL with ?narrow=<that tree>;
    // the server maps it to the card's columns, checks it against the card's
    // data and ANDs it on (components.listened_narrow), so it only ever narrows.
    // A chip on the listener says what it's showing and clears it. What travels
    // is an address, never rows; an identical re-send is dropped (the guard for
    // cards pointed at each other); `last` lets a card that loads later catch up.
    var CHANNELS = {};
    function channel(name) { return (CHANNELS[name] = CHANNELS[name] || { subs: [], last: null }); }

    function cellUrl(cell, body) {
        var raw = (body && body.getAttribute("hx-get")) || cell.getAttribute("data-cell-url") || "";
        return raw ? new URL(raw, location.href) : null;
    }
    function redraw(cell, slice) {
        var body = cell.querySelector(".dash-cell-body");
        var url = cellUrl(cell, body);
        if (!body || !url || !window.htmx) return;
        if (slice) url.searchParams.set("narrow", slice.narrow); else url.searchParams.delete("narrow");
        var next = url.pathname + url.search;
        if (body.hasAttribute("hx-get")) body.setAttribute("hx-get", next);   // refreshes and period changes keep it
        else cell.setAttribute("data-cell-url", next);
        if (slice) cell.dataset.sliceLabel = slice.label || ""; else delete cell.dataset.sliceLabel;
        chip(cell, slice);
        window.htmx.ajax("GET", next, { target: body, swap: "innerHTML" });
    }
    function chip(cell, slice) {
        var old = cell.querySelector(".dash-slice");
        if (old) old.remove();
        if (!slice) return;
        var bar = document.createElement("div");
        bar.className = "dash-slice";
        bar.setAttribute("role", "status");
        var text = document.createElement("span");
        text.className = "dash-slice-text";
        text.textContent = "Showing " + (slice.label || "a slice");
        var clear = document.createElement("button");
        clear.type = "button";
        clear.className = "dash-slice-clear";
        clear.setAttribute("aria-label", "Show everything again");
        clear.title = "Show everything again";
        clear.textContent = "✕";
        clear.addEventListener("click", function () {
            var ch = channel(cell.getAttribute("data-listen"));
            ch.last = null;   // so the same click can send it again
            redraw(cell, null);
        });
        bar.appendChild(text);
        bar.appendChild(clear);
        cell.insertBefore(bar, cell.querySelector(".dash-cell-body"));
    }
    function publish(name, slice) {
        var ch = channel(name);
        if (ch.last && ch.last.narrow === slice.narrow) return;
        ch.last = slice;
        document.querySelectorAll('.dash-cell[data-listen="' + CSS.escape(name) + '"]').forEach(function (cell) {
            redraw(cell, slice);
        });
        document.dispatchEvent(new CustomEvent("dashboards:slice", { detail: { channel: name, slice: slice } }));
    }

    // A calendar day (data-day="YYYY-MM-DD") as a slice: that day, [day, next day),
    // on the field "date", which the listening card maps to its own date column.
    function daySlice(dayEl) {
        var iso = dayEl.getAttribute("data-day");
        var next = new Date(iso + "T00:00:00Z");
        next.setUTCDate(next.getUTCDate() + 1);
        var tree = { and: [
            { field: "date", op: ">=", value: iso },
            { field: "date", op: "<", value: next.toISOString().slice(0, 10) },
        ] };
        return { narrow: JSON.stringify(tree), label: dayEl.getAttribute("data-day-label") || iso };
    }

    // Clicks in a publishing card: caught before htmx and the rows window see them.
    document.addEventListener("click", function (ev) {
        if (!ev.target.closest) return;
        var cell = ev.target.closest(".dash-cell[data-publish]");
        var body = cell && cell.querySelector(".dash-cell-body");
        if (!body || !body.contains(ev.target)) return;
        if (document.querySelector(".dash-editing")) return;   // arranging cards: clicks are for that
        var target = ev.target.closest("[hx-get], a[href]");
        var day = ev.target.closest("[data-day]");
        // A day, unless the click was on something inside it with a link of its own (an event).
        if (day && body.contains(day) && (!target || target === day || !day.contains(target))) {
            ev.preventDefault();
            ev.stopPropagation();
            cell.querySelectorAll(".is-sent").forEach(function (n) { n.classList.remove("is-sent"); });
            day.classList.add("is-sent");
            publish(cell.getAttribute("data-publish"), daySlice(day));
            return;
        }
        if (!target) return;
        var raw = target.getAttribute("hx-get") || target.getAttribute("href") || "";
        var narrow = raw ? new URL(raw, location.href).searchParams.get("narrow") : null;
        if (!narrow) return;   // a click with nothing to narrow by (the whole number) opens its rows as usual
        ev.preventDefault();
        ev.stopPropagation();
        // The clicked thing in a few words: "POST", not "Requests, POST" — and,
        // when this card is itself narrowed, what it was narrowed to as well.
        var label = (target.getAttribute("data-stat-modal") || target.getAttribute("aria-label") || target.textContent || "")
            .trim().replace(/, show the rows$/, "");
        var title = cell.querySelector(".trend-label, .stat-card-label");
        if (title && label.indexOf(title.textContent.trim() + ", ") === 0) label = label.slice(title.textContent.trim().length + 2);
        if (cell.dataset.sliceLabel) label = cell.dataset.sliceLabel + " · " + label;
        cell.querySelectorAll(".is-sent").forEach(function (n) { n.classList.remove("is-sent"); });
        target.classList.add("is-sent");
        publish(cell.getAttribute("data-publish"), { narrow: narrow, label: label });
    }, true);

    // Days in a publishing card that aren't links (the upcoming list's) become
    // focusable buttons in effect: Tab reaches them, Enter or Space sends the day.
    document.addEventListener("dashboards:card-drawn", function (ev) {
        var cell = ev.target.closest && ev.target.closest(".dash-cell[data-publish]");
        if (!cell) return;
        cell.querySelectorAll("[data-day]:not(a):not(button)").forEach(function (d) {
            d.setAttribute("tabindex", "0");
            d.setAttribute("role", "button");
            d.setAttribute("aria-label", "Show " + (d.getAttribute("data-day-label") || d.getAttribute("data-day")) + " on the linked cards");
        });
    });
    document.addEventListener("keydown", function (ev) {
        if (ev.key !== "Enter" && ev.key !== " ") return;
        var d = ev.target.closest && ev.target.closest(".dash-cell[data-publish] [data-day][role=button]");
        if (!d || d !== ev.target) return;
        ev.preventDefault();
        d.click();
    });

    // A listener drawn after a slice was sent (lazy, or revealed late) catches up.
    document.addEventListener("dashboards:card-drawn", function (ev) {
        var cell = ev.target.closest && ev.target.closest(".dash-cell[data-listen]");
        if (!cell || cell.querySelector(".dash-slice")) return;
        var ch = CHANNELS[cell.getAttribute("data-listen")];
        if (ch && ch.last) redraw(cell, ch.last);
    });

    window.SmallStackDashboards = window.SmallStackDashboards || {};
    window.SmallStackDashboards.cardDrawn = drawn;
    window.SmallStackDashboards.choiceWidget = choiceWidget;
    window.SmallStackDashboards.publish = publish;
    // Option editors a project registers for its own option types (see the
    // component builder): optionEditors[type] = function ({spec, value, set, columns}) → element.
    window.SmallStackDashboards.optionEditors = window.SmallStackDashboards.optionEditors || {};
})();
