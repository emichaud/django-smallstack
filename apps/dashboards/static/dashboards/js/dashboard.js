/* Dashboards — the grid, edit mode and the "Add card" dialog.
 *
 * View mode: gridstack positions the cells (static grid); each cell's body
 * loads itself over htmx (hx-trigger="load[, every Ns]"), so this file has
 * nothing to do with values.
 *
 * Edit mode: the grid becomes draggable/resizable; Add/Remove mutate a local
 * copy of the layout; Save posts the WHOLE layout to d/<slug>/layout/, where
 * Dashboard.clean() validates it (one write, client state authoritative), and
 * reloads so every cell re-renders from the saved state.
 */
(function () {
    "use strict";
    // Loaded by full pages and by the list displays, which htmx re-renders
    // (and so re-executes) — document-level listeners must attach once.
    if (window.__smallstackDashboardsJs) return;
    window.__smallstackDashboardsJs = true;

    function csrf() {
        var el = document.querySelector("#dash-page [name=csrfmiddlewaretoken]");
        return el ? el.value : "";
    }

    function showErrors(list) {
        var box = document.getElementById("dash-errors");
        if (!box) return;
        box.textContent = "";
        if (!list || !list.length) { box.classList.remove("open"); return; }
        var title = document.createElement("strong");
        title.textContent = "The layout wasn't saved:";
        var ul = document.createElement("ul");
        list.forEach(function (msg) {
            var li = document.createElement("li");
            li.textContent = msg;
            ul.appendChild(li);
        });
        box.appendChild(title);
        box.appendChild(ul);
        box.classList.add("open");
        box.scrollIntoView({ block: "nearest" });
    }

    function initGrid() {
        var page = document.getElementById("dash-page");
        var gridEl = document.getElementById("dash-grid");
        if (!page || !gridEl || typeof GridStack === "undefined") return null;
        return GridStack.init({
            column: 12,
            cellHeight: 70,
            margin: 6,
            staticGrid: true,
            float: false,
            animate: true,
            columnOpts: { breakpoints: [{ w: 700, c: 1 }] },
        }, gridEl);
    }

    function initEditor(grid) {
        var dataEl = document.getElementById("dash-editor-data");
        var page = document.getElementById("dash-page");
        if (!dataEl || !page || !grid) return;
        var editor = JSON.parse(dataEl.textContent);
        var layout = JSON.parse(JSON.stringify(editor.layout || []));
        var removed = {};

        function setEditing(on) {
            grid.setStatic(!on);
            page.classList.toggle("dash-editing", on);
            document.body.classList.toggle("dash-editing-page", on);
        }

        function positions() {
            var pos = {};
            grid.save(false).forEach(function (n) { pos[n.id] = n; });
            return pos;
        }

        function collect(extra) {
            var pos = positions();
            var out = [];
            layout.forEach(function (cell) {
                if (removed[cell.id]) return;
                var p = pos[cell.id];
                var c = Object.assign({}, cell);
                if (p) { c.x = p.x; c.y = p.y; c.w = p.w; c.h = p.h; }
                out.push(c);
            });
            if (extra) out.push(extra);
            return out;
        }

        function save(extra) {
            showErrors([]);
            return fetch(page.dataset.layoutUrl, {
                method: "POST",
                headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
                body: JSON.stringify({ layout: collect(extra) }),
                credentials: "same-origin",
            }).then(function (resp) {
                return resp.json().then(function (data) { return { ok: resp.ok, data: data }; });
            }).then(function (r) {
                if (r.ok) { window.location.reload(); return true; }
                showErrors(r.data.errors || ["Unknown error"]);
                return false;
            }).catch(function () { showErrors(["Network error — try again."]); return false; });
        }

        var editBtn = document.getElementById("dash-edit");
        if (editBtn) editBtn.addEventListener("click", function () { setEditing(true); });
        var cancelBtn = document.getElementById("dash-cancel");
        if (cancelBtn) cancelBtn.addEventListener("click", function () { window.location.reload(); });
        var saveBtn = document.getElementById("dash-save");
        if (saveBtn) saveBtn.addEventListener("click", function () { save(null); });

        page.addEventListener("click", function (ev) {
            var btn = ev.target.closest("[data-remove]");
            if (!btn) return;
            var id = btn.getAttribute("data-remove");
            var item = gridEl().querySelector('.grid-stack-item[gs-id="' + CSS.escape(id) + '"]');
            removed[id] = true;
            if (item) grid.removeWidget(item);
        });

        function gridEl() { return document.getElementById("dash-grid"); }

        // -- Add card dialog -------------------------------------------------
        var dialog = document.getElementById("dash-add-dialog");
        var form = document.getElementById("dash-add-form");
        if (!dialog || !form) return;
        var typeSel = document.getElementById("dash-add-type");
        var metricSel = document.getElementById("dash-add-metric");
        var dimSel = document.getElementById("dash-add-dimension");
        var widgetSel = document.getElementById("dash-add-widget");
        var typeHelp = document.getElementById("dash-add-type-help");
        var types = {};

        function option(sel, value, label) {
            var o = document.createElement("option");
            o.value = value;
            o.textContent = label;
            sel.appendChild(o);
        }

        // "Saved card" places a component from the builder by key; the server
        // copies its design in (normalize_layout) and keeps it in step.
        var compSel = document.getElementById("dash-add-component");
        var savedCards = editor.components || [];
        var typeSizes = {};
        (editor.types || []).forEach(function (t) { typeSizes[t.type] = t.default_size; });
        if (savedCards.length) {
            types.__component = { type: "__component", label: "Saved card", description: "A card from the component builder.", default_size: { w: 3, h: 2 }, options: [] };
            option(typeSel, "__component", "Saved card");
            savedCards.forEach(function (c) { if (compSel) option(compSel, c.key, c.name); });
        }
        (editor.types || []).forEach(function (t) {
            if (t.type === "widget" && !(editor.widgets || []).length) return;
            types[t.type] = t;
            option(typeSel, t.type, t.label);
        });
        (editor.metrics || []).forEach(function (m) { option(metricSel, m.key, m.name + "  (" + m.key + ")"); });
        (editor.widgets || []).forEach(function (w) { option(widgetSel, w.key, w.title); });

        function field(name) { return form.querySelectorAll('[data-for="' + name + '"]'); }
        function toggle(name, on) { field(name).forEach(function (el) { el.hidden = !on; }); }

        function loadDimensions() {
            dimSel.textContent = "";
            var m = (editor.metrics || []).find(function (x) { return x.key === metricSel.value; });
            if (!m) return;
            var url = page.dataset.schemaUrl.replace("DATASET", encodeURIComponent(m.dataset));
            fetch(url, { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (schema) {
                var filterable = {};
                (schema.filters || []).forEach(function (f) { filterable[f.name] = true; });
                (schema.columns || []).forEach(function (c) {
                    var isDate = c.type === "date" || c.type === "datetime";  // one group per instant reads as noise
                    if (c.role === "dimension" && !c.computed && !isDate) option(dimSel, c.name, c.label + (filterable[c.name] ? "" : " (no drill-down)"));
                });
            });
        }

        // The built-in types have hand-built fields above; any other type (one an
        // app registered) gets its fields from its options_schema:
        // [{name, label, type: choice|integer|number|text|boolean, choices?, default?, min?, max?, help?}].
        var BUILTIN = { metric: 1, metric_group: 1, widget: 1, text: 1, __component: 1 };
        var optionsBox = document.getElementById("dash-add-options");
        function renderOptions(t) {
            optionsBox.textContent = "";
            if (BUILTIN[t.type]) return;
            (t.options || []).forEach(function (spec) {
                var label = document.createElement("label");
                var input;
                if (spec.type === "choice") {
                    input = document.createElement("select");
                    (spec.choices || []).forEach(function (c) {
                        var pair = Array.isArray(c) ? c : [c, c];
                        option(input, pair[0], pair[1]);
                    });
                } else if (spec.type === "boolean") {
                    input = document.createElement("input");
                    input.type = "checkbox";
                    input.checked = !!spec.default;
                } else {
                    input = document.createElement("input");
                    input.type = (spec.type === "number" || spec.type === "integer") ? "number" : "text";
                    if (spec.min != null) input.min = spec.min;
                    if (spec.max != null) input.max = spec.max;
                }
                if (spec.type !== "boolean" && spec.default != null) input.value = spec.default;
                input.name = "opt:" + spec.name;
                input.className = spec.type === "boolean" ? "" : "vTextField";
                input.dataset.optType = spec.type || "text";
                if (spec.type === "boolean") { label.appendChild(input); label.appendChild(document.createTextNode(" " + spec.label)); }
                else { label.appendChild(document.createTextNode(spec.label)); label.appendChild(input); }
                optionsBox.appendChild(label);
                if (spec.help) {
                    var help = document.createElement("p");
                    help.className = "dash-hint";
                    help.textContent = spec.help;
                    optionsBox.appendChild(help);
                }
            });
        }
        function readOptions(cell) {
            optionsBox.querySelectorAll("[name^='opt:']").forEach(function (input) {
                var name = input.name.slice(4), kind = input.dataset.optType;
                if (kind === "boolean") cell.options[name] = input.checked;
                else if (kind === "number" || kind === "integer") { if (input.value !== "") cell.options[name] = Number(input.value); }
                else if (input.value !== "") cell.options[name] = input.value;
            });
        }

        function syncType() {
            var t = types[typeSel.value] || {};
            renderOptions(t);
            typeHelp.textContent = t.description || "";
            toggle("component", t.type === "__component");
            toggle("metric", !!t.needs_metric);
            toggle("dimension", t.type === "metric_group");
            toggle("limit", t.type === "metric_group");
            toggle("widget", t.type === "widget");
            toggle("markdown", t.type === "text");
            if (t.type === "metric_group") loadDimensions();
        }

        typeSel.addEventListener("change", syncType);
        metricSel.addEventListener("change", function () { if (typeSel.value === "metric_group") loadDimensions(); });

        document.getElementById("dash-add").addEventListener("click", function () {
            syncType();
            dialog.showModal();
        });
        document.getElementById("dash-add-cancel").addEventListener("click", function () { dialog.close(); });

        form.addEventListener("submit", function (ev) {
            ev.preventDefault();
            var t = types[typeSel.value];
            if (!t) return;
            var data = new FormData(form);
            var bottom = 0;
            collect(null).forEach(function (c) { bottom = Math.max(bottom, (c.y || 0) + (c.h || 1)); });
            if (t.type === "__component") {
                var saved = savedCards.find(function (c) { return c.key === data.get("component"); });
                if (!saved) return;
                var size = typeSizes[saved.type] || { w: 3, h: 2 };
                var placed = { component: saved.key, x: 0, y: bottom, w: size.w, h: size.h };
                if (data.get("title")) placed.title = data.get("title");
                dialog.close();
                save(placed);
                return;
            }
            var cell = { type: t.type, x: 0, y: bottom, w: t.default_size.w, h: t.default_size.h, options: {} };
            if (data.get("title")) cell.title = data.get("title");
            if (t.needs_metric) cell.metric = data.get("metric");
            if (t.type === "metric_group") {
                cell.options.dimension = data.get("dimension");
                cell.options.limit = parseInt(data.get("limit") || "5", 10);
            }
            if (t.type === "widget") cell.options.widget = data.get("widget");
            if (t.type === "text") cell.options.markdown = data.get("markdown") || "";
            readOptions(cell);
            dialog.close();
            save(cell);
        });
    }

    // A search box that hides list items whose data-filter-text doesn't match.
    // On the document, so a box swapped in by htmx (a sort, a period) still works.
    function listFilters() {
        document.addEventListener("input", function (ev) {
            var input = ev.target;
            if (!input.matches || !input.matches("[data-filter-list]")) return;
            var list = document.getElementById(input.getAttribute("data-filter-list"));
            var empty = document.getElementById(input.getAttribute("data-filter-list") + "-empty");
            if (!list) return;
            var q = input.value.trim().toLowerCase(), shown = 0;
            list.querySelectorAll("[data-filter-text]").forEach(function (li) {
                var hit = !q || li.getAttribute("data-filter-text").indexOf(q) >= 0;
                li.hidden = !hit;
                if (hit) shown += 1;
            });
            if (empty) empty.hidden = shown > 0;
        });
    }

    // "Updated 10:42" follows the cells' own loads (initial, auto-refresh,
    // or the Refresh button, which re-fires every cell's hx-trigger).
    function freshness() {
        var stamp = document.getElementById("dash-updated");
        var btn = document.getElementById("dash-refresh");
        if (!stamp) return;
        var fmt = function () {
            return new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
        };
        document.body.addEventListener("htmx:afterSwap", function (ev) {
            if (ev.target.classList && ev.target.classList.contains("dash-cell-body")) {
                stamp.textContent = "Updated " + fmt();
            }
        });
        if (btn) btn.addEventListener("click", function () {
            stamp.textContent = "Refreshing…";
            document.querySelectorAll(".dash-cell-body").forEach(function (el) {
                if (window.htmx) window.htmx.trigger(el, "dash-refresh");
            });
        });
    }

    // The metrics list's toolbar (search, filters, sort) and paginator send only
    // their own inputs over htmx; carry the chosen ?period= along so searching
    // doesn't reset it. hx-get="" (the toolbar) resolves to this page's URL,
    // which already carries it.
    document.addEventListener("htmx:configRequest", function (e) {
        var period = new URLSearchParams(window.location.search).get("period");
        var path = e.detail.path || "";
        var already = ("period" in e.detail.parameters) || /[?&]period=/.test(path) || path === "" || path === window.location.href;
        if (period && e.detail.verb === "get" && !already) e.detail.parameters.period = period;
    });

    // -- changing the period without reloading the page ----------------------
    // A dashboard's period links re-point each card at the new period and let
    // it refresh in place: the old value stays until the new one arrives, so
    // nothing collapses to "Loading…" and the grid doesn't jump. The links keep
    // a real href (and the select a Go button), so it all works without JS.
    function periodInPlace() {
        var page = document.getElementById("dash-page");
        var nav = page && page.querySelector(".dash-toolbar .md-periods");
        if (!nav) return;
        var select = document.getElementById("dash-period-select");
        var quick = {};
        nav.querySelectorAll("a.md-period").forEach(function (a) { quick[keyOf(a.href)] = a; });
        var current = nav.querySelector('a.md-period[aria-current="true"]');
        var initial = current ? keyOf(current.href) : ((select && select.value) || "all");

        function keyOf(href) { return new URL(href, location.href).searchParams.get("period") || "all"; }

        function apply(key, push) {
            page.querySelectorAll(".dash-cell-body[hx-get]").forEach(function (body) {
                var url = new URL(body.getAttribute("hx-get"), location.href);
                url.searchParams.set("period", key);
                var fresh = body.cloneNode(true);   // keeps showing the current value
                fresh.setAttribute("hx-get", url.pathname + url.search);
                body.replaceWith(fresh);
                if (window.htmx) window.htmx.process(fresh);   // its "load" trigger fetches the new value
            });
            Object.keys(quick).forEach(function (k) {
                if (k === key) quick[k].setAttribute("aria-current", "true");
                else quick[k].removeAttribute("aria-current");
            });
            if (select) {
                select.value = quick[key] ? "" : key;
                select.classList.toggle("is-current", !quick[key]);
            }
            if (push) history.pushState({ dashPeriod: key }, "", "?period=" + encodeURIComponent(key));
        }

        nav.addEventListener("click", function (ev) {
            var a = ev.target.closest("a.md-period");
            if (!a || ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.button !== 0) return;  // new-tab clicks still work
            ev.preventDefault();
            apply(keyOf(a.href), true);
        });
        if (select) {
            select.addEventListener("change", function () { if (select.value) apply(select.value, true); });
        }
        window.addEventListener("popstate", function () {
            apply(new URLSearchParams(location.search).get("period") || initial, false);
        });
    }

    // After a period swap elsewhere (index, metrics list, metric page) the
    // clicked link was replaced — put focus back on the newly current one.
    document.addEventListener("htmx:afterSettle", function (ev) {
        var elt = ev.detail && ev.detail.requestConfig && ev.detail.requestConfig.elt;
        if (!elt || !elt.matches) return;
        if (elt.matches("a.md-period")) {
            var now = document.querySelector('.md-periods a.md-period[aria-current="true"]');
            if (now) now.focus({ preventScroll: true });
        } else if (elt.matches("form.md-more")) {
            var sel = document.getElementById(elt.querySelector("select") ? elt.querySelector("select").id : "md-more-period");
            if (sel) sel.focus({ preventScroll: true });
        }
    });


    function onReady(fn) {
        // A script loaded by an htmx swap runs after DOMContentLoaded has fired.
        if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", fn);
        else fn();
    }

    onReady(function () {
        listFilters();
        freshness();
        periodInPlace();
        var grid = initGrid();
        initEditor(grid);
    });
})();
