/**
 * Help App JavaScript
 * Provides search, FAQ collapsibles, and TOC highlighting
 */

(function() {
    'use strict';

    // ===========================================
    // Client-side Search
    // ===========================================

    let searchIndex = null;

    async function loadSearchIndex() {
        try {
            const response = await fetch('/help/search-index.json');
            if (response.ok) {
                const data = await response.json();
                searchIndex = data.pages;
            }
        } catch (error) {
            console.error('Failed to load search index:', error);
        }
    }

    function initSearch() {
        const searchInput = document.getElementById('help-search');
        const resultsContainer = document.getElementById('help-search-results');

        if (!searchInput || !resultsContainer) return;

        // Load search index
        loadSearchIndex();

        // Debounce search input
        let debounceTimer;
        searchInput.addEventListener('input', (e) => {
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(() => {
                performSearch(e.target.value, resultsContainer);
            }, 200);
        });

        // Hide results when clicking outside
        document.addEventListener('click', (e) => {
            if (!searchInput.contains(e.target) && !resultsContainer.contains(e.target)) {
                resultsContainer.classList.remove('show');
            }
        });

        // Show results when focusing on input with existing query
        searchInput.addEventListener('focus', (e) => {
            if (e.target.value.length >= 2 && resultsContainer.innerHTML) {
                resultsContainer.classList.add('show');
            }
        });

        // Keyboard navigation
        searchInput.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                resultsContainer.classList.remove('show');
                searchInput.blur();
            }
        });
    }

    function performSearch(query, resultsContainer) {
        query = query.toLowerCase().trim();

        if (query.length < 2 || !searchIndex) {
            resultsContainer.innerHTML = '';
            resultsContainer.classList.remove('show');
            return;
        }

        const results = searchIndex.filter(page => {
            const titleMatch = page.title.toLowerCase().includes(query);
            const textMatch = page.text.toLowerCase().includes(query);
            return titleMatch || textMatch;
        }).slice(0, 6);

        if (results.length === 0) {
            resultsContainer.innerHTML = '<div class="search-no-results">No results found</div>';
        } else {
            resultsContainer.innerHTML = results.map(page => {
                // Highlight matching text in title
                const highlightedTitle = highlightMatch(page.title, query);
                return `
                    <a href="/help/${page.slug}/" class="search-result-item">
                        <strong>${highlightedTitle}</strong>
                    </a>
                `;
            }).join('');
        }
        resultsContainer.classList.add('show');
    }

    function highlightMatch(text, query) {
        const regex = new RegExp(`(${escapeRegex(query)})`, 'gi');
        return text.replace(regex, '<mark>$1</mark>');
    }

    function escapeRegex(string) {
        return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    }

    // ===========================================
    // FAQ Collapsible Sections
    // ===========================================

    function initFaqCollapsibles() {
        const faqContent = document.querySelector('.faq-content');
        if (!faqContent) return;

        const headings = faqContent.querySelectorAll('h2');

        headings.forEach(heading => {
            // Remove the permalink if present
            const permalink = heading.querySelector('.header-link');
            if (permalink) {
                permalink.remove();
            }

            heading.addEventListener('click', () => {
                // Close other open sections
                headings.forEach(h => {
                    if (h !== heading && h.classList.contains('open')) {
                        h.classList.remove('open');
                    }
                });

                // Toggle current section
                heading.classList.toggle('open');
            });
        });

        // Open first section by default
        if (headings.length > 0) {
            headings[0].classList.add('open');
        }
    }

    // ===========================================
    // Table of Contents Highlighting
    // ===========================================

    function initTocHighlight() {
        const toc = document.querySelector('.help-toc');
        const content = document.querySelector('.help-content');

        if (!toc || !content) return;

        const headings = content.querySelectorAll('h2[id], h3[id]');
        const tocLinks = toc.querySelectorAll('a');

        if (headings.length === 0 || tocLinks.length === 0) return;

        // Create intersection observer
        const observer = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    const id = entry.target.getAttribute('id');
                    updateActiveTocLink(id, tocLinks);
                }
            });
        }, {
            rootMargin: '-20% 0% -70% 0%',
            threshold: 0
        });

        headings.forEach(heading => observer.observe(heading));
    }

    function updateActiveTocLink(activeId, tocLinks) {
        tocLinks.forEach(link => {
            const href = link.getAttribute('href');
            if (href === `#${activeId}`) {
                link.classList.add('active');
            } else {
                link.classList.remove('active');
            }
        });
    }

    // ===========================================
    // Smooth Scroll for Anchor Links
    // ===========================================

    function initSmoothScroll() {
        document.querySelectorAll('a[href^="#"]').forEach(anchor => {
            anchor.addEventListener('click', function(e) {
                const targetId = this.getAttribute('href').slice(1);
                const target = document.getElementById(targetId);

                if (target) {
                    e.preventDefault();
                    const topOffset = parseInt(getComputedStyle(document.documentElement)
                        .getPropertyValue('--topbar-height')) || 56;

                    window.scrollTo({
                        top: target.offsetTop - topOffset - 20,
                        behavior: 'smooth'
                    });

                    // Update URL without scrolling
                    history.pushState(null, null, `#${targetId}`);
                }
            });
        });
    }

    // ===========================================
    // Copy Code Button
    // ===========================================

    function initCopyButtons() {
        const codeBlocks = document.querySelectorAll('.markdown-body pre');

        codeBlocks.forEach(pre => {
            const wrapper = document.createElement('div');
            wrapper.className = 'code-block-wrapper';
            wrapper.style.position = 'relative';

            pre.parentNode.insertBefore(wrapper, pre);
            wrapper.appendChild(pre);

            const button = document.createElement('button');
            button.className = 'copy-code-btn';
            button.innerHTML = `
                <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">
                    <path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/>
                </svg>
            `;
            button.title = 'Copy code';
            button.style.cssText = `
                position: absolute;
                top: 8px;
                right: 8px;
                padding: 6px;
                background: var(--card-bg);
                border: 1px solid var(--card-border);
                border-radius: 4px;
                cursor: pointer;
                opacity: 0;
                transition: opacity 0.2s;
                color: var(--text-muted);
            `;

            wrapper.appendChild(button);

            wrapper.addEventListener('mouseenter', () => {
                button.style.opacity = '1';
            });

            wrapper.addEventListener('mouseleave', () => {
                button.style.opacity = '0';
            });

            button.addEventListener('click', async () => {
                const code = pre.querySelector('code');
                const text = code ? code.textContent : pre.textContent;

                try {
                    await navigator.clipboard.writeText(text);
                    button.innerHTML = `
                        <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">
                            <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/>
                        </svg>
                    `;
                    setTimeout(() => {
                        button.innerHTML = `
                            <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">
                                <path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/>
                            </svg>
                        `;
                    }, 2000);
                } catch (err) {
                    console.error('Failed to copy:', err);
                }
            });
        });
    }

    // ===========================================
    // Initialize on DOM Ready
    // ===========================================

    document.addEventListener('DOMContentLoaded', () => {
        initSearch();
        initFaqCollapsibles();
        initTocHighlight();
        initSmoothScroll();
        initCopyButtons();
    });

})();
