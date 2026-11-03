// Moved from apps/scheduler/templates/scheduler/crud/form_scheduler.html (inline <script>) so the CSP needs no 'unsafe-inline'.
(function () {
    var form = document.querySelector('.sjf');
    if (!form) return;

    // ── real inputs (source of truth) ──────────────────────────
    var typeSel = document.getElementById('id_schedule_type');
    var intInput = document.getElementById('id_interval_spec');
    var cronInput = document.getElementById('id_cron_expression');
    var tzInput = document.getElementById('id_timezone');

    // ── helpers ────────────────────────────────────────────────
    function setActive(container, matchFn) {
        container.querySelectorAll('.sjf-seg-btn, .sjf-chip').forEach(function (b) {
            b.classList.toggle('active', matchFn(b));
        });
    }
    var DOW = { 0: 'Sun', 1: 'Mon', 2: 'Tue', 3: 'Wed', 4: 'Thu', 5: 'Fri', 6: 'Sat' };
    var UNIT_WORD = { s: 'second', m: 'minute', h: 'hour', d: 'day', w: 'week', mo: 'month', y: 'year' };
    function pl(n, w) { return n + ' ' + w + (n == 1 ? '' : 's'); }
    function pad(n) { return (n < 10 ? '0' : '') + n; }
    function h12(h, m) { var ap = h < 12 ? 'AM' : 'PM'; var hh = h % 12; if (hh === 0) hh = 12; return hh + ':' + pad(m) + ' ' + ap; }
    function tzSuffix() { var v = tzInput && tzInput.value.trim(); return v ? ' (' + v + ')' : ''; }

    // ── summary ────────────────────────────────────────────────
    var summaryEl = document.getElementById('sjf-summary-text');
    function setSummary(html) { summaryEl.innerHTML = html; }

    // ── progressive disclosure by schedule type ────────────────
    var typeSeg = document.getElementById('sjf-type-seg');
    function showType(val) {
        typeSel.value = val;
        setActive(typeSeg, function (b) { return b.dataset.value === val; });
        form.querySelectorAll('.sjf-group').forEach(function (g) {
            g.style.display = (g.dataset.group === val) ? '' : 'none';
        });
        refreshSummary();
    }
    typeSeg.addEventListener('click', function (e) {
        var btn = e.target.closest('.sjf-seg-btn'); if (btn) showType(btn.dataset.value);
    });

    // ── INTERVAL builder ───────────────────────────────────────
    var intNum = document.getElementById('sjf-int-num');
    var intUnitSeg = document.getElementById('sjf-int-unit');
    var intPresets = document.getElementById('sjf-int-presets');
    function currentUnit() { var a = intUnitSeg.querySelector('.sjf-seg-btn.active'); return a ? a.dataset.unit : 'm'; }
    function buildInterval() {
        var n = Math.max(1, parseInt(intNum.value, 10) || 1);
        var u = currentUnit();
        intInput.value = n + u;
        setActive(intPresets, function (b) { return b.dataset.preset === (n + u); });
        refreshSummary();
    }
    function loadInterval(spec) {
        var m = /^(\d+)\s*(mo|[smhdwy])$/i.exec((spec || '').trim());
        if (m) {
            intNum.value = m[1];
            var u = m[2].toLowerCase();
            setActive(intUnitSeg, function (b) { return b.dataset.unit === u; });
        } else {
            intNum.value = 1;
            setActive(intUnitSeg, function (b) { return b.dataset.unit === 'm'; });
        }
    }
    intNum.addEventListener('input', buildInterval);
    intUnitSeg.addEventListener('click', function (e) {
        var b = e.target.closest('.sjf-seg-btn'); if (!b) return;
        setActive(intUnitSeg, function (x) { return x === b; }); buildInterval();
    });
    intPresets.addEventListener('click', function (e) {
        var b = e.target.closest('.sjf-chip'); if (!b) return;
        loadInterval(b.dataset.preset); buildInterval();
    });
    intInput.addEventListener('input', function () { loadInterval(intInput.value); refreshSummary(); });

    // ── CRON builder ───────────────────────────────────────────
    var freqSeg = document.getElementById('sjf-cron-freq');
    var cMin = document.getElementById('sjf-cron-min');
    var cTime = document.getElementById('sjf-cron-time');
    var cDom = document.getElementById('sjf-cron-dom');
    var dowChips = document.getElementById('sjf-cron-dow');
    function currentFreq() { var a = freqSeg.querySelector('.sjf-seg-btn.active'); return a ? a.dataset.freq : 'daily'; }
    function timeParts() { var p = (cTime.value || '00:00').split(':'); return [parseInt(p[1], 10) || 0, parseInt(p[0], 10) || 0]; } // [min, hour]
    function selectedDows() {
        return Array.prototype.map.call(dowChips.querySelectorAll('.sjf-chip.active'), function (c) { return parseInt(c.dataset.dow, 10); });
    }
    function showFreqRows(freq) {
        form.querySelectorAll('.sjf-cron-row').forEach(function (r) {
            r.hidden = r.dataset.when.split(' ').indexOf(freq) === -1;
        });
    }
    function buildCron() {
        var freq = currentFreq();
        if (freq === 'advanced') { refreshSummary(); return; }  // raw field is the source
        var tp = timeParts(), mm = tp[0], hh = tp[1], expr = '';
        if (freq === 'hourly') { expr = (parseInt(cMin.value, 10) || 0) + ' * * * *'; }
        else if (freq === 'daily') { expr = mm + ' ' + hh + ' * * *'; }
        else if (freq === 'weekly') {
            var d = selectedDows(); if (!d.length) d = [1];
            expr = mm + ' ' + hh + ' * * ' + d.sort(function (a, b) { return a - b; }).join(',');
        } else if (freq === 'monthly') { expr = mm + ' ' + hh + ' ' + (parseInt(cDom.value, 10) || 1) + ' * *'; }
        cronInput.value = expr;
        refreshSummary();
    }
    function loadCron(expr) {
        var parts = (expr || '').trim().split(/\s+/);
        if (parts.length !== 5) { setActive(freqSeg, function (b) { return b.dataset.freq === 'advanced'; }); showFreqRows('advanced'); return; }
        var mi = parts[0], ho = parts[1], dom = parts[2], mon = parts[3], dow = parts[4];
        var isNum = function (s) { return /^\d+$/.test(s); };
        var freq = 'advanced';
        if (ho === '*' && dom === '*' && mon === '*' && dow === '*' && isNum(mi)) { freq = 'hourly'; cMin.value = mi; }
        else if (isNum(mi) && isNum(ho) && dom === '*' && mon === '*' && dow === '*') { freq = 'daily'; cTime.value = pad(ho) + ':' + pad(mi); }
        else if (isNum(mi) && isNum(ho) && dom === '*' && mon === '*' && /^[0-6](,[0-6])*$/.test(dow)) {
            freq = 'weekly'; cTime.value = pad(ho) + ':' + pad(mi);
            var set = dow.split(',');
            dowChips.querySelectorAll('.sjf-chip').forEach(function (c) { c.classList.toggle('active', set.indexOf(c.dataset.dow) !== -1); });
        } else if (isNum(mi) && isNum(ho) && isNum(dom) && mon === '*' && dow === '*') { freq = 'monthly'; cTime.value = pad(ho) + ':' + pad(mi); cDom.value = dom; }
        setActive(freqSeg, function (b) { return b.dataset.freq === freq; });
        showFreqRows(freq);
    }
    freqSeg.addEventListener('click', function (e) {
        var b = e.target.closest('.sjf-seg-btn'); if (!b) return;
        setActive(freqSeg, function (x) { return x === b; }); showFreqRows(b.dataset.freq); buildCron();
    });
    [cMin, cTime, cDom].forEach(function (el) { el.addEventListener('input', buildCron); });
    dowChips.addEventListener('click', function (e) {
        var c = e.target.closest('.sjf-chip'); if (!c) return; c.classList.toggle('active'); buildCron();
    });
    cronInput.addEventListener('input', function () { loadCron(cronInput.value); refreshSummary(); });

    // ── cron → English (builder-driven, deterministic) ─────────
    function cronEnglish() {
        var freq = currentFreq();
        var tp = timeParts(), at = h12(tp[1], tp[0]);
        if (freq === 'hourly') { var m = parseInt(cMin.value, 10) || 0; return 'every hour at <b>:' + pad(m) + '</b>'; }
        if (freq === 'daily') { return 'every day at <b>' + at + '</b>'; }
        if (freq === 'weekly') {
            var d = selectedDows(); if (!d.length) return 'weekly — <b>pick a day</b>';
            return 'every <b>' + d.sort(function (a, b) { return a - b; }).map(function (x) { return DOW[x]; }).join(', ') + '</b> at <b>' + at + '</b>';
        }
        if (freq === 'monthly') { return 'on day <b>' + (parseInt(cDom.value, 10) || 1) + '</b> of every month at <b>' + at + '</b>'; }
        return 'cron <b>' + (cronInput.value.trim() || '—') + '</b>';
    }

    // ── unified summary ────────────────────────────────────────
    function refreshSummary() {
        var t = typeSel.value;
        if (t === 'once') {
            var rv = document.getElementById('id_run_at');
            setSummary('runs <b>once</b>' + (rv && rv.value ? ' at <b>' + rv.value.replace('T', ' ') + '</b>' : '') + tzSuffix());
        } else if (t === 'interval') {
            var m = /^(\d+)\s*(mo|[smhdwy])$/i.exec((intInput.value || '').trim());
            if (m) setSummary('runs every <b>' + pl(parseInt(m[1], 10), UNIT_WORD[m[2].toLowerCase()]) + '</b>' + tzSuffix());
            else setSummary('runs on an <b>interval</b>' + tzSuffix());
        } else if (t === 'cron') {
            setSummary('runs ' + cronEnglish() + tzSuffix());
        } else { setSummary('Pick a cadence below'); }
        document.body.dispatchEvent(new CustomEvent('sjf:cadence'));  // → htmx next-runs preview
    }

    // ── catch-up segmented (drives hidden select) ──────────────
    var catchSel = document.getElementById('id_catch_up');
    var catchupSeg = document.getElementById('sjf-catchup-seg');
    if (catchupSeg && catchSel) {
        catchupSeg.addEventListener('click', function (e) {
            var b = e.target.closest('.sjf-seg-btn'); if (!b) return;
            catchSel.value = b.dataset.value;
            setActive(catchupSeg, function (x) { return x === b; });
        });
        setActive(catchupSeg, function (b) { return b.dataset.value === catchSel.value; });
    }

    // ── timezone select → refresh summary + preview ───────────
    if (tzInput) tzInput.addEventListener('change', refreshSummary);

    // ── run-at quick presets ───────────────────────────────────
    var runAtEl = document.getElementById('id_run_at');
    var runPresets = document.getElementById('sjf-runat-presets');
    function fmtLocal(d) {
        return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) + 'T' + pad(d.getHours()) + ':' + pad(d.getMinutes());
    }
    if (runAtEl) runAtEl.addEventListener('input', refreshSummary);
    if (runPresets && runAtEl) runPresets.addEventListener('click', function (e) {
        var b = e.target.closest('.sjf-chip'); if (!b) return;
        var d = new Date(), k = b.dataset.run;
        if (k === '+1h') { d.setHours(d.getHours() + 1, 0, 0, 0); }
        else if (k === 'tonight') { d.setHours(20, 0, 0, 0); }
        else if (k === 'tomorrow9') { d.setDate(d.getDate() + 1); d.setHours(9, 0, 0, 0); }
        else if (k === 'nextmon9') { d.setDate(d.getDate() + ((8 - d.getDay()) % 7 || 7)); d.setHours(9, 0, 0, 0); }
        runAtEl.value = fmtLocal(d); refreshSummary();
    });

    // ── project calendar button on the datetime fields ─────────
    ['id_run_at', 'id_anchor_at'].forEach(function (id) {
        var input = document.getElementById(id);
        if (!input || input.closest('.crud-date-wrapper')) return;
        var wrap = document.createElement('div');
        wrap.className = 'crud-date-wrapper';
        input.parentNode.insertBefore(wrap, input);
        wrap.appendChild(input);
        var btn = document.createElement('button');
        btn.type = 'button'; btn.className = 'crud-date-btn'; btn.setAttribute('aria-label', 'Open calendar');
        btn.innerHTML = '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><path d="M19 3h-1V1h-2v2H8V1H6v2H5c-1.11 0-1.99.9-1.99 2L3 19c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm0 16H5V8h14v11zM9 10H7v2h2v-2zm4 0h-2v2h2v-2zm4 0h-2v2h2v-2zm-8 4H7v2h2v-2zm4 0h-2v2h2v-2zm4 0h-2v2h2v-2z"/></svg>';
        btn.addEventListener('click', function () { if (input.showPicker) { input.showPicker(); } else { input.focus(); } });
        wrap.appendChild(btn);
    });

    // ── init from existing values ──────────────────────────────
    loadInterval(intInput.value);
    loadCron(cronInput.value);
    showType(typeSel.value || 'interval');
})();
