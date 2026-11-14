/* Component builder — the form for a saved card (ComponentCRUDView).
 *
 * The real inputs are the palette's `type` radios, the source fields and a
 * hidden `options` JSON field (what REST/MCP and agents write directly). A
 * card that draws data has one of two sources:
 *
 *   - a dataset it filters here: `dataset`, the hidden `filter_tree` (drawn by
 *     datasets/js/filter-tree.js, the metric form's editor), `agg`, `measure`
 *     and `period_field` — any design;
 *   - a saved metric: the `metric` select — only the designs that show one
 *     number (`single_value`), since a metric is a filtered result rolled up to
 *     one value and a chart needs the rows.
 *
 * The `cb_source` radios are the switch between them; picking a chart while
 * on a metric switches to a dataset with that metric's filter copied in.
 * This file draws each type's options from its options_schema — so a type an
 * app registers (a chart) gets a form with no builder changes — dims the
 * designs the source can't support, drops column options and drill-down
 * columns that aren't in a newly chosen dataset (saying which), and keeps a
 * live preview rendered by dashboards/api/card-preview/, the same render_cell
 * a dashboard uses. A card with its own source has no rows route until it's
 * placed, so the preview's rows are posted to dashboards/preview-rows/ with
 * the definition.
 *
 * Option field types: choice | multichoice (a tick-list of the choices, kept
 * as one comma-separated string) | integer | number | text | boolean | column
 * (a column of the source's dataset) | widget (a published info card) |
 * markdown. A `stylable` type also gets "Style it": the shared settings in
 * data.style (components.CARD_STYLE) → options.style, and its own colour rules
 * → options.thresholds. A card over a metric inherits its number format, unit
 * and colour rules: the style section says what it's taking from the metric,
 * marks a setting that overrides it, and resets it. A card with its own source
 * formats itself.
 */
