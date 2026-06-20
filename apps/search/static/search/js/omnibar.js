/* SmallStack omnibar — Ctrl+K / Cmd+K opens, debounced fetch, keyboard nav.
 *
 * Single global controller hooked onto window.__smallstackOmnibar so the
 * button onclick handlers can reach it without module gymnastics. ~150
 * lines of vanilla JS, no framework. */
(function () {
  const OMNIBAR_URL = "/smallstack/search/omnibar/";
  const DEBOUNCE_MS = 200;

  function init() {
    const overlay = document.getElementById("search-omnibar");
    const input = document.getElementById("omnibar-input");
    const results = document.getElementById("omnibar-results");
    const fullpageLink = document.getElementById("omnibar-fullpage-link");

    if (!overlay || !input || !results) return;

    let debounceTimer = null;
    let activeIndex = -1;

    function open() {
      overlay.hidden = false;
      requestAnimationFrame(() => input.focus());
    }

    function close() {
      overlay.hidden = true;
      input.value = "";
      results.innerHTML = "";
      activeIndex = -1;
    }

    function navigate(hit) {
      if (hit && hit.url) {
        window.location.href = hit.url;
      }
    }

    function renderResults(items, query) {
      activeIndex = -1;
      if (!items.length) {
        results.innerHTML = `<div class="omnibar-empty">No matches for "${escapeHtml(query)}".</div>`;
        if (fullpageLink) {
          fullpageLink.href = `/smallstack/search/?q=${encodeURIComponent(query)}`;
        }
        return;
      }
      const rows = items.map((hit, i) => `
        <a href="${hit.url || '#'}"
           class="omnibar-row"
           data-index="${i}"
           data-url="${hit.url || ''}">
          <div class="omnibar-row-main">
            <span class="omnibar-row-title">${escapeHtml(hit.display)}</span>
            <span class="omnibar-row-model">${escapeHtml(hit.model_verbose)}</span>
          </div>
          ${hit.snippet || hit.subtitle ? `
            <div class="omnibar-row-snippet">${escapeHtml(hit.snippet || hit.subtitle)}</div>
          ` : ""}
        </a>
      `).join("");
      results.innerHTML = rows;
      if (fullpageLink) {
        fullpageLink.href = `/smallstack/search/?q=${encodeURIComponent(query)}`;
      }
    }

    function setActive(index) {
      const rows = results.querySelectorAll(".omnibar-row");
      rows.forEach(r => r.classList.remove("active"));
      if (index < 0 || index >= rows.length) {
        activeIndex = -1;
        return;
      }
      activeIndex = index;
      rows[index].classList.add("active");
      rows[index].scrollIntoView({ block: "nearest" });
    }

    async function fetchResults(q) {
      if (!q) {
        results.innerHTML = "";
        return;
      }
      try {
        const resp = await fetch(`${OMNIBAR_URL}?q=${encodeURIComponent(q)}&limit=8`, {
          headers: { Accept: "application/json" },
        });
        if (!resp.ok) {
          results.innerHTML = `<div class="omnibar-empty">Search error (${resp.status}).</div>`;
          return;
        }
        const data = await resp.json();
        renderResults(data.results || [], q);
      } catch (err) {
        results.innerHTML = `<div class="omnibar-empty">Search failed: ${err.message}</div>`;
      }
    }

    input.addEventListener("input", () => {
      clearTimeout(debounceTimer);
      const q = input.value.trim();
      debounceTimer = setTimeout(() => fetchResults(q), DEBOUNCE_MS);
    });

    input.addEventListener("keydown", e => {
      const rows = results.querySelectorAll(".omnibar-row");
      if (e.key === "Escape") {
        e.preventDefault();
        close();
      } else if (e.key === "ArrowDown") {
        e.preventDefault();
        setActive(Math.min(activeIndex + 1, rows.length - 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setActive(Math.max(activeIndex - 1, -1));
      } else if (e.key === "Enter") {
        const row = rows[activeIndex];
        if (row && row.dataset.url) {
          e.preventDefault();
          window.location.href = row.dataset.url;
        }
        // Otherwise let Enter submit the implicit form (no-op here)
      }
    });

    // Click outside the modal closes.
    overlay.addEventListener("click", e => {
      if (e.target === overlay) close();
    });

    // Global keyboard shortcut.
    document.addEventListener("keydown", e => {
      const isModK = (e.ctrlKey || e.metaKey) && (e.key === "k" || e.key === "K");
      if (isModK) {
        e.preventDefault();
        if (overlay.hidden) open();
        else close();
      }
    });

    window.__smallstackOmnibar = { open, close };
  }

  function escapeHtml(s) {
    if (s == null) return "";
    return String(s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
