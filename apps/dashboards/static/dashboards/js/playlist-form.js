/* Playlist settings form — an editor over the hidden `items` JSON field
 * (what REST/MCP and agents write directly). An item is a dashboard
 * ({dashboard: slug}) or a goal list ({goals: slug}). Rows can be
 * moved, removed, and given their own seconds and period; the textarea is
 * rewritten on every change, so what's posted is exactly what's shown. */
(function () {
    "use strict";

    function el(tag, attrs, text) {
        var node = document.createElement(tag);
        Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, attrs[k]); });
        if (text != null) node.textContent = text;
        return node;
    }

    document.addEventListener("DOMContentLoaded", function () {
        var form = document.getElementById("plf-form");
        if (!form) return;
        var data = JSON.parse(document.getElementById("plf-data").textContent);
        var byslug = {}, goalsBySlug = {};
        data.dashboards.forEach(function (d) { byslug[d.slug] = d; });
        (data.goal_lists || []).forEach(function (g) { goalsBySlug[g.slug] = g; });
        function itemOf(item) { return item.goals ? goalsBySlug[item.goals] : byslug[item.dashboard]; }
        function itemSlug(item) { return item.goals || item.dashboard; }
        var field = form.querySelector('[name="items"]');
        var list = document.getElementById("plf-items");
        var empty = document.getElementById("plf-empty");
        var picker = document.getElementById("plf-add-select");
        var sharedNote = document.getElementById("plf-shared-note");
        var seconds = form.querySelector('[name="seconds"]');
        var total = document.getElementById("plf-total");
        var tableWrap = document.getElementById("plf-table-wrap");
        var sortedNote = document.getElementById("plf-sorted");
        var sortedText = document.getElementById("plf-sorted-text");
        var sortButtons = Array.prototype.slice.call(document.querySelectorAll(".plf-sort"));

        var items = [];
        try { items = JSON.parse(field.value || "[]"); } catch (e) { items = []; }
        if (!Array.isArray(items)) items = [];
        items = items.map(function (i) { return typeof i === "string" ? { dashboard: i } : i; });

        function shared() {
            var v = form.querySelector('[name="visibility"]:checked');
            return !!v && v.value === "shared";
        }
        function write() {
            field.value = JSON.stringify(items, null, 2);
        }
        function fmt(s) {
            if (s < 60) return s + " s";
            var m = Math.floor(s / 60), r = s % 60;
            return m + " min" + (r ? " " + r + " s" : "");
        }

        function render() {
            list.replaceChildren();
            items.forEach(function (item, n) {
                var d = itemOf(item);
                var row = el("tr", { "class": "plf-item" + (d ? "" : " plf-item--missing") });
                var label = el("span", { "class": "plf-item-name" }, d ? d.name : itemSlug(item) + " (not available)");
                if (item.goals) label.appendChild(el("span", { "class": "dash-badge plf-kind" }, "Goals"));
                // Seconds: the default (a pill saying what it is) until the slide gets a
                // time of its own — then − / value / + with a way back to the default.
                var who = d ? d.name : itemSlug(item);
                var sec = el("span", { "class": "plf-secs" });
                var paintSecs = function () {
                    sec.replaceChildren();
                    var dwell = parseInt(seconds.value, 10) || 30;
                    if (!item.seconds) {
                        var pill = el("button", { type: "button", "class": "plf-secs-default", title: "The playlist's default. Click to give this slide its own time.", "aria-label": "Seconds on " + who + ": the default, " + dwell + ". Set its own" });
                        pill.appendChild(el("span", { "class": "plf-secs-default-word" }, "Default"));
                        pill.appendChild(el("span", { "class": "plf-secs-default-n" }, dwell + " s"));
                        pill.addEventListener("click", function () { item.seconds = dwell; write(); paintSecs(); summary(); sec.querySelector("input").focus(); });
                        sec.appendChild(pill);
                        return;
                    }
                    var input = el("input", { type: "number", min: "5", max: "3600", "class": "vTextField plf-item-seconds", "data-no-stepper": "", "aria-label": "Seconds on " + who });
                    input.value = item.seconds;
                    var step = function (delta) {
                        var v = Math.min(3600, Math.max(5, (parseInt(input.value, 10) || dwell) + delta));
                        input.value = v; item.seconds = v; write(); summary();
                    };
                    var minus = el("button", { type: "button", "class": "plf-secs-btn", "aria-label": "Less time on " + who }, "−");
                    var plus = el("button", { type: "button", "class": "plf-secs-btn", "aria-label": "More time on " + who }, "+");
                    minus.addEventListener("click", function () { step(-5); });
                    plus.addEventListener("click", function () { step(5); });
                    input.addEventListener("input", function () {
                        var v = parseInt(input.value, 10);
                        if (v) item.seconds = v;
                        write(); summary();
                    });
                    input.addEventListener("change", function () {
                        if (!parseInt(input.value, 10)) { delete item.seconds; write(); paintSecs(); summary(); }
                    });
                    var back = el("button", { type: "button", "class": "plf-tool plf-secs-back", title: "Back to the default (" + dwell + " s)", "aria-label": "Use the default time on " + who }, "↺");
                    back.addEventListener("click", function () { delete item.seconds; write(); paintSecs(); summary(); sec.querySelector("button").focus(); });
                    [minus, input, plus, back].forEach(function (x) { sec.appendChild(x); });
                };
                paintSecs();
                var per = el("select", { "class": "vTextField plf-item-period", "aria-label": "Period for " + (d ? d.name : itemSlug(item)) });
                per.appendChild(el("option", { value: "" }, "Dashboard's own"));
                data.periods.forEach(function (p) {
                    var o = el("option", { value: p[0] }, p[1]);
                    if (item.period === p[0]) o.selected = true;
                    per.appendChild(o);
                });
                per.addEventListener("change", function () {
                    if (per.value) item.period = per.value; else delete item.period;
                    write();
                });
                if (item.goals) {
                    // A goal list shows its goals now, last week, or week over week.
                    var show = el("select", { "class": "vTextField plf-item-show", "aria-label": "What " + (d ? d.name : itemSlug(item)) + " shows" });
                    [["", "Goals now"], ["week", "Last week"], ["weeks", "Week over week"]].forEach(function (o) {
                        var x = el("option", { value: o[0] }, o[1]);
                        if ((item.show || "") === o[0]) x.selected = true;
                        show.appendChild(x);
                    });
                    show.addEventListener("change", function () {
                        if (show.value) item.show = show.value; else delete item.show;
                        per.disabled = !!show.value;
                        write();
                    });
                    per.disabled = !!item.show;
                    label.appendChild(show);
                }
                var tools = el("span", { "class": "plf-item-tools" });
                [["up", "Move up", "↑"], ["down", "Move down", "↓"], ["remove", "Remove", "✕"]].forEach(function (b) {
                    var btn = el("button", { type: "button", "class": "plf-tool", "data-act": b[0], "aria-label": b[1] + ": " + (d ? d.name : itemSlug(item)) }, b[2]);
                    if ((b[0] === "up" && n === 0) || (b[0] === "down" && n === items.length - 1)) btn.disabled = true;
                    btn.addEventListener("click", function () { act(b[0], n); });
                    tools.appendChild(btn);
                });
                var cell = function (child, cls) {
                    var td = el("td", cls ? { "class": cls } : {});
                    td.appendChild(child);
                    row.appendChild(td);
                    return td;
                };
                cell(el("span", { "class": "plf-item-n" }, String(n + 1)));
                cell(label);
                cell(sec);   // the column header says "Seconds": no unit after each field
                cell(per);
                cell(tools, "plf-tools-cell");
                list.appendChild(row);
            });
            empty.hidden = items.length > 0;
            tableWrap.hidden = !items.length;
            fillPicker();
            summary();
        }
        // -- sorting: the rows ARE the play order, so a sort rewrites it (until Save, and Undo restores it)
        var beforeSort = null, sortKey = "", sortDir = "";
        var SORT_WORDS = { name: "slide name", seconds: "seconds", period: "period" };
        function periodLabel(item) {
            var hit = data.periods.filter(function (p) { return p[0] === item.period; })[0];
            return hit ? String(hit[1]).toLowerCase() : "";
        }
        function sortValue(item, key) {
            if (key === "seconds") return item.seconds || parseInt(seconds.value, 10) || 30;
            if (key === "period") return periodLabel(item);
            var d = itemOf(item);
            return String(d ? d.name : itemSlug(item)).toLowerCase();
        }
        function paintSort() {
            sortButtons.forEach(function (b) {
                var on = b.getAttribute("data-sort") === sortKey;
                b.closest("th").setAttribute("aria-sort", on ? (sortDir === "asc" ? "ascending" : "descending") : "none");
                b.querySelector(".dm-sort-ind").textContent = on ? (sortDir === "asc" ? "▲" : "▼") : "";
            });
            sortedNote.hidden = !beforeSort;
            if (beforeSort) sortedText.textContent = "Sorted by " + SORT_WORDS[sortKey] + ". This is now the order the slides play in; save to keep it.";
        }
        function clearSort() { beforeSort = null; sortKey = ""; sortDir = ""; paintSort(); }
        sortButtons.forEach(function (b) {
            b.addEventListener("click", function () {
                var key = b.getAttribute("data-sort");
                if (!beforeSort) beforeSort = items.slice();
                sortDir = sortKey === key && sortDir === "asc" ? "desc" : "asc";
                sortKey = key;
                var sign = sortDir === "asc" ? 1 : -1;
                // Blank periods ("its own") go last either way; ties keep their order (a stable sort).
                items.sort(function (x, y) {
                    var a = sortValue(x, key), c = sortValue(y, key);
                    if (key === "period" && (!a || !c)) return a === c ? 0 : (a ? -1 : 1);
                    return a < c ? -sign : (a > c ? sign : 0);
                });
                write(); render(); paintSort();
                b.focus();
            });
        });
        document.getElementById("plf-undo").addEventListener("click", function () {
            items = beforeSort;
            clearSort();
            write(); render();
            if (sortButtons[0]) sortButtons[0].focus();
        });

        function act(what, n) {
            clearSort();  // a hand move or removal: the rows are no longer in sorted order
            if (what === "remove") items.splice(n, 1);
            else {
                var to = what === "up" ? n - 1 : n + 1;
                var moved = items.splice(n, 1)[0];
                items.splice(to, 0, moved);
            }
            write(); render();
            var focus = list.querySelectorAll(".plf-item")[Math.min(n, items.length - 1)];
            if (focus) (focus.querySelector('[data-act="' + what + '"]:not(:disabled)') || focus.querySelector("input")).focus();
        }
        function fillPicker() {
            var only = shared();
            picker.replaceChildren(el("option", { value: "" }, "Choose a dashboard or goal list…"));
            var boards = el("optgroup", { label: "Dashboards" });
            data.dashboards.forEach(function (d) {
                if (only && !d.shared) return;
                boards.appendChild(el("option", { value: "d:" + d.slug }, d.name + (d.shared ? "" : " (personal)")));
            });
            picker.appendChild(boards);
            if ((data.goal_lists || []).length) {
                var goals = el("optgroup", { label: "Goal lists" });
                data.goal_lists.forEach(function (g) {
                    if (only && !g.shared) return;
                    goals.appendChild(el("option", { value: "g:" + g.slug }, g.name + (g.shared ? "" : " (personal)")));
                });
                picker.appendChild(goals);
            }
            sharedNote.hidden = !only;
        }
        function summary() {
            var dwell = parseInt(seconds.value, 10) || 30;
            var sum = items.reduce(function (acc, i) { return acc + (i.seconds || dwell); }, 0);
            total.textContent = items.length
                ? items.length + " slide" + (items.length === 1 ? "" : "s") + ", about " + fmt(Math.round(sum)) + " a round."
                : "Add dashboards or goal lists to see how long a round takes.";
            presets.forEach(function (b) { b.setAttribute("aria-pressed", String(b.getAttribute("data-seconds") === seconds.value)); });
            // A slide on the default shows the number it takes, as the default changes.
            form.querySelectorAll(".plf-secs-default-n").forEach(function (n) { n.textContent = (parseInt(seconds.value, 10) || 30) + " s"; });
        }

        document.getElementById("plf-add").addEventListener("click", function () {
            if (!picker.value) { picker.focus(); return; }
            clearSort();
            var v = picker.value;
            items.push(v.indexOf("g:") === 0 ? { goals: v.slice(2) } : { dashboard: v.slice(2) });
            write(); render();
            picker.focus();
        });
        var presets = Array.prototype.slice.call(document.querySelectorAll("#plf-seconds-presets [data-seconds]"));
        presets.forEach(function (b) {
            b.addEventListener("click", function () { seconds.value = b.getAttribute("data-seconds"); render(); });
        });
        seconds.addEventListener("input", render);
        form.addEventListener("change", function (ev) { if (ev.target.name === "visibility") fillPicker(); });

        write();
        render();
    });
})();
