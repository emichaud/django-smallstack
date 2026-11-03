/* Component builder — the form for a saved card (ComponentCRUDView).
 *
 * The real inputs are the palette's `type` radios, the `metric` select and a
 * hidden `options` JSON field (what REST/MCP and agents write directly). This
 * file draws each type's options from its options_schema — so a type an app
 * registers (a chart) gets a form with no builder changes — dims the designs
 * the chosen metric's data can't support, and keeps a live preview rendered
 * by dashboards/api/card-preview/, the same render_cell a dashboard uses.
 *
 * Option field types: choice | integer | number | text | boolean | column
 * (a column of the metric's dataset) | widget (a published info card) |
 * markdown. A `stylable` type also gets "Style it": the shared settings in
 * data.style (components.CARD_STYLE) → options.style, and its own colour rules
 * → options.thresholds (absent = the metric's rules). A card inherits its
 * metric's number format, unit and colour rules: the style section says what
 * it's taking from the metric, marks a setting that overrides it, and resets it.
 */
(function () {
    "use strict";

    function el(tag, attrs, text) {
        var node = document.createElement(tag);
        Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, attrs[k]); });
        if (text != null) node.textContent = text;
        return node;
    }

    document.addEventListener("DOMContentLoaded", function () {
        var form = document.getElementById("cb-form");
        if (!form) return;
        var data = JSON.parse(document.getElementById("cb-data").textContent);
        var NEEDS = data.reasons || {};   // apps.datasets.capabilities.REASONS
        var types = {};
        data.types.forEach(function (t) { types[t.type] = t; });
        var metrics = {};
        data.metrics.forEach(function (m) { metrics[m.key] = m; });
        var metricSel = document.getElementById("cb-metric");
        var metricField = document.getElementById("cb-metric-field");
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
            var v = form.querySelector('[name="visibility"]:checked');
            return !!v && v.value === "shared";
        }
        function writeOptions() { optionsInput.value = JSON.stringify(options); }

        // -- the palette: dim what the metric's data can't draw ---------------
        function whyNot(t) {
            if (!t.needs_metric || !t.requires.length) return "";
            var m = metrics[metricSel.value];
            if (!m) return "";
            var missing = t.requires.filter(function (r) { return m.caps.indexOf(r) < 0; });
            return missing.length ? "This metric's data " + missing.map(function (r) { return NEEDS[r] || "needs " + r; }).join(" and ") + "." : "";
        }
        function paintPalette() {
            form.querySelectorAll(".cb-tile").forEach(function (tile) {
                var t = types[tile.getAttribute("data-type")];
                var why = t ? whyNot(t) : "";
                tile.classList.toggle("is-unavailable", !!why);
                tile.querySelector("[data-why]").textContent = why;
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

        // -- options, from the type's options_schema --------------------------
        function columnsFor(done) {
            var m = metrics[metricSel.value];
            if (!m) { done([]); return; }
            if (schemaCache[m.dataset]) { done(schemaCache[m.dataset]); return; }
            var url = form.getAttribute("data-schema-url").replace("DATASET", encodeURIComponent(m.dataset));
            fetch(url, { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (schema) {
                var cols = (schema.columns || []).filter(function (c) {
                    var isDate = c.type === "date" || c.type === "datetime";
                    return c.role === "dimension" && !c.computed && !isDate;
                }).map(function (c) { return [c.name, c.label]; });
                schemaCache[m.dataset] = cols;
                done(cols);
            }).catch(function () { done([]); });
        }

        function renderOptions() {
            var t = currentType();
            optionsBox.textContent = "";
            if (!t) return;
            // Drop options another type left behind.
            var names = (t.options || []).map(function (s) { return s.name; });
            if (t.stylable) names.push("style", "thresholds");   // the shared styling (Style it)
            if (t.drillable) names.push("drilldown");            // Drill-down
            Object.keys(options).forEach(function (k) { if (names.indexOf(k) < 0) delete options[k]; });
            noOptions.hidden = !!(t.options || []).length || !!t.needs_metric;
            (t.options || []).forEach(function (spec) {
                var id = "cb-opt-" + spec.name;
                var wrap = el("div", { class: "mb-field" });
                var label = el("label", { for: id }, spec.label);
                var input;
                var value = options[spec.name] != null ? options[spec.name] : spec.default;
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
                    input = el("textarea", { id: id, rows: "5", class: "vTextField" });
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
                optionsBox.appendChild(wrap);
                if (spec.type === "boolean" && options[spec.name] == null) { options[spec.name] = !!value; }
                if ((spec.type === "integer" || spec.type === "number") && options[spec.name] == null && value != null) {
                    options[spec.name] = value;
                }
            });
            writeOptions();
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
        function renderInherit() {
            var m = metrics[metricSel.value];
            var t = currentType();
            inheritNote.textContent = "";
            inheritNote.hidden = !(m && t && t.needs_metric);
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
            var m = metrics[metricSel.value];
            var allowed = (t && t.style_settings) || STYLE.map(function (x) { return x.name; });
            STYLE.forEach(function (spec) {
                if (allowed.indexOf(spec.name) < 0) return;   // e.g. an info card has no number format
                var id = "cb-style-" + spec.name;
                var inherited = INHERITED[spec.name] && m && t && t.needs_metric;
                var overridden = inherited && current[spec.name];
                var wrap = el("div", { class: "mb-field" + (overridden ? " cb-overridden" : "") });
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
        function renderRules() {
            var m = metrics[metricSel.value];
            var t = currentType();
            // An info card has no metric: without its own rules it keeps the app's status colour.
            rulesFallback.textContent = t && !t.needs_metric
                ? "Otherwise it keeps the colour its app gives it. Rules compare the card's number."
                : "Otherwise it uses the metric's: " + describeRules(m && m.thresholds) + ". They stay in step with the metric until you override them.";
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
                var st = el("select", { class: "vTextField", "aria-label": "Rule " + (i + 1) + " colour" });
                STATES.forEach(function (o) { var x = el("option", { value: o }, o); if (o === rule.state) x.selected = true; st.appendChild(x); });
                var rm = el("button", { type: "button", class: "plf-tool", "aria-label": "Remove rule " + (i + 1) }, "✕");
                var sync = function () {
                    rule.op = op.value;
                    rule.state = st.value;
                    hi.hidden = op.value !== "between";
                    var a = lo.value === "" ? 0 : Number(lo.value), b = hi.value === "" ? a : Number(hi.value);
                    rule.value = op.value === "between" ? [a, b] : a;
                    writeOptions();
                    schedulePreview();
                };
                [op, lo, hi, st].forEach(function (x) { x.addEventListener("change", sync); x.addEventListener("input", sync); });
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
                var m = metrics[metricSel.value];
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
            var step = 3;
            if (on) step += 1;
            drillStep.textContent = String(step);
            if (drill) step += 1;
            nameStep.textContent = String(step);
            if (on) { renderStyle(); renderRules(); }
            if (drill) renderDrill();
        }

        // -- Drill-down: the columns the rows modal (and its CSV) shows --------
        var drillCard = document.getElementById("cb-drill-card");
        var drillStep = document.getElementById("cb-drill-step");
        var drillOwn = document.getElementById("cb-drill-own");
        var drillBox = document.getElementById("cb-drill");
        var drillCols = document.getElementById("cb-drill-cols");
        var drillAddField = document.getElementById("cb-drill-add-field");
        var drillSort = document.getElementById("cb-drill-sort");
        var drillDir = document.getElementById("cb-drill-dir");
        var drillLimit = document.getElementById("cb-drill-limit");
        var FORMATS = (data.drilldown && data.drilldown.formats) || [["", "As stored"]];
        var fullSchema = {};

        function allColumns(done) {
            var m = metrics[metricSel.value];
            if (!m) { done([]); return; }
            if (fullSchema[m.dataset]) { done(fullSchema[m.dataset]); return; }
            var url = form.getAttribute("data-schema-url").replace("DATASET", encodeURIComponent(m.dataset));
            fetch(url, { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (schema) {
                fullSchema[m.dataset] = (schema.columns || []).filter(function (c) { return !c.computed; });
                done(fullSchema[m.dataset]);
            }).catch(function () { done([]); });
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
        // -- sorting: these rows ARE the order the columns appear in, so a sort
        // rewrites it (until Save; Undo restores it).
        var drillByName = {}, drillBefore = null, drillSortKey = "", drillSortDir = "";
        var drillSortButtons = Array.prototype.slice.call(document.querySelectorAll("[data-drill-sort]"));
        var DRILL_WORDS = { column: "column", heading: "heading", format: "format" };
        function drillSortValue(col, key) {
            var c = drillByName[col.field] || { label: col.field };
            if (key === "column") return String(c.label).toLowerCase();
            if (key === "heading") return String(col.label || c.label).toLowerCase();
            var hit = FORMATS.filter(function (f) { return f[0] === (col.format || ""); })[0];
            return col.format && hit ? String(hit[1]).toLowerCase() : null;  // "as stored" goes last
        }
        function paintDrillSort() {
            drillSortButtons.forEach(function (b) {
                var on = b.getAttribute("data-drill-sort") === drillSortKey;
                b.closest("th").setAttribute("aria-sort", on ? (drillSortDir === "asc" ? "ascending" : "descending") : "none");
                b.querySelector(".dm-sort-ind").textContent = on ? (drillSortDir === "asc" ? "▲" : "▼") : "";
            });
            document.getElementById("cb-drill-sorted").hidden = !drillBefore;
            if (drillBefore) {
                document.getElementById("cb-drill-sorted-text").textContent = "Sorted by " + DRILL_WORDS[drillSortKey] + ". This is now the order the columns appear in the drill-down and its CSV; save to keep it.";
            }
        }
        function clearDrillSort() { drillBefore = null; drillSortKey = ""; drillSortDir = ""; paintDrillSort(); }
        drillSortButtons.forEach(function (b) {
            b.addEventListener("click", function () {
                var key = b.getAttribute("data-drill-sort");
                var d = options.drilldown;
                if (!drillBefore) drillBefore = d.columns.slice();
                drillSortDir = drillSortKey === key && drillSortDir === "asc" ? "desc" : "asc";
                drillSortKey = key;
                var sign = drillSortDir === "asc" ? 1 : -1;
                d.columns.sort(function (x, y) {
                    var a = drillSortValue(x, key), c = drillSortValue(y, key);
                    if (a === null || c === null) return a === c ? 0 : (a === null ? 1 : -1);
                    return a < c ? -sign : (a > c ? sign : 0);
                });
                writeDrill(); renderDrill();
                b.focus();
            });
        });
        document.getElementById("cb-drill-undo").addEventListener("click", function () {
            options.drilldown.columns = drillBefore;
            clearDrillSort();
            writeDrill(); renderDrill();
            if (drillSortButtons[0]) drillSortButtons[0].focus();
        });
        function renderDrill() {
            var own = !!options.drilldown;
            drillOwn.checked = own;
            drillBox.hidden = !own;
            if (!own) return;
            allColumns(function (cols) {
                var byName = {};
                cols.forEach(function (c) { byName[c.name] = c; });
                var d = options.drilldown;
                d.columns = d.columns || [];
                drillByName = byName;
                drillCols.textContent = "";
                document.getElementById("cb-drill-wrap").hidden = !d.columns.length;
                paintDrillSort();
                d.columns.forEach(function (col, n) {
                    var c = byName[col.field] || { name: col.field, label: col.field };
                    var row = el("tr", { class: "plf-item" });
                    var cell = function (node, cls) {
                        var td = el("td", cls ? { class: cls } : {});
                        td.appendChild(node);
                        row.appendChild(td);
                    };
                    cell(el("span", { class: "plf-item-n" }, String(n + 1)));
                    cell(el("span", { class: "plf-item-name", title: c.name }, c.label));
                    var lab = el("input", { class: "vTextField", type: "text", maxlength: "60", placeholder: c.label, "aria-label": "Heading for " + c.label });
                    lab.value = col.label || "";
                    lab.addEventListener("input", function () { if (lab.value) col.label = lab.value; else delete col.label; writeDrill(); });
                    var fmt = el("select", { class: "vTextField", "aria-label": "Format for " + c.label });
                    FORMATS.forEach(function (f) { var o = el("option", { value: f[0] }, f[1]); if ((col.format || "") === f[0]) o.selected = true; fmt.appendChild(o); });
                    fmt.addEventListener("change", function () { if (fmt.value) col.format = fmt.value; else delete col.format; writeDrill(); });
                    var tools = el("span", { class: "plf-item-tools" });
                    [["up", "Move up", "↑"], ["down", "Move down", "↓"], ["remove", "Remove", "✕"]].forEach(function (b) {
                        var btn = el("button", { type: "button", class: "plf-tool", "aria-label": b[1] + ": " + c.label }, b[2]);
                        if ((b[0] === "up" && n === 0) || (b[0] === "down" && n === d.columns.length - 1)) btn.disabled = true;
                        btn.addEventListener("click", function () {
                            clearDrillSort();
                            if (b[0] === "remove") d.columns.splice(n, 1);
                            else { var to = b[0] === "up" ? n - 1 : n + 1; d.columns.splice(to, 0, d.columns.splice(n, 1)[0]); }
                            writeDrill(); renderDrill();
                        });
                        tools.appendChild(btn);
                    });
                    cell(lab);
                    cell(fmt);
                    cell(tools, "plf-tools-cell");
                    drillCols.appendChild(row);
                });
                var used = d.columns.map(function (x) { return x.field; });
                drillAddField.textContent = "";
                drillAddField.appendChild(el("option", { value: "" }, "Choose a column…"));
                cols.forEach(function (c) { if (used.indexOf(c.name) < 0) drillAddField.appendChild(el("option", { value: c.name }, c.label)); });
                drillSort.textContent = "";
                drillSort.appendChild(el("option", { value: "" }, "The data's own order"));
                cols.forEach(function (c) { drillSort.appendChild(el("option", { value: c.name }, c.label)); });
                var sort = d.sort || "";
                drillSort.value = sort.replace(/^-/, "");
                drillDir.value = sort.charAt(0) === "-" || !sort ? "-" : "";
                drillDir.disabled = !drillSort.value;
                drillLimit.value = d.limit || "";
            });
        }
        drillOwn.addEventListener("change", function () {
            clearDrillSort();
            if (drillOwn.checked) options.drilldown = { columns: [] };
            else delete options.drilldown;
            writeDrill(); renderDrill();
        });
        document.getElementById("cb-drill-add").addEventListener("click", function () {
            if (!drillAddField.value) { drillAddField.focus(); return; }
            clearDrillSort();
            options.drilldown.columns.push({ field: drillAddField.value });
            writeDrill(); renderDrill();
        });
        function syncSort() {
            drillDir.disabled = !drillSort.value;
            options.drilldown.sort = drillSort.value ? drillDir.value + drillSort.value : "";
            writeDrill();
        }
        drillSort.addEventListener("change", syncSort);
        drillDir.addEventListener("change", syncSort);
        drillLimit.addEventListener("input", function () {
            var v = parseInt(drillLimit.value, 10);
            options.drilldown.limit = v >= 1 && v <= 500 ? v : 0;
            writeDrill();
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
            if (t.needs_metric && !metricSel.value) {
                preview.replaceChildren(el("p", { class: "mb-help" }, "Choose a metric to see the card."));
                problemsEl.textContent = "";
                return;
            }
            // A required choice not made yet is a next step, not a problem: say what to pick.
            var missing = (t.options || []).filter(function (spec) {
                return spec.required && (options[spec.name] === undefined || options[spec.name] === "" || options[spec.name] === null);
            })[0];
            if (missing) {
                preview.replaceChildren(el("p", { class: "mb-help" }, "Choose a " + missing.label.toLowerCase() + " to see the card."));
                problemsEl.textContent = "";
                return;
            }
            var mine = ++seq;
            var body = { type: t.type, options: options, name: nameInput.value, period: periodSel.value, visibility: shared() ? "shared" : "personal" };
            if (t.needs_metric) body.metric = metricSel.value;
            fetch(form.getAttribute("data-preview-url"), {
                method: "POST",
                credentials: "same-origin",
                headers: { "Content-Type": "application/json" },
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
                } else if ((out.problems || []).length) {
                    preview.replaceChildren(el("p", { class: "mb-help" }, "Fix the problems below to see the card."));
                }
            }).catch(function () {
                if (mine === seq) preview.replaceChildren(el("p", { class: "mb-help" }, "The preview couldn't be loaded."));
            });
        }

        // -- wiring -------------------------------------------------------------
        function onType() {
            var t = currentType();
            metricField.hidden = !(t && t.needs_metric);
            renderOptions();
            syncStyleCard();
            paintPalette();
            schedulePreview();
        }
        form.addEventListener("change", function (ev) {
            var n = ev.target.name;
            if (n === "type") onType();
            else if (n === "metric") { renderOptions(); syncStyleCard(); paintPalette(); schedulePreview(); }
            else if (n === "visibility") { filterMetrics(); schedulePreview(); }
        });
        nameInput.addEventListener("input", schedulePreview);
        periodSel.addEventListener("change", schedulePreview);

        filterMetrics();
        onType();
    });
})();
