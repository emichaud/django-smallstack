(function () {
    "use strict";

    var slides = document.querySelectorAll(".slide");
    var total = slides.length;
    if (total === 0) return;

    var titles = window.SLIDE_TITLES || [];
    var current = 0;

    var progressBar = document.getElementById("slides-progress-bar");
    var counter = document.getElementById("slides-counter");
    var prevBtn = document.getElementById("slides-prev");
    var nextBtn = document.getElementById("slides-next");
    var prevTitle = document.getElementById("slides-prev-title");
    var nextTitle = document.getElementById("slides-next-title");

    function getInitialSlide() {
        var hash = window.location.hash;
        if (hash && hash.startsWith("#slide-")) {
            var idx = parseInt(hash.substring(7), 10);
            if (!isNaN(idx) && idx >= 0 && idx < total) {
                return idx;
            }
        }
        return 0;
    }

    function showSlide(index) {
        if (index < 0 || index >= total) return;
        slides[current].classList.remove("slide--active");
        slides[current].classList.remove("slide--enter-left");
        slides[current].classList.remove("slide--enter-right");

        var direction = index > current ? "right" : "left";
        current = index;

        slides[current].classList.add("slide--enter-" + direction);
        // Force reflow to trigger transition
        void slides[current].offsetWidth;
        slides[current].classList.add("slide--active");

        updateUI();
        window.location.hash = "slide-" + current;
    }

    function updateUI() {
        // Progress bar
        var progress = ((current + 1) / total) * 100;
        progressBar.style.width = progress + "%";

        // Counter
        counter.textContent = (current + 1) + " / " + total;

        // Prev button
        prevBtn.disabled = current === 0;
        prevTitle.textContent = current > 0 ? titles[current - 1] || "Previous" : "Previous";

        // Next button
        nextBtn.disabled = current === total - 1;
        nextTitle.textContent = current < total - 1 ? titles[current + 1] || "Next" : "Next";
    }

    prevBtn.addEventListener("click", function () {
        showSlide(current - 1);
    });

    nextBtn.addEventListener("click", function () {
        showSlide(current + 1);
    });

    document.addEventListener("keydown", function (e) {
        if (e.key === "ArrowLeft") {
            showSlide(current - 1);
        } else if (e.key === "ArrowRight") {
            showSlide(current + 1);
        }
    });

    window.addEventListener("hashchange", function () {
        var idx = getInitialSlide();
        if (idx !== current) {
            showSlide(idx);
        }
    });

    // Initialize
    current = getInitialSlide();
    slides.forEach(function (s) { s.classList.remove("slide--active"); });
    slides[current].classList.add("slide--active");
    updateUI();
})();
