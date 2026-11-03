// Moved from apps/activity/templates/activity/includes/histogram.html (inline <script>) so the CSP needs no 'unsafe-inline'.
(function () {
    document.querySelectorAll('.activity-hist-wrap').forEach(function (wrap) {
        if (wrap.dataset.tipInit) { return; }
        wrap.dataset.tipInit = '1';
        var tip = wrap.querySelector('.activity-hist-tip');
        document.body.appendChild(tip);  // escape the card's stacking context
        var rows = [
            ['ok', '2xx', 'activity-hist-seg--ok'],
            ['redirect', '3xx', 'activity-hist-seg--redirect'],
            ['client', '4xx', 'activity-hist-seg--client'],
            ['server', '5xx', 'activity-hist-seg--server']
        ];
        function show(bar) {
            var d = bar.dataset;
            var total = parseInt(d.total, 10) || 0;
            var html = '<div class="tip-when">' + d.when + '</div>';
            if (total) {
                html += '<div class="tip-total">' + total.toLocaleString() + ' request' + (total === 1 ? '' : 's')
                      + ' <span class="tip-share">· ' + d.share + '% of window</span></div><div class="tip-rows">';
                rows.forEach(function (r) {
                    var n = parseInt(d[r[0]], 10) || 0;
                    if (n) {
                        html += '<span class="tip-dot ' + r[2] + '"></span><span>' + r[1] + '</span><span class="tip-n">' + n.toLocaleString() + '</span>';
                    }
                });
                html += '</div>';
            } else {
                html += '<div class="tip-empty">No requests</div>';
            }
            tip.innerHTML = html;
            tip.classList.add('is-visible');
            tip.setAttribute('aria-hidden', 'false');
            var br = bar.getBoundingClientRect();
            var stack = bar.querySelector('.activity-hist-stack, .activity-hist-empty');
            var topEdge = stack ? stack.getBoundingClientRect().top : br.top;
            var half = tip.offsetWidth / 2;
            // Centre on the column, clamped to the viewport; sit just above the bar.
            var x = Math.max(half + 8, Math.min(window.innerWidth - half - 8, br.left + br.width / 2));
            tip.style.left = x + 'px';
            tip.style.top = (topEdge - 6) + 'px';
            tip.style.transform = 'translate(-50%, -100%)';
            bar.classList.add('is-active');
        }
        function hide(bar) {
            tip.classList.remove('is-visible');
            tip.setAttribute('aria-hidden', 'true');
            if (bar) { bar.classList.remove('is-active'); }
        }
        var active = null;
        wrap.querySelectorAll('.activity-hist-bar').forEach(function (bar) {
            bar.addEventListener('mouseenter', function () { active = bar; show(bar); });
            bar.addEventListener('mouseleave', function () { hide(bar); active = null; });
        });
        window.addEventListener('scroll', function () { if (active) { hide(active); active = null; } }, { passive: true });
    });
})();
