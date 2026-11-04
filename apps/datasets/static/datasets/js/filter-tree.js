/* Filter tree editor — the visual editor for a dataset filter tree.
 *
 * One editor serves every page that filters a dataset (the metric builder, the
 * dataset browser). It draws nested ALL/ANY groups of conditions over a
 * dataset's ``schema()["filters"]`` and writes the JSON tree (filter_tree.py's
 * shape) into a hidden input, which stays the source of truth: a form posts
 * it, REST/MCP write the same JSON. The JSON itself isn't shown.
 *
 *   var editor = SmallStackFilterTree.create({
 *       mount: document.getElementById("my-tree"),   // where the controls draw
 *       input: form.querySelector('[name="filter_tree"]'),  // hidden JSON
 *       onChange: function (tree) { ... },            // after every edit
 *       placeholder: "Pick a dataset to start filtering.",  // shown with no schema
 *   });
 *   editor.setSchema(schema);   // a dataset's schema() — re-reads the input
 *   editor.value();             // the tree as JSON ({} = no filter)
 *   editor.reset();             // an empty filter
 *
 * A tree the editor can't draw (NOT, written over the API) is kept as it is:
 * the editor says so and offers to start over. Theme classes only (ft-*).
 */
(function () {
    "use strict";

    var OP_LABELS = {
        "=": "is", "!=": "is not", ">": ">", ">=": "≥", "<": "<", "<=": "≤",
        between: "between", "in": "is any of", contains: "contains", isnull: "is empty?", period: "in period",
    };

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

    // -- the tree model: {kind:"group", joiner, children} | {kind:"leaf", field, op, value, value2}
    function group(joiner, children) { return { kind: "group", joiner: joiner, children: children }; }
    function leaf() { return { kind: "leaf", field: "", op: "=", value: "" }; }
    function fromJSON(node) {
        if (!node || (typeof node === "object" && !Object.keys(node).length)) return group("and", []);
        if (node.and || node.or) {
            var j = node.and ? "and" : "or";
            return group(j, (node[j] || []).map(fromJSON));
        }
        if (node.not) throw new Error("not");
        return { kind: "leaf", field: node.field || "", op: node.op || "=", value: node.value, value2: node.value2 };
    }
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

    function create(opts) {
        var mount = opts.mount, input = opts.input;
        var onChange = opts.onChange || function () {};
        var placeholder = opts.placeholder || "Pick a dataset to start filtering.";
        var schema = null, fields = {}, tree = null;

        function write() {
            var json = toJSON(tree, true);
            if (input) input.value = JSON.stringify(json, null, 2);
            onChange(json);
        }
        // The input → the model. False when the stored tree uses what the editor can't draw.
        function read() {
            var raw = (input && input.value.trim()) || "{}";
            try {
                tree = fromJSON(JSON.parse(raw));
                // A single stored condition is a leaf at the root; the editor
                // always edits a group, so wrap it (toJSON unwraps it again).
                if (tree.kind !== "group") tree = group("and", [tree]);
                return true;
            } catch (e) {
                tree = null;
                return false;
            }
        }

        function renderLeaf(node, parent) {
            var row = el("div", { class: "ft-leaf" });
            var fsel = el("select", { class: "vTextField", "aria-label": "Field" });
            opt(fsel, "", "— field —", !node.field);
            Object.keys(fields).forEach(function (name) { opt(fsel, name, fields[name].label || name, name === node.field); });
            if (node.field && !fields[node.field]) opt(fsel, node.field, node.field + " (unknown)", true);
            var f = fields[node.field];
            var osel = el("select", { class: "vTextField", "aria-label": "Operator" });
            (f ? f.ops : ["="]).forEach(function (o) { opt(osel, o, OP_LABELS[o] || o, o === node.op); });
            if (f && f.ops.indexOf(node.op) < 0) { node.op = f.ops[0]; }
            var values = el("div", { class: "ft-values" });
            values.appendChild(valueControl(f, node.op, node.value, function (v, silent) { node.value = v; if (!silent) write(); }));
            if (node.op === "between") {
                values.appendChild(valueControl(f, "between", node.value2, function (v) { node.value2 = v; write(); }));
            }
            var rm = el("button", { type: "button", class: "ft-btn ft-danger", "aria-label": "Remove condition" }, "✕");
            rm.addEventListener("click", function () {
                parent.children.splice(parent.children.indexOf(node), 1);
                render(); write();
            });
            fsel.addEventListener("change", function () {
                node.field = fsel.value; node.value = ""; node.value2 = undefined;
                var nf = fields[node.field];
                node.op = nf ? nf.ops[0] : "=";
                render(); write();
            });
            osel.addEventListener("change", function () {
                node.op = osel.value;
                if (node.op === "in") node.value = node.value === "" || node.value == null ? [] : [node.value];
                else if (Array.isArray(node.value)) node.value = node.value[0] || "";
                if (node.op === "isnull") node.value = true;
                render(); write();
            });
            row.appendChild(fsel); row.appendChild(osel); row.appendChild(values); row.appendChild(rm);
            return row;
        }

        function renderGroup(node, parent) {
            var box = el("div", { class: "ft-group" });
            var head = el("div", { class: "ft-head" });
            head.appendChild(el("span", {}, "Match"));
            var joiner = el("span", { class: "ft-joiner", role: "group", "aria-label": "Match all or any" });
            [["and", "ALL"], ["or", "ANY"]].forEach(function (j) {
                var b = el("button", { type: "button", "aria-pressed": String(node.joiner === j[0]) }, j[1]);
                b.addEventListener("click", function () { node.joiner = j[0]; render(); write(); });
                joiner.appendChild(b);
            });
            head.appendChild(joiner);
            head.appendChild(el("span", {}, "of these"));
            head.appendChild(el("span", { class: "ft-spacer" }));
            var addLeaf = el("button", { type: "button", class: "ft-btn" }, "+ condition");
            addLeaf.addEventListener("click", function () {
                node.children.push(leaf());
                render();
            });
            var addGroup = el("button", { type: "button", class: "ft-btn" }, "+ group");
            addGroup.addEventListener("click", function () {
                node.children.push(group(node.joiner === "and" ? "or" : "and", [leaf()]));
                render();
            });
            head.appendChild(addLeaf); head.appendChild(addGroup);
            if (parent) {
                var rm = el("button", { type: "button", class: "ft-btn ft-danger", "aria-label": "Remove group" }, "✕");
                rm.addEventListener("click", function () {
                    parent.children.splice(parent.children.indexOf(node), 1);
                    render(); write();
                });
                head.appendChild(rm);
            }
            box.appendChild(head);
            if (!node.children.length && !parent) {
                box.appendChild(el("p", { class: "ft-help" }, "No conditions: every row counts."));
            }
            node.children.forEach(function (child) {
                box.appendChild(child.kind === "group" ? renderGroup(child, node) : renderLeaf(child, node));
            });
            return box;
        }

        function render() {
            mount.textContent = "";
            if (!schema) { mount.appendChild(el("p", { class: "ft-help" }, placeholder)); return; }
            if (!tree) {
                // Written through the API or by an agent (NOT has no control here).
                // It still works and is saved unchanged; Start over replaces it.
                mount.appendChild(el("p", { class: "ft-help" },
                    "This filter was written through the API and uses conditions the editor can't show, such as NOT. " +
                    "It still works, and saving keeps it as it is."));
                var reset = el("button", { type: "button", class: "ft-btn" }, "Start over with an empty filter");
                reset.addEventListener("click", function () { editor.reset(); });
                mount.appendChild(reset);
                return;
            }
            mount.appendChild(renderGroup(tree, null));
        }

        var editor = {
            // A dataset's schema() (or null for none). Re-reads the input, so a
            // page that swaps the stored tree before calling this shows the new one.
            setSchema: function (s) {
                schema = s || null;
                fields = {};
                ((schema && schema.filters) || []).forEach(function (f) { fields[f.name] = f; });
                read();
                render();
            },
            // The tree as JSON. A tree the editor can't draw comes back as stored.
            value: function () {
                if (tree) return toJSON(tree, true);
                try { return JSON.parse((input && input.value.trim()) || "{}"); } catch (e) { return {}; }
            },
            reset: function () {
                tree = group("and", []);
                write();
                render();
            },
            render: render,
            fields: function () { return fields; },
        };
        read();
        render();
        return editor;
    }

    window.SmallStackFilterTree = { create: create, OP_LABELS: OP_LABELS };
})();
