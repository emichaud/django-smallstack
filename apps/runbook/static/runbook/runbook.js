/* Runbook app JavaScript */

document.addEventListener("DOMContentLoaded", function () {
    // ── Slide Navigation ────────────────────────────────────────
    var deck = document.getElementById("slideDeck");
    if (deck) {
        var slides = deck.querySelectorAll(".slide-card");
        var prev = document.getElementById("prevSlide");
        var next = document.getElementById("nextSlide");
        var counter = document.getElementById("slideCounter");
        var progress = document.getElementById("slideProgress");
        var current = 0;

        function showSlide(idx) {
            if (idx < 0 || idx >= slides.length) return;
            slides[current].classList.remove("active");
            current = idx;
            slides[current].classList.add("active");
            prev.disabled = current === 0;
            next.disabled = current === slides.length - 1;
            counter.textContent = (current + 1) + " / " + slides.length;
            progress.style.width = ((current + 1) / slides.length * 100) + "%";
        }

        prev.addEventListener("click", function () { showSlide(current - 1); });
        next.addEventListener("click", function () { showSlide(current + 1); });

        // Keyboard navigation
        document.addEventListener("keydown", function (e) {
            if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
                e.preventDefault();
                showSlide(current - 1);
            } else if (e.key === "ArrowRight" || e.key === "ArrowDown" || e.key === " ") {
                e.preventDefault();
                showSlide(current + 1);
            }
        });

        // Initialize progress
        showSlide(0);
    }

    // ── Step smooth scroll ──────────────────────────────────────
    var stepLinks = document.querySelectorAll('a[href^="#step-"]');
    stepLinks.forEach(function (link) {
        link.addEventListener("click", function (e) {
            e.preventDefault();
            var target = document.querySelector(this.getAttribute("href"));
            if (target) {
                target.scrollIntoView({ behavior: "smooth", block: "start" });
            }
        });
    });
});