(function () {
    "use strict";

    function el(tag, attrs, text) {
        var node = document.createElement(tag);
        Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, attrs[k]); });
        if (text != null) node.textContent = text;
        return node;
    }

    function start() {
        var form = document.getElementById("cb-form");
        if (!form) return;
        var data = JSON.parse(document.getElementById("cb-data").textContent);
        var NEEDS = data.reasons || {};   // apps.datasets.capabilities.REASONS
        var types = {};
        data.types.forEach(function (t) { types[t.type] = t; });
        var metrics = {};
        data.metrics.forEach(function (m) { metrics[m.key] = m; });
        var datasets = {};
        (data.datasets || []).forEach(function (d) { datasets[d.key] = d; });
        var metricSel = document.getElementById("cb-metric");
        var sourceCard = document.getElementById("cb-source-card");
        var sourceDataset = document.getElementById("cb-source-dataset");
        var sourceMetric = document.getElementById("cb-source-metric");
        var datasetSel = document.getElementById("cb-dataset");
        var aggSel = document.getElementById("cb-agg");
        var measureInput = document.getElementById("cb-measure");
        var measureSel = document.getElementById("cb-measure-select");
        var measureField = document.getElementById("cb-measure-field");
        var periodFieldInput = document.getElementById("cb-period-field");
        var periodFieldSel = document.getElementById("cb-period-select");
        var treeInput = form.querySelector('[name="filter_tree"]');
        var clearedNote = document.getElementById("cb-cleared");
        var switchedNote = document.getElementById("cb-source-switched");
        var optionsBox = document.getElementById("cb-options");
        var noOptions = document.getElementById("cb-no-options");
        var optionsInput = form.querySelector('[name="options"]');
        var preview = document.getElementById("cb-preview");
        var frame = document.getElementById("cb-frame");
        var problemsEl = document.getElementById("cb-problems");
        var periodSel = document.getElementById("cb-period");
        var nameInput = form.querySelector('[name="name"]');
        var schemaCache = {};

        var options = {};
        try { options = JSON.parse(optionsInput.value || "{}") || {}; } catch (e) { options = {}; }

        function currentType() {
            var r = form.querySelector('input[name="type"]:checked');
            return r ? types[r.value] : null;
        }
        function shared() {
            // The card's own choice, or (a card of one dashboard) that dashboard's, as a hidden field.
            var v = form.querySelector('[name="visibility"]:checked, input[type="hidden"][name="visibility"]');
            return !!v && v.value === "shared";
        }
        function writeOptions() { optionsInput.value = JSON.stringify(options); }
        function postHeaders() {
            var token = form.querySelector("[name=csrfmiddlewaretoken]");
            return { "Content-Type": "application/json", "X-CSRFToken": token ? token.value : "" };
        }

        // -- the source: a dataset filtered here, or a saved metric ---------------
        function sourceMode() {
            var r = form.querySelector('input[name="cb_source"]:checked');
            return r ? r.value : "dataset";
        }
        function setSourceMode(mode) {
            var r = form.querySelector('input[name="cb_source"][value="' + mode + '"]');
            if (r) r.checked = true;
        }
        // The chosen source in one shape, whichever kind it is: what the palette,
        // the options, the style section and the preview read.
        //   {dataset, caps, no_period, inline, key?, name, format, unit, thresholds, edit_url?}
        function currentSource() {
            if (sourceMode() === "metric") return metrics[metricSel.value] || null;
            var d = datasets[datasetSel.value];
            if (!d) return null;
            var hasDate = d.caps.indexOf("date") >= 0;
            var pf = periodFieldInput.value;
            return {
                dataset: d.key, name: d.label, inline: true,
                caps: pf ? d.caps : d.caps.filter(function (c) { return c !== "date"; }),
                no_period: hasDate && !pf,
                format: (options.style || {}).format || "number", unit: (options.style || {}).unit || "", thresholds: options.thresholds || [],
            };
        }
        // What the form posts for the source: the fields of one kind, the other blank.
        function sourceBody() {
            if (sourceMode() === "metric") return { metric: metricSel.value };
            var tree = {};
            try { tree = JSON.parse(treeInput.value || "{}") || {}; } catch (e) { tree = {}; }
            return { dataset: datasetSel.value, filter_tree: tree, agg: aggSel.value || "count", measure: measureInput.value, period_field: periodFieldInput.value };
        }

        // -- the palette: dim what the source can't draw ---------------------------
        function whyNot(t) {
            if (!t.needs_metric) return "";
            var src = currentSource();
            // A metric over a dataset: a chart filters that dataset itself. One with no
            // dataset (entered by hand, a rate) is drawn as it is.
            if (sourceMode() === "metric" && !t.single_value && src && src.definition) return "Filters a dataset of its own. Pick it and the metric's filter is copied in.";
            if (!src || !t.requires.length) return "";
            var missing = t.requires.filter(function (r) { return src.caps.indexOf(r) < 0; });
            if (!missing.length) return "";
            // The data has dates; the source doesn't say which column it's read over.
            if (src.no_period && missing.indexOf("date") >= 0) {
                return src.inline ? "Needs a period column: the date column it is read over." : "This metric has no period field, so it can't be read over time.";
            }
            return "This data " + missing.map(function (r) { return NEEDS[r] || "needs " + r; }).join(" and ") + ".";
        }
        // Under the metric picker: where the period field is set, since it isn't here.
        function syncPeriodNote() {
            var note = document.getElementById("cb-metric-period");
            if (!note) return;
            var t = currentType(), m = sourceMode() === "metric" ? metrics[metricSel.value] : null;
            var show = !!t && t.needs_metric && t.requires.indexOf("date") >= 0 && !!m && !!m.no_period;
            note.hidden = !show;
            if (!show) return;
            var link = document.getElementById("cb-metric-period-link"), owner = document.getElementById("cb-metric-period-owner");
            link.hidden = !m.edit_url;
            owner.hidden = !!m.edit_url;
            if (m.edit_url) link.href = m.edit_url;
        }
        function paintPalette() {
            form.querySelectorAll(".cb-tile").forEach(function (tile) {
                var t = types[tile.getAttribute("data-type")];
                var why = t ? whyNot(t) : "";
                tile.classList.toggle("is-unavailable", !!why);
                tile.querySelector("[data-why]").textContent = why;
                // The compact view has no room for the reason: the tooltip carries it.
                tile.title = (t ? t.description : "") + (why ? " — " + why : "");
            });
        }

        // -- the metric select: shared cards draw only shared metrics ----------
        function filterMetrics() {
            var only = shared();
            Array.prototype.forEach.call(metricSel.options, function (o) {
                if (!o.value) return;
                var hide = only && o.getAttribute("data-shared") !== "1";
                o.hidden = hide;
                o.disabled = hide;
            });
            if (metricSel.selectedOptions[0] && metricSel.selectedOptions[0].disabled) metricSel.value = "";
        }

        // -- the dataset branch: the filter editor, the roll-up, the period column --
        var treeEditor = null;
        var schemas = {};        // dataset key → schema(), once loaded
        var schemaSeq = 0;
        function schemaFor(key, done) {
            if (!key) { done(null); return; }
            if (schemas[key]) { done(schemas[key]); return; }
            var url = form.getAttribute("data-schema-url").replace("DATASET", encodeURIComponent(key));
            fetch(url, { credentials: "same-origin" }).then(function (r) { return r.ok ? r.json() : null; }).then(function (schema) {
                if (schema) schemas[key] = schema;
                done(schema);
            }).catch(function () { done(null); });
        }
        function fillSelect(sel, pairs, current, emptyLabel) {
            sel.textContent = "";
            sel.appendChild(el("option", { value: "" }, emptyLabel));
            var known = false;
            pairs.forEach(function (pair) {
                var o = el("option", { value: pair[0] }, pair[1]);
                if (pair[0] === current) { o.selected = true; known = true; }
                sel.appendChild(o);
            });
            if (current && !known) { var o = el("option", { value: current }, current + " (not in this data)"); o.selected = true; sel.appendChild(o); }
        }
        function syncMeasure() {
            var needs = ["sum", "avg", "median", "min", "max", "distinct"].indexOf(aggSel.value) >= 0;
            measureField.hidden = !needs;
            if (!needs) { measureInput.value = ""; measureSel.value = ""; }
        }
        // Draw the roll-up and period controls for the chosen dataset's columns.
        function applySchema(schema) {
            var cols = (schema && schema.columns) || [];
            var measures = cols.filter(function (c) { return c.role === "measure"; }).map(function (c) { return [c.name, c.label + (c.computed ? " (ratio)" : "")]; });
            var others = cols.filter(function (c) { return c.role !== "measure"; }).map(function (c) { return [c.name, c.label]; });
            fillSelect(measureSel, measures.concat(others), measureInput.value, "Choose a column…");
            var dates = ((schema && schema.filters) || []).filter(function (f) { return f.column_type === "date" || f.column_type === "datetime"; })
                .map(function (f) { return [f.name, f.label || f.name]; });
            fillSelect(periodFieldSel, dates, periodFieldInput.value, "— none: the card ignores the period —");
            if (treeEditor) treeEditor.setSchema(schema);
            syncMeasure();
        }
        function loadDataset(done) {
            var key = datasetSel.value;
            var mine = ++schemaSeq;
            schemaFor(key, function (schema) {
                if (mine !== schemaSeq) return;
                applySchema(schema);
                if (done) done(schema);
            });
        }

        // -- options that name a column: drop what isn't in the data any more --
        // A card's Group by, Of column and drill-down columns are columns of its
        // source's dataset. Change the dataset (or the metric, to one over another
        // dataset) and some of them stop existing: the server would refuse the
        // save, so clear them here and say which went.
        var lastDataset = null;
        function reconcileColumns(schema) {
            var key = schema ? datasetKey() : "";
            if (lastDataset === key) return;
            var first = lastDataset === null;
            lastDataset = key;
            if (first || !schema) return;
            stash = {};   // another design's settings named the old dataset's columns
            var names = (schema.columns || []).map(function (c) { return c.name; });
            var t = currentType(), gone = [];
            (t && t.options || []).forEach(function (spec) {
                if (spec.type === "column" && options[spec.name] && names.indexOf(options[spec.name]) < 0) {
                    gone.push(spec.label.toLowerCase());
                    delete options[spec.name];
                }
            });
            var d = options.drilldown;
            if (d) {
                var kept = (d.columns || []).filter(function (c) { return names.indexOf(typeof c === "string" ? c : c.field) >= 0; });
                var dropped = (d.columns || []).length - kept.length;
                if (dropped) gone.push(dropped + " drill-down column" + (dropped === 1 ? "" : "s"));
                d.columns = kept;
                if (d.sort && names.indexOf(String(d.sort).replace(/^-/, "")) < 0) { delete d.sort; gone.push("the drill-down sort"); }
                if (!kept.length) { delete options.drilldown; drillStash = null; }
            }
            Object.keys(schemaCache).forEach(function (k) { delete schemaCache[k]; });
            writeOptions();
            var label = (datasets[key] || {}).label || key;
            clearedNote.hidden = !gone.length;
            clearedNote.textContent = gone.length ? "Cleared " + gone.join(", ") + ": not in " + label + ". Choose again below." : "";
        }
        function datasetKey() {
            var src = currentSource();
            return src ? src.dataset : "";
        }
        // Columns of the source's dataset for a "column" option (dimensions only).
        function columnsFor(done) {
            var key = datasetKey();
            if (!key) { done([]); return; }
            if (schemaCache[key]) { done(schemaCache[key]); return; }
            schemaFor(key, function (schema) {
                var cols = ((schema && schema.columns) || []).filter(function (c) {
                    var isDate = c.type === "date" || c.type === "datetime";
                    return c.role === "dimension" && !c.computed && !isDate;
                }).map(function (c) { return [c.name, c.label]; });
                schemaCache[key] = cols;
                done(cols);
            });
        }

        // -- start from a metric's filter: copy its definition into this card ----
        function copyDefinition(m, note) {
            var def = m.definition;
            if (!def) return;
            datasetSel.value = def.dataset;
            treeInput.value = JSON.stringify(def.filter_tree || {});
            aggSel.value = def.agg || "count";
            measureInput.value = def.measure || "";
            periodFieldInput.value = def.period_field || "";
            // Its format, unit and colour rules, where this card hasn't set its own.
            var style = Object.assign({}, options.style || {});
            if (!style.format && m.format && m.format !== "number") style.format = m.format;
            if (!style.unit && m.unit) style.unit = m.unit;
            if (Object.keys(style).length) options.style = style;
            if (!options.thresholds && m.thresholds && m.thresholds.length) options.thresholds = JSON.parse(JSON.stringify(m.thresholds));
            writeOptions();
            switchedNote.hidden = false;
            switchedNote.textContent = note;
            onSourceChange();
        }
        var startSel = document.getElementById("cb-start-metric");
        var startBtn = document.getElementById("cb-start-copy");
        if (startSel && startBtn) {
            startSel.addEventListener("change", function () { startBtn.disabled = !startSel.value; });
            startBtn.addEventListener("click", function () {
                var m = metrics[startSel.value];
                if (m) copyDefinition(m, "Started from “" + m.name + "”. The filter is this card's own now: changing it here changes nothing else.");
            });
        }

        function syncSourceMode() {
            var t = currentType();
            var draws = !!(t && t.needs_metric);
            sourceCard.hidden = !draws;
            var mode = sourceMode();
            sourceDataset.hidden = mode !== "dataset";
            sourceMetric.hidden = mode !== "metric";
            // One source: the other kind's field is blank, so the form never posts both.
            if (mode === "dataset") metricSel.value = "";
            else datasetSel.value = "";
            metricSel.disabled = mode !== "metric";
            datasetSel.disabled = mode !== "dataset";
        }
        function onSourceChange() {
            syncSourceMode();
            if (sourceMode() === "dataset") {
                loadDataset(function (schema) {
                    reconcileColumns(schema);
                    renderOptions(); syncStyleCard(); paintPalette(); syncPeriodNote(); schedulePreview();
                });
                return;
            }
            var m = metrics[metricSel.value];
            schemaFor(m ? m.dataset : "", function (schema) {
                reconcileColumns(schema);
                renderOptions(); syncStyleCard(); paintPalette(); syncPeriodNote(); schedulePreview();
            });
        }

        // Several of the choices, ticked: the value is their keys, comma-separated,
        // in the order the choices come. A key already saved that isn't offered
        // (a calendar this person can't see) stays, shown by its key, until unticked.
        function multichoice(spec, id) {
            var chosen = String(options[spec.name] == null ? "" : options[spec.name]).split(",")
                .map(function (k) { return k.trim(); }).filter(Boolean);
            var offered = (spec.choices || []).map(function (c) { return Array.isArray(c) ? c : [c, c]; });
            var known = offered.map(function (c) { return String(c[0]); });
            var rows = offered.map(function (c) { return [String(c[0]), c[1], false]; });
            chosen.forEach(function (k) { if (known.indexOf(k) < 0) rows.push([k, k, true]); });
            var wrap = el("fieldset", { class: "mb-field cb-multi", id: id });
            wrap.appendChild(el("legend", {}, spec.label));
            var list = el("div", { class: "cb-multi-list" });
            var boxes = [];
            var sync = function () {
                var keys = boxes.filter(function (b) { return b.checked; }).map(function (b) { return b.value; });
                if (keys.length) options[spec.name] = keys.join(",");
                else delete options[spec.name];
                writeOptions();
                schedulePreview();
            };
            rows.forEach(function (r, n) {
                var box = el("input", { type: "checkbox", id: id + "-" + n, value: r[0] });
                box.checked = chosen.indexOf(r[0]) >= 0;
                box.addEventListener("change", sync);
                boxes.push(box);
                var row = el("label", { class: "cb-multi-item", for: id + "-" + n });
                row.appendChild(box);
                row.appendChild(el("span", {}, r[1]));
                if (r[2]) row.appendChild(el("span", { class: "cb-multi-note" }, "not one you can see"));
                list.appendChild(row);
            });
            if (!rows.length) list.appendChild(el("p", { class: "mb-help" }, "There's nothing to choose from yet."));
            wrap.appendChild(list);
            if (spec.help) wrap.appendChild(el("p", { class: "mb-help" }, spec.help));
            return wrap;
        }

        // A "links" option (the menu card): rows of label, address and new-window,
        // in the order they'll show; stored as [{label, url, new_window}].
        function linksEditor(spec, id) {
            var wrap = el("div", { class: "mb-field cb-links" });
            wrap.appendChild(el("span", { class: "cb-links-label", id: id + "-label" }, spec.label));
            var list = el("ol", { class: "cb-links-rows", "aria-labelledby": id + "-label" });
            var items = Array.isArray(options[spec.name]) ? options[spec.name].map(function (i) { return Object.assign({}, i); }) : [];
            var focusAfter = null;
            var sync = function () {
                options[spec.name] = items.map(function (i) {
                    var out = { label: i.label || "", url: i.url || "" };
                    if (i.new_window) out.new_window = true;
                    return out;
                });
                writeOptions();
                schedulePreview();
            };
            var paint = function () {
                list.textContent = "";
                items.forEach(function (item, n) {
                    var row = el("li", { class: "cb-links-row" });
                    var label = el("input", { type: "text", class: "vTextField", placeholder: "Words", maxlength: "60", "aria-label": "Link " + (n + 1) + " words" });
                    label.value = item.label || "";
                    label.addEventListener("input", function () { item.label = label.value; sync(); });
                    var url = el("input", { type: "text", class: "vTextField", placeholder: "/page or https://…", "aria-label": "Link " + (n + 1) + " address" });
                    url.value = item.url || "";
                    url.addEventListener("input", function () { item.url = url.value; sync(); });
                    var win = el("label", { class: "plf-check cb-links-win", title: "Open in a new window" });
                    var box = el("input", { type: "checkbox", "aria-label": "Link " + (n + 1) + " opens a new window" });
                    box.checked = !!item.new_window;
                    box.addEventListener("change", function () { item.new_window = box.checked; sync(); });
                    win.appendChild(box);
                    win.appendChild(el("span", {}, "New window"));
                    var tools = el("span", { class: "cb-links-tools" });
                    [["↑", "Move up", -1], ["↓", "Move down", 1]].forEach(function (b) {
                        var btn = el("button", { type: "button", class: "plf-tool", "aria-label": b[1] + " link " + (n + 1) }, b[0]);
                        btn.disabled = n + b[2] < 0 || n + b[2] >= items.length;
                        btn.addEventListener("click", function () {
                            items.splice(n + b[2], 0, items.splice(n, 1)[0]);
                            focusAfter = [n + b[2], b[2] < 0 ? "up" : "down"];
                            sync(); paint();
                        });
                        tools.appendChild(btn);
                    });
                    var rm = el("button", { type: "button", class: "plf-tool", "aria-label": "Remove link " + (n + 1) }, "✕");
                    rm.addEventListener("click", function () { items.splice(n, 1); sync(); paint(); });
                    tools.appendChild(rm);
                    [label, url, win, tools].forEach(function (x) { row.appendChild(x); });
                    row.setAttribute("data-row", String(n));
                    list.appendChild(row);
                });
                if (!items.length) list.appendChild(el("li", { class: "mb-help" }, "No links yet."));
                if (focusAfter) {
                    var btns = list.querySelectorAll('[data-row="' + focusAfter[0] + '"] .plf-tool');
                    var target = btns[focusAfter[1] === "up" ? 0 : 1];
                    if (target && !target.disabled) target.focus(); else if (btns[0]) btns[0].focus();
                    focusAfter = null;
                }
            };
            var add = el("button", { type: "button", class: "btn-outline btn-sm" }, "Add a link");
            add.addEventListener("click", function () {
                items.push({ label: "", url: "", new_window: false });
                sync(); paint();
                var last = list.querySelector('[data-row="' + (items.length - 1) + '"] input');
                if (last) last.focus();
            });
            paint();
            wrap.appendChild(list);
            wrap.appendChild(add);
            if (spec.help) wrap.appendChild(el("p", { class: "mb-help" }, spec.help));
            return wrap;
        }

        // What another design was set to, kept while this one is tried: a trend's
        // buckets survive a look at the pie, and come back when the trend does.
        // By option name, so a column the designs share (the group-by) carries
        // straight across. Never saved: only `options` goes with the form.
        var stash = {};
        function stashed(spec) {
            var v = stash[spec.name];
            if (v == null) return null;
            if (spec.type === "choice") {   // another design's "kind" may mean other choices
                var ok = (spec.choices || []).some(function (c) { return String(Array.isArray(c) ? c[0] : c) === String(v); });
                return ok ? v : null;
            }
            return v;
        }
        function renderOptions() {
            var t = currentType();
            optionsBox.textContent = "";
            if (!t) return;
            // Set aside what this design doesn't take, and bring back what it does.
            var names = (t.options || []).map(function (s) { return s.name; });
            if (t.stylable) names.push("style", "thresholds");   // the shared styling (Style it)
            if (t.drillable) names.push("drilldown");            // Drill-down
            if (t.needs_metric) names.push("publish", "listen");  // Linked cards
            else if (t.publishes) names.push("publish");
            Object.keys(options).forEach(function (k) { if (names.indexOf(k) < 0) { stash[k] = options[k]; delete options[k]; } });
            (t.options || []).forEach(function (spec) {
                if (options[spec.name] == null && stashed(spec) != null) options[spec.name] = stashed(spec);
            });
            ["style", "thresholds", "drilldown"].forEach(function (k) {
                if (names.indexOf(k) >= 0 && options[k] == null && stash[k] != null) options[k] = stash[k];
            });
            noOptions.hidden = !!(t.options || []).length;
            (t.options || []).forEach(function (spec) {
                var id = "cb-opt-" + spec.name;
                var wrap = el("div", { class: "mb-field" });
                var label = el("label", { for: id }, spec.label);
                var input;
                var value = options[spec.name] != null ? options[spec.name] : spec.default;
                // A project's own editor for its own option type (cards.js: optionEditors).
                var custom = (window.SmallStackDashboards && window.SmallStackDashboards.optionEditors || {})[spec.type];
                if (custom) {
                    var node = custom({
                        spec: spec,
                        value: options[spec.name],
                        set: function (v) {
                            if (v == null || v === "") delete options[spec.name]; else options[spec.name] = v;
                            writeOptions(); schedulePreview();
                        },
                        columns: columnsFor,
                        source: currentSource,
                    });
                    if (node) { node.classList.add("cb-opt--wide"); optionsBox.appendChild(node); }
                    return;
                }
                if (spec.type === "multichoice") {
                    var ticks = multichoice(spec, id);
                    ticks.classList.add("cb-opt--wide");
                    optionsBox.appendChild(ticks);
                    return;
                }
                if (spec.type === "links") {
                    var links = linksEditor(spec, id);
                    links.classList.add("cb-opt--wide");
                    optionsBox.appendChild(links);
                    return;
                }
                // A choice drawn as pills or swatches (cards.js), not a select.
                var picker = spec.type === "choice" && window.SmallStackDashboards && window.SmallStackDashboards.choiceWidget
                    ? window.SmallStackDashboards.choiceWidget(spec, value, function (v) {
                        if (v === "") delete options[spec.name]; else options[spec.name] = v;
                        writeOptions(); schedulePreview();
                    }, id)
                    : null;
                if (picker) {
                    if (value != null && value !== "" && options[spec.name] == null) options[spec.name] = value;
                    wrap.appendChild(el("span", { class: "cb-opt-label", id: id + "-label" }, spec.label));
                    picker.setAttribute("aria-labelledby", id + "-label");
                    wrap.appendChild(picker);
                    if (spec.help) wrap.appendChild(el("p", { class: "mb-help" }, spec.help));
                    optionsBox.appendChild(wrap);
                    return;
                }
                if (spec.type === "choice" || spec.type === "column" || spec.type === "widget") {
                    input = el("select", { id: id, class: "vTextField" });
                    var fill = function (pairs) {
                        input.textContent = "";
                        if (!spec.required || spec.type !== "choice") input.appendChild(el("option", { value: "" }, spec.type === "choice" ? "—" : "Choose…"));
                        pairs.forEach(function (c) {
                            var pair = Array.isArray(c) ? c : [c, c];
                            var o = el("option", { value: pair[0] }, pair[1]);
                            if (String(pair[0]) === String(value == null ? "" : value)) o.selected = true;
                            input.appendChild(o);
                        });
                        if (input.value && options[spec.name] == null) { options[spec.name] = input.value; writeOptions(); }
                    };
                    if (spec.type === "choice") fill(spec.choices || []);
                    else if (spec.type === "widget") fill((data.widgets || []).map(function (w) { return [w.key, w.title]; }));
                    else columnsFor(function (cols) { fill(cols); schedulePreview(); });
                } else if (spec.type === "boolean") {
                    input = el("input", { id: id, type: "checkbox" });
                    input.checked = !!value;
                } else if (spec.type === "markdown") {
                    input = el("textarea", { id: id, rows: "5", class: "vTextField cb-markdown" });
                    input.value = value || "";
                } else {
                    input = el("input", { id: id, class: "vTextField", type: (spec.type === "number" || spec.type === "integer") ? "number" : "text" });
                    if (spec.min != null) input.min = spec.min;
                    if (spec.max != null) input.max = spec.max;
                    if (value != null) input.value = value;
                }
                var sync = function () {
                    if (spec.type === "boolean") options[spec.name] = input.checked;
                    else if (spec.type === "number" || spec.type === "integer") {
                        if (input.value === "") delete options[spec.name];
                        else options[spec.name] = spec.type === "integer" ? parseInt(input.value, 10) : Number(input.value);
                    } else if (input.value === "") delete options[spec.name];
                    else options[spec.name] = input.value;
                    writeOptions();
                    schedulePreview();
                };
                input.addEventListener("change", sync);
                input.addEventListener("input", sync);
                if (spec.type === "boolean") {
                    var box = el("label", { class: "plf-check" });
                    box.appendChild(input);
                    box.appendChild(el("span", {}, spec.label));
                    wrap.appendChild(box);
                } else {
                    wrap.appendChild(label);
                    wrap.appendChild(input);
                }
                if (spec.help) wrap.appendChild(el("p", { class: "mb-help" }, spec.help));
                if (spec.type === "markdown" || spec.type === "text") wrap.classList.add("cb-opt--wide");
                optionsBox.appendChild(wrap);
                if (spec.type === "boolean" && options[spec.name] == null) { options[spec.name] = !!value; }
                if ((spec.type === "integer" || spec.type === "number") && options[spec.name] == null && value != null) {
                    options[spec.name] = value;
                }
            });
            renderLinks(t);
            writeOptions();
        }

        // -- Linked cards: a click here narrows another card, or this one listens --
        // options.publish = "<channel>"; options.listen = {channel, map?: {their: mine}}.
        // Checked on save (components.link_problems); the page's bus is cards.js.
        var CHANNEL_HELP = "A name both cards use: lower-case letters, digits, - or _.";
        function renderLinks(t) {
            if (!t || !(t.needs_metric || t.publishes)) return;
            var box = el("div", { class: "cb-opt--wide cb-links-block" });
            box.appendChild(el("span", { class: "cb-opt-label" }, "Linked cards (optional)"));
            var row = el("div", { class: "cb-links-grid" });
            var field = function (labelText, input, help) {
                var f = el("div", { class: "mb-field" });
                f.appendChild(el("label", { for: input.id }, labelText));
                f.appendChild(input);
                if (help) f.appendChild(el("p", { class: "mb-help" }, help));
                row.appendChild(f);
                return f;
            };
            var clean = function (v) { return v.trim().toLowerCase().replace(/[^a-z0-9_-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40); };
            if (t.publishes && !t.shows_rows) {
                var pub = el("input", { id: "cb-link-publish", type: "text", class: "vTextField", placeholder: "e.g. day", maxlength: "40" });
                pub.value = options.publish || "";
                pub.addEventListener("change", function () {
                    var v = clean(pub.value);
                    pub.value = v;
                    if (v) options.publish = v; else delete options.publish;
                    writeOptions();
                });
                field("Send clicks to", pub, t.needs_metric
                    ? "A click on a group, bar or bucket narrows the cards listening here, instead of opening its rows."
                    : "A click on a day narrows the cards listening here to that day: their own date column, unless they say otherwise.");
            }
            if (!t.needs_metric) { box.appendChild(row); optionsBox.appendChild(box); return; }   // sends only; nothing of its own to narrow
            var listen = options.listen || {};
            var mapping = listen.map || {};
            var theirs = Object.keys(mapping)[0] || "";
            var lis = el("input", { id: "cb-link-listen", type: "text", class: "vTextField", placeholder: "e.g. day", maxlength: "40" });
            lis.value = listen.channel || "";
            var from = el("input", { id: "cb-link-from", type: "text", class: "vTextField", placeholder: "their column", maxlength: "60" });
            from.value = theirs;
            var to = el("select", { id: "cb-link-to", class: "vTextField" });
            var sync = function () {
                var ch = clean(lis.value);
                lis.value = ch;
                if (!ch) { delete options.listen; writeOptions(); return; }
                var next = { channel: ch };
                if (from.value.trim() && to.value) { next.map = {}; next.map[from.value.trim()] = to.value; }
                options.listen = next;
                writeOptions();
            };
            [lis, from, to].forEach(function (x) { x.addEventListener("change", sync); });
            field("Listen to", lis, CHANNEL_HELP + " This card shows only what the other card's click selects.");
            var mapField = field("Match their column", from, "Only when the cards read different data: the column the other card filters (a calendar sends date)…");
            mapField.appendChild(el("label", { for: "cb-link-to", class: "cb-link-to-label" }, "…to this card's column"));
            mapField.appendChild(to);
            allColumns(function (cols) {
                to.appendChild(el("option", { value: "" }, "The same name"));
                cols.forEach(function (c) {
                    var o = el("option", { value: c.name }, c.label || c.name);
                    if (mapping[theirs] === c.name) o.selected = true;
                    to.appendChild(o);
                });
            });
            box.appendChild(row);
            optionsBox.appendChild(box);
        }

        // -- Style it: the shared card styling (components.CARD_STYLE) ----------
        var styleCard = document.getElementById("cb-style-card");
        var styleBox = document.getElementById("cb-style");
        var ownRules = document.getElementById("cb-own-rules");
        var rulesBox = document.getElementById("cb-rules");
        var ruleRows = document.getElementById("cb-rule-rows");
        var rulesFallback = document.getElementById("cb-rules-fallback");
        var nameStep = document.getElementById("cb-name-step");
        var STYLE = data.style || [];
        var OPS = (data.thresholds && data.thresholds.ops) || [">", ">=", "<", "<=", "=", "!=", "between"];
        var STATES = (data.thresholds && data.thresholds.states) || ["success", "warning", "danger", "muted"];

        // What a card takes from its metric unless the card sets its own.
        var INHERITED = { format: 1, unit: 1 };
        function formatLabel(key) {
            var spec = STYLE.filter(function (x) { return x.name === "format"; })[0];
            var hit = spec && spec.choices.filter(function (c) { return c[0] === key; })[0];
            return hit ? hit[1].split(" — ")[0] : key;
        }
        var inheritNote = document.getElementById("cb-inherit");
        // The metric a card over one inherits from; null for a card with its own source.
        function inheritedMetric() {
            var t = currentType();
            return t && t.needs_metric && sourceMode() === "metric" ? metrics[metricSel.value] || null : null;
        }
        function renderInherit() {
            var m = inheritedMetric();
            inheritNote.textContent = "";
            inheritNote.hidden = !m;
            if (inheritNote.hidden) return;
            inheritNote.appendChild(el("strong", {}, "From " + m.name + ": "));
            var parts = ["format: " + formatLabel(m.format || "number"), m.unit ? "unit: " + m.unit : "no unit",
                (m.thresholds && m.thresholds.length) ? m.thresholds.length + " colour rule" + (m.thresholds.length === 1 ? "" : "s") : "no colour rules"];
            inheritNote.appendChild(document.createTextNode(parts.join(", ") + ". Change any of them below for this card only; edits to the metric reach every setting you leave alone."));
        }
        function renderStyle() {
            styleBox.textContent = "";
            renderInherit();
            var current = options.style || {};
            var t = currentType();
            var m = inheritedMetric();
            var allowed = (t && t.style_settings) || STYLE.map(function (x) { return x.name; });
            STYLE.forEach(function (spec) {
                if (allowed.indexOf(spec.name) < 0) return;   // e.g. an info card has no number format
                var id = "cb-style-" + spec.name;
                var inherited = INHERITED[spec.name] && !!m;
                var overridden = inherited && current[spec.name];
                var wrap = el("div", { class: "mb-field" + (overridden ? " cb-overridden" : "") });
                // Pills or swatches (cards.js) for a setting that asks for them.
                var picker = window.SmallStackDashboards && window.SmallStackDashboards.choiceWidget
                    ? window.SmallStackDashboards.choiceWidget(spec, current[spec.name] || spec.default, function (v) {
                        var style = Object.assign({}, options.style || {});
                        if (v === "" || v === spec.default) delete style[spec.name]; else style[spec.name] = v;
                        if (Object.keys(style).length) options.style = style; else delete options.style;
                        writeOptions(); schedulePreview();
                    }, id)
                    : null;
                if (picker) {
                    wrap.appendChild(el("span", { class: "cb-opt-label", id: id + "-label" }, spec.label));
                    picker.setAttribute("aria-labelledby", id + "-label");
                    wrap.appendChild(picker);
                    styleBox.appendChild(wrap);
                    return;
                }
                wrap.classList.add("cb-opt--wide-ish");
                wrap.appendChild(el("label", { for: id }, spec.label));
                var input;
                if (spec.choices) {
                    input = el("select", { id: id, class: "vTextField" });
                    spec.choices.forEach(function (c) {
                        var text = c[1];
                        if (spec.name === "format" && c[0] === "" && inherited) text = "From the metric: " + formatLabel(m.format || "number");
                        var o = el("option", { value: c[0] }, text);
                        if (String(current[spec.name] || spec.default) === String(c[0])) o.selected = true;
                        input.appendChild(o);
                    });
                } else {
                    input = el("input", { id: id, class: "vTextField", type: "text", maxlength: String(spec.max || 20) });
                    input.value = current[spec.name] || "";
                    if (spec.name === "unit" && inherited) input.placeholder = m.unit ? "From the metric: " + m.unit : "From the metric: none";
                }
                var sync = function () {
                    var style = Object.assign({}, options.style || {});
                    if (input.value === "" || input.value === spec.default) delete style[spec.name];
                    else style[spec.name] = input.value;
                    if (Object.keys(style).length) options.style = style; else delete options.style;
                    writeOptions();
                    schedulePreview();
                };
                input.addEventListener("change", function () {
                    sync();
                    if (INHERITED[spec.name]) { renderStyle(); var again = document.getElementById(id); if (again) again.focus(); }
                });
                input.addEventListener("input", sync);
                wrap.appendChild(input);
                if (overridden) {
                    var note = el("p", { class: "cb-override" }, "Overrides the metric. ");
                    var reset = el("button", { type: "button", class: "cb-reset" }, "Use the metric's");
                    reset.addEventListener("click", function () {
                        var style = Object.assign({}, options.style || {});
                        delete style[spec.name];
                        if (Object.keys(style).length) options.style = style; else delete options.style;
                        writeOptions(); renderStyle(); schedulePreview();
                        var again = document.getElementById(id); if (again) again.focus();
                    });
                    note.appendChild(reset);
                    wrap.appendChild(note);
                }
                if (spec.help && !inherited) wrap.appendChild(el("p", { class: "mb-help" }, spec.help));
                styleBox.appendChild(wrap);
            });
        }

        function describeRules(rules) {
            if (!rules || !rules.length) return "none set";
            return rules.map(function (r) {
                var v = r.op === "between" && Array.isArray(r.value) ? r.value[0] + "–" + r.value[1] : r.value;
                return r.op + " " + v + " → " + r.state;
            }).join(", ");
        }
        var rulesTitle = document.getElementById("cb-rules-title");
        function renderRules() {
            var m = inheritedMetric();
            var t = currentType();
            // An info card has no metric: without its own rules it keeps the app's status colour.
            rulesTitle.textContent = m ? "Override the metric's colour rules for this card." : "Colour rules for this card.";
            rulesFallback.textContent = t && !t.needs_metric
                ? "Otherwise it keeps the colour its app gives it. Rules compare the card's number."
                : m ? "Otherwise it uses the metric's: " + describeRules(m.thresholds) + ". They stay in step with the metric until you override them."
                : "Without rules the number keeps the card's colour. Rules compare the card's number.";
            var own = Array.isArray(options.thresholds);
            ownRules.checked = own;
            rulesBox.hidden = !own;
            ruleRows.textContent = "";
            (options.thresholds || []).forEach(function (rule, i) {
                var row = el("div", { class: "cb-rule" });
                var op = el("select", { class: "vTextField", "aria-label": "Rule " + (i + 1) + " comparison" });
                OPS.forEach(function (o) { var x = el("option", { value: o }, o); if (o === rule.op) x.selected = true; op.appendChild(x); });
                var lo = el("input", { class: "vTextField", type: "number", step: "any", "aria-label": "Rule " + (i + 1) + " value" });
                var hi = el("input", { class: "vTextField", type: "number", step: "any", "aria-label": "Rule " + (i + 1) + " upper value" });
                var between = rule.op === "between" && Array.isArray(rule.value);
                lo.value = between ? rule.value[0] : (rule.value != null ? rule.value : "");
                hi.value = between ? rule.value[1] : "";
                hi.hidden = rule.op !== "between";
                // The colour as swatches (cards.js), a select where that isn't there.
                var state = rule.state;
                var st = window.SmallStackDashboards && window.SmallStackDashboards.choiceWidget
                    ? window.SmallStackDashboards.choiceWidget(
                        { name: "state", label: "Rule " + (i + 1) + " colour", widget: "swatches", choices: STATES.map(function (o) { return [o, o]; }) },
                        state, function (v) { state = v; sync(); }, "cb-rule-" + i + "-state")
                    : null;
                if (!st) {
                    st = el("select", { class: "vTextField", "aria-label": "Rule " + (i + 1) + " colour" });
                    STATES.forEach(function (o) { var x = el("option", { value: o }, o); if (o === rule.state) x.selected = true; st.appendChild(x); });
                    st.addEventListener("change", function () { state = st.value; });
                }
                var rm = el("button", { type: "button", class: "plf-tool", "aria-label": "Remove rule " + (i + 1) }, "✕");
                var sync = function () {
                    rule.op = op.value;
                    rule.state = state;
                    hi.hidden = op.value !== "between";
                    var a = lo.value === "" ? 0 : Number(lo.value), b = hi.value === "" ? a : Number(hi.value);
                    rule.value = op.value === "between" ? [a, b] : a;
                    writeOptions();
                    schedulePreview();
                };
                [op, lo, hi].forEach(function (x) { x.addEventListener("change", sync); x.addEventListener("input", sync); });
                rm.addEventListener("click", function () {
                    options.thresholds.splice(i, 1);
                    writeOptions(); renderRules(); schedulePreview();
                });
                [op, lo, hi, el("span", { class: "cb-rule-arrow", "aria-hidden": "true" }, "→"), st, rm].forEach(function (x) { row.appendChild(x); });
                ruleRows.appendChild(row);
            });
        }
        ownRules.addEventListener("change", function () {
            if (ownRules.checked) {
                var m = inheritedMetric();
                // Start from the metric's rules, so "own" means "adjusted", not "blank".
                options.thresholds = JSON.parse(JSON.stringify((m && m.thresholds) || []));
            } else {
                delete options.thresholds;
            }
            writeOptions(); renderRules(); schedulePreview();
        });
        document.getElementById("cb-rule-add").addEventListener("click", function () {
            options.thresholds = options.thresholds || [];
            options.thresholds.push({ op: ">=", value: 0, state: "warning" });
            writeOptions(); renderRules(); schedulePreview();
        });
        function syncStyleCard() {
            var t = currentType();
            var on = !!(t && t.stylable);
            var drill = !!(t && t.drillable && t.needs_metric);
            styleCard.hidden = !on;
            drillCard.hidden = !drill;
            // A table's drill-down design is its own columns: the step says so.
            var rowsCard = !!(t && t.shows_rows);
            document.getElementById("cb-drill-heading").textContent = rowsCard ? "Columns" : "Drill-down";
            document.getElementById("cb-drill-optional").hidden = rowsCard;
            var drillHelp = document.getElementById("cb-drill-help");
            drillHelp.innerHTML = drillHelp.getAttribute(rowsCard ? "data-rows" : "data-drill");  // our own template text
            document.getElementById("cb-drill-title").textContent = rowsCard ? "Table columns" : "Drill-down columns";
            document.getElementById("cb-drill-limit-field").hidden = rowsCard;
            // Steps count up over the cards shown: source (data cards only), design, what it shows, style, drill-down, name.
            var step = t && t.needs_metric ? 2 : 1;
            document.getElementById("cb-design-step").textContent = String(step);
            document.getElementById("cb-options-step").textContent = String(++step);
            if (on) document.getElementById("cb-style-step").textContent = String(++step);
            if (drill) drillStep.textContent = String(++step);
            nameStep.textContent = String(++step);
            if (on) { renderStyle(); renderRules(); }
            if (drill) renderDrill();
        }

        // -- Drill-down: the columns the rows modal (and its CSV) shows --------
        // The design is options.drilldown ({columns, sort, limit}); absent = the
        // data's first columns, as stored. It's made in a dialog: every column
        // of the metric's dataset in one list (ticked ones on top, in the order
        // they appear) beside the rows that design opens, redrawn as it changes
        // (dashboards/api/metrics/<key>/rows/?drill=). The form shows it in
        // short. Cancel or Escape puts back what was there when it opened.
        var drillCard = document.getElementById("cb-drill-card");
        var drillStep = document.getElementById("cb-drill-step");
        var drillOwn = document.getElementById("cb-drill-own");
        var drillBox = document.getElementById("cb-drill");
        var drillChips = document.getElementById("cb-drill-chips");
        var drillNote = document.getElementById("cb-drill-note");
        var drillDialog = document.getElementById("cb-drill-dialog");
        var drillShown = document.getElementById("cbd-shown");
        var drillHidden = document.getElementById("cbd-hidden");
        var drillFind = document.getElementById("cbd-find");
        var drillPreview = document.getElementById("cbd-preview");
        var drillFoot = document.getElementById("cbd-foot");
        var drillSort = document.getElementById("cb-drill-sort");
        var drillDir = document.getElementById("cb-drill-dir");
        var drillLimit = document.getElementById("cb-drill-limit");
        var drillAll = document.getElementById("cbd-all");
        var drillNone = document.getElementById("cbd-none");
        var DRILL = data.drilldown || {};
        var FORMATS = DRILL.formats || [["", "As stored"]];
        var MAX_COLS = DRILL.max_columns || 12;
        var DEFAULT_COLS = DRILL.default_columns || 6;
        var DEFAULT_ROWS = DRILL.default_rows || 50;
        var MAX_ROWS = DRILL.max_rows || 500;
        var SAMPLE_ROWS = 25;               // rows the dialog draws, whatever the design opens with
        var NEWEST_FIRST = ["date", "datetime", "integer", "float", "decimal"];
        var fullSchema = {};
        var drillColumns = [], drillByName = {};   // the dataset's columns, once loaded
        var drillStash = null;                     // a design unticked on this page: ticking again brings it back
        var drillBefore = null, drillStashBefore = null, drillKept = false;   // what Cancel restores

        function allColumns(done) {
            var key = datasetKey();
            if (!key) { done([]); return; }
            if (fullSchema[key]) { done(fullSchema[key]); return; }
            schemaFor(key, function (schema) {
                fullSchema[key] = ((schema && schema.columns) || []).filter(function (c) { return !c.computed; });
                done(fullSchema[key]);
            });
        }
        function writeDrill() {
            var d = options.drilldown;
            if (d) {
                if (!d.sort) delete d.sort;
                if (!d.limit) delete d.limit;
            }
            writeOptions();
            schedulePreview();
        }
        function columnLabel(name) { return (drillByName[name] || {}).label || name; }
        function formatName(value) {
            var hit = FORMATS.filter(function (f) { return f[0] === value; })[0];
            return hit ? String(hit[1]).split(" — ")[0] : value;
        }
        function sortWords(sort) {
            var name = sort.replace(/^-/, ""), down = sort.charAt(0) === "-";
            var type = (drillByName[name] || {}).type;
            var how = type === "date" || type === "datetime" ? (down ? "newest first" : "oldest first")
                : NEWEST_FIRST.indexOf(type) >= 0 ? (down ? "largest first" : "smallest first")
                : (down ? "Z to A" : "A to Z");
            return "Sorted by " + columnLabel(name) + ", " + how + ".";
        }
        // The design in short, in the form.
        function paintSummary() {
            var d = options.drilldown;
            drillChips.textContent = "";
            d.columns.forEach(function (col) {
                var chip = el("li", { class: "cbd-chip" + (drillByName[col.field] ? "" : " cbd-chip--missing") }, col.label || columnLabel(col.field));
                if (col.format) chip.appendChild(el("span", { class: "cbd-chip-format" }, formatName(col.format)));
                drillChips.appendChild(chip);
            });
            drillChips.hidden = !d.columns.length;
            var t = currentType();
            drillNote.textContent = (d.columns.length ? "" : "Nothing is ticked, so it shows the data's first six columns. ")
                + (d.sort ? sortWords(d.sort) : "In the data's own order.")
                + (t && t.shows_rows ? " " + (options.rows || 10) + " rows a page." : " Opens with up to " + (d.limit || DEFAULT_ROWS) + " rows.");
        }
        function renderDrill() {
            var own = !!options.drilldown;
            drillOwn.checked = own;
            drillBox.hidden = !own;
            allColumns(function (cols) {
                drillColumns = cols;
                drillByName = {};
                cols.forEach(function (c) { drillByName[c.name] = c; });
                var d = options.drilldown;
                if (!d) return;
                // REST and agents may write a bare field name for {field: name}.
                d.columns = (d.columns || []).map(function (c) { return typeof c === "string" ? { field: c } : c; });
                paintSummary();
                if (drillDialog.open) paintDialog();
            });
        }

        // -- the dialog: one row per column -------------------------------------
        function focusIn(field, role) {
            var rows = drillDialog.querySelectorAll(".cbd-row");
            for (var i = 0; i < rows.length; i++) {
                if (rows[i].getAttribute("data-field") !== field) continue;
                var node = rows[i].querySelector('[data-role="' + role + '"]');
                if (!node || node.disabled) node = rows[i].querySelector("button:not(:disabled), input:not(:disabled)");
                if (node) node.focus();
                return;
            }
        }
        function moveColumn(from, to) {
            var d = options.drilldown;
            if (to < 0 || to >= d.columns.length || to === from) return;
            d.columns.splice(to, 0, d.columns.splice(from, 1)[0]);
            writeDrill(); paintDialog();
        }
        var dragFrom = -1;
        function clearDrop() {
            drillShown.querySelectorAll(".is-drop-before, .is-drop-after").forEach(function (n) { n.classList.remove("is-drop-before", "is-drop-after"); });
        }
        function shownRow(col, n, count) {
            var c = drillByName[col.field];
            var label = c ? c.label : col.field;
            var id = "cbd-col-" + n;
            var row = el("li", { class: "cbd-row cbd-row--on" + (c ? "" : " cbd-row--missing"), "data-field": col.field });
            var grip = el("span", { class: "cbd-grip", "aria-hidden": "true", title: "Drag to reorder" }, "⠿");
            var tick = el("input", { type: "checkbox", id: id, "data-role": "tick" });
            tick.checked = true;
            var name = el("label", { class: "cbd-name", for: id, title: label + " (" + col.field + ")" });
            name.appendChild(el("span", { class: "cbd-label" }, label));
            name.appendChild(el("span", { class: "cbd-kind" }, c ? c.type : "not in this data"));
            var heading = el("input", { class: "vTextField", type: "text", maxlength: "60", placeholder: label, "aria-label": "Heading for " + label, "data-role": "heading" });
            heading.value = col.label || "";
            var format = el("select", { class: "vTextField", "aria-label": "Format for " + label, "data-role": "format" });
            FORMATS.forEach(function (f) { var o = el("option", { value: f[0] }, f[1]); if ((col.format || "") === f[0]) o.selected = true; format.appendChild(o); });
            var tools = el("span", { class: "plf-item-tools" });
            [["up", "Move up", "↑", -1], ["down", "Move down", "↓", 1]].forEach(function (b) {
                var btn = el("button", { type: "button", class: "plf-tool", "aria-label": b[1] + ": " + label, "data-role": b[0] }, b[2]);
                btn.disabled = n + b[3] < 0 || n + b[3] >= count;
                btn.addEventListener("click", function () { moveColumn(n, n + b[3]); focusIn(col.field, b[0]); });
                tools.appendChild(btn);
            });
            tick.addEventListener("change", function () {
                options.drilldown.columns.splice(n, 1);
                writeDrill(); paintDialog(); focusIn(col.field, "tick");
            });
            heading.addEventListener("input", function () {
                if (heading.value) col.label = heading.value; else delete col.label;
                writeDrill(); scheduleRows();
            });
            format.addEventListener("change", function () {
                if (format.value) col.format = format.value; else delete col.format;
                writeDrill(); loadRows();
            });
            // Dragging starts from the grip only, so text in the heading can still be selected.
            grip.addEventListener("mousedown", function () { row.setAttribute("draggable", "true"); });
            grip.addEventListener("mouseup", function () { row.removeAttribute("draggable"); });
            row.addEventListener("dragstart", function (ev) {
                dragFrom = n;
                ev.dataTransfer.effectAllowed = "move";
                ev.dataTransfer.setData("text/plain", col.field);
                row.classList.add("is-dragging");
            });
            row.addEventListener("dragend", function () {
                dragFrom = -1;
                row.removeAttribute("draggable");
                row.classList.remove("is-dragging");
                clearDrop();
            });
            row.addEventListener("dragover", function (ev) {
                if (dragFrom < 0) return;
                ev.preventDefault();
                var box = row.getBoundingClientRect();
                clearDrop();
                row.classList.add(ev.clientY > box.top + box.height / 2 ? "is-drop-after" : "is-drop-before");
            });
            row.addEventListener("drop", function (ev) {
                if (dragFrom < 0) return;
                ev.preventDefault();
                var to = n + (row.classList.contains("is-drop-after") ? 1 : 0);
                if (dragFrom < to) to -= 1;
                var from = dragFrom;
                dragFrom = -1;
                moveColumn(from, to);
                focusIn(options.drilldown.columns[to].field, "tick");
            });
            [grip, tick, name, heading, format, tools].forEach(function (node) { row.appendChild(node); });
            return row;
        }
        function hiddenRow(c, n, full) {
            var id = "cbd-rest-" + n;
            var row = el("li", { class: "cbd-row", "data-field": c.name });
            var tick = el("input", { type: "checkbox", id: id, "data-role": "tick" });
            tick.disabled = full;
            var name = el("label", { class: "cbd-name", for: id, title: c.label + " (" + c.name + ")" });
            name.appendChild(el("span", { class: "cbd-label" }, c.label));
            name.appendChild(el("span", { class: "cbd-kind" }, c.type));
            tick.addEventListener("change", function () {
                options.drilldown.columns.push({ field: c.name });
                writeDrill(); paintDialog(); focusIn(c.name, "tick");
            });
            [el("span", { class: "cbd-grip", "aria-hidden": "true" }), tick, name].forEach(function (node) { row.appendChild(node); });
            return row;
        }
        function paintSortControls() {
            var d = options.drilldown;
            var sort = d.sort || "";
            drillSort.textContent = "";
            drillSort.appendChild(el("option", { value: "" }, "The data's own order"));
            drillColumns.forEach(function (c) { drillSort.appendChild(el("option", { value: c.name }, c.label)); });
            drillSort.value = sort.replace(/^-/, "");
            drillDir.value = sort.charAt(0) === "-" || !sort ? "-" : "";
            drillDir.disabled = !drillSort.value;
            drillLimit.value = d.limit || "";
            drillLimit.placeholder = String(DEFAULT_ROWS);
        }
        function paintDialog() {
            var d = options.drilldown;
            var used = d.columns.map(function (c) { return c.field; });
            var full = used.length >= MAX_COLS;
            var rest = drillColumns.filter(function (c) { return used.indexOf(c.name) < 0; });
            var query = drillFind.value.trim().toLowerCase();
            var found = rest.filter(function (c) {
                return !query || String(c.label).toLowerCase().indexOf(query) >= 0 || c.name.toLowerCase().indexOf(query) >= 0;
            });
            document.getElementById("cbd-count").textContent = used.length + " of " + (used.length + rest.length) + " shown";
            drillShown.textContent = "";
            d.columns.forEach(function (col, n) { drillShown.appendChild(shownRow(col, n, d.columns.length)); });
            document.getElementById("cbd-empty").hidden = !!used.length;
            drillHidden.textContent = "";
            found.forEach(function (c, n) { drillHidden.appendChild(hiddenRow(c, n, full)); });
            document.getElementById("cbd-rest").hidden = !rest.length;
            document.getElementById("cbd-find-wrap").hidden = rest.length < 8;
            document.getElementById("cbd-nomatch").hidden = !!found.length || !rest.length;
            var fullNote = document.getElementById("cbd-full");
            fullNote.hidden = !full || !rest.length;
            fullNote.textContent = "A drill-down shows " + MAX_COLS + " columns at most. Untick one to add another.";
            drillAll.hidden = drillColumns.length > MAX_COLS;
            drillAll.disabled = !rest.length;
            drillNone.disabled = !used.length;
            paintSortControls();
            loadRows();
        }
        function existing(name) {
            return options.drilldown.columns.filter(function (c) { return c.field === name; })[0] || { field: name };
        }
        drillAll.addEventListener("click", function () {
            var d = options.drilldown;
            var used = d.columns.map(function (c) { return c.field; });
            drillColumns.forEach(function (c) { if (used.indexOf(c.name) < 0 && d.columns.length < MAX_COLS) d.columns.push({ field: c.name }); });
            writeDrill(); paintDialog();
            (drillAll.disabled ? drillNone : drillAll).focus();
        });
        document.getElementById("cbd-six").addEventListener("click", function () {
            options.drilldown.columns = drillColumns.slice(0, DEFAULT_COLS).map(function (c) { return existing(c.name); });
            writeDrill(); paintDialog();
        });
        drillNone.addEventListener("click", function () {
            options.drilldown.columns = [];
            writeDrill(); paintDialog();
            document.getElementById("cbd-six").focus();
        });
        drillFind.addEventListener("input", function () { paintDialog(); });
        function syncSort() {
            drillDir.disabled = !drillSort.value;
            options.drilldown.sort = drillSort.value ? drillDir.value + drillSort.value : "";
            writeDrill(); loadRows();
        }
        drillSort.addEventListener("change", syncSort);
        drillDir.addEventListener("change", syncSort);
        drillLimit.addEventListener("input", function () {
            var v = parseInt(drillLimit.value, 10);
            options.drilldown.limit = v >= 1 && v <= MAX_ROWS ? v : 0;
            writeDrill(); paintRowsFoot();
        });

        // -- the rows the design opens -------------------------------------------
        var rowsTimer = null, rowsSeq = 0, rowsOut = null, headFocus = "";
        function scheduleRows() {
            clearTimeout(rowsTimer);
            rowsTimer = setTimeout(loadRows, 300);
        }
        function rowsMessage(text) {
            rowsOut = null;
            drillPreview.replaceChildren(el("p", { class: "cbd-hint" }, text));
            drillFoot.textContent = "";
        }
        function loadRows() {
            clearTimeout(rowsTimer);
            var src = currentSource(), d = options.drilldown;
            if (!src || !d) return;
            var spec = { columns: d.columns };
            if (d.sort) spec.sort = d.sort;
            var period = periodSel.value && periodSel.value !== "all" ? periodSel.value : "";
            var mine = ++rowsSeq;
            var request;
            if (src.inline) {
                // No rows route until the card is placed: post the definition.
                var body = Object.assign(sourceBody(), { limit: SAMPLE_ROWS, drill: spec, period: period });
                request = fetch(form.getAttribute("data-api-preview-rows-url"), {
                    method: "POST", credentials: "same-origin", headers: postHeaders(), body: JSON.stringify(body),
                });
            } else {
                var url = form.getAttribute("data-rows-url").replace("KEY", encodeURIComponent(src.key))
                    + "?limit=" + SAMPLE_ROWS + "&drill=" + encodeURIComponent(JSON.stringify(spec));
                if (period) url += "&period=" + encodeURIComponent(period);
                request = fetch(url, { credentials: "same-origin" });
            }
            request.then(function (r) { return r.json(); }).then(function (out) {
                if (mine !== rowsSeq) return;
                if (out.error || !out.columns) { rowsMessage(out.error || "The rows couldn't be loaded."); return; }
                paintRows(out);
            }).catch(function () {
                if (mine === rowsSeq) rowsMessage("The rows couldn't be loaded.");
            });
        }
        function headerSort(c) {
            var d = options.drilldown, current = d.sort || "";
            d.sort = current === c.name ? "-" + c.name
                : current === "-" + c.name ? c.name
                : (NEWEST_FIRST.indexOf(c.type) >= 0 ? "-" : "") + c.name;
            headFocus = c.name;
            writeDrill(); paintSortControls(); loadRows();
        }
        function paintRowsFoot() {
            if (!rowsOut) return;
            var total = rowsOut.total, shown = rowsOut.rows.length;
            var opens = Math.min(total, (options.drilldown && options.drilldown.limit) || DEFAULT_ROWS);
            drillFoot.textContent = !total ? ""
                : (shown < total ? "First " + shown + " of " + total.toLocaleString() + " rows." : total === 1 ? "The only row." : "All " + total + " rows.")
                + (opens > shown ? " The drill-down opens with " + opens.toLocaleString() + "." : "");
        }
        function paintRows(out) {
            rowsOut = out;
            if (!out.rows.length) {
                drillPreview.replaceChildren(el("p", { class: "cbd-hint" }, "No rows match right now, so there's nothing to show here. The design still applies when there are."));
                drillFoot.textContent = "";
                return;
            }
            var table = el("table", { class: "cbd-table" });
            var head = el("tr");
            var refocus = null;
            out.columns.forEach(function (c) {
                var state = out.sort === c.name ? "ascending" : out.sort === "-" + c.name ? "descending" : "none";
                var th = el("th", { scope: "col", "aria-sort": state });
                var btn = el("button", { type: "button", class: "dm-sort dm-sort--btn", title: "Sort the rows by " + c.label }, c.label);
                btn.appendChild(el("span", { class: "dm-sort-ind", "aria-hidden": "true" }, state === "ascending" ? "▲" : state === "descending" ? "▼" : ""));
                btn.addEventListener("click", function () { headerSort(c); });
                if (headFocus === c.name) refocus = btn;
                th.appendChild(btn);
                head.appendChild(th);
            });
            var thead = el("thead");
            thead.appendChild(head);
            table.appendChild(thead);
            var body = el("tbody");
            out.rows.forEach(function (r) {
                var tr = el("tr");
                r.cells.forEach(function (v) {
                    var text = v === null || v === undefined ? "" : String(v);
                    tr.appendChild(el("td", { title: text }, text));
                });
                body.appendChild(tr);
            });
            table.appendChild(body);
            drillPreview.replaceChildren(table);
            if (refocus) refocus.focus();
            headFocus = "";
            paintRowsFoot();
        }

        // -- opening and closing -------------------------------------------------
        function openDrill(before, stash) {
            drillBefore = before;
            drillStashBefore = stash;
            drillKept = false;
            drillFind.value = "";
            rowsMessage("Loading the rows…");
            paintDialog();
            drillDialog.showModal();
            var first = drillDialog.querySelector(".cbd-row input[type=checkbox]:not(:disabled)");
            if (first) first.focus();
        }
        drillOwn.addEventListener("change", function () {
            if (!drillOwn.checked) {
                drillStash = options.drilldown || null;
                delete options.drilldown;
                writeDrill(); renderDrill();
                return;
            }
            allColumns(function (cols) {
                var stash = drillStash;
                // Start from what it shows now, so choosing is adjusting.
                options.drilldown = stash || { columns: cols.slice(0, DEFAULT_COLS).map(function (c) { return { field: c.name }; }) };
                drillStash = null;
                writeDrill(); renderDrill();
                openDrill(null, stash);
            });
        });
        document.getElementById("cb-drill-edit").addEventListener("click", function () {
            openDrill(JSON.stringify(options.drilldown), drillStash);
        });
        document.getElementById("cb-drill-done").addEventListener("click", function () { drillKept = true; drillDialog.close(); });
        document.getElementById("cb-drill-cancel").addEventListener("click", function () { drillDialog.close(); });
        document.getElementById("cb-drill-x").addEventListener("click", function () { drillDialog.close(); });
        drillDialog.addEventListener("close", function () {
            if (!drillKept) {
                if (drillBefore === null) { delete options.drilldown; drillStash = drillStashBefore; }
                else options.drilldown = JSON.parse(drillBefore);
                writeDrill();
            }
            renderDrill();
        });

        // -- the live preview ---------------------------------------------------
        var timer = null, seq = 0;
        function schedulePreview() {
            clearTimeout(timer);
            timer = setTimeout(runPreview, 300);
        }
        function sizeFrame(t) {
            var w = (t && t.default_size.w) || 3, h = (t && t.default_size.h) || 2;
            frame.style.setProperty("--cb-w", w);
            frame.style.setProperty("--cb-h", h);
        }
        function runPreview() {
            var t = currentType();
            sizeFrame(t);
            if (!t) return;
            if (t.needs_metric && !currentSource()) {
                preview.replaceChildren(el("p", { class: "mb-help" }, sourceMode() === "metric" ? "Choose a metric to see the card." : "Choose a dataset to see the card."));
                problemsEl.textContent = "";
                return;
            }
            // A required choice not made yet is a next step, not a problem: say what to pick.
            var missing = (t.options || []).filter(function (spec) {
                var v = options[spec.name];
                return spec.required && (v === undefined || v === "" || v === null || (Array.isArray(v) && !v.length));
            })[0];
            if (missing) {
                var what = (missing.type === "multichoice" ? "" : "a ") + missing.label.toLowerCase();
                if (missing.type === "links") what = "a link";
                preview.replaceChildren(el("p", { class: "mb-help" }, (missing.type === "links" ? "Add " : "Choose ") + what + " to see the card."));
                problemsEl.textContent = "";
                return;
            }
            var mine = ++seq;
            var body = { type: t.type, options: options, name: nameInput.value, period: periodSel.value, visibility: shared() ? "shared" : "personal" };
            if (t.needs_metric) Object.assign(body, sourceBody());
            fetch(form.getAttribute("data-preview-url"), {
                method: "POST",
                credentials: "same-origin",
                headers: postHeaders(),
                body: JSON.stringify(body),
            }).then(function (r) { return r.json(); }).then(function (out) {
                if (mine !== seq) return;
                problemsEl.textContent = "";
                (out.problems || []).forEach(function (p) { problemsEl.appendChild(el("li", {}, p)); });
                if (out.html) {
                    var holder = el("div", { class: "dash-cell-body" });
                    holder.innerHTML = out.html;
                    preview.replaceChildren(holder);
                    if (window.htmx) window.htmx.process(holder);
                    // Not an htmx swap, so say so ourselves: a scripted card mounts here too (cards.js).
                    if (window.SmallStackDashboards && window.SmallStackDashboards.cardDrawn) window.SmallStackDashboards.cardDrawn(preview);
                } else if ((out.problems || []).length) {
                    preview.replaceChildren(el("p", { class: "mb-help" }, "Fix the problems below to see the card."));
                }
            }).catch(function () {
                if (mine === seq) preview.replaceChildren(el("p", { class: "mb-help" }, "The preview couldn't be loaded."));
            });
        }

        // A card with its own source isn't placed anywhere yet, so its preview
        // links its rows to the preview-rows route: open them by posting the
        // definition with the link's query (a group's narrowing, the drill-down
        // design, the period), and sort the same way from the modal's headers.
        var previewRowsUrl = form.getAttribute("data-preview-rows-url");
        var modalBody = document.getElementById("stat-modal-body");
        function postRows(query, order) {
            var params = {};
            new URLSearchParams(query).forEach(function (v, k) { params[k] = v; });
            var body = Object.assign(sourceBody(), { period: params.period || "", drill: params.drill || "", order: order || "" });
            if (params.narrow) { try { body.narrow = JSON.parse(params.narrow); } catch (e) { body.narrow = null; } }
            if (modalBody) modalBody.innerHTML = '<p style="padding: 24px; text-align: center; color: var(--body-quiet-color);">Loading…</p>';
            fetch(previewRowsUrl, {
                method: "POST", credentials: "same-origin", headers: postHeaders(), body: JSON.stringify(body),
            }).then(function (r) { return r.text(); }).then(function (html) {
                if (!modalBody) return;
                modalBody.innerHTML = html;
                modalBody.setAttribute("data-cb-rows-query", query);
                if (window.htmx) window.htmx.process(modalBody);
            }).catch(function () { if (modalBody) modalBody.textContent = "The rows couldn't be loaded."; });
        }
        preview.addEventListener("click", function (ev) {
            var link = ev.target.closest && ev.target.closest("[hx-get]");
            if (!link || !preview.contains(link) || !previewRowsUrl) return;
            var url = link.getAttribute("hx-get") || "";
            if (url.split("?")[0] !== previewRowsUrl) return;
            ev.preventDefault();
            ev.stopPropagation();
            if (window.openStatModal) window.openStatModal(link.getAttribute("data-stat-modal") || nameInput.value || "Rows", link);
            postRows(url.split("?")[1] || "", "");
        }, true);
        document.addEventListener("click", function (ev) {
            var b = ev.target.closest && ev.target.closest("#stat-modal-body [data-preview-order]");
            if (!b || !modalBody || !modalBody.hasAttribute("data-cb-rows-query")) return;
            postRows(modalBody.getAttribute("data-cb-rows-query"), b.getAttribute("data-preview-order"));
        });

        // -- wiring -------------------------------------------------------------
        function onType() {
            var t = currentType();
            // A chart picked while on a metric: the card filters the dataset itself
            // from here, starting from that metric's filter.
            if (t && t.needs_metric && !t.single_value && sourceMode() === "metric") {
                var m = metrics[metricSel.value];
                if (!m || m.definition) {
                    setSourceMode("dataset");
                    if (m) {
                        copyDefinition(m, "A " + t.label.toLowerCase() + " filters a dataset of its own, so this card started from “" + m.name + "”. Its filter is its own now.");
                        return;
                    }
                    switchedNote.hidden = false;
                    switchedNote.textContent = "A " + t.label.toLowerCase() + " filters a dataset of its own: pick the dataset here.";
                }
            }
            onSourceChange();
        }
        form.addEventListener("change", function (ev) {
            var n = ev.target.name;
            if (n === "type") onType();
            else if (n === "cb_source") { switchedNote.hidden = true; onSourceChange(); }
            else if (n === "metric" || n === "dataset") onSourceChange();
            else if (n === "agg") { syncMeasure(); schedulePreview(); }
            else if (n === "visibility") { filterMetrics(); schedulePreview(); }
        });
        datasetSel.addEventListener("change", function () {
            // Another table: its filter, roll-up column and period column no longer apply.
            treeInput.value = "{}";
            measureInput.value = "";
            periodFieldInput.value = "";
        });
        measureSel.addEventListener("change", function () { measureInput.value = measureSel.value; schedulePreview(); });
        periodFieldSel.addEventListener("change", function () { periodFieldInput.value = periodFieldSel.value; paintPalette(); schedulePreview(); });
        nameInput.addEventListener("input", schedulePreview);
        periodSel.addEventListener("change", schedulePreview);
        form.addEventListener("submit", function () { syncSourceMode(); metricSel.disabled = false; datasetSel.disabled = false; });

        if (window.SmallStackFilterTree) {
            treeEditor = window.SmallStackFilterTree.create({
                mount: document.getElementById("cb-tree"),
                input: treeInput,
                onChange: schedulePreview,
                placeholder: "Pick a dataset to start filtering. No filter means every row.",
            });
        }
        // The palette's view: full for a new card, compact for one being edited,
        // unless this person chose otherwise for that situation before (kept in
        // localStorage per situation, so Full while choosing a design doesn't
        // make every edit page long).
        var palette = document.getElementById("cb-palette");
        if (palette) {
            var VIEW_KEY = "ss_cb_palette_view:" + (palette.getAttribute("data-palette-mode") || "new");
            var paletteView = function (view) {
                palette.classList.toggle("cb-palette--mini", view === "mini");
                var radio = document.getElementById("cb-palette-" + (view === "mini" ? "mini" : "full"));
                if (radio) radio.checked = true;
            };
            var chosen = null;
            try { chosen = window.localStorage.getItem(VIEW_KEY); } catch (e) { chosen = null; }
            paletteView(chosen === "mini" || chosen === "full" ? chosen : palette.getAttribute("data-default-view"));
            form.querySelectorAll('input[name="cb_palette_view"]').forEach(function (r) {
                r.addEventListener("change", function () {
                    if (!r.checked) return;
                    paletteView(r.value);
                    try { window.localStorage.setItem(VIEW_KEY, r.value); } catch (e) { /* private mode: this visit only */ }
                });
            });
        }

        // The card's saved source decides where the switch starts: a metric when
        // it names one, else a dataset (the default for a new card).
        setSourceMode(metricSel.value && !datasetSel.value ? "metric" : "dataset");
        filterMetrics();
        onType();
    }

    // The builder runs on its own page, and inside a dashboard's Edit card
    // dialog, where its form arrives later: dashboard.js calls this then.
    window.SmallStackDashboards = window.SmallStackDashboards || {};
    window.SmallStackDashboards.startComponentBuilder = start;
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
    else start();
})();
