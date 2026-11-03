// Moved from apps/smallstack/templates/smallstack/api/swagger.html (inline <script>) so the CSP needs no 'unsafe-inline'.
// Server values arrive as data- attributes on this script's tag.
var swaggerConfig = document.currentScript.dataset;

SwaggerUIBundle({
    url: swaggerConfig.schemaUrl,
    dom_id: "#swagger-ui",
    deepLinking: true,
    presets: [
        SwaggerUIBundle.presets.apis,
        SwaggerUIBundle.SwaggerUIStandalonePreset,
    ],
    layout: "BaseLayout",
});
