/* Dashboard settings form — small progressive enhancements over real inputs
 * (the page works without JS): slug from name, refresh presets, layout JSON
 * pretty-printed, and the live preview tile. */
(function () {
    "use strict";

    function q(form, name) { return form.querySelector('[name="' + name + '"]'); }

    document.addEventListener("DOMContentLoaded", function () {
        var form = document.getElementById("df-form");
        if (!form) return;
        var name = q(form, "name"), desc = q(form, "description");
        var refresh = q(form, "refresh_seconds"), layout = q(form, "layout");

        name.addEventListener("input", render);
        desc.addEventListener("input", render);

        // Refresh presets drive the number input (and mirror it back).
        var presets = document.querySelectorAll("#df-refresh-presets [data-seconds]");
        function syncPresets() {
            presets.forEach(function (b) {
                b.setAttribute("aria-pressed", String(b.getAttribute("data-seconds") === (refresh.value || "")));
            });
        }
        presets.forEach(function (b) {
            b.addEventListener("click", function () {
                refresh.value = b.getAttribute("data-seconds");
                syncPresets(); render();
            });
        });
        refresh.addEventListener("input", function () { syncPresets(); render(); });
        form.addEventListener("change", render);

        // The picture: preview a chosen file before it's uploaded, in the
        // input and on the preview tile; Remove greys the current one out.
        var cover = form.querySelector("[data-cover-input]");
        if (cover) {
            var file = cover.querySelector("[data-cover-file]");
            var frame = cover.querySelector(".df-cover-frame");
            var img = cover.querySelector("[data-cover-preview]");
            var clear = cover.querySelector("[data-cover-clear]");
            var fileName = cover.querySelector("[data-cover-filename]");
            var pickLabel = cover.querySelector("[data-cover-pick-label]");
            var tileImg = document.getElementById("df-prev-cover");
            var original = img.getAttribute("src") || "";
            var objectUrl = null;
            function show(src) {
                if (src) img.setAttribute("src", src); else img.removeAttribute("src");
                frame.classList.toggle("is-empty", !src);
                if (tileImg) {
                    if (src) tileImg.setAttribute("src", src); else tileImg.removeAttribute("src");
                    tileImg.hidden = !src;
                }
            }
            file.addEventListener("change", function () {
                if (objectUrl) URL.revokeObjectURL(objectUrl);
                objectUrl = null;
                var chosen = file.files && file.files[0];
                if (chosen) {
                    objectUrl = URL.createObjectURL(chosen);
                    if (clear) clear.checked = false;
                    frame.classList.remove("is-removed");
                    fileName.textContent = chosen.name;
                    pickLabel.textContent = "Choose another";
                    show(objectUrl);
                } else {
                    fileName.textContent = "";
                    show(original);
                }
            });
            if (clear) {
                clear.addEventListener("change", function () {
                    if (clear.checked && file.value) {
                        // Remove wins over a file picked a moment ago.
                        file.value = "";
                        fileName.textContent = "";
                        pickLabel.textContent = "Replace";
                        show(original);
                    }
                    frame.classList.toggle("is-removed", clear.checked);
                    if (tileImg) tileImg.hidden = clear.checked;
                });
            }
        }

        // Pretty-print the layout JSON for anyone who opens Advanced.
        try {
            if (layout && layout.value.trim()) layout.value = JSON.stringify(JSON.parse(layout.value), null, 2);
        } catch (e) { /* leave invalid JSON as typed so its error still makes sense */ }

        function render() {
            document.getElementById("df-prev-name").textContent = name.value || "Untitled dashboard";
            document.getElementById("df-prev-desc").textContent = desc.value;
            var vis = form.querySelector('[name="visibility"]:checked');
            var visEl = document.getElementById("df-prev-vis");
            var shared = vis && vis.value === "shared";
            visEl.textContent = shared ? "Shared" : "Personal";
            visEl.classList.toggle("dash-badge--shared", shared);
            var per = form.querySelector('[name="default_period"]:checked');
            var heading = per ? (per.getAttribute("data-heading") || per.parentNode.textContent.trim()) : "All time";
            document.getElementById("df-prev-period").textContent = "Opens on " + heading.toLowerCase();
            var r = document.getElementById("df-prev-refresh");
            var secs = parseInt(refresh.value, 10);
            r.hidden = !secs;
            if (secs) r.textContent = "Refresh " + (secs % 60 === 0 ? secs / 60 + " min" : secs + " s");
        }
        // -- the miniature's live values, for the period it would open on ----
        var valuesUrl = form.getAttribute("data-values-url");
        var status = document.getElementById("df-mini-status");
        var seq = 0, lastPeriod = null;
        function cellText(cell) {
            if (cell.error || cell.restricted) return { text: "—" };
            if (cell.result) {
                var r = cell.result;
                if (r.error || r.restricted) return { text: "—" };
                return { text: r.display + (r.unit ? " " + r.unit : ""), state: r.state };
            }
            if (cell.groups && cell.groups.length) {
                var g = cell.groups[0];
                return { label: g.label, text: g.display, state: g.state };
            }
            return null;
        }
        function loadValues() {
            if (!valuesUrl) return;
            var per = form.querySelector('[name="default_period"]:checked');
            var key = per && per.value ? per.value : "all";
            if (key === lastPeriod) return;
            lastPeriod = key;
            var mine = ++seq;
            var heading = per ? (per.getAttribute("data-heading") || "All time") : "All time";
            if (status) status.textContent = "Loading values for " + heading.toLowerCase() + "…";
            fetch(valuesUrl + "?period=" + encodeURIComponent(key), { credentials: "same-origin" })
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    if (mine !== seq) return;
                    (data.cells || []).forEach(function (cell) {
                        var box = form.querySelector('.df-mini-cell[data-cell-id="' + CSS.escape(String(cell.id)) + '"] .df-mini-value');
                        if (!box) return;
                        var v = cellText(cell);
                        box.textContent = "";
                        if (v && v.label) {
                            var lbl = document.createElement("span");
                            lbl.className = "df-mini-value-label";
                            lbl.textContent = v.label + " ";
                            box.appendChild(lbl);
                        }
                        if (v) box.appendChild(document.createTextNode(v.text));
                        box.className = "df-mini-value" + (v && v.state ? " df-mini-value--" + v.state : "");
                    });
                    if (status) status.textContent = "Values as it opens on " + heading.toLowerCase() + ". Click a metric card for its rows.";
                    renderDigest(data.cells || [], heading);
                })
                .catch(function () { if (status) status.textContent = ""; });
        }
        form.addEventListener("change", function (ev) { if (ev.target.name === "default_period") loadValues(); });

        // -- the dashboards list's "needs attention" line, for this period ----
        function renderDigest(cells, heading) {
            var line = document.getElementById("df-digest");
            if (!line) return;
            var attention = [], fine = 0;
            function rate(name, st) {
                if (st === "danger" || st === "warning") attention.push({ name: name, state: st });
                else if (st === "success") fine += 1;
            }
            cells.forEach(function (c) {
                var name = c.title || labelFor(c.id);
                if (c.type === "metric" && c.result) rate(name, c.result.state);
                // A grouped card: each group carries its own threshold state.
                if (c.type === "metric_group" && c.groups) {
                    c.groups.forEach(function (g) { if (!g.other) rate(name + ": " + g.label, g.state); });
                }
            });
            line.textContent = "";
            if (!attention.length && !fine) { line.hidden = true; return; }
            attention.sort(function (a, b) { return (a.state !== "danger") - (b.state !== "danger"); });
            function state(cls, text) {
                var s = document.createElement("span");
                s.className = "bl-state bl-state--" + cls;
                var dot = document.createElement("span"); dot.className = "bl-dot"; dot.setAttribute("aria-hidden", "true");
                s.appendChild(dot); s.appendChild(document.createTextNode(text));
                return s;
            }
            var wrap = document.createElement("span"); wrap.className = "bl-health";
            if (attention.length) {
                var names = attention.slice(0, 2).map(function (a) { return a.name; }).join(", ");
                var more = attention.length > 2 ? " and " + (attention.length - 2) + " more" : "";
                wrap.appendChild(state(attention[0].state, attention.length + (attention.length === 1 ? " needs" : " need") + " attention: " + names + more));
                if (fine) wrap.appendChild(state("success", fine + " fine"));
            } else {
                wrap.appendChild(state("success", "All clear"));
            }
            line.appendChild(wrap);
            var when = document.createElement("span"); when.className = "rl-moves-when";
            when.textContent = " on " + heading.toLowerCase();
            line.appendChild(when);
            line.hidden = false;
        }
        function labelFor(id) {
            var cell = form.querySelector('.df-mini-cell[data-cell-id="' + CSS.escape(String(id)) + '"]');
            return cell ? (cell.getAttribute("data-label") || "") : "";
        }

        // -- a metric card in the miniature opens its rows for this period ------
        function openRows(cell) {
            var url = form.getAttribute("data-rows-url").replace("METRIC", encodeURIComponent(cell.getAttribute("data-metric")));
            var per = form.querySelector('[name="default_period"]:checked');
            var key = per && per.value ? per.value : "";
            if (key) url += "?period=" + encodeURIComponent(key);
            var heading = per ? (per.getAttribute("data-heading") || "All time") : "All time";
            var title = cell.getAttribute("data-label") + (key ? ", " + heading.toLowerCase() : "");
            if (window.openStatModal) window.openStatModal(title, cell);
            if (window.htmx) window.htmx.ajax("GET", url, { target: "#stat-modal-body", swap: "innerHTML" });
        }
        form.querySelectorAll(".df-mini-cell[data-metric]").forEach(function (cell) {
            cell.addEventListener("click", function () { openRows(cell); });
            cell.addEventListener("keydown", function (ev) {
                if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); openRows(cell); }
            });
        });

        syncPresets();
        render();
        loadValues();
    });
})();
