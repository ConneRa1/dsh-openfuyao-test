# Embed the official Console behind Nginx and automate only Bootstrap

**Status:** accepted (2026-10-19)

The quick start has three stages: Bootstrap, create a Business Cluster from Console, and install an Application from the application market. The current PolyMind branch tries to iframe the Console directly, but the Console sends `X-Frame-Options: DENY` and `frame-ancestors 'none'`, uses OAuth cookies and a self-signed certificate, and lives on a host-private address. We therefore automate only Bootstrap, keep the Manual Stages in the official Console, and embed that Console through an Nginx reverse proxy that strips the frame headers and adapts cookies and TLS.

**Considered options:**

- **Direct iframe**: rejected; the Console explicitly forbids it and OAuth/TLS/network make it unworkable.
- **Native panel over openFuyao APIs**: viable and avoids the proxy, but requires reimplementing cluster creation, node validation, cluster logs, application-market repositories, and Helm releases, plus Console auth. Too large for the first MVP.
- **Node gateway**: viable fallback, but Nginx is already part of the installer and handles WebSocket/TLS/header control with less new code.
- **Automate all three stages**: rejected for the first MVP; the Manual Stages exercise the official Console and avoid storing node SSH credentials and chart configuration in PolyMind.

**Consequences:**

- Nginx gains a second server block on port 3002, and its template must generate the frontend origin for CSP.
- The proxy is the security boundary; for the MVP it is restricted by network/firewall rather than a ticket.
- Stage 2/3 completion is user-confirmed, not machine-observed; the panel must not claim they are automated.
- The target host must be 8C/16G and clean, with openEuler 26.09 validated against the 22.03 quick-start baseline.
- Phase 2 can replace the Nginx path with a native panel and openFuyao APIs without changing the Environment model.
