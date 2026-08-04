# Frontend assets

The admin UI's frontend dependencies are **vendored** into
`src/polar_flow_server/static/vendor/` and served from `/static` (issue #71).
No CDN is contacted at runtime, so a self-hosted install works offline / on a
LAN, and no third party can inject code into the admin panel.

| File | Source | Version |
|---|---|---|
| `htmx.min.js` | unpkg `htmx.org` | 2.0.4 (byte-identical to the previously SRI-pinned build) |
| `chart.umd.js` | jsdelivr `chart.js` | 4.4.0 (byte-identical to the previously SRI-pinned build) |
| `tailwind.css` | built from the templates | Tailwind 3.4.17 |

`chartjs-adapter-date-fns` was dropped entirely — no chart uses a time scale.

## Rebuilding tailwind.css

The CSS is generated statically from every class used in the templates. If you
add markup that uses a Tailwind utility class **not already present** in any
template, rebuild:

```bash
npx -y tailwindcss@3.4.17 \
  --content "src/polar_flow_server/templates/**/*.html" \
  -o src/polar_flow_server/static/vendor/tailwind.css \
  --minify
```

Notes:
- Class names must appear as complete literal strings somewhere in a template
  (including inside `<script>` blocks) — Tailwind's scanner cannot see class
  names concatenated at runtime.
- `tests/test_vendored_assets.py` asserts the built CSS covers sentinel classes
  and that no template references an external CDN for app assets.

## Upgrading htmx / Chart.js

Download the new pinned version, verify its hash against the release, and
update this table:

```bash
curl -sSL -o src/polar_flow_server/static/vendor/htmx.min.js "https://unpkg.com/htmx.org@<version>"
curl -sSL -o src/polar_flow_server/static/vendor/chart.umd.js "https://cdn.jsdelivr.net/npm/chart.js@<version>"
```
