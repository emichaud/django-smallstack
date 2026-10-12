/* Markdown editor enhancement for the blog console.
 *
 * Attaches to any `textarea.blog-markdown-input` and adds a toolbar, a live
 * preview pane and a font-size control. Deliberately *additive*: the
 * framework's generated form markup is untouched, so field validation, CSRF,
 * error rendering and the messages framework all keep working, and an upstream
 * change to object_form.html flows straight through.
 *
 * The preview is fetched from the server (blog_post_preview), which calls the
 * SAME render_markdown the service stores. A client-side markdown renderer
 * would be faster and would eventually disagree with what gets published —
 * which is the one thing a preview must never do.
 */
(function () {
    "use strict";

    var FONT_SIZES = ["0.75rem", "0.85rem", "0.95rem", "1.05rem"];
    var STORE_KEY = "smallstack.blog.editorFontSize";

    function csrfToken(form) {
        var input = form && form.querySelector('input[name="csrfmiddlewaretoken"]');
        return input ? input.value : "";
    }

    function readStoredSize() {
        // localStorage throws in a private window with site data blocked.
        try {
            var raw = window.localStorage.getItem(STORE_KEY);
            var n = parseInt(raw, 10);
            return isNaN(n) ? 1 : Math.min(Math.max(n, 0), FONT_SIZES.length - 1);
        } catch (e) {
            return 1;
        }
    }

    function writeStoredSize(index) {
        try {
            window.localStorage.setItem(STORE_KEY, String(index));
        } catch (e) {
            /* per-viewer convenience only — never load-bearing */
        }
    }

    function makeButton(label, title) {
        var b = document.createElement("button");
        b.type = "button";
        b.className = "blog-editor-btn";
        b.textContent = label;
        if (title) {
            b.title = title;
            b.setAttribute("aria-label", title);
        }
        return b;
    }

    function enhance(textarea) {
        if (textarea.dataset.blogEnhanced === "1") { return; }
        textarea.dataset.blogEnhanced = "1";

        var form = textarea.closest("form");
        var previewUrl = textarea.dataset.previewUrl || "";

        var split = document.createElement("div");
        split.className = "blog-editor-split";
        var editorPane = document.createElement("div");
        editorPane.className = "blog-editor-pane";
        var previewPane = document.createElement("div");
        previewPane.className = "blog-preview-pane";
        previewPane.innerHTML =
            '<p class="blog-preview-label">Preview</p>' +
            '<div class="blog-article"><p class="blog-preview-empty">Loading…</p></div>';
        previewPane.setAttribute("aria-live", "polite");

        var toolbar = document.createElement("div");
        toolbar.className = "blog-editor-toolbar";

        var previewBtn = makeButton("Preview", "Toggle the rendered preview");
        previewBtn.setAttribute("aria-pressed", "false");
        toolbar.appendChild(previewBtn);

        var spacer = document.createElement("span");
        spacer.className = "blog-editor-spacer";
        toolbar.appendChild(spacer);

        var hint = document.createElement("span");
        hint.className = "blog-editor-hint";
        hint.textContent = "Markdown. Raw HTML is shown as text, not rendered.";
        toolbar.appendChild(hint);

        var sizeIndex = readStoredSize();
        function applySize() {
            textarea.style.setProperty("--blog-editor-font-size", FONT_SIZES[sizeIndex]);
            textarea.style.fontSize = FONT_SIZES[sizeIndex];
        }
        var smaller = makeButton("A−", "Smaller editor text");
        var bigger = makeButton("A+", "Larger editor text");
        smaller.addEventListener("click", function () {
            sizeIndex = Math.max(0, sizeIndex - 1);
            applySize();
            writeStoredSize(sizeIndex);
        });
        bigger.addEventListener("click", function () {
            sizeIndex = Math.min(FONT_SIZES.length - 1, sizeIndex + 1);
            applySize();
            writeStoredSize(sizeIndex);
        });
        toolbar.appendChild(smaller);
        toolbar.appendChild(bigger);
        applySize();

        // Re-parent the textarea into the split layout.
        textarea.parentNode.insertBefore(toolbar, textarea);
        textarea.parentNode.insertBefore(split, textarea);
        split.appendChild(editorPane);
        split.appendChild(previewPane);
        editorPane.appendChild(textarea);

        var pending = null;
        var inFlight = false;

        function refreshPreview() {
            if (!previewUrl || !split.classList.contains("is-previewing")) { return; }
            if (inFlight) { return; }
            inFlight = true;

            var body = new FormData();
            body.append("body_markdown", textarea.value);
            body.append("csrfmiddlewaretoken", csrfToken(form));

            fetch(previewUrl, {
                method: "POST",
                body: body,
                credentials: "same-origin",
                headers: { "X-Requested-With": "XMLHttpRequest" }
            })
                .then(function (r) { return r.ok ? r.text() : null; })
                .then(function (html) {
                    if (html !== null) {
                        var label = '<p class="blog-preview-label">Preview</p>';
                        previewPane.innerHTML = label + html;
                    }
                })
                .catch(function () {
                    /* A failed preview must never block writing or saving. */
                })
                .then(function () { inFlight = false; });
        }

        function schedule() {
            if (pending) { window.clearTimeout(pending); }
            pending = window.setTimeout(refreshPreview, 400);
        }

        previewBtn.addEventListener("click", function () {
            var on = split.classList.toggle("is-previewing");
            previewBtn.setAttribute("aria-pressed", on ? "true" : "false");
            if (on) { refreshPreview(); }
        });

        textarea.addEventListener("input", schedule);
    }

    function init() {
        document.querySelectorAll("textarea.blog-markdown-input").forEach(enhance);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
