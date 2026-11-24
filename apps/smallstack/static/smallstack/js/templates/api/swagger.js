// Moved from apps/smallstack/templates/smallstack/api/swagger.html (inline <script>) so the CSP needs no 'unsafe-inline'.
// Server values arrive as data- attributes on this script's tag.
var swaggerConfig = document.currentScript.dataset;

// "Try it out" runs on the signed-in session unless a token was entered under
// Authorize. A write on a session must carry the CSRF token (the API checks it
// since eval 45 A-csrf), so add the csrftoken cookie's value as X-CSRFToken to
// same-origin requests that don't already carry an Authorization header.
function smallstackCsrfToken() {
    var match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
}

SwaggerUIBundle({
    url: swaggerConfig.schemaUrl,
    dom_id: "#swagger-ui",
    deepLinking: true,
    presets: [
        SwaggerUIBundle.presets.apis,
        SwaggerUIBundle.SwaggerUIStandalonePreset,
    ],
    layout: "BaseLayout",
    requestInterceptor: function (req) {
        var sameOrigin = req.url.indexOf("/") === 0 || req.url.indexOf(window.location.origin + "/") === 0;
        var hasAuth = req.headers && (req.headers.Authorization || req.headers.authorization);
        var token = smallstackCsrfToken();
        if (sameOrigin && !hasAuth && token) {
            req.headers["X-CSRFToken"] = token;
        }
        return req;
    },
});
