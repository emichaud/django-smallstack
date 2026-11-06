/* Goals editor — the goal list form's editor over the hidden `sections` JSON
 * field (what REST/MCP and agents write directly). Sections have a title and
 * goals; a goal is a metric or a single-stat card plus its target rule, an
 * optional at-risk line, label, period and note. Goals move by drag (the
 * handle) or by ↑/↓, which also cross into the next or previous section.
 * Each section is a table: its headers sort that section's goals, which changes
 * the order they're read in, so a note says so and offers Undo; its columns
 * resize (table-resize.js, one key, so the sections stay aligned).
 * The field is rewritten on every change, so what's posted is what's shown;
 * the server (goals.normalize_sections) is the gate. */
(function () {
    "use strict";

    function el(tag, attrs, text) {
        var node = document.createElement(tag);
        Object.keys(attrs || {}).forEach(function (k) {
            if (attrs[k] !== null && attrs[k] !== undefined) node.setAttribute(k, attrs[k]);
        });
        if (text != null) node.textContent = text;
        return node;
    }
    function num(value) {
        if (value === "" || value == null) return null;
        var n = Number(value);
        return isNaN(n) ? null : n;
    }
    // The unit a value is typed in, as a hint beside the box ("%", "s", "ms").
    function unitHint(src) {
        if (!src) return "";
        if (src.format === "percent") return "%";
        if (src.format === "duration") return "seconds";
        if (src.format === "currency") return src.unit || "$";
        return src.unit || "";
    }

    document.addEventListener("DOMContentLoaded", function () {
        var form = document.getElementById("glf-form");
        if (!form) return;
        var data = JSON.parse(document.getElementById("glf-data").textContent);
        var field = form.querySelector('[name="sections"]');
        var box = document.getElementById("glf-sections");
        var empty = document.getElementById("glf-empty");
        var total = document.getElementById("glf-total");
        var sharedNote = document.getElementById("glf-shared-note");
        var metrics = {}, cards = {};
        data.metrics.forEach(function (m) { metrics[m.key] = m; });
        data.cards.forEach(function (c) { cards[c.key] = c; });

        var sections = [];
        try { sections = JSON.parse(field.value || "[]"); } catch (e) { sections = []; }
        if (!Array.isArray(sections)) sections = [];
        if (sections.length && sections.every(function (s) { return s && !s.goals && (s.metric || s.component); })) {
            sections = [{ title: "", goals: sections }];
        }
        sections = sections.filter(function (s) { return s && typeof s === "object"; }).map(function (s) {
            return { title: s.title || "", goals: Array.isArray(s.goals) ? s.goals.filter(function (g) { return g && typeof g === "object"; }) : [] };
        });

        function shared() {
            var v = form.querySelector('[name="visibility"]:checked');
            return !!v && v.value === "shared";
        }
        function sourceOf(goal) {
            if (goal.component) return cards[goal.component] || null;
            return metrics[goal.metric] || null;
        }
        function goalName(goal) {
            var src = sourceOf(goal);
            return goal.label || (src ? src.name : (goal.metric || goal.component || "New goal"));
        }
        function write() {
            field.value = JSON.stringify(sections.map(function (s) {
                return { title: s.title, goals: s.goals.map(function (g) {
                    var out = {};
                    ["id", "metric", "component", "label", "target", "warn", "period", "note"].forEach(function (k) {
                        if (g[k] !== undefined && g[k] !== "" && g[k] !== null) out[k] = g[k];
                    });
                    // A cadence with no target isn't set: an at-risk line alone means nothing.
                    var own = {};
                    Object.keys(g.targets || {}).forEach(function (c) {
                        if (g.targets[c] && g.targets[c].target) own[c] = g.targets[c];
                    });
                    if (Object.keys(own).length) out.targets = own;
                    return out;
                }) };
            }));
            var n = sections.reduce(function (acc, s) { return acc + s.goals.length; }, 0);
            total.textContent = n
                ? n + " goal" + (n === 1 ? "" : "s") + (sections.length > 1 ? " in " + sections.length + " sections" : "")
                : "";
            empty.hidden = sections.length > 0;
        }

        // -- one rule (target / at risk): an operator, a number, a second for "between"
        // *goal* holds the rule; *owner* is the goal it's named after, when that's another object.
        function ruleEditor(goal, slot, label, optional, src, owner) {
            var rule = goal[slot] || null;
            var title = goalName(owner || goal);
            var wrap = el("div", { "class": "glf-rule glf-rule--" + slot });
            var op = el("select", { "class": "vTextField glf-op", "aria-label": label + " rule for " + title });
            if (optional) op.appendChild(el("option", { value: "" }, "None"));
            data.ops.forEach(function (o) {
                var opt = el("option", { value: o[0] }, o[1]);
                if (rule && rule.op === o[0]) opt.selected = true;
                op.appendChild(opt);
            });
            if (!rule && !optional) op.value = ">=";
            var a = el("input", { type: "number", step: "any", "class": "vTextField glf-num", "aria-label": label + " for " + title });
            var and = el("span", { "class": "glf-and" }, "and");
            var b = el("input", { type: "number", step: "any", "class": "vTextField glf-num", "aria-label": label + " upper bound for " + title });
            var unit = el("span", { "class": "glf-unit" }, unitHint(src));
            if (rule) {
                if (Array.isArray(rule.value)) { a.value = rule.value[0]; b.value = rule.value[1]; }
                else if (rule.value != null) a.value = rule.value;
            }
            function sync() {
                var between = op.value === "between";
                and.hidden = b.hidden = !between;
                var off = optional && !op.value;
                a.hidden = off;
                if (off) { delete goal[slot]; write(); return; }
                var value = between ? [num(a.value), num(b.value)] : num(a.value);
                goal[slot] = { op: op.value, value: value };
                write();
            }
            op.addEventListener("change", sync);
            a.addEventListener("input", sync);
            b.addEventListener("input", sync);
            [op, a, and, b, unit].forEach(function (n) { wrap.appendChild(n); });
            and.hidden = b.hidden = op.value !== "between";
            a.hidden = optional && !op.value;
            return { node: wrap, sync: sync, op: op, a: a, b: b, unit: unit };
        }

        // -- targets for particular cadences, tucked under the goal
        var CADENCES = [["hourly", "Hourly"], ["daily", "Daily"], ["weekly", "Weekly"], ["monthly", "Monthly"], ["quarterly", "Quarterly"]];
        function cadenceRow(si, gi, colspan) {
            var goal = sections[si].goals[gi];
            var src = sourceOf(goal);
            var row = el("tr", { "class": "glf-cadence-row" });
            var td = el("td", { colspan: String(colspan) });
            var box2 = el("details", { "class": "glf-cadence" });
            box2.open = !!goal._cadenceOpen;
            box2.addEventListener("toggle", function () { goal._cadenceOpen = box2.open; });
            var set = Object.keys(goal.targets || {}).filter(function (c) { return goal.targets[c] && goal.targets[c].target; }).length;
            box2.appendChild(el("summary", {}, "Targets by cadence" + (set ? " (" + set + " set)" : "")));
            box2.appendChild(el("p", { "class": "mb-help" }, src && src.scales
                ? "This number grows with time, so a weekly target doesn't fit an hour. Left blank, weekly uses the main target and the others show the value without judging it."
                : "This number reads the same at any length, so a blank uses the main target."));
            var grid = el("div", { "class": "glf-cadence-grid" });
            CADENCES.forEach(function (c) {
                goal.targets = goal.targets || {};
                var holder = goal.targets[c[0]] = goal.targets[c[0]] || {};
                grid.appendChild(el("span", { "class": "glf-cadence-name" }, c[1]));
                grid.appendChild(ruleEditor(holder, "target", c[1] + " target", true, src, goal).node);
                grid.appendChild(ruleEditor(holder, "warn", c[1] + " at risk", true, src, goal).node);
            });
            box2.appendChild(grid);
            td.appendChild(box2);
            row.appendChild(td);
            return row;
        }
        function sourceSelect(goal) {
            var sel = el("select", { "class": "vTextField glf-source", "aria-label": "Metric or card" });
            sel.appendChild(el("option", { value: "" }, "Choose a metric or card…"));
            var only = shared();
            var gm = el("optgroup", { label: "Metrics" });
            data.metrics.forEach(function (m) {
                if (only && !m.shared && goal.metric !== m.key) return;
                gm.appendChild(el("option", { value: "m:" + m.key }, m.name + (m.shared ? "" : " (personal)")));
            });
            sel.appendChild(gm);
            if (data.cards.length) {
                var gc = el("optgroup", { label: "Single-stat cards" });
                data.cards.forEach(function (c) {
                    if (only && !c.shared && goal.component !== c.key) return;
                    gc.appendChild(el("option", { value: "c:" + c.key }, c.name + (c.shared ? "" : " (personal)")));
                });
                sel.appendChild(gc);
            }
            var current = goal.component ? "c:" + goal.component : (goal.metric ? "m:" + goal.metric : "");
            if (current && !sel.querySelector('option[value="' + current.replace(/"/g, "") + '"]')) {
                sel.appendChild(el("option", { value: current }, (goal.metric || goal.component) + " (not available)"));
            }
            sel.value = current;
            return sel;
        }

        // -- moving goals: by index, crossing section edges
        function move(si, gi, dir) {
            clearSorts();
            var goal = sections[si].goals[gi];
            if (dir < 0) {
                if (gi > 0) { sections[si].goals.splice(gi, 1); sections[si].goals.splice(gi - 1, 0, goal); return [si, gi - 1]; }
                if (si > 0) { sections[si].goals.splice(gi, 1); sections[si - 1].goals.push(goal); return [si - 1, sections[si - 1].goals.length - 1]; }
            } else {
                if (gi < sections[si].goals.length - 1) { sections[si].goals.splice(gi, 1); sections[si].goals.splice(gi + 1, 0, goal); return [si, gi + 1]; }
                if (si < sections.length - 1) { sections[si].goals.splice(gi, 1); sections[si + 1].goals.unshift(goal); return [si + 1, 0]; }
            }
            return [si, gi];
        }
        var dragging = null;  // [si, gi] of the goal being dragged

        function goalRow(si, gi) {
            var goal = sections[si].goals[gi];
            var src = sourceOf(goal);
            var row = el("tr", { "class": "glf-goal", "data-si": si, "data-gi": gi });
            var handle = el("span", { "class": "glf-handle", draggable: "true", title: "Drag to move", "aria-hidden": "true" }, "⠿");
            handle.addEventListener("dragstart", function (ev) {
                dragging = [si, gi];
                row.classList.add("is-dragging");
                ev.dataTransfer.effectAllowed = "move";
                ev.dataTransfer.setData("text/plain", goalName(goal));
                ev.dataTransfer.setDragImage(row, 20, 20);
            });
            handle.addEventListener("dragend", function () { dragging = null; row.classList.remove("is-dragging"); clearDrop(); });
            row.addEventListener("dragover", function (ev) {
                if (!dragging) return;
                ev.preventDefault();
                ev.stopPropagation();
                clearDrop();
                var r = row.getBoundingClientRect();
                row.classList.add(ev.clientY < r.top + r.height / 2 ? "drop-before" : "drop-after");
            });
            row.addEventListener("drop", function (ev) {
                if (!dragging) return;
                ev.preventDefault();
                ev.stopPropagation();
                var after = row.classList.contains("drop-after");
                drop(si, gi + (after ? 1 : 0));
            });

            var sel = sourceSelect(goal);
            var label = el("input", { type: "text", "class": "vTextField glf-label", maxlength: "120", placeholder: src ? src.name : "Label", "aria-label": "Label (blank = the name)" });
            label.value = goal.label || "";
            var tools = el("span", { "class": "glf-tools" });
            var flat = [];
            sections.forEach(function (s, i) { s.goals.forEach(function (_, j) { flat.push(i + ":" + j); }); });
            var pos = flat.indexOf(si + ":" + gi);
            [["up", "Move up", "↑"], ["down", "Move down", "↓"], ["remove", "Remove", "✕"]].forEach(function (b) {
                var btn = el("button", { type: "button", "class": "plf-tool", "data-act": b[0], "aria-label": b[1] + ": " + goalName(goal) }, b[2]);
                if ((b[0] === "up" && pos === 0) || (b[0] === "down" && pos === flat.length - 1)) btn.disabled = true;
                btn.addEventListener("click", function () {
                    if (b[0] === "remove") { clearSorts(); sections[si].goals.splice(gi, 1); render(); focusAt(si, Math.min(gi, sections[si].goals.length - 1), "remove"); return; }
                    var to = move(si, gi, b[0] === "up" ? -1 : 1);
                    render();
                    focusAt(to[0], to[1], b[0]);
                });
                tools.appendChild(btn);
            });
            var target = ruleEditor(goal, "target", "Target", false, src);
            var warn = ruleEditor(goal, "warn", "At risk", true, src);
            var per = el("select", { "class": "vTextField glf-period", "aria-label": "Period for " + goalName(goal) });
            per.appendChild(el("option", { value: "" }, "The list's period"));
            data.periods.forEach(function (p) {
                var o = el("option", { value: p[0] }, p[1]);
                if (goal.period === p[0]) o.selected = true;
                per.appendChild(o);
            });
            per.addEventListener("change", function () { if (per.value) goal.period = per.value; else delete goal.period; write(); });

            var note = el("input", { type: "text", "class": "vTextField glf-note", maxlength: "280", placeholder: "Note: who owns it, or why the target is what it is", "aria-label": "Note for " + goalName(goal) });
            note.value = goal.note || "";
            note.addEventListener("input", function () { if (note.value) goal.note = note.value; else delete goal.note; write(); });
            label.addEventListener("input", function () { if (label.value) goal.label = label.value; else delete goal.label; write(); });

            sel.addEventListener("change", function () {
                delete goal.metric; delete goal.component;
                var v = sel.value;
                if (v.indexOf("m:") === 0) goal.metric = v.slice(2);
                else if (v.indexOf("c:") === 0) goal.component = v.slice(2);
                var s2 = sourceOf(goal);
                // A metric with colour rules suggests its target and at-risk line.
                var suggest = goal.metric && metrics[goal.metric] ? metrics[goal.metric].suggest : null;
                var blank = !goal.target || goal.target.value == null || goal.target.value === "";
                if (suggest && suggest.target && blank) {
                    goal.target = suggest.target;
                    if (suggest.warn && !goal.warn) goal.warn = suggest.warn;
                }
                label.placeholder = s2 ? s2.name : "Label";
                write();
                render();
                focusAt(si, gi, null, ".glf-source");
            });

            var cell = function (nodes, cls) {
                var td = el("td", cls ? { "class": cls } : {});
                nodes.forEach(function (n) { td.appendChild(n); });
                row.appendChild(td);
            };
            cell([handle], "glf-handle-cell");
            var stack = el("div", { "class": "glf-goal-stack" });
            [sel, label, note].forEach(function (n) { stack.appendChild(n); });
            cell([stack]);
            cell([target.node]);
            cell([warn.node]);
            cell([per]);
            cell([tools], "glf-tools-cell");
            if (!goal.target) target.sync();
            return row;
        }

        function clearDrop() {
            box.querySelectorAll(".drop-before, .drop-after, .drop-into").forEach(function (n) {
                n.classList.remove("drop-before", "drop-after", "drop-into");
            });
        }
        function drop(si, gi) {
            var from = dragging;
            dragging = null;
            clearDrop();
            if (!from) return;
            clearSorts();
            var goal = sections[from[0]].goals.splice(from[1], 1)[0];
            if (from[0] === si && from[1] < gi) gi -= 1;
            sections[si].goals.splice(gi, 0, goal);
            render();
            focusAt(si, gi, null, ".glf-source");
        }
        function focusAt(si, gi, act, selector) {
            var row = box.querySelector('.glf-goal[data-si="' + si + '"][data-gi="' + gi + '"]');
            if (!row) {
                var sec = box.querySelectorAll(".glf-section")[si];
                if (sec) sec.querySelector(".glf-add-goal").focus();
                return;
            }
            var target = (act && row.querySelector('[data-act="' + act + '"]:not(:disabled)')) || row.querySelector(selector || ".glf-source");
            if (target) target.focus();
        }

        // -- sorting: a section's rows ARE the order it's read in, so a sort rewrites
        // that order (until Save; Undo restores it). Kept on the section object;
        // write() only ever posts its title and goals.
        var SORT_WORDS = { goal: "goal", target: "target", warn: "at-risk line", period: "period" };
        function clearSorts() {
            sections.forEach(function (s) { delete s._before; delete s._sortKey; delete s._sortDir; });
        }
        function ruleNumber(rule) {
            if (!rule) return null;
            var v = Array.isArray(rule.value) ? rule.value[0] : rule.value;
            return typeof v === "number" ? v : null;
        }
        function periodName(goal) {
            var hit = data.periods.filter(function (p) { return p[0] === goal.period; })[0];
            return hit ? String(hit[1]).toLowerCase() : null;
        }
        function sortValue(goal, key) {
            if (key === "goal") return String(goalName(goal)).toLowerCase();
            if (key === "period") return periodName(goal);
            return ruleNumber(goal[key]);
        }
        function sortSection(si, key) {
            var section = sections[si];
            if (!section._before) section._before = section.goals.slice();
            section._sortDir = section._sortKey === key && section._sortDir === "asc" ? "desc" : "asc";
            section._sortKey = key;
            var sign = section._sortDir === "asc" ? 1 : -1;
            // Nothing to sort by goes last either way; ties keep their order (a stable sort).
            section.goals.sort(function (x, y) {
                var a = sortValue(x, key), c = sortValue(y, key);
                if (a === null || c === null) return a === c ? 0 : (a === null ? 1 : -1);
                return a < c ? -sign : (a > c ? sign : 0);
            });
            render();
            var again = box.querySelectorAll(".glf-section")[si].querySelector('[data-sort="' + key + '"]');
            if (again) again.focus();
        }
        var COLUMNS = [["goal", "Goal"], ["target", "Target"], ["warn", "At risk"], ["period", "Period"]];
        function goalsTable(si) {
            var section = sections[si];
            var table = el("table", {
                "class": "crud-table glf-table",
                "aria-label": (section.title || "Untitled section") + " goals",
                "data-table-key": "dashboards/goal-form:goal,target,warn,period",
            });
            var head = el("tr");
            head.appendChild(el("th", { scope: "col", "class": "glf-handle-col" }));
            COLUMNS.forEach(function (c) {
                var on = section._sortKey === c[0];
                var th = el("th", { scope: "col", "data-field": c[0], "class": "glf-col-" + c[0], "aria-sort": on ? (section._sortDir === "asc" ? "ascending" : "descending") : "none" });
                var sort = el("button", { type: "button", "class": "plf-sort", "data-sort": c[0] }, c[1]);
                sort.appendChild(el("span", { "class": "dm-sort-ind", "aria-hidden": "true" }, on ? (section._sortDir === "asc" ? "▲" : "▼") : ""));
                sort.addEventListener("click", function () { sortSection(si, c[0]); });
                th.appendChild(sort);
                th.appendChild(el("span", {
                    "class": "col-resizer", role: "separator", "aria-orientation": "vertical", tabindex: "0",
                    "aria-label": "Resize " + c[1] + " column", "aria-valuemin": "48", title: "Drag to resize, double-click to fit",
                }));
                head.appendChild(th);
            });
            head.appendChild(el("th", { scope: "col", "class": "glf-tools-col" }));
            var thead = el("thead");
            thead.appendChild(head);
            table.appendChild(thead);
            var body = el("tbody");
            section.goals.forEach(function (_, gi) {
                body.appendChild(goalRow(si, gi));
                body.appendChild(cadenceRow(si, gi, COLUMNS.length + 2));
            });
            table.appendChild(body);
            var scroller = el("div", { "class": "glf-table-wrap" });
            scroller.appendChild(table);
            return scroller;
        }

        function sectionBlock(si) {
            var section = sections[si];
            var wrap = el("section", { "class": "glf-section", "data-si": si });
            var head = el("div", { "class": "glf-section-head" });
            var title = el("input", { type: "text", "class": "vTextField glf-section-title", maxlength: "120", placeholder: "Section title, like Support or Uptime", "aria-label": "Section " + (si + 1) + " title" });
            title.value = section.title;
            title.addEventListener("input", function () { section.title = title.value; write(); });
            var tools = el("span", { "class": "glf-tools" });
            [["up", "Move section up", "↑"], ["down", "Move section down", "↓"], ["remove", "Remove section", "✕"]].forEach(function (b) {
                var btn = el("button", { type: "button", "class": "plf-tool", "data-sact": b[0], "aria-label": b[1] + (section.title ? ": " + section.title : "") }, b[2]);
                if ((b[0] === "up" && si === 0) || (b[0] === "down" && si === sections.length - 1)) btn.disabled = true;
                btn.addEventListener("click", function () {
                    if (b[0] === "remove") {
                        if (section.goals.length && !window.confirm("Remove this section and its " + section.goals.length + " goal" + (section.goals.length === 1 ? "" : "s") + "?")) return;
                        sections.splice(si, 1);
                        render();
                        var next = box.querySelectorAll(".glf-section-title")[Math.min(si, sections.length - 1)];
                        (next || document.getElementById("glf-add-section")).focus();
                        return;
                    }
                    var to = b[0] === "up" ? si - 1 : si + 1;
                    sections.splice(to, 0, sections.splice(si, 1)[0]);
                    render();
                    var moved = box.querySelectorAll(".glf-section")[to];
                    var btn2 = moved && moved.querySelector('[data-sact="' + b[0] + '"]:not(:disabled)');
                    (btn2 || moved.querySelector(".glf-section-title")).focus();
                });
                tools.appendChild(btn);
            });
            head.appendChild(title);
            head.appendChild(el("span", { "class": "glf-section-count" }, section.goals.length + " goal" + (section.goals.length === 1 ? "" : "s")));
            head.appendChild(tools);
            wrap.appendChild(head);

            if (section._before) {
                var noted = el("p", { "class": "plf-sorted", role: "status" }, "Sorted by " + SORT_WORDS[section._sortKey] + ". This is now the order this section reads in; save to keep it. ");
                var undo = el("button", { type: "button", "class": "plf-undo" }, "Undo");
                undo.addEventListener("click", function () {
                    section.goals = section._before;
                    delete section._before; delete section._sortKey; delete section._sortDir;
                    render();
                    var title = box.querySelectorAll(".glf-section-title")[si];
                    if (title) title.focus();
                });
                noted.appendChild(undo);
                wrap.appendChild(noted);
            }
            // Dropping on the section's empty space (or an empty section) appends.
            wrap.addEventListener("dragover", function (ev) {
                if (!dragging) return;
                ev.preventDefault();
                clearDrop();
                wrap.classList.add("drop-into");
            });
            wrap.addEventListener("drop", function (ev) {
                if (!dragging) return;
                ev.preventDefault();
                drop(si, section.goals.length);
            });
            if (section.goals.length) wrap.appendChild(goalsTable(si));
            if (!section.goals.length) wrap.appendChild(el("p", { "class": "mb-help glf-section-empty" }, "No goals here yet. Add one, or drag one in."));
            var add = el("button", { type: "button", "class": "btn-outline btn-sm glf-add-goal" }, "Add goal");
            add.addEventListener("click", function () {
                clearSorts();
                section.goals.push({ target: { op: ">=", value: null } });
                render();
                focusAt(si, section.goals.length - 1, null, ".glf-source");
            });
            wrap.appendChild(add);
            return wrap;
        }

        function render() {
            box.replaceChildren();
            sections.forEach(function (_, si) { box.appendChild(sectionBlock(si)); });
            sharedNote.hidden = !shared();
            write();
            // These tables are built here, so they register with the resizer themselves.
            if (window.SmallStackTableResize) window.SmallStackTableResize.init(box);
        }

        document.getElementById("glf-add-section").addEventListener("click", function () {
            sections.push({ title: "", goals: [] });
            render();
            var titles = box.querySelectorAll(".glf-section-title");
            titles[titles.length - 1].focus();
        });
        form.addEventListener("change", function (ev) { if (ev.target.name === "visibility") render(); });

        if (!sections.length && form.getAttribute("data-creating") === "1") sections.push({ title: "", goals: [] });
        render();
    });
})();
