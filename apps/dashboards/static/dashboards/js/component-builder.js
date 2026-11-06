/* Component builder — the form for a saved card (ComponentCRUDView).
 *
 * The real inputs are the palette's `type` radios, the `metric` select and a
 * hidden `options` JSON field (what REST/MCP and agents write directly). This
 * file draws each type's options from its options_schema — so a type an app
 * registers (a chart) gets a form with no builder changes — dims the designs
 * the chosen metric's data can't support, and keeps a live preview rendered
 * by dashboards/api/card-preview/, the same render_cell a dashboard uses.
 *
 * Option field types: choice | multichoice (a tick-list of the choices, kept
 * as one comma-separated string) | integer | number | text | boolean | column
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

    function start() {
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
            // The card's own choice, or (a card of one dashboard) that dashboard's, as a hidden field.
            var v = form.querySelector('[name="visibility"]:checked, input[type="hidden"][name="visibility"]');
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
                if (spec.type === "multichoice") {
                    optionsBox.appendChild(multichoice(spec, id));
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
            drillNote.textContent = (d.columns.length ? "" : "Nothing is ticked, so it shows the data's first six columns. ")
                + (d.sort ? sortWords(d.sort) : "In the data's own order.")
                + " Opens with up to " + (d.limit || DEFAULT_ROWS) + " rows.";
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
            var m = metrics[metricSel.value], d = options.drilldown;
            if (!m || !d) return;
            var spec = { columns: d.columns };
            if (d.sort) spec.sort = d.sort;
            var url = form.getAttribute("data-rows-url").replace("KEY", encodeURIComponent(m.key))
                + "?limit=" + SAMPLE_ROWS + "&drill=" + encodeURIComponent(JSON.stringify(spec));
            if (periodSel.value && periodSel.value !== "all") url += "&period=" + encodeURIComponent(periodSel.value);
            var mine = ++rowsSeq;
            fetch(url, { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (out) {
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
                var what = (missing.type === "multichoice" ? "" : "a ") + missing.label.toLowerCase();
                preview.replaceChildren(el("p", { class: "mb-help" }, "Choose " + what + " to see the card."));
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
    }

    // The builder runs on its own page, and inside a dashboard's Edit card
    // dialog, where its form arrives later: dashboard.js calls this then.
    window.SmallStackDashboards = window.SmallStackDashboards || {};
    window.SmallStackDashboards.startComponentBuilder = start;
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
    else start();
})();
