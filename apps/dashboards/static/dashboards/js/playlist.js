/* Dashboard playlist player — drives every [data-playlist] on the page
 * (dashboards/includes/playlist_player.html). The markup works without it:
 * prev / next / steps are links to ?slide=N. This adds, per player:
 *
 * - paging in place: the next slide's markup comes from data-slide-url
 *   (…/slides/0/ with the position swapped in); its cards load over htmx as
 *   on any dashboard, and the slide after is fetched ahead;
 * - the timer: each step's data-seconds (or data-seconds on the player, a
 *   link's ?seconds=), a progress fill on the current step, loop or stop at
 *   the end (data-loop), auto-start (data-play);
 * - pausing on its own when the tab is hidden, or when someone clicks into a
 *   card (to read a drill-down), and resuming when the tab comes back;
 * - keys: ←/→ (PageUp/PageDown), Home/End, space or k to play/pause, f for
 *   full screen. Page-wide on the playlist page (data-keys="page"), inside
 *   the player when it's embedded;
 * - data-sync-url: the address bar follows (?slide=N&play=1|0), so a copied
 *   link opens on the same dashboard, playing or not.
 */
(function () {
    "use strict";

    var reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    function Player(root) {
        var count = parseInt(root.getAttribute("data-count"), 10) || 0;
        var index = parseInt(root.getAttribute("data-start"), 10) || 0;
        var loop = root.getAttribute("data-loop") === "1";
        var override = parseInt(root.getAttribute("data-seconds"), 10) || 0;
        var slideUrl = root.getAttribute("data-slide-url");
        var stage = root.querySelector("[data-pl-stage]");
        var steps = Array.prototype.slice.call(root.querySelectorAll("[data-pl-step]"));
        var toggleBtn = root.querySelector('[data-pl="toggle"]');
        var toggleLabel = root.querySelector("[data-pl-toggle-label]");
        var posEl = root.querySelector("[data-pl-pos]");
        var nameEl = root.querySelector("[data-pl-name]");
        var prevLink = root.querySelector('[data-pl="prev"]');
        var nextLink = root.querySelector('[data-pl="next"]');

        var playing = false;
        var started = false;
        var timer = null;
        var startedAt = 0;
        var remaining = 0;
        var resumeOnShow = false;
        var seq = 0;
        var ahead = {};

        function wrap(i) { return ((i % count) + count) % count; }
        function duration(i) {
            var s = override || parseInt(steps[i] && steps[i].getAttribute("data-seconds"), 10) || 30;
            return s * 1000;
        }
        function urlFor(i) { return slideUrl.replace(/\/0\/$/, "/" + (i + 1) + "/"); }
        function fetchSlide(i) {
            if (!ahead[i]) {
                ahead[i] = fetch(urlFor(i), { credentials: "same-origin", headers: { "X-Requested-With": "XMLHttpRequest" } })
                    .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); });
            }
            var p = ahead[i];
            delete ahead[i];   // used once: the next visit fetches afresh
            return p;
        }
        function prefetch(i) {
            if (count < 2 || ahead[i]) return;
            ahead[i] = fetch(urlFor(i), { credentials: "same-origin" })
                .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); });
            ahead[i].catch(function () { delete ahead[i]; });
        }

        // -- what the bar shows ------------------------------------------------
        function linkFor(i) {
            var u = new URL(window.location.href);
            if (!root.hasAttribute("data-sync-url")) u = new URL(steps[i].href, window.location.href);
            u.searchParams.set("slide", String(i + 1));
            return u.pathname + u.search;
        }
        function showPosition(i) {
            steps.forEach(function (step, n) {
                step.classList.toggle("is-current", n === i);
                step.classList.toggle("is-done", n < i);
                step.classList.remove("is-running");
                if (n === i) step.setAttribute("aria-current", "step"); else step.removeAttribute("aria-current");
            });
            if (posEl) posEl.textContent = String(i + 1);
            if (nameEl && steps[i]) {
                nameEl.textContent = steps[i].getAttribute("data-name");
                nameEl.setAttribute("href", steps[i].getAttribute("data-url"));
            }
            if (prevLink) prevLink.setAttribute("href", linkFor(wrap(i - 1)));
            if (nextLink) nextLink.setAttribute("href", linkFor(wrap(i + 1)));
            syncUrl();
        }
        function syncUrl() {
            if (!started || !root.hasAttribute("data-sync-url")) return;   // the link as opened stays as is
            var u = new URL(window.location.href);
            u.searchParams.set("slide", String(index + 1));
            u.searchParams.set("play", playing ? "1" : "0");
            history.replaceState(history.state, "", u.pathname + u.search + u.hash);
        }
        function showPlaying() {
            root.classList.toggle("is-paused", !playing);
            if (toggleBtn) toggleBtn.setAttribute("aria-pressed", playing ? "true" : "false");
            if (toggleLabel) toggleLabel.textContent = playing ? "Pause" : "Play";
            syncUrl();
        }

        // -- the timer ---------------------------------------------------------
        function runFill(ms, total) {
            var step = steps[index];
            if (!step) return;
            step.style.setProperty("--pl-ms", ms + "ms");
            step.style.setProperty("--pl-from", String(1 - ms / total));
            step.classList.remove("is-running");
            void step.offsetWidth;   // restart the animation
            step.classList.add("is-running");
        }
        function arm(ms) {
            clearTimeout(timer);
            remaining = ms;
            startedAt = Date.now();
            runFill(ms, duration(index));
            timer = setTimeout(function () { advance(1, true); }, ms);
        }
        function play() {
            if (count < 2) return;
            playing = true;
            showPlaying();
            arm(remaining > 0 ? remaining : duration(index));
        }
        function pause() {
            if (!playing) return;
            playing = false;
            clearTimeout(timer);
            remaining = Math.max(0, remaining - (Date.now() - startedAt));
            showPlaying();
        }

        // -- paging ------------------------------------------------------------
        function go(i) {
            if (!count) return;
            var target = wrap(i);
            var mine = ++seq;
            clearTimeout(timer);
            remaining = 0;
            index = target;
            showPosition(target);
            stage.style.minHeight = stage.offsetHeight + "px";   // no collapse while the next one loads
            fetchSlide(target).then(function (html) {
                if (mine !== seq) return;
                var holder = document.createElement("div");
                holder.innerHTML = html;
                var slide = holder.firstElementChild;
                if (!slide) throw new Error("empty slide");
                if (!reduceMotion) slide.classList.add("is-entering");
                stage.replaceChildren(slide);
                if (window.htmx) window.htmx.process(slide);
                if (!reduceMotion) requestAnimationFrame(function () { slide.classList.remove("is-entering"); });
                setTimeout(function () { if (mine === seq) stage.style.minHeight = ""; }, 800);
            }).catch(function () {
                if (mine !== seq) return;
                var msg = document.createElement("p");
                msg.className = "pl-error";
                msg.textContent = "This dashboard couldn't be loaded.";
                stage.replaceChildren(msg);
                stage.style.minHeight = "";
            }).then(function () {
                if (mine !== seq) return;
                if (playing) arm(duration(index));
                prefetch(wrap(index + 1));
            });
        }
        function advance(delta, fromTimer) {
            var target = index + delta;
            if (fromTimer && !loop && target >= count) {   // the end of a non-looping run
                pause();
                remaining = 0;
                return;
            }
            go(target);
        }

        // -- input -------------------------------------------------------------
        root.addEventListener("click", function (ev) {
            if (ev.defaultPrevented || ev.button !== 0 || ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) return;
            var control = ev.target.closest("[data-pl], [data-pl-step]");
            if (control && root.contains(control)) {
                var what = control.getAttribute("data-pl");
                if (what === "prev") { ev.preventDefault(); advance(-1, false); }
                else if (what === "next") { ev.preventDefault(); advance(1, false); }
                else if (what === "toggle") { if (playing) pause(); else play(); }
                else if (what === "fullscreen") fullscreen();
                else if (control.hasAttribute("data-pl-step")) {
                    ev.preventDefault();
                    go(parseInt(control.getAttribute("data-pl-step"), 10));
                }
                return;
            }
            // Clicking into a card (a drill-down, a link) holds the slide.
            if (stage.contains(ev.target) && playing) pause();
        });

        function onKey(ev) {
            if (ev.defaultPrevented || ev.metaKey || ev.ctrlKey || ev.altKey) return;
            var t = ev.target;
            if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
            if (document.querySelector("dialog[open]")) return;
            var k = ev.key;
            if (k === "ArrowRight" || k === "PageDown") advance(1, false);
            else if (k === "ArrowLeft" || k === "PageUp") advance(-1, false);
            else if (k === "Home") go(0);
            else if (k === "End") go(count - 1);
            else if ((k === " " && !(t && t.tagName === "BUTTON")) || k === "k") { if (playing) pause(); else play(); }
            else if (k === "f") fullscreen();
            else return;
            ev.preventDefault();
        }
        (root.getAttribute("data-keys") === "page" ? document : root).addEventListener("keydown", onKey);

        function fullscreen() {
            if (document.fullscreenElement) { document.exitFullscreen(); return; }
            if (root.requestFullscreen) root.requestFullscreen().catch(function () {});
        }
        document.addEventListener("fullscreenchange", function () {
            root.classList.toggle("is-fullscreen", document.fullscreenElement === root);
        });

        document.addEventListener("visibilitychange", function () {
            if (document.hidden) { resumeOnShow = playing; pause(); }
            else if (resumeOnShow) { resumeOnShow = false; play(); }
        });

        // -- start -------------------------------------------------------------
        showPosition(index);
        prefetch(wrap(index + 1));
        if (root.getAttribute("data-play") === "1") play(); else showPlaying();
        started = true;
    }

    function init(scope) {
        (scope || document).querySelectorAll("[data-playlist]").forEach(function (root) {
            if (root.__plPlayer) return;
            root.__plPlayer = true;
            Player(root);
        });
    }

    if (window.__smallstackPlaylistJs) return;   // the include can load this file more than once
    window.__smallstackPlaylistJs = true;
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", function () { init(); });
    else init();
    document.addEventListener("htmx:afterSettle", function (ev) { init(ev.target); });
})();
