// Moved from apps/webhooks/templates/webhooks/crud/webhookendpoint_detail.html (inline <script>) so the CSP needs no 'unsafe-inline'.
// Server values arrive as data- attributes on this script's tag.
var webhookendpointDetailConfig = document.currentScript.dataset;

(function () {
    var btn = document.getElementById("wh-reveal-btn");
    if (!btn) return;
    btn.addEventListener("click", function () {
        var csrf = document.querySelector("input[name=csrfmiddlewaretoken]").value;
        fetch(webhookendpointDetailConfig.webhooksRevealSecretUrl, {
            method: "POST",
            headers: {"X-CSRFToken": csrf},
        }).then(function (r) { return r.json(); }).then(function (data) {
            if (!data.secret) return;
            document.getElementById("wh-secret-value").textContent = data.secret;
            document.getElementById("wh-secret-box").hidden = false;
        });
    });
    document.getElementById("wh-secret-copy").addEventListener("click", function () {
        navigator.clipboard.writeText(document.getElementById("wh-secret-value").textContent);
        this.textContent = "Copied";
    });
})();
