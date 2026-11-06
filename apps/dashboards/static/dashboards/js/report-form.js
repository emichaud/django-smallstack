/* Report form — a row builder over the report's real `items` JSON field (each
 * row a metric, an optional label, and an optional target + at-risk line that
 * colour its values on target / at risk / missed). The rows are a table: its
 * headers sort them, which changes the report's row order (with Undo), and its
 * columns resize. Plus
 * period quick-picks and a live shape preview. The JSON field
 * stays the source of truth (what REST/MCP/agents write), so the page still
 * works without JS. */
(function () {
    "use strict";

    var form, items = [], metrics = [], byKey = {};

    function $(id) { return document.getElementById(id); }
    function q(name) { return form.querySelector('[name="' + name + '"]'); }
    function el(tag, attrs, text) {
        var n = document.createElement(tag);
        Object.keys(attrs || {}).forEach(function (k) {
            if (k === "class") n.className = attrs[k]; else n.setAttribute(k, attrs[k]);
        });
        if (text != null) n.textContent = text;
        return n;
    }
    function readItems() {
        try {
            var parsed = JSON.parse(q("items").value || "[]");
            items = (Array.isArray(parsed) ? parsed : []).map(function (i) {
                if (typeof i === "string") return { metric: i };
                var row = { metric: i.metric || "", label: i.label || "" };
                if (i.target) row.target = i.target;
                if (i.warn) row.warn = i.warn;
                return row;
            });
            return true;
        } catch (e) { return false; }
    }
    function writeItems() {
        q("items").value = JSON.stringify(items.map(function (i) {
            var o = { metric: i.metric };
            if (i.label) o.label = i.label;
            if (i.target) { o.target = i.target; if (i.warn) o.warn = i.warn; }
            return o;
        }), null, 2);
        preview();
    }

    function renderRows() {
        var list = $("rf-rows");
        list.textContent = "";
        $("rf-table-wrap").hidden = !items.length;
        $("rf-empty").hidden = items.length > 0;
        items.forEach(function (item, i) {
            var m = byKey[item.metric];
            var li = el("tr", { class: "rf-row" + (m ? "" : " rf-row--missing") });
            var cell = function (nodes, cls) {
                var td = el("td", cls ? { class: cls } : {});
                nodes.forEach(function (n) { td.appendChild(n); });
                li.appendChild(td);
            };
            cell([el("span", { class: "rf-row-num", "aria-hidden": "true" }, String(i + 1))]);
            var info = el("div", { class: "rf-row-info" });
            info.appendChild(el("div", { class: "rf-row-name" }, m ? m.name : item.metric + " (not available)"));
            var meta = el("div", { class: "rf-row-meta" });
            meta.appendChild(el("code", {}, item.metric));
            if (m) meta.appendChild(document.createTextNode(" · " + m.dataset + (m.period_aware ? "" : " · not period-aware")));
            info.appendChild(meta);
            var label = el("input", { type: "text", class: "vTextField rf-row-label", placeholder: m ? m.name : "Label", "aria-label": "Row label (optional)", maxlength: "120" });
            label.value = item.label || "";
            label.addEventListener("input", function () { item.label = label.value; writeItems(); });
            info.appendChild(label);
            cell([info]);
            var tools = el("div", { class: "rf-row-tools" });
            [["↑", "Move up", -1], ["↓", "Move down", 1]].forEach(function (t) {
                var b = el("button", { type: "button", class: "mb-icon-btn", "aria-label": t[1] + ": " + (m ? m.name : item.metric) }, t[0]);
                var j = i + t[2];
                b.disabled = j < 0 || j >= items.length;
                b.addEventListener("click", function () {
                    clearSort();
                    items.splice(j, 0, items.splice(i, 1)[0]);
                    renderRows(); writeItems();
                });
                tools.appendChild(b);
            });
            var rm = el("button", { type: "button", class: "mb-icon-btn mb-danger", "aria-label": "Remove " + (m ? m.name : item.metric) }, "✕");
            rm.addEventListener("click", function () { clearSort(); items.splice(i, 1); renderRows(); writeItems(); });
            tools.appendChild(rm);
            cell([targetCell(item, m)]);
            cell([item.target ? ruleBox(item, "warn", "At risk", m ? m.name : item.metric) : el("span", { class: "rf-quiet" }, "—")]);
            cell([tools], "rf-tools-cell");
            list.appendChild(li);
        });
        // The add picker offers what isn't already a row.
        var sel = $("rf-add-metric");
        sel.textContent = "";
        var used = {};
        items.forEach(function (i) { used[i.metric] = true; });
        var left = metrics.filter(function (m) { return !used[m.key]; });
        left.forEach(function (m) { sel.appendChild(el("option", { value: m.key }, m.name + "  (" + m.key + ")")); });
        if (!left.length && metrics.length) sel.appendChild(el("option", { value: "" }, "Every metric is already a row"));
        sel.disabled = $("rf-add-btn").disabled = !left.length;
        $("rf-no-metrics").hidden = metrics.length > 0;
    }

    // -- a row's target: its rule, and an optional at-risk line --------------
    var OPS = [[">=", "at least (≥)"], [">", "more than (>)"], ["<=", "at most (≤)"], ["<", "less than (<)"],
        ["=", "exactly (=)"], ["!=", "not (≠)"], ["between", "between"]];
    function num(v) { if (v === "" || v == null) return null; var n = Number(v); return isNaN(n) ? null : n; }
    function ruleBox(item, slot, label, name) {
        var rule = item[slot] || null;
        var wrap = el("div", { class: "rf-rule" });
        var op = el("select", { class: "vTextField", "aria-label": label + " for " + name });
        op.appendChild(el("option", { value: "" }, slot === "target" ? "No target" : "None"));
        OPS.forEach(function (o) { var x = el("option", { value: o[0] }, o[1]); if (rule && rule.op === o[0]) x.selected = true; op.appendChild(x); });
        var a = el("input", { type: "number", step: "any", class: "vTextField rf-num", "aria-label": label + " value for " + name });
        var and = el("span", { class: "rf-and" }, "and");
        var b = el("input", { type: "number", step: "any", class: "vTextField rf-num", "aria-label": label + " upper value for " + name });
        if (rule) {
            if (Array.isArray(rule.value)) { a.value = rule.value[0]; b.value = rule.value[1]; } else if (rule.value != null) a.value = rule.value;
        }
        function sync() {
            var between = op.value === "between";
            and.hidden = b.hidden = !between;
            a.hidden = !op.value;
            if (!op.value) { delete item[slot]; if (slot === "target") delete item.warn; }
            else item[slot] = { op: op.value, value: between ? [num(a.value), num(b.value)] : num(a.value) };
            writeItems();
        }
        op.addEventListener("change", function () { sync(); if (slot === "target") renderRows(); });
        a.addEventListener("input", sync);
        b.addEventListener("input", sync);
        [op, a, and, b].forEach(function (n) { wrap.appendChild(n); });
        and.hidden = b.hidden = op.value !== "between";
        a.hidden = !op.value;
        return wrap;
    }
    function targetCell(item, m) {
        var box = el("div", { class: "rf-target-cell" });
        box.appendChild(ruleBox(item, "target", "Target", m ? m.name : item.metric));
        if (!item.target && m && m.suggest && m.suggest.target) {
            var use = el("button", { type: "button", class: "rf-suggest" }, "Use the colour rules");
            use.addEventListener("click", function () {
                item.target = m.suggest.target;
                if (m.suggest.warn) item.warn = m.suggest.warn;
                renderRows(); writeItems();
            });
            box.appendChild(use);
        }
        return box;
    }

    // -- sorting: these rows ARE the order the report reads in, so a sort rewrites
    // it (until Save; Undo restores it).
    var beforeSort = null, sortKey = "", sortDir = "";
    var SORT_WORDS = { metric: "metric", target: "target", warn: "at-risk line" };
    function ruleNumber(rule) {
        if (!rule) return null;
        var v = Array.isArray(rule.value) ? rule.value[0] : rule.value;
        return typeof v === "number" ? v : null;
    }
    function sortValue(item, key) {
        if (key !== "metric") return ruleNumber(item[key]);
        var m = byKey[item.metric];
        return String(item.label || (m ? m.name : item.metric)).toLowerCase();
    }
    function paintSort() {
        Array.prototype.forEach.call(form.querySelectorAll(".plf-sort"), function (b) {
            var on = b.getAttribute("data-sort") === sortKey;
            b.closest("th").setAttribute("aria-sort", on ? (sortDir === "asc" ? "ascending" : "descending") : "none");
            b.querySelector(".dm-sort-ind").textContent = on ? (sortDir === "asc" ? "▲" : "▼") : "";
        });
        $("rf-sorted").hidden = !beforeSort;
        if (beforeSort) $("rf-sorted-text").textContent = "Sorted by " + SORT_WORDS[sortKey] + ". This is now the order the report reads in; save to keep it.";
    }
    function clearSort() { beforeSort = null; sortKey = ""; sortDir = ""; paintSort(); }
    function bindSorting() {
        Array.prototype.forEach.call(form.querySelectorAll(".plf-sort"), function (b) {
            b.addEventListener("click", function () {
                var key = b.getAttribute("data-sort");
                if (!beforeSort) beforeSort = items.slice();
                sortDir = sortKey === key && sortDir === "asc" ? "desc" : "asc";
                sortKey = key;
                var sign = sortDir === "asc" ? 1 : -1;
                // Nothing to sort by goes last either way; ties keep their order (a stable sort).
                items.sort(function (x, y) {
                    var a = sortValue(x, key), c = sortValue(y, key);
                    if (a === null || c === null) return a === c ? 0 : (a === null ? 1 : -1);
                    return a < c ? -sign : (a > c ? sign : 0);
                });
                renderRows(); writeItems(); paintSort();
                b.focus();
            });
        });
        $("rf-undo").addEventListener("click", function () {
            items = beforeSort;
            clearSort();
            renderRows(); writeItems();
            form.querySelector(".plf-sort").focus();
        });
    }

    // -- columns: the order the person chose, not the chips' order ------------
    var order = [];
    function chip(key) { return form.querySelector('[name="periods"][value="' + key + '"]'); }
    function labelOf(key) {
        var c = chip(key);
        return c ? (c.getAttribute("data-heading") || c.getAttribute("aria-label") || c.parentNode.textContent.trim()) : key;
    }
    function checkedPeriods() {
        return order.map(function (k) { return { key: k, label: labelOf(k) }; });
    }
    function syncOrderFromChips() {
        // Keep the existing order; append newly ticked, drop unticked.
        var ticked = Array.prototype.map.call(form.querySelectorAll('[name="periods"]:checked'), function (c) { return c.value; });
        order = order.filter(function (k) { return ticked.indexOf(k) >= 0; });
        ticked.forEach(function (k) { if (order.indexOf(k) < 0) order.push(k); });
    }
    function renderOrder() {
        var list = $("rf-order");
        list.textContent = "";
        if (!order.length) {
            list.appendChild(el("li", { class: "rf-order-empty" }, "No periods: one “All time” column."));
            return;
        }
        order.forEach(function (k, i) {
            var li = el("li", { class: "rf-order-item" + (i === 0 && order.length > 1 ? " rf-order-item--now" : "") });
            if (i === 1) li.appendChild(el("span", { class: "rf-order-joiner" }, "compared with"));
            if (i > 1) li.appendChild(el("span", { class: "rf-order-joiner" }, "then"));
            var pill = el("span", { class: "rf-order-pill" });
            pill.appendChild(el("span", {}, labelOf(k)));
            if (i > 0) {
                var left = el("button", { type: "button", class: "rf-order-btn", "aria-label": "Move " + labelOf(k) + " earlier" }, "←");
                left.addEventListener("click", function () {
                    order.splice(i - 1, 0, order.splice(i, 1)[0]); renderOrder(); preview();
                });
                pill.insertBefore(left, pill.firstChild);
            }
            var rm = el("button", { type: "button", class: "rf-order-btn", "aria-label": "Remove " + labelOf(k) }, "✕");
            rm.addEventListener("click", function () {
                var c = chip(k); if (c) c.checked = false;
                order.splice(i, 1); renderOrder(); preview();
            });
            pill.appendChild(rm);
            li.appendChild(pill);
            list.appendChild(li);
        });
    }

    // -- the live preview: the unsaved report, evaluated like the report page --
    var timer = null, seq = 0;
    function preview() {
        $("rf-prev-name").textContent = q("name").value || "Untitled report";
        $("rf-prev-desc").textContent = q("description").value;
        var vis = form.querySelector('[name="visibility"]:checked');
        var shared = vis && vis.value === "shared";
        $("rf-prev-vis").textContent = shared ? "Shared" : "Personal";
        $("rf-prev-vis").classList.toggle("dash-badge--shared", shared);
        var n = Math.max(order.length, 1);
        $("rf-prev-shape").textContent = items.length + " row" + (items.length === 1 ? "" : "s") + " × " + n + " column" + (n === 1 ? "" : "s");
        clearTimeout(timer);
        timer = setTimeout(fetchPreview, 300);
    }
    function fetchPreview() {
        var mine = ++seq;
        $("rf-mini-status").textContent = "Updating…";
        fetch(form.getAttribute("data-preview-url"), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "same-origin",
            body: JSON.stringify({ items: items.filter(function (i) { return i.metric; }), periods: order }),
        }).then(function (r) { return r.json(); }).then(function (data) {
            if (mine !== seq) return;  // a newer edit superseded this one
            $("rf-mini-status").textContent = "";
            renderPreview(data);
        }).catch(function () { $("rf-mini-status").textContent = "Preview unavailable"; });
    }
    // A value opens the rows behind it in the global modal (like the report page).
    function drillButton(v, drill) {
        var b = el("button", { type: "button", class: "rf-drill", "aria-haspopup": "dialog",
            "aria-label": drill.title + ": " + v.display + (v.unit ? " " + v.unit : "") + ", show the rows" }, v.display);
        if (v.unit) b.appendChild(el("span", { class: "rp-unit" }, v.unit));
        b.addEventListener("click", function () {
            if (window.openStatModal) window.openStatModal(drill.title, b);
            if (window.htmx) window.htmx.ajax("GET", drill.url, { target: "#stat-modal-body", swap: "innerHTML" });
        });
        return b;
    }
    function valueCell(v, drill) {
        if (!v || v.na) return el("td", { class: "rf-na" }, "n/a");
        if (v.restricted) return el("td", { class: "rf-na" }, "restricted");
        if (v.error) return el("td", { class: "rf-bad", title: v.error }, "error");
        var td = el("td", { class: v.state ? "rf-val--" + v.state : "" });
        if (drill) {
            td.appendChild(drillButton(v, drill));
        } else {
            td.textContent = v.display;
            if (v.unit) td.appendChild(el("span", { class: "rp-unit" }, v.unit));
        }
        return td;
    }
    function drillFor(row, col) {
        if (!row.metric) return null;
        var url = form.getAttribute("data-rows-url").replace("METRIC", encodeURIComponent(row.metric));
        var key = row.period_aware && col && col.key ? col.key : "";
        if (key) url += "?period=" + encodeURIComponent(key);
        return { url: url, title: row.label + (key ? ", " + col.heading.toLowerCase() : "") };
    }
    function renderDigest(data) {
        var line = $("rf-digest");
        var cols = data.columns || [];
        if (cols.length < 2) { line.hidden = true; return; }
        var c = { up: 0, down: 0, flat: 0 };
        (data.rows || []).forEach(function (r) { if (r.delta) c[r.delta.dir] += 1; });
        if (!c.up && !c.down && !c.flat) { line.hidden = true; return; }
        line.textContent = "";
        var moves = el("span", { class: "rl-moves" });
        if (c.up) moves.appendChild(el("span", {}, "▲ " + c.up + " up"));
        if (c.down) moves.appendChild(el("span", {}, "▼ " + c.down + " down"));
        if (c.flat) moves.appendChild(el("span", {}, "= " + c.flat + " unchanged"));
        line.appendChild(moves);
        var against = (data.partial ? "all of " : "") + cols[1].heading.toLowerCase();
        line.appendChild(el("span", { class: "rl-moves-when" }, " " + cols[0].heading.toLowerCase() + " vs " + against));
        line.hidden = false;
    }
    function renderPreview(data) {
        renderDigest(data);
        var mini = $("rf-mini");
        mini.textContent = "";
        var cols = data.columns || [];
        var table = el("table", { class: "rf-mini-table" });
        var head = el("tr");
        head.appendChild(el("th", {}, "Metric"));
        cols.forEach(function (c) { head.appendChild(el("th", {}, c.heading)); });
        var thead = el("thead"); thead.appendChild(head); table.appendChild(thead);
        var tbody = el("tbody");
        (data.rows || []).slice(0, 12).forEach(function (row) {
            var tr = el("tr");
            tr.appendChild(el("td", {}, row.label));
            if (row.missing) {
                tr.appendChild(el("td", { colspan: String(cols.length), class: "rf-bad" }, "metric gone"));
            } else if (row.cells.length === 1 && row.cells[0].span) {
                var span = valueCell(row.cells[0], drillFor(row, null));
                span.setAttribute("colspan", String(cols.length));
                span.classList.add("rf-span");
                span.title = "Same in every period";
                tr.appendChild(span);
            } else {
                row.cells.forEach(function (v, i) {
                    var td = valueCell(v, drillFor(row, cols[i]));
                    if (i === 0 && row.delta) {
                        var arrow = row.delta.dir === "up" ? "▲ " : row.delta.dir === "down" ? "▼ " : "= ";
                        // Narrow sidebar: just the arrow and the figure; the full wording on hover.
                        var short = row.delta.dir === "flat" ? "no change" : row.delta.text.split(" vs ")[0];
                        td.appendChild(el("span", { class: "rf-delta", title: row.delta.text }, arrow + short));
                    }
                    tr.appendChild(td);
                });
            }
            tbody.appendChild(tr);
        });
        if (!(data.rows || []).length) {
            var tr = el("tr");
            tr.appendChild(el("td", { colspan: String(cols.length + 1), class: "rf-na" }, "Add a metric to see rows."));
            tbody.appendChild(tr);
        }
        table.appendChild(tbody);
        mini.appendChild(table);
        var note = (data.rows || []).length > 12 ? "Showing the first 12 rows. " : "";
        if (data.partial) note += "The first column is still running, so its change is against all of the next period.";
        $("rf-mini-note").textContent = note;
    }

    document.addEventListener("DOMContentLoaded", function () {
        form = $("rf-form");
        if (!form) return;
        metrics = JSON.parse($("rf-metrics").textContent || "[]");
        metrics.forEach(function (m) { byKey[m.key] = m; });
        if (!readItems()) items = [];
        renderRows();
        bindSorting();

        $("rf-add-btn").addEventListener("click", function () {
            var key = $("rf-add-metric").value;
            if (!key) return;
            clearSort();
            items.push({ metric: key, label: "" });
            renderRows(); writeItems();
        });

        var name = q("name");
        name.addEventListener("input", preview);
        q("description").addEventListener("input", preview);
        form.addEventListener("change", function (ev) {
            if (ev.target.name === "periods") { syncOrderFromChips(); renderOrder(); }
            preview();
        });

        form.querySelectorAll("[data-preset]").forEach(function (b) {
            b.addEventListener("click", function () {
                var want = b.getAttribute("data-preset").split(",").filter(Boolean);
                form.querySelectorAll('[name="periods"]').forEach(function (c) { c.checked = want.indexOf(c.value) >= 0; });
                order = want.filter(function (k) { return chip(k); });  // the preset's own order
                renderOrder(); preview();
            });
        });

        // Columns start in their saved order (the chips sit in group order).
        try {
            var saved = JSON.parse($("rf-period-order").textContent || "[]");
            order = Array.isArray(saved) ? saved.filter(function (k) { var c = chip(k); return c && c.checked; }) : [];
        } catch (e) { order = []; }
        syncOrderFromChips();
        renderOrder();

        // Submit the columns in the chosen order: the browser would send the
        // checkboxes in DOM (group) order, which would reorder the report.
        form.addEventListener("submit", function () {
            form.querySelectorAll('[name="periods"]').forEach(function (c) { c.removeAttribute("name"); c.setAttribute("data-was-period", c.value); });
            order.forEach(function (k) {
                form.appendChild(el("input", { type: "hidden", name: "periods", value: k }));
            });
        });
        writeItems();  // normalise + pretty-print
    });
})();
