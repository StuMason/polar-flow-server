"""MCP Apps extension: rendered health cards inside the conversation.

The Apps extension (io.modelcontextprotocol/ui, spec 2026-01-26) lets a tool
carry a ``ui://`` HTML resource that capable hosts (claude.ai, Claude
Desktop, VS Code, ...) render in a sandboxed iframe, pushing the tool's
result in via postMessage. Hosts without the extension just use the tool's
normal structured result - the card is progressive enhancement, never the
data channel.

The card is one self-contained HTML document (inline CSS/JS - the default
Apps sandbox CSP allows exactly that and nothing external) themed with the
host's CSS variables so it follows the client's light/dark automatically.

Claude additionally requires a ``domain`` derived from the public /mcp URL
("domain signing") - computed here from BASE_URL when configured.
"""

import hashlib

from mcp.server.apps import Apps

from polar_flow_server.core.config import settings

INSIGHTS_RESOURCE_URI = "ui://polar-flow/insights-card.html"

INSIGHTS_CARD_HTML = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Today at a glance</title>
<style>
  :root { color-scheme: light dark; }
  body {
    margin: 0;
    font-family: var(--font-sans, system-ui, -apple-system, sans-serif);
    color: var(--color-text-primary, light-dark(#111827, #f3f4f6));
    background: transparent;
  }
  .card { padding: 16px; }
  .head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
  .title { font-size: 15px; font-weight: 600; }
  .pill {
    font-size: 11px; font-weight: 600; padding: 2px 10px; border-radius: 999px;
    border: 1px solid var(--color-border-primary, light-dark(#e5e7eb, #374151));
  }
  .pill.ready { color: #059669; border-color: #05966955; }
  .pill.partial { color: #d97706; border-color: #d9770655; }
  .pill.unavailable { color: var(--color-text-secondary, #6b7280); }
  .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); gap: 8px; }
  .tile {
    border: 1px solid var(--color-border-primary, light-dark(#e5e7eb, #374151));
    border-radius: var(--border-radius-md, 10px); padding: 10px 12px;
  }
  .tile .label { font-size: 11px; color: var(--color-text-secondary, #6b7280); }
  .tile .value { font-size: 22px; font-weight: 700; line-height: 1.3; }
  .tile .value .unit { font-size: 11px; font-weight: 500; color: var(--color-text-secondary, #6b7280); }
  .tile .delta { font-size: 11px; color: var(--color-text-secondary, #6b7280); }
  .tile .delta.up { color: #059669; }
  .tile .delta.down { color: #dc2626; }
  .section { margin-top: 14px; }
  .section h3 {
    font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em;
    color: var(--color-text-secondary, #6b7280); margin: 0 0 6px;
  }
  .obs { display: flex; gap: 8px; align-items: baseline; font-size: 13px; margin-bottom: 5px; }
  .dot { width: 7px; height: 7px; border-radius: 999px; flex: none; background: #9ca3af; position: relative; top: -1px; }
  .dot.high { background: #dc2626; }
  .dot.medium { background: #d97706; }
  .sugg { font-size: 13px; margin-bottom: 5px; }
  .sugg .conf { font-size: 11px; color: var(--color-text-secondary, #6b7280); }
  .empty { font-size: 13px; color: var(--color-text-secondary, #6b7280); padding: 8px 0; }
</style>
</head>
<body>
<div class="card">
  <div class="head">
    <div class="title">Today at a glance</div>
    <div class="pill" id="status"></div>
  </div>
  <div id="content"><div class="empty">Waiting for data&hellip;</div></div>
</div>
<script>
(function () {
  "use strict";

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function fmt(value, digits) {
    if (value === null || value === undefined) return null;
    return Number(value).toFixed(digits);
  }

  function tile(label, value, unit, comparison) {
    var t = el("div", "tile");
    t.appendChild(el("div", "label", label));
    var v = el("div", "value", value === null ? "--" : value);
    if (value !== null && unit) {
      v.appendChild(document.createTextNode("\\u00a0"));
      v.appendChild(el("span", "unit", unit));
    }
    t.appendChild(v);
    if (comparison && comparison.percent_of_baseline !== null && comparison.percent_of_baseline !== undefined) {
      var pct = Math.round(comparison.percent_of_baseline - 100);
      var cls = "delta" + (pct > 2 ? " up" : pct < -2 ? " down" : "");
      var arrow = pct > 2 ? "\\u2191" : pct < -2 ? "\\u2193" : "\\u2192";
      t.appendChild(el("div", cls, arrow + " " + (pct > 0 ? "+" : "") + pct + "% vs baseline"));
    }
    return t;
  }

  function render(data) {
    var status = (data.status || "unavailable");
    var pill = document.getElementById("status");
    pill.textContent = status === "ready" ? "Ready" : status === "partial" ? "Building baselines" : "Not enough data";
    pill.className = "pill " + status;

    var content = document.getElementById("content");
    content.textContent = "";

    if (status === "unavailable") {
      content.appendChild(el("div", "empty",
        "Only " + (data.data_age_days || 0) + " days of history so far - insights unlock at 7 days."));
      notifySize();
      return;
    }

    var metrics = data.current_metrics || {};
    var baselines = data.baselines || {};
    var tiles = el("div", "tiles");
    tiles.appendChild(tile("HRV", fmt(metrics.hrv, 0), "ms", baselines.hrv_rmssd));
    tiles.appendChild(tile("Sleep score", fmt(metrics.sleep_score, 0), "", baselines.sleep_score));
    tiles.appendChild(tile("Resting HR", fmt(metrics.resting_hr, 0), "bpm", baselines.resting_hr));
    tiles.appendChild(tile("Load ratio", fmt(metrics.training_load_ratio, 2), "", baselines.training_load_ratio));
    content.appendChild(tiles);

    var observations = (data.observations || []).slice(0, 3);
    if (observations.length) {
      var section = el("div", "section");
      section.appendChild(el("h3", null, "Observations"));
      observations.forEach(function (o) {
        var row = el("div", "obs");
        row.appendChild(el("span", "dot " + (o.priority || "")));
        row.appendChild(el("span", null, o.fact + (o.context ? " (" + o.context + ")" : "")));
        section.appendChild(row);
      });
      content.appendChild(section);
    }

    var suggestions = (data.suggestions || []).slice(0, 2);
    if (suggestions.length) {
      var section2 = el("div", "section");
      section2.appendChild(el("h3", null, "Suggestions"));
      suggestions.forEach(function (s) {
        var row = el("div", "sugg");
        row.appendChild(document.createTextNode(s.description + " "));
        row.appendChild(el("span", "conf", Math.round((s.confidence || 0) * 100) + "% confidence"));
        section2.appendChild(row);
      });
      content.appendChild(section2);
    }
    notifySize();
  }

  function notifySize() {
    try {
      window.parent.postMessage({
        jsonrpc: "2.0",
        method: "ui/notifications/size-changed",
        params: { height: document.documentElement.scrollHeight }
      }, "*");
    } catch (e) { /* host may not support sizing - fine */ }
  }

  function extractPayload(container) {
    if (!container) return null;
    if (container.structuredContent) return container.structuredContent;
    if (container.structured_content) return container.structured_content;
    var text = container.content && container.content[0] && container.content[0].text;
    if (text) { try { return JSON.parse(text); } catch (e) { return null; } }
    return null;
  }

  // The MCP Apps bridge (spec 2026-01-26): the HOST WAITS for the view to
  // complete the ui/initialize handshake before it delivers any tool data.
  // A view that only listens renders forever-blank.
  var INIT_ID = 1;
  window.addEventListener("message", function (event) {
    var msg = event.data;
    if (!msg || msg.jsonrpc !== "2.0") return;

    if (msg.id === INIT_ID && msg.result) {
      // Handshake step 3: confirm readiness; host then sends tool-result
      window.parent.postMessage({ jsonrpc: "2.0", method: "ui/notifications/initialized" }, "*");
      return;
    }

    if (msg.method === "ui/notifications/tool-result" && msg.params) {
      var payload = extractPayload(msg.params);
      if (payload) render(payload);
      return;
    }

    // Lenient fallback for hosts that push a bare CallToolResult
    var legacy = extractPayload(msg.result || (msg.params && msg.params.result));
    if (legacy) render(legacy);
  });

  // Handshake step 1: announce ourselves
  window.parent.postMessage({
    jsonrpc: "2.0",
    id: INIT_ID,
    method: "ui/initialize",
    params: {
      appCapabilities: { availableDisplayModes: ["inline"] },
      clientInfo: { name: "polar-today-at-a-glance", version: "1.0.0" },
      protocolVersion: "2026-01-26"
    }
  }, "*");
})();
</script>
</body>
</html>
"""


def claude_ui_domain() -> str | None:
    """Claude's "domain signing" value for our Apps resources.

    Per Claude's cross-compatibility docs: sha256 of the public MCP URL,
    first 32 hex chars, under .claudemcpcontent.com. Only computable when
    BASE_URL is configured.
    """
    if not settings.base_url:
        return None
    public_mcp_url = f"{str(settings.base_url).rstrip('/')}/mcp"
    digest = hashlib.sha256(public_mcp_url.encode()).hexdigest()[:32]
    return f"{digest}.claudemcpcontent.com"


def build_apps_extension() -> Apps:
    """Create the Apps extension with all card resources registered.

    Tools are bound to resources in ``server.py`` (via ``apps.tool``) so
    tool registration order - the wire order - stays in one place.
    """
    apps = Apps()
    apps.add_html_resource(
        INSIGHTS_RESOURCE_URI,
        INSIGHTS_CARD_HTML,
        title="Today at a glance",
        description="Health metrics vs personal baselines, observations, suggestions",
        domain=claude_ui_domain(),
        prefers_border=True,
    )
    return apps
