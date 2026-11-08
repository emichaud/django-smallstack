/* Dashboards — the grid, edit mode, the "Add card" dialog, each card's menu
 * and the "Edit card" dialog.
 *
 * View mode: gridstack positions the cells (static grid); each cell's body
 * loads itself over htmx (hx-trigger="load[, every Ns]"), so this file has
 * nothing to do with values.
 *
 * Edit mode: the grid becomes draggable/resizable; Add/Remove mutate a local
 * copy of the layout; Save posts the WHOLE layout to d/<slug>/layout/, where
 * Dashboard.clean() validates it (one write, client state authoritative), and
 * reloads so every cell re-renders from the saved state.
 *
 * A card's menu (the ⋯ at its corner) works without edit mode: Edit card opens
 * the component builder for that one card in a dialog (d/<slug>/cards/<id>/edit/)
 * and reloads when it saves; Remove saves the layout without the card; Make a
 * unique copy (d/<slug>/cards/<id>/copy/) makes a placed saved card this
 * dashboard's own, where it sits.
 *
 * The page's controls (Refresh, Edit layout…) live in the page header, outside
 * #dash-page; everything here finds them by id.
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

    // What a card's menu may ask of the editor (set by initEditor, for someone who can edit).
    var editorApi = null;

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

        // Each card's place from its own node, not grid.save(): that strips a
        // width or height of 1 as "the default", and the server then fills in
        // the design's default size, so a note squeezed to one row posted as
        // two and "overlapped" the card below it.
        function positions() {
            var pos = {};
            grid.engine.nodes.forEach(function (n) {
                if (n.id) pos[n.id] = { x: n.x || 0, y: n.y || 0, w: n.w || 1, h: n.h || 1 };
            });
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

        editorApi = {
            arrange: function () { setEditing(true); },
            // Straight from the menu: the layout as saved, minus this card.
            removeNow: function (id) { removed[id] = true; return save(null); },
        };

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
        // A split or a chart filters a dataset of its own, which takes the
        // builder: those designs are placed as saved cards (or any card here,
        // then Edit card). The quick picks are a metric's number and the
        // designs that draw no data.
        var builderOnly = [];
        (editor.types || []).forEach(function (t) {
            if (t.type === "widget" && !(editor.widgets || []).length) return;
            if (t.needs_metric && !t.single_value) { builderOnly.push(t.label.toLowerCase()); return; }
            types[t.type] = t;
            option(typeSel, t.type, t.label);
        });
        var builderNote = document.getElementById("dash-add-builder");
        if (builderNote) {
            builderNote.hidden = !builderOnly.length;
            builderNote.querySelector("[data-designs]").textContent = builderOnly.join(", ");
        }
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
        // [{name, label, type: choice|multichoice|integer|number|text|boolean, choices?, default?, min?, max?, help?}].
        // The dialog's own fields for the framework types' first options (the
        // metric, the group-by, the widget, the note's markdown); any other
        // option a type has is drawn from its schema like an app type's.
        var BUILTIN = { metric: 1, metric_group: 1, widget: 1, text: 1, __component: 1 };
        var OWN_FIELDS = { metric: 1, dimension: 1, limit: 1, widget: 1, markdown: 1 };
        var optionsBox = document.getElementById("dash-add-options");
        var customValues = {};   // what a project's own option editors set (readOptions adds them)
        function renderOptions(t) {
            optionsBox.textContent = "";
            customValues = {};
            if (t.type === "__component") return;
            (t.options || []).forEach(function (spec) {
                if (BUILTIN[t.type] && OWN_FIELDS[spec.name]) return;
                var custom = (window.SmallStackDashboards && window.SmallStackDashboards.optionEditors || {})[spec.type];
                if (custom) {
                    var node = custom({
                        spec: spec,
                        value: spec.default,
                        set: function (v) { if (v == null || v === "") delete customValues[spec.name]; else customValues[spec.name] = v; },
                    });
                    if (node) optionsBox.appendChild(node);
                    return;
                }
                if (spec.type === "multichoice") {
                    // A tick-list; readOptions joins the ticked values with commas.
                    var group = document.createElement("fieldset");
                    group.className = "dash-multi";
                    var legend = document.createElement("legend");
                    legend.textContent = spec.label;
                    group.appendChild(legend);
                    var list = document.createElement("div");
                    list.className = "dash-multi-list";
                    group.appendChild(list);
                    (spec.choices || []).forEach(function (c) {
                        var pair = Array.isArray(c) ? c : [c, c];
                        var item = document.createElement("label");
                        item.className = "dash-multi-item";
                        var box = document.createElement("input");
                        box.type = "checkbox";
                        box.value = pair[0];
                        box.dataset.multi = spec.name;
                        item.appendChild(box);
                        item.appendChild(document.createTextNode(" " + pair[1]));
                        list.appendChild(item);
                    });
                    if (spec.help) {
                        var note = document.createElement("p");
                        note.className = "dash-hint";
                        note.textContent = spec.help;
                        group.appendChild(note);
                    }
                    optionsBox.appendChild(group);
                    return;
                }
                var picker = spec.type === "choice" && window.SmallStackDashboards && window.SmallStackDashboards.choiceWidget
                    ? window.SmallStackDashboards.choiceWidget(spec, spec.default, function () {}, "dash-opt-" + spec.name)
                    : null;
                if (picker) {   // pills or swatches: radios named opt:<name>, read like any input
                    picker.querySelectorAll("input").forEach(function (r) { r.name = "opt:" + spec.name; r.dataset.optType = "choice"; });
                    var field = document.createElement("div");
                    field.className = "dash-opt-field";
                    var caption = document.createElement("span");
                    caption.className = "dash-opt-label";
                    caption.textContent = spec.label;
                    field.appendChild(caption);
                    field.appendChild(picker);
                    if (spec.help) {
                        var hint = document.createElement("p");
                        hint.className = "dash-hint";
                        hint.textContent = spec.help;
                        field.appendChild(hint);
                    }
                    optionsBox.appendChild(field);
                    return;
                }
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
                } else if (spec.type === "links") {
                    // One link a line: "Words | /where | new" (the builder has the row editor).
                    input = document.createElement("textarea");
                    input.rows = 4;
                    input.placeholder = "Runbook | /smallstack/runbook/\nStatus | https://status.example.com | new";
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
                // The hint sits inside the field, so a small field keeps its hint beside it in the flow.
                var field2 = document.createElement("div");
                field2.className = "dash-opt-field" + ((spec.type === "markdown" || spec.type === "links" || spec.type === "text") ? " dash-opt-field--wide" : "");
                field2.appendChild(label);
                if (spec.help || spec.type === "links") {
                    var help = document.createElement("p");
                    help.className = "dash-hint";
                    help.textContent = (spec.help || "") + (spec.type === "links" ? " One a line: words | address | new (for a new window)." : "");
                    field2.appendChild(help);
                }
                optionsBox.appendChild(field2);
            });
            renderLinkFields(t);
        }

        // Linked cards (the builder's block, in short): a card that can send its
        // clicks gets "Send clicks to"; a card that draws data gets "Listen to".
        // Channel names are cleaned as typed; the server checks them on save
        // (components.link_problems). A column mapping is the builder's job.
        function linkField(id, labelText, hint) {
            var field = document.createElement("div");
            field.className = "dash-opt-field";
            var label = document.createElement("label");
            label.textContent = labelText;
            var input = document.createElement("input");
            input.type = "text";
            input.id = id;
            input.className = "vTextField";
            input.maxLength = 40;
            input.placeholder = "e.g. day";
            input.addEventListener("change", function () {
                input.value = input.value.trim().toLowerCase().replace(/[^a-z0-9_-]+/g, "-").replace(/^-+|-+$/g, "");
            });
            label.appendChild(input);
            field.appendChild(label);
            var p = document.createElement("p");
            p.className = "dash-hint";
            p.textContent = hint;
            field.appendChild(p);
            return field;
        }
        function renderLinkFields(t) {
            if (!t || t.type === "__component" || !(t.publishes || t.needs_metric)) return;
            var group = document.createElement("fieldset");
            group.className = "dash-multi dash-link-fields";
            var legend = document.createElement("legend");
            legend.textContent = "Linked cards (optional)";
            group.appendChild(legend);
            var row = document.createElement("div");
            row.className = "dash-link-row";
            if (t.publishes && !t.needs_metric) {   // the calendar; charts link in the builder
                row.appendChild(linkField("dash-add-publish", "Send clicks to", "A click on a day narrows the cards listening here to that day."));
            }
            if (t.needs_metric) {
                row.appendChild(linkField("dash-add-listen", "Listen to", "Show only what a click on that channel selects. To match a different column, use Edit card."));
            }
            group.appendChild(row);
            optionsBox.appendChild(group);
        }
        function readOptions(cell) {
            optionsBox.querySelectorAll("[name^='opt:']").forEach(function (input) {
                var name = input.name.slice(4), kind = input.dataset.optType;
                if (input.type === "radio") { if (input.checked && input.value !== "") cell.options[name] = input.value; return; }
                if (kind === "boolean") cell.options[name] = input.checked;
                else if (kind === "links") {
                    cell.options[name] = input.value.split("\n").map(function (line) {
                        var parts = line.split("|").map(function (p) { return p.trim(); });
                        if (!parts[0] && !parts[1]) return null;
                        var item = { label: parts[0] || parts[1] || "", url: parts[1] || "" };
                        if (/^new/i.test(parts[2] || "")) item.new_window = true;
                        return item;
                    }).filter(Boolean);
                }
                else if (kind === "number" || kind === "integer") { if (input.value !== "") cell.options[name] = Number(input.value); }
                else if (input.value !== "") cell.options[name] = input.value;
            });
            var ticked = {};
            optionsBox.querySelectorAll("[data-multi]:checked").forEach(function (box) {
                (ticked[box.dataset.multi] = ticked[box.dataset.multi] || []).push(box.value);
            });
            Object.keys(ticked).forEach(function (name) { cell.options[name] = ticked[name].join(","); });
            var pub = document.getElementById("dash-add-publish"), lis = document.getElementById("dash-add-listen");
            if (pub && pub.value.trim()) cell.options.publish = pub.value.trim();
            if (lis && lis.value.trim()) cell.options.listen = { channel: lis.value.trim() };
            Object.keys(customValues).forEach(function (name) { cell.options[name] = customValues[name]; });
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

    // -- Edit card: the component builder, for one card, in a dialog ---------
    // The fragment is the builder's own form (includes/component_builder.html);
    // component-builder.js starts on it as it does on its page. A save answers
    // JSON and the page reloads; a refusal answers the form again (422).
    function cardEditor() {
        var dialog = document.getElementById("dash-card-dialog");
        var body = document.getElementById("dash-card-dialog-body");
        if (!dialog || !body) return null;

        function note(text) {
            var p = document.createElement("p");
            p.className = "dash-card-dialog-note";
            p.textContent = text;
            body.replaceChildren(p);
        }
        function mount(html) {
            body.innerHTML = html;  // our own template, from our own server
            body.scrollTop = 0;
            var start = window.SmallStackDashboards && window.SmallStackDashboards.startComponentBuilder;
            if (start) start();
            var form = body.querySelector("#cb-form");
            if (!form) return;
            body.querySelectorAll("[data-card-cancel]").forEach(function (b) {
                b.addEventListener("click", function () { dialog.close(); });
            });
            form.addEventListener("submit", function (ev) {
                ev.preventDefault();
                var saveBtn = form.querySelector('[type="submit"]');
                if (saveBtn) saveBtn.disabled = true;
                fetch(form.action, {
                    method: "POST",
                    body: new FormData(form),
                    credentials: "same-origin",
                    headers: { "X-Requested-With": "XMLHttpRequest" },
                }).then(function (resp) {
                    var json = (resp.headers.get("Content-Type") || "").indexOf("json") >= 0;
                    if (resp.ok && json) { window.location.reload(); return null; }
                    if (resp.status === 422) return resp.text().then(mount);
                    throw new Error("not saved");
                }).catch(function () {
                    if (saveBtn) saveBtn.disabled = false;
                    var line = form.querySelector(".cb-dialog-failed") || document.createElement("p");
                    line.className = "crud-error cb-dialog-failed";
                    line.setAttribute("role", "alert");
                    line.textContent = "The card wasn't saved. Check your connection and try again.";
                    var actions = form.querySelector(".cb-dialog-actions");
                    if (actions) actions.appendChild(line);
                });
            });
        }

        document.getElementById("dash-card-dialog-x").addEventListener("click", function () { dialog.close(); });
        // Closed: the builder goes, so its ids are free for the next card.
        dialog.addEventListener("close", function () { body.replaceChildren(); });

        return function open(url) {
            note("Loading the card…");
            dialog.showModal();
            fetch(url, { credentials: "same-origin", headers: { "X-Requested-With": "XMLHttpRequest" } })
                .then(function (resp) {
                    if (!resp.ok) throw new Error("not found");
                    return resp.text();
                })
                .then(mount)
                .catch(function () { note("This card couldn't be opened for editing."); });
        };
    }

    // -- a card's menu (the ⋯ at its corner) --------------------------------
    // One menu for the page, moved to the card that opened it: a card clips
    // what's drawn inside it, and a menu is often taller than a card. Entries
    // are shown by what the opening button carries (data-edit-url,
    // data-metric-url, data-copy-url…); the rest by who's looking (the template
    // leaves out what a viewer can't do). An action that changes the dashboard
    // asks first, in the menu itself.
    function cardMenu(openEditor) {
        var page = document.getElementById("dash-page");
        var menu = document.getElementById("dash-card-menu");
        if (!page || !menu) return;
        var opener = null;
        var pending = null;   // what the question on screen does when answered yes
        var confirm = menu.querySelector("[data-card-confirm]");
        var note = menu.querySelector("[data-card-note]");

        function entry(name) { return menu.querySelector('[data-card-action="' + name + '"]'); }
        function show(name, on) { var n = entry(name); if (n) n.hidden = !on; }
        function attr(name) { return opener.getAttribute(name) || ""; }
        function link(name, url) {
            var a = entry(name);
            if (!a) return;
            a.hidden = !url;
            a.setAttribute("href", url || "#");
        }
        function entries() {
            return Array.prototype.filter.call(menu.querySelectorAll('[role="menuitem"]'), function (n) {
                return n.offsetParent !== null;
            });
        }
        function place() {
            var r = opener.getBoundingClientRect();
            var w = menu.offsetWidth, h = menu.offsetHeight;
            var left = Math.min(Math.max(8, r.right - w), window.innerWidth - w - 8);
            var top = r.bottom + 4;
            if (top + h > window.innerHeight - 8) top = Math.max(8, r.top - h - 4);
            menu.style.left = left + "px";
            menu.style.top = top + "px";
        }
        function settle() {
            pending = null;
            menu.classList.remove("is-asking");
            if (confirm) confirm.hidden = true;
        }
        function close(refocus) {
            if (menu.hidden) return;
            menu.hidden = true;
            settle();
            var was = opener;
            opener = null;
            if (was) {
                was.setAttribute("aria-expanded", "false");
                if (refocus) was.focus();
            }
        }
        function open(btn) {
            close(false);
            opener = btn;
            var linked = !!attr("data-saved-name"), copy = !!attr("data-copy-url");
            show("edit", !!attr("data-edit-url"));
            link("metric", attr("data-metric-url"));
            link("metric-edit", attr("data-metric-edit-url"));
            // A saved card other dashboards show can be made this one's own; a card
            // that is already this dashboard's can be given a metric of its own.
            show("unique", copy && linked);
            show("own-metric", copy && !linked);
            if (note) {
                note.hidden = !linked;
                note.textContent = linked ? "A saved card, on " + attr("data-saved-count") + " dashboards" : "";
            }
            menu.hidden = false;
            btn.setAttribute("aria-expanded", "true");
            place();
            var first = entries()[0];
            if (first) first.focus();
        }
        // Ask before changing the dashboard: {text, option?, yes, run(optionTicked)}.
        function ask(question, back) {
            pending = { run: question.run, back: back };
            menu.querySelector("[data-card-confirm-text]").textContent = question.text;
            var option = menu.querySelector("[data-card-confirm-option]");
            option.hidden = !question.option;
            option.querySelector("span").textContent = question.option || "";
            option.querySelector("input").checked = true;
            entry("yes").textContent = question.yes;
            menu.classList.add("is-asking");
            confirm.hidden = false;
            place();
            entry("keep").focus();
        }
        function quoted(text) { return "“" + text + "”"; }
        function copyCard(url, withMetric) {
            var body = new URLSearchParams();
            if (withMetric) body.set("metric", "1");
            fetch(url, {
                method: "POST",
                body: body,
                credentials: "same-origin",
                headers: { "X-CSRFToken": csrf(), "X-Requested-With": "XMLHttpRequest" },
            }).then(function (resp) {
                return resp.json().then(function (data) { return { ok: resp.ok, data: data }; });
            }).then(function (r) {
                if (r.ok) window.location.reload();
                else showErrors(r.data.errors || ["The card wasn't copied."]);
            }).catch(function () { showErrors(["Network error — try again."]); });
        }

        page.addEventListener("click", function (ev) {
            var btn = ev.target.closest("[data-cell-menu]");
            if (!btn) return;
            if (opener === btn) close(true); else open(btn);
        });
        document.addEventListener("click", function (ev) {
            if (menu.hidden || menu.contains(ev.target) || ev.target.closest("[data-cell-menu]")) return;
            close(false);
        });
        window.addEventListener("resize", function () { close(false); });
        window.addEventListener("scroll", function () { close(false); }, true);

        menu.addEventListener("keydown", function (ev) {
            var list = entries(), at = list.indexOf(document.activeElement);
            if (ev.key === "Escape") { ev.preventDefault(); close(true); }
            else if (ev.key === "Tab" && !pending) close(false);  // a question keeps its checkbox reachable
            else if (ev.key === "ArrowDown") { ev.preventDefault(); list[(at + 1) % list.length].focus(); }
            else if (ev.key === "ArrowUp") { ev.preventDefault(); list[(at - 1 + list.length) % list.length].focus(); }
            else if (ev.key === "Home") { ev.preventDefault(); list[0].focus(); }
            else if (ev.key === "End") { ev.preventDefault(); list[list.length - 1].focus(); }
        });

        menu.addEventListener("click", function (ev) {
            var item = ev.target.closest("[data-card-action]");
            if (!item || !opener) return;
            var action = item.getAttribute("data-card-action");
            var id = attr("data-cell-menu");
            var copyUrl = attr("data-copy-url"), metricName = attr("data-metric-name");
            if (action === "edit") {
                var url = attr("data-edit-url");
                close(false);
                if (openEditor && url) openEditor(url);
            } else if (action === "arrange") {
                close(false);
                if (editorApi) editorApi.arrange();
            } else if (action === "refresh") {
                var body = page.querySelector('.dash-cell[data-cell-id="' + CSS.escape(id) + '"] .dash-cell-body');
                close(true);
                if (body && window.htmx) window.htmx.trigger(body, "dash-refresh");
            } else if (action === "metric" || action === "metric-edit") {
                close(false);  // the link goes on to the metric
            } else if (action === "remove") {
                ask({
                    text: "Remove this card? Its metric stays.",
                    yes: "Remove",
                    run: function () { if (editorApi) editorApi.removeNow(id); },
                }, "remove");
            } else if (action === "unique") {
                ask({
                    text: quoted(attr("data-saved-name")) + " is a saved card on " + attr("data-saved-count")
                        + " dashboards. This one becomes this dashboard's own copy. The saved card and the other dashboards don't change.",
                    option: metricName ? "Copy its metric too (" + quoted(metricName) + "), so its filter can change here alone." : "",
                    yes: "Make the copy",
                    run: function (withMetric) { copyCard(copyUrl, !!metricName && withMetric); },
                }, "unique");
            } else if (action === "own-metric") {
                ask({
                    text: "Copies " + quoted(metricName) + " for this dashboard and points this card at the copy, so its filter can change here alone. The original metric doesn't change.",
                    yes: "Copy the metric",
                    run: function () { copyCard(copyUrl, true); },
                }, "own-metric");
            } else if (action === "keep") {
                var back = pending && pending.back;
                settle();
                place();
                if (back && entry(back)) entry(back).focus();
            } else if (action === "yes") {
                var run = pending && pending.run;
                var ticked = menu.querySelector("[data-card-confirm-option] input").checked;
                close(false);
                if (run) run(ticked);
            }
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
        cardMenu(cardEditor());
    });
})();
