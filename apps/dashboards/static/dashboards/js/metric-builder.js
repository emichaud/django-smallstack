/* Metric builder — a visual editor over the metric form's JSON fields.
 *
 * The form's real inputs stay the source of truth: the filter tree and the
 * thresholds are hidden JSON fields (what REST/MCP/agents write), and measure /
 * period_field are text inputs. This file renders friendlier controls that
 * write into them, plus a live preview through dashboards/api/preview/ — the
 * same evaluate() the saved metric will use. The JSON itself isn't shown:
 * people use the builder; agents write the JSON over REST/MCP.
 *
 * The filter tree itself is drawn by the shared editor in
 * datasets/js/filter-tree.js (SmallStackFilterTree), which the dataset browser
 * uses too; this file owns what is metric-only: the dataset picker, measure
 * and period field, thresholds, and the preview.
 */
(function () {
    "use strict";

    var form, schema = null, treeEditor = null, thresholds = [];

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
    // The operator words the tree editor uses, so a threshold reads the same way.
    function opLabel(o) { return window.SmallStackFilterTree.OP_LABELS[o] || o; }

    var STATES = ["danger", "warning", "success", "muted"];

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
        var cols = schema.columns || [];
        var measures = cols.filter(function (c) { return c.role === "measure"; }).map(function (c) { return [c.name, c.label + (c.computed ? " (ratio)" : "")]; });
        var others = cols.filter(function (c) { return c.role !== "measure"; }).map(function (c) { return [c.name, c.label]; });
        selectFor("measure", measures.concat(others), "— none (count rows) —");
        var dates = (schema.filters || []).filter(function (f) { return f.column_type === "date" || f.column_type === "datetime"; })
            .map(function (f) { return [f.name, f.label || f.name]; });
        selectFor("period_field", dates, "None: this number doesn't change over time");
        treeEditor.setSchema(schema);
    }

    function loadSchema() {
        var key = input("dataset").value;
        schema = null;
        if (!key) { treeEditor.setSchema(null); renderDatasetInfo(); return; }
        var url = form.getAttribute("data-schema-url").replace("DATASET", encodeURIComponent(key));
        fetch(url, { credentials: "same-origin" })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (s) {
                schema = s;
                if (s) applySchema(); else treeEditor.setSchema(null);
                renderDatasetInfo(); syncMeasure(); schedulePreview();
            });
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
            [">", ">=", "<", "<=", "=", "!=", "between"].forEach(function (o) { opt(op, o, opLabel(o), o === rule.op); });
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
        // "All rows" isn't true of a value typed in, and a rate says itself once it has two metrics.
        $("mb-summary").closest(".mf-reads-box").hidden = source !== "dataset";
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
        $("mf-fact-period").textContent = (val("source") === "rate") ? "follows its two metrics" : pf ? "counted by " + pfLabel.toLowerCase() : "doesn't change over time";
        var card = $("mb-card"), value = $("mb-card-value"), label = $("mb-card-label");
        var problems = $("mb-problems");
        label.textContent = input("name").value || "Preview";
        var source = val("source") || "dataset";
        if (source === "dataset" && !dataset) { value.textContent = "—"; return; }
        if (source === "rate" && !(input("numerator").value && input("denominator").value)) { value.textContent = "—"; return; }
        if (source === "manual") {
            value.textContent = "—";
            $("mf-fact-period").textContent = "by each value's date";
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
        treeEditor = window.SmallStackFilterTree.create({
            mount: $("mb-tree"),
            input: input("filter_tree"),
            onChange: schedulePreview,
            placeholder: "Pick a dataset to start filtering.",
        });
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
                keyPreview.textContent = name.value.toLowerCase().normalize("NFKD").replace(/[̀-ͯ]/g, "")
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
