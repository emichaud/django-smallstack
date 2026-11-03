/* Metric builder — a visual editor over the metric form's JSON fields.
 *
 * The form's real inputs stay the source of truth: the filter tree and the
 * thresholds are hidden JSON fields (what REST/MCP/agents write), and measure /
 * period_field are text inputs. This file renders friendlier controls that
 * write into them, plus a live preview through dashboards/api/preview/ — the
 * same evaluate() the saved metric will use. The JSON itself isn't shown:
 * people use the builder; agents write the JSON over REST/MCP.
 */
(function () {
    "use strict";

    var form, schema = null, fields = {}, tree, thresholds = [];

    function $(id) { return document.getElementById(id); }
    function el(tag, attrs, text) {
        var n = document.createElement(tag);
        Object.keys(attrs || {}).forEach(function (k) {
            if (k === "class") n.className = attrs[k];
            else n.setAttribute(k, attrs[k]);
        });
        if (text != null) n.textContent = text;
        return n;
    }
    function opt(sel, value, label, selected) {
        var o = el("option", { value: value }, label);
        if (selected) o.selected = true;
        sel.appendChild(o);
        return o;
    }
    // NB: never read data-* via form.dataset here — the form has a control
    // named "dataset", and form.<name> returns the control.
    function input(name) { return form.querySelector('[name="' + name + '"]'); }
    // A field's current value — radios (agg, format, visibility) read the checked one.
    function val(name) {
        var checked = form.querySelector('[name="' + name + '"]:checked');
        if (checked) return checked.value;
        var el = input(name);
        return el && el.type !== "radio" ? el.value : "";
    }

    var OP_LABELS = {
        "=": "is", "!=": "is not", ">": ">", ">=": "≥", "<": "<", "<=": "≤",
        between: "between", "in": "is any of", contains: "contains", isnull: "is empty?", period: "in period",
    };
    var STATES = ["danger", "warning", "success", "muted"];

    // -- the tree model: {kind:"group", joiner, children} | {kind:"leaf", field, op, value, value2}
    function fromJSON(node) {
        if (!node || (typeof node === "object" && !Object.keys(node).length)) return group("and", []);
        if (node.and || node.or) {
            var j = node.and ? "and" : "or";
            return group(j, (node[j] || []).map(fromJSON));
        }
        if (node.not) throw new Error("not");
        return { kind: "leaf", field: node.field || "", op: node.op || "=", value: node.value, value2: node.value2 };
    }
    function group(joiner, children) { return { kind: "group", joiner: joiner, children: children }; }
    function toJSON(node, top) {
        if (node.kind === "leaf") {
            if (!node.field) return null;  // a condition still being picked
            var out = { field: node.field, op: node.op };
            if (node.op !== "isnull" || node.value === false) out.value = node.value;
            if (node.op === "isnull") out.value = node.value !== false;
            if (node.op === "between") out.value2 = node.value2;
            return out;
        }
        var kids = node.children.map(function (c) { return toJSON(c, false); }).filter(Boolean);
        if (!kids.length) return top ? {} : null;
        if (kids.length === 1 && top) return kids[0];
        var o = {};
        o[node.joiner] = kids;
        return o;
    }

    function writeTree() {
        var ta = input("filter_tree");
        if (!ta) return;
        var json = toJSON(tree, true);
        ta.value = JSON.stringify(json, null, 2);
        schedulePreview();
    }

    function readTree() {
        var ta = input("filter_tree");
        var raw = (ta && ta.value.trim()) || "{}";
        try {
            tree = fromJSON(JSON.parse(raw));
            // A single stored condition is a leaf at the root; the builder
            // always edits a group, so wrap it (toJSON unwraps it again).
            if (tree.kind !== "group") tree = group("and", [tree]);
            return true;
        } catch (e) {
            tree = null;
            return false;
        }
    }

    // -- value coercion for the JSON (numbers stay numbers) ------------------
    function coerce(f, raw) {
        if (raw === "" || raw == null) return "";
        var t = f && f.column_type;
        if (t === "integer" || t === "float" || t === "decimal") {
            var n = Number(raw);
            return isNaN(n) ? raw : n;
        }
        if (t === "boolean") return raw === "true";
        if (t === "fk" && /^\d+$/.test(String(raw))) return parseInt(raw, 10);
        return raw;
    }

    function valueControl(f, op, value, onChange) {
        var t = f ? f.column_type : "string";
        if (op === "isnull") {
            var s = el("select", { class: "vTextField", "aria-label": "Empty or not" });
            opt(s, "true", "is empty", value !== false);
            opt(s, "false", "is not empty", value === false);
            s.addEventListener("change", function () { onChange(s.value === "true"); });
            return s;
        }
        if (op === "period") {
            var p = el("select", { class: "vTextField", "aria-label": "Period" });
            (f && f.periods || []).forEach(function (pp) { opt(p, pp.key, pp.label, pp.key === value); });
            if (!value && p.options.length) onChange(p.options[0].value, true);
            p.addEventListener("change", function () { onChange(p.value); });
            return p;
        }
        var choices = (f && f.choices || []).filter(function (c) { return c[0] !== ""; });
        if (t === "boolean" || (choices.length && (op === "=" || op === "!=") && !(f && f.is_date))) {
            var c = el("select", { class: "vTextField", "aria-label": "Value" });
            if (t === "boolean" && !choices.length) choices = [["true", "Yes"], ["false", "No"]];
            opt(c, "", "— pick —", value === "" || value == null);
            choices.forEach(function (ch) { opt(c, ch[0], ch[1], String(value) === String(ch[0])); });
            c.addEventListener("change", function () { onChange(coerce(f, c.value)); });
            return c;
        }
        if (op === "in") {
            var i = el("input", { type: "text", class: "vTextField", placeholder: "a, b, c", "aria-label": "Values, comma separated" });
            i.value = Array.isArray(value) ? value.join(", ") : (value || "");
            i.addEventListener("input", function () {
                onChange(i.value.split(",").map(function (v) { return coerce(f, v.trim()); }).filter(function (v) { return v !== ""; }));
            });
            return i;
        }
        var type = (t === "date") ? "date" : (t === "datetime") ? "datetime-local"
            : (t === "integer" || t === "float" || t === "decimal") ? "number" : "text";
        var x = el("input", { type: type, class: "vTextField", "aria-label": "Value" });
        if (type === "number") x.step = "any";
        x.value = value == null ? "" : value;
        x.addEventListener("input", function () { onChange(coerce(f, x.value)); });
        return x;
    }

    function renderLeaf(node, parent) {
        var row = el("div", { class: "mb-leaf" });
        var fsel = el("select", { class: "vTextField", "aria-label": "Field" });
        opt(fsel, "", "— field —", !node.field);
        Object.keys(fields).forEach(function (name) { opt(fsel, name, fields[name].label || name, name === node.field); });
        if (node.field && !fields[node.field]) opt(fsel, node.field, node.field + " (unknown)", true);
        var f = fields[node.field];
        var osel = el("select", { class: "vTextField", "aria-label": "Operator" });
        (f ? f.ops : ["="]).forEach(function (o) { opt(osel, o, OP_LABELS[o] || o, o === node.op); });
        if (f && f.ops.indexOf(node.op) < 0) { node.op = f.ops[0]; }
        var values = el("div", { class: "mb-values" });
        values.appendChild(valueControl(f, node.op, node.value, function (v, silent) { node.value = v; if (!silent) writeTree(); }));
        if (node.op === "between") {
            values.appendChild(valueControl(f, "between", node.value2, function (v) { node.value2 = v; writeTree(); }));
        }
        var rm = el("button", { type: "button", class: "mb-icon-btn mb-danger", "aria-label": "Remove condition" }, "✕");
        rm.addEventListener("click", function () {
            parent.children.splice(parent.children.indexOf(node), 1);
            render(); writeTree();
        });
        fsel.addEventListener("change", function () {
            node.field = fsel.value; node.value = ""; node.value2 = undefined;
            var nf = fields[node.field];
            node.op = nf ? nf.ops[0] : "=";
            render(); writeTree();
        });
        osel.addEventListener("change", function () {
            node.op = osel.value;
            if (node.op === "in") node.value = node.value === "" || node.value == null ? [] : [node.value];
            else if (Array.isArray(node.value)) node.value = node.value[0] || "";
            if (node.op === "isnull") node.value = true;
            render(); writeTree();
        });
        row.appendChild(fsel); row.appendChild(osel); row.appendChild(values); row.appendChild(rm);
        return row;
    }

    function renderGroup(node, parent) {
        var box = el("div", { class: "mb-tree-group" });
        var head = el("div", { class: "mb-tree-head" });
        head.appendChild(el("span", {}, "Match"));
        var joiner = el("span", { class: "mb-joiner", role: "group", "aria-label": "Match all or any" });
        [["and", "ALL"], ["or", "ANY"]].forEach(function (j) {
            var b = el("button", { type: "button", "aria-pressed": String(node.joiner === j[0]) }, j[1]);
            b.addEventListener("click", function () { node.joiner = j[0]; render(); writeTree(); });
            joiner.appendChild(b);
        });
        head.appendChild(joiner);
        head.appendChild(el("span", {}, "of these"));
        head.appendChild(el("span", { class: "dash-spacer" }));
        var addLeaf = el("button", { type: "button", class: "mb-icon-btn" }, "+ condition");
        addLeaf.addEventListener("click", function () {
            node.children.push({ kind: "leaf", field: "", op: "=", value: "" });
            render();
        });
        var addGroup = el("button", { type: "button", class: "mb-icon-btn" }, "+ group");
        addGroup.addEventListener("click", function () {
            node.children.push(group(node.joiner === "and" ? "or" : "and", [{ kind: "leaf", field: "", op: "=", value: "" }]));
            render();
        });
        head.appendChild(addLeaf); head.appendChild(addGroup);
        if (parent) {
            var rm = el("button", { type: "button", class: "mb-icon-btn mb-danger", "aria-label": "Remove group" }, "✕");
            rm.addEventListener("click", function () {
                parent.children.splice(parent.children.indexOf(node), 1);
                render(); writeTree();
            });
            head.appendChild(rm);
        }
        box.appendChild(head);
        if (!node.children.length && !parent) {
            box.appendChild(el("p", { class: "mb-help" }, "No conditions: every row counts."));
        }
        node.children.forEach(function (child) {
            box.appendChild(child.kind === "group" ? renderGroup(child, node) : renderLeaf(child, node));
        });
        return box;
    }

    function render() {
        var mount = $("mb-tree");
        mount.textContent = "";
        if (!schema) { mount.appendChild(el("p", { class: "mb-help" }, "Pick a dataset to start filtering.")); return; }
        if (!tree) {
            // Written through the API or by an agent (NOT has no builder control).
            // It still works and is saved unchanged; Start over replaces it.
            mount.appendChild(el("p", { class: "mb-help" },
                "This filter was written through the API and uses conditions the builder can't show, such as NOT. " +
                "It still works, and saving keeps it as it is."));
            var reset = el("button", { type: "button", class: "mb-icon-btn" }, "Start over with an empty filter");
            reset.addEventListener("click", function () {
                tree = group("and", []);
                writeTree();
                render();
            });
            mount.appendChild(reset);
            return;
        }
        mount.appendChild(renderGroup(tree, null));
    }

    // -- measure / period field as selects over the hidden inputs --------------
    function selectFor(name, options, emptyLabel) {
        var inp = input(name);
        if (!inp) return;
        var existing = document.getElementById("mb-select-" + name);
        if (existing) existing.remove();
        var sel = el("select", { class: "vTextField", id: "mb-select-" + name, "aria-label": inp.labels && inp.labels[0] ? inp.labels[0].textContent : name });
        opt(sel, "", emptyLabel, !inp.value);
        options.forEach(function (o) { opt(sel, o[0], o[1], o[0] === inp.value); });
        if (inp.value && !options.some(function (o) { return o[0] === inp.value; })) opt(sel, inp.value, inp.value + " (unknown)", true);
        sel.addEventListener("change", function () { inp.value = sel.value; schedulePreview(); });
        inp.type = "hidden";
        inp.parentNode.insertBefore(sel, inp);
        if (inp.labels && inp.labels[0]) inp.labels[0].setAttribute("for", sel.id);
    }

    function applySchema() {
        fields = {};
        (schema.filters || []).forEach(function (f) {
            fields[f.name] = f;
        });
        var cols = schema.columns || [];
        var measures = cols.filter(function (c) { return c.role === "measure"; }).map(function (c) { return [c.name, c.label + (c.computed ? " (ratio)" : "")]; });
        var others = cols.filter(function (c) { return c.role !== "measure"; }).map(function (c) { return [c.name, c.label]; });
        selectFor("measure", measures.concat(others), "— none (count rows) —");
        var dates = (schema.filters || []).filter(function (f) { return f.column_type === "date" || f.column_type === "datetime"; })
            .map(function (f) { return [f.name, f.label || f.name]; });
        selectFor("period_field", dates, "— not period-aware —");
        if (!readTree()) tree = null;
        render();
    }

    function loadSchema() {
        var key = input("dataset").value;
        schema = null;
        if (!key) { render(); renderDatasetInfo(); return; }
        var url = form.getAttribute("data-schema-url").replace("DATASET", encodeURIComponent(key));
        fetch(url, { credentials: "same-origin" })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (s) { schema = s; if (s) applySchema(); else render(); renderDatasetInfo(); syncMeasure(); schedulePreview(); });
    }

    // -- thresholds -----------------------------------------------------------
    function readThresholds() {
        try { thresholds = JSON.parse(input("thresholds").value || "[]"); } catch (e) { thresholds = []; }
        if (!Array.isArray(thresholds)) thresholds = [];
    }
    function writeThresholds() {
        input("thresholds").value = JSON.stringify(thresholds, null, 2);
        schedulePreview();
    }
    function renderThresholds() {
        var mount = $("mb-thresholds");
        mount.textContent = "";
        thresholds.forEach(function (rule, i) {
            var row = el("div", { class: "mb-threshold mb-threshold--" + (rule.state || "warning") });
            var op = el("select", { class: "vTextField", "aria-label": "Comparison" });
            [">", ">=", "<", "<=", "=", "!=", "between"].forEach(function (o) { opt(op, o, OP_LABELS[o] || o, o === rule.op); });
            var val = el("input", { type: "text", class: "vTextField", "aria-label": "Value", placeholder: rule.op === "between" ? "low, high" : "value" });
            val.value = Array.isArray(rule.value) ? rule.value.join(", ") : (rule.value == null ? "" : rule.value);
            var st = el("select", { class: "vTextField", "aria-label": "State" });
            STATES.forEach(function (s) { opt(st, s, s, s === rule.state); });
            var rm = el("button", { type: "button", class: "mb-icon-btn mb-danger", "aria-label": "Remove rule" }, "✕");
            function sync() {
                rule.op = op.value; rule.state = st.value;
                row.className = "mb-threshold mb-threshold--" + rule.state;
                if (rule.op === "between") rule.value = val.value.split(",").map(function (v) { return Number(v.trim()); });
                else rule.value = Number(val.value);
                writeThresholds();
            }
            op.addEventListener("change", sync); val.addEventListener("input", sync); st.addEventListener("change", sync);
            rm.addEventListener("click", function () { thresholds.splice(i, 1); renderThresholds(); writeThresholds(); });
            row.appendChild(op); row.appendChild(val); row.appendChild(st); row.appendChild(rm);
            mount.appendChild(row);
        });
    }

    // -- roll-up affordances ------------------------------------------------------
    // A dataset metric, a hand-entered one and a rate ask for different things.
    function syncSource() {
        var source = val("source") || "dataset";
        form.querySelectorAll("[data-for-source]").forEach(function (el) {
            el.hidden = el.getAttribute("data-for-source").split(" ").indexOf(source) < 0;
        });
        if (source !== "rate") {
            var agg = form.querySelector('[name="agg"]:checked');
            var offered = agg && !agg.closest("[data-for-source]").hidden;
            if (!offered) {
                var first = form.querySelector('[name="agg"][value="' + (source === "manual" ? "latest" : "count") + '"]');
                if (first) first.checked = true;
            }
        }
        // Facts about rows and a dataset mean nothing for the other two.
        ["mb-rows", "mf-fact-ds"].forEach(function (id) {
            var fact = $(id);
            if (fact) fact.closest("div").classList.toggle("mf-fact--off", source !== "dataset");
        });
        // Renumber, so a hidden step doesn't leave a gap.
        var step = 0;
        form.querySelectorAll(".mf-step").forEach(function (n) {
            if (!n.closest("[data-for-source][hidden]")) n.textContent = String(++step);
        });
        syncMeasure();
    }
    function syncMeasure() {
        var needs = val("agg") !== "count" && (val("source") || "dataset") === "dataset";
        var box = $("mb-field-measure");
        if (box) box.hidden = !needs;
        if (!needs) {
            input("measure").value = "";
            var sel = $("mb-select-measure");
            if (sel) sel.value = "";
        }
        var label = box && box.querySelector("label");
        if (label) label.textContent = val("agg") === "distinct" ? "Distinct values of" : "Of column";
    }
    function syncUnit() {
        var f = val("format");
        var box = input("unit").closest(".mb-field");
        box.hidden = f === "percent" || f === "duration";
        $("mf-unit-label").textContent = f === "currency" ? "Currency symbol" : "Unit (optional)";
        $("mf-unit-help").textContent = f === "currency" ? "Put before the number. Blank means $." : "Shown small after the number, e.g. ms or tickets.";
    }
    var CAP_LABELS = { measure: "numeric columns", dimension: "groupable", dimension2: "cross-tabs", date: "dates" };
    function renderDatasetInfo() {
        var box = $("mb-ds-info");
        box.textContent = "";
        if (!schema) { box.hidden = true; $("mf-fact-ds").textContent = "—"; return; }
        box.hidden = false;
        if (schema.description) box.appendChild(el("p", {}, schema.description));
        var chips = el("div", { class: "mf-ds-chips" });
        chips.appendChild(el("span", { class: "dash-badge" }, (schema.columns || []).length + " columns"));
        chips.appendChild(el("span", { class: "dash-badge" }, (schema.filters || []).length + " filterable"));
        (schema.capabilities || []).forEach(function (c) {
            chips.appendChild(el("span", { class: "dash-badge dash-badge--shared" }, CAP_LABELS[c] || c));
        });
        box.appendChild(chips);
        $("mf-fact-ds").textContent = schema.label || schema.key;
    }

    // -- "See them": the rows behind the UNSAVED metric, in the global modal ----
    var lastPayload = null;
    function loadRows(order, sortedBy) {
        var body = document.getElementById("stat-modal-body");
        var token = form.querySelector("[name=csrfmiddlewaretoken]");
        return fetch(form.getAttribute("data-preview-rows-url"), {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-CSRFToken": token ? token.value : "" },
            credentials: "same-origin",
            body: JSON.stringify(order ? Object.assign({}, lastPayload, { order: order }) : lastPayload),
        }).then(function (r) { return r.text(); }).then(function (html) {
            if (!body) return;
            body.innerHTML = html;
            if (window.htmx) window.htmx.process(body);
            // Filled here, not by an htmx swap, so the table registers with the resizer itself.
            if (window.SmallStackTableResize) window.SmallStackTableResize.init(body);
            if (sortedBy) {
                var again = body.querySelector('th[data-field="' + CSS.escape(sortedBy) + '"] [data-preview-order]');
                if (again) again.focus();
            }
        });
    }
    function seeRows() {
        if (!lastPayload) return;
        var opt = $("mb-preview-period").selectedOptions[0];
        var heading = opt && opt.value ? opt.getAttribute("data-heading") : "";
        var title = (input("name").value || "Preview") + (heading ? ", " + heading.toLowerCase() : "");
        var body = document.getElementById("stat-modal-body");
        if (window.openStatModal) window.openStatModal(title, $("mb-see-rows"));
        if (body) body.innerHTML = '<p style="padding: 24px; text-align: center; color: var(--body-quiet-color);">Loading…</p>';
        loadRows("");
    }
    // A header in that modal: the metric is unsaved, so post it again, sorted.
    document.addEventListener("click", function (ev) {
        var b = ev.target.closest && ev.target.closest("#stat-modal-body [data-preview-order]");
        if (!b || !lastPayload) return;
        loadRows(b.getAttribute("data-preview-order"), b.closest("th").getAttribute("data-field"));
    });

    // -- the comparison under the preview: this period against the one before --
    var compareSeq = 0;
    var TO_DATE = { today: 1, wtd: 1, mtd: 1, qtd: 1, ytd: 1 };
    function compare(payload, res) {
        var box = $("mb-compare");
        var prevMap = {};
        try { prevMap = JSON.parse($("mb-previous-periods").textContent || "{}"); } catch (e) { prevMap = {}; }
        var prev = prevMap[payload.period];
        var mine = ++compareSeq;
        box.hidden = true;
        if (!prev || !payload.period_field || !res || res.error || res.restricted || typeof res.value !== "number") return;
        var body = Object.assign({}, payload, { period: prev[0] });
        fetch(form.getAttribute("data-preview-url"), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "same-origin",
            body: JSON.stringify(body),
        }).then(function (r) { return r.json(); }).then(function (data) {
            if (mine !== compareSeq || !data.result || typeof data.result.value !== "number") return;
            var a = res.value, b = data.result.value;
            var against = (TO_DATE[payload.period] ? "all of " : "") + prev[1];
            var text;
            if (a === b) text = "= No change vs " + against;
            else if (b === 0) text = "▲ Up from 0 in " + against;
            else {
                var pct = (a - b) / Math.abs(b) * 100;
                var shown = Math.abs(pct) >= 1 ? Math.abs(pct).toFixed(0) : Math.abs(pct).toFixed(1);
                text = (pct > 0 ? "▲ " : "▼ ") + shown + "% vs " + against + " (" + data.result.display + ")";
            }
            box.textContent = text;
            box.hidden = false;
        }).catch(function () {});
    }

    // -- preview ----------------------------------------------------------------
    var previewTimer = null;
    function schedulePreview() {
        clearTimeout(previewTimer);
        previewTimer = setTimeout(preview, 350);
    }
    function preview() {
        var dataset = input("dataset").value;
        var pf = input("period_field").value;
        var pfSel = $("mb-select-period_field");
        var pfLabel = pfSel && pfSel.selectedOptions[0] ? pfSel.selectedOptions[0].textContent : pf;
        $("mf-fact-period").textContent = (val("source") === "rate") ? "follows its two metrics" : pf ? "narrows " + pfLabel.toLowerCase() : "not period-aware";
        var card = $("mb-card"), value = $("mb-card-value"), label = $("mb-card-label");
        var problems = $("mb-problems");
        label.textContent = input("name").value || "Preview";
        var source = val("source") || "dataset";
        if (source === "dataset" && !dataset) { value.textContent = "—"; return; }
        if (source === "rate" && !(input("numerator").value && input("denominator").value)) { value.textContent = "—"; return; }
        if (source === "manual") {
            value.textContent = "—";
            $("mf-fact-period").textContent = "narrows the value's date";
            return;
        }
        var payload = {
            source: source,
            numerator: input("numerator").value,
            denominator: input("denominator").value,
            visibility: val("visibility"),
            dataset: dataset,
            agg: val("agg"),
            measure: input("measure").value,
            period_field: input("period_field").value,
            period: $("mb-preview-period").value,
            format: val("format"),
            unit: input("unit").value,
        };
        try { payload.filter_tree = JSON.parse(input("filter_tree").value || "{}"); } catch (e) { payload.filter_tree = "invalid"; }
        try { payload.thresholds = JSON.parse(input("thresholds").value || "[]"); } catch (e) { payload.thresholds = "invalid"; }
        fetch(form.getAttribute("data-preview-url"), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "same-origin",
            body: JSON.stringify(payload),
        }).then(function (r) { return r.json(); }).then(function (data) {
            problems.textContent = "";
            var list = (data.problems || []).slice();
            var res = data.result;
            card.className = "stat-card";
            if (res && res.state) card.classList.add("stat-card--" + res.state);
            if (res && res.error) list.unshift(res.error);
            value.textContent = res && !res.error ? res.display : "—";
            if (res && res.unit && !res.error) {
                var u = el("span", { class: "stat-card-unit" }, res.unit);
                value.appendChild(u);
            }
            if (res && res.period_label) {
                var opt = $("mb-preview-period").selectedOptions[0];
                label.textContent += " · " + ((opt && opt.getAttribute("data-heading")) || res.period_label);
            }
            $("mb-rows").textContent = data.row_count != null ? data.row_count.toLocaleString() : "—";
            lastPayload = payload;
            $("mb-see-rows").hidden = !(data.ok && data.row_count);
            var reading = res && res.summary ? res.summary.replace(/ AND /g, " and ").replace(/ OR /g, " or ") : "All rows";
            $("mb-summary").textContent = reading;
            $("mb-tree-summary").textContent = res && res.summary ? "Reads as: " + reading : "";
            list.forEach(function (p) { problems.appendChild(el("li", {}, p)); });
            problems.hidden = !list.length;
            compare(payload, res);
        }).catch(function () { /* preview is best-effort */ });
    }

    document.addEventListener("DOMContentLoaded", function () {
        form = $("mb-form");
        if (!form) return;
        readTree();
        readThresholds();
        renderThresholds();
        input("dataset").addEventListener("change", function () {
            input("measure").value = ""; input("period_field").value = "";
            input("filter_tree").value = "{}";
            loadSchema();
        });
        input("unit").addEventListener("input", schedulePreview);
        // Radios (agg, format, visibility) and the generated selects all bubble here.
        form.addEventListener("change", function (ev) {
            var n = ev.target.name;
            if (n === "agg") syncMeasure();
            if (n === "format") syncUnit();
            if (n === "source") syncSource();
            if (n === "agg" || n === "format" || n === "visibility" || n === "source" || n === "numerator" || n === "denominator") schedulePreview();
        });
        // The key is made from the name on save (MetricForm); this previews it.
        var name = input("name"), keyPreview = $("mf-key-preview");
        name.addEventListener("input", function () {
            if (keyPreview) {
                keyPreview.textContent = name.value.toLowerCase().normalize("NFKD").replace(/[\u0300-\u036f]/g, "")
                    .replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 56) || "—";
            }
            schedulePreview();
        });
        syncSource();
        syncUnit();
        $("mb-preview-period").addEventListener("change", schedulePreview);
        $("mb-see-rows").addEventListener("click", seeRows);
        $("mb-threshold-add").addEventListener("click", function () {
            thresholds.push({ op: ">=", value: 0, state: "warning" });
            renderThresholds(); writeThresholds();
        });
        loadSchema();
    });
})();
