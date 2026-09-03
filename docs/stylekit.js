/* Per-user layer styling for the grid maps.
 *
 * Canonical copy lives in docs/stylekit.js. It is viewer-agnostic and meant to
 * be copied to the gated viewer the same way permalink.js and feedback.js are
 * (one source, two viewers); as of 2026-09-03 only the public map wires it in.
 *
 * What it does: every legend row gets a small edit control. It changes the
 * colour, opacity, size (line width or circle radius) and dash of the layers
 * that row toggles, applies them live and saves them in THIS browser's
 * localStorage. Nothing leaves the machine, nothing travels in a permalink,
 * and a cleared browser profile forgets them. The map's own defaults are never
 * modified: "reset" restores them.
 *
 * Limits, stated where the reader meets them: a colour override flattens a
 * layer that colours per feature (fuel group, DC vs AC) to one colour, and the
 * editor says so on that row. Size is a multiplier on the layer's own zoom
 * stops, so it composes with the thickness slider rather than fighting it.
 *
 * How it coexists with the viewer: the viewer keeps resetting some paint
 * properties itself (line widths when the thickness slider moves, demand
 * colours when the scenario changes). The module wraps map.setPaintProperty,
 * so every write that is not its own is recorded as the new base for that
 * property, and the override is recomputed on top of it at the next apply.
 * (Comparing values instead was ambiguous: a thickness of 2x and a saved size
 * of 2x produce the same numbers, and the viewer's write went unnoticed.)
 */
(function () {
  "use strict";

  var cfg = { map: null, key: "gridmap.layerstyles.v1" };
  var saved = {};       // layer id -> {color, opacity, size, dash}
  var base = {};        // layer id -> {color, opacity, size, dash}: the viewer's own values
  var touched = {};     // layer id -> true once this module has written to it
  var writing = false;  // true while this module itself calls setPaintProperty
  var rows = [];        // {row, ids, swatch, swatchOrig}

  var PROPS = {
    line:   { color: "line-color",   opacity: "line-opacity",   size: "line-width",    dash: "line-dasharray" },
    circle: { color: "circle-color", opacity: "circle-opacity", size: "circle-radius" },
    fill:   { color: "fill-color",   opacity: "fill-opacity" },
  };
  var SIZE_DEFAULT = { line: 1, circle: 5 };
  var DASHES = { solid: null, long: [5, 1.8], dashed: [2.2, 1.6], dotted: [0.8, 1.6] };
  var DASH_LABELS = [["", "as designed"], ["solid", "solid"], ["long", "long dash"],
                     ["dashed", "short dash"], ["dotted", "dotted"]];

  // ---- persistence -------------------------------------------------------
  function load() {
    try {
      var s = JSON.parse(localStorage.getItem(cfg.key) || "null");
      saved = (s && s.layers) || {};
    } catch (e) { saved = {}; }
  }
  function store() {
    try { localStorage.setItem(cfg.key, JSON.stringify({ version: 1, layers: saved })); }
    catch (e) { /* private mode or quota: styles still apply for this page view */ }
  }

  // ---- expression helpers ------------------------------------------------
  function same(a, b) { return JSON.stringify(a) === JSON.stringify(b); }

  /** Multiply a size expression by k without moving ["zoom"] off the top level. */
  function scaleSize(expr, k) {
    if (typeof expr === "number") return expr * k;
    if (!Array.isArray(expr)) return expr;
    var op = expr[0], out, i;
    if (op === "interpolate") {
      out = expr.slice(0, 3);
      for (i = 3; i < expr.length; i += 2) { out.push(expr[i]); out.push(scaleSize(expr[i + 1], k)); }
      return out;
    }
    if (op === "step") {
      out = [expr[0], expr[1], scaleSize(expr[2], k)];
      for (i = 3; i < expr.length; i += 2) { out.push(expr[i]); out.push(scaleSize(expr[i + 1], k)); }
      return out;
    }
    if (op === "case") {
      out = ["case"];
      for (i = 1; i < expr.length - 1; i += 2) { out.push(expr[i]); out.push(scaleSize(expr[i + 1], k)); }
      out.push(scaleSize(expr[expr.length - 1], k));
      return out;
    }
    if (op === "match") {
      out = ["match", expr[1]];
      for (i = 2; i < expr.length - 1; i += 2) { out.push(expr[i]); out.push(scaleSize(expr[i + 1], k)); }
      out.push(scaleSize(expr[expr.length - 1], k));
      return out;
    }
    return ["*", k, expr];
  }

  function toHex(css) {
    if (!css) return "#888888";
    var s = String(css).trim();
    if (/^#[0-9a-f]{6}$/i.test(s)) return s.toLowerCase();
    if (/^#[0-9a-f]{3}$/i.test(s)) return ("#" + s[1] + s[1] + s[2] + s[2] + s[3] + s[3]).toLowerCase();
    var m = s.match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/i);
    if (m) return "#" + [m[1], m[2], m[3]].map(function (v) { return ("0" + (+v).toString(16)).slice(-2); }).join("");
    return "#888888";
  }

  // ---- applying ----------------------------------------------------------
  function keyFor(id, prop) {
    var layer = cfg.map.getLayer(id), P = layer && PROPS[layer.type];
    if (!P) return null;
    for (var k in P) if (P[k] === prop) return k;
    return null;
  }

  /** Wrap the map so the viewer's own paint writes become the new base. */
  function watch(map) {
    var orig = map.setPaintProperty;
    map.setPaintProperty = function (id, prop, value) {
      if (!writing) {
        var key = keyFor(id, prop);
        if (key) (base[id] || (base[id] = {}))[key] = value;
      }
      return orig.apply(map, arguments);
    };
  }

  function applyLayer(id) {
    var map = cfg.map;
    if (!map || !map.getLayer(id)) return;
    var layer = map.getLayer(id), P = PROPS[layer.type];
    if (!P) return;
    var b = base[id] || (base[id] = {});
    var s = saved[id] || {};
    writing = true;
    try {
      Object.keys(P).forEach(function (key) {
        var prop = P[key];
        // first sight of this property: whatever is there is the viewer's
        if (!(key in b)) b[key] = map.getPaintProperty(id, prop);
        var target;
        if (key === "color") target = s.color != null ? s.color : b.color;
        else if (key === "opacity") target = s.opacity != null ? s.opacity : b.opacity;
        else if (key === "size") target = s.size != null
          ? scaleSize(b.size === undefined ? SIZE_DEFAULT[layer.type] : b.size, s.size) : b.size;
        else if (key === "dash") target = s.dash ? (DASHES[s.dash] || undefined) : b.dash;
        if (!same(map.getPaintProperty(id, prop), target)) map.setPaintProperty(id, prop, target);
      });
    } finally { writing = false; }
    touched[id] = true;
  }

  function reapply() {
    if (!cfg.map) return;
    Object.keys(touched).concat(Object.keys(saved)).forEach(function (id) {
      if (cfg.map.getLayer(id)) applyLayer(id);
    });
  }

  function paintSwatch(entry) {
    if (!entry.swatch) return;
    var color = null;
    entry.ids.forEach(function (id) { if (saved[id] && saved[id].color) color = saved[id].color; });
    var sw = entry.swatch;
    if (color) {
      if (sw.classList.contains("dot") || sw.classList.contains("sq")) sw.style.background = color;
      else sw.style.borderColor = color;
    } else {
      sw.style.background = entry.swatchOrig.background;
      sw.style.borderColor = entry.swatchOrig.borderColor;
    }
  }

  // ---- editor UI ---------------------------------------------------------
  function el(tag, attrs, html) {
    var n = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    if (html != null) n.innerHTML = html;
    return n;
  }

  var uid = 0;
  function buildEditor(entry) {
    var map = cfg.map, ids = entry.ids.filter(function (id) { return map.getLayer(id); });
    var types = ids.map(function (id) { return map.getLayer(id).type; });
    var hasLine = types.indexOf("line") >= 0;
    var first = saved[ids[0]] || {};
    var n = ++uid;
    var ed = el("div", { class: "sk-ed" });
    // Current colour: the override, else the swatch the legend already shows.
    var swatchColor = entry.swatch
      ? toHex(getComputedStyle(entry.swatch).borderTopColor !== "rgba(0, 0, 0, 0)" && !entry.swatch.classList.contains("dot") && !entry.swatch.classList.contains("sq")
              ? getComputedStyle(entry.swatch).borderTopColor : getComputedStyle(entry.swatch).backgroundColor)
      : "#888888";
    var perFeature = ids.some(function (id) {
      var P = PROPS[map.getLayer(id).type]; if (!P) return false;
      return Array.isArray(map.getPaintProperty(id, P.color));
    });
    ed.innerHTML =
      '<label for="sk-c' + n + '">Colour</label><input id="sk-c' + n + '" type="color" value="' + (first.color || swatchColor) + '"><span></span>' +
      '<label for="sk-o' + n + '">Opacity</label><input id="sk-o' + n + '" type="range" min="0.05" max="1" step="0.05" value="' + (first.opacity != null ? first.opacity : 1) + '"><output>' + (first.opacity != null ? first.opacity : "–") + '</output>' +
      '<label for="sk-s' + n + '">Size</label><input id="sk-s' + n + '" type="range" min="0.3" max="3" step="0.1" value="' + (first.size != null ? first.size : 1) + '"><output>' + (first.size != null ? first.size.toFixed(1) + "×" : "1.0×") + '</output>' +
      (hasLine ? '<label for="sk-d' + n + '">Dash</label><select id="sk-d' + n + '">' +
        DASH_LABELS.map(function (d) { return '<option value="' + d[0] + '"' + ((first.dash || "") === d[0] ? " selected" : "") + '>' + d[1] + '</option>'; }).join("") +
        '</select><span></span>' : "") +
      (perFeature ? '<div class="sk-note">This layer colours each feature by its own attribute; a colour here paints them all one colour.</div>' : "") +
      '<div class="sk-note">Saved in this browser only. Line width and circle size are display settings; they never encode capacity.</div>' +
      '<button type="button" class="sk-row-reset">Reset this layer</button>';
    var cIn = ed.querySelector('#sk-c' + n), oIn = ed.querySelector('#sk-o' + n), sIn = ed.querySelector('#sk-s' + n), dIn = ed.querySelector('#sk-d' + n);
    function write(patch) {
      ids.forEach(function (id) {
        var s = saved[id] || (saved[id] = {});
        Object.keys(patch).forEach(function (k) { if (patch[k] == null) delete s[k]; else s[k] = patch[k]; });
        if (!Object.keys(s).length) delete saved[id];
        applyLayer(id);
      });
      store();
      paintSwatch(entry);
    }
    cIn.addEventListener("input", function () { write({ color: cIn.value }); });
    oIn.addEventListener("input", function () { write({ opacity: +oIn.value }); oIn.nextElementSibling.textContent = oIn.value; });
    sIn.addEventListener("input", function () { write({ size: +sIn.value }); sIn.nextElementSibling.textContent = (+sIn.value).toFixed(1) + "×"; });
    if (dIn) dIn.addEventListener("change", function () { write({ dash: dIn.value || null }); });
    ed.querySelector(".sk-row-reset").addEventListener("click", function () {
      ids.forEach(function (id) { delete saved[id]; applyLayer(id); });
      store(); paintSwatch(entry);
      cIn.value = swatchColor; oIn.value = 1; oIn.nextElementSibling.textContent = "–";
      sIn.value = 1; sIn.nextElementSibling.textContent = "1.0×"; if (dIn) dIn.value = "";
    });
    return ed;
  }

  function decorateRow(row, ids, label) {
    if (!row || !ids || !ids.length) return;
    var swatch = row.querySelector(".swatch");
    var entry = { row: row, ids: ids.slice(), swatch: swatch,
                  swatchOrig: swatch ? { background: swatch.style.background, borderColor: swatch.style.borderColor } : null };
    rows.push(entry);
    var name = label || (row.textContent || "").trim() || ids[0];
    var btn = el("button", { type: "button", class: "sk-edit", title: "Edit style (saved in this browser)",
                             "aria-label": "Edit style of " + name, "aria-expanded": "false" }, "✎");
    row.appendChild(btn);
    var ed = null;
    btn.addEventListener("click", function (e) {
      e.preventDefault();
      if (ed) { ed.remove(); ed = null; btn.setAttribute("aria-expanded", "false"); return; }
      ed = buildEditor(entry);
      row.insertAdjacentElement("afterend", ed);
      btn.setAttribute("aria-expanded", "true");
    });
    paintSwatch(entry);
  }

  function mountReset(container) {
    if (!container) return;
    var btn = el("button", { type: "button", class: "sk-reset" }, "Reset layer styles to the map's defaults");
    btn.title = "Removes the colours, opacities, sizes and dashes saved in this browser";
    btn.addEventListener("click", resetAll);
    container.appendChild(btn);
    updateReset();
    return btn;
  }
  function updateReset() {
    var b = document.querySelector(".sk-reset");
    if (b) b.hidden = !Object.keys(saved).length;
  }
  function resetAll() {
    var ids = Object.keys(saved);
    saved = {}; store();
    ids.forEach(function (id) { applyLayer(id); });
    rows.forEach(paintSwatch);
    document.querySelectorAll(".sk-ed").forEach(function (n) { n.remove(); });
    document.querySelectorAll(".sk-edit").forEach(function (b) { b.setAttribute("aria-expanded", "false"); });
    updateReset();
  }

  var css =
    ".row .sk-edit{margin-left:auto;border:0;background:none;color:var(--muted,#666);cursor:pointer;font:inherit;font-size:12px;line-height:1;padding:0 2px;opacity:.75}" +
    ".row .sk-edit:hover{opacity:1;color:var(--ink,#000)}" +
    ".sk-ed{margin:2px 0 6px 29px;padding:6px 8px;border:1px solid var(--rule,#ccc);border-radius:6px;font-size:11.5px;display:grid;grid-template-columns:auto 1fr 3em;gap:4px 8px;align-items:center;background:var(--paper,#fff)}" +
    ".sk-ed label{color:var(--muted,#666)}.sk-ed input[type=range]{width:100%;margin:0}.sk-ed input[type=color]{width:100%;height:20px;padding:0;border:1px solid var(--rule,#ccc);background:none}" +
    ".sk-ed select{font:inherit;font-size:11px}.sk-ed output{font-variant-numeric:tabular-nums;color:var(--ink,#000)}" +
    ".sk-ed .sk-note{grid-column:1/-1;color:var(--muted,#666);line-height:1.35}" +
    ".sk-ed .sk-row-reset{grid-column:1/-1;justify-self:start;font:inherit;font-size:11px;cursor:pointer}" +
    ".sk-reset{margin-top:6px;width:100%;padding:5px 8px;font:inherit;font-size:11.5px;cursor:pointer;border:1px solid var(--rule,#ccc);border-radius:6px;background:var(--paper,#fff);color:var(--ink,#000)}" +
    ".sk-reset[hidden]{display:none}";
  var style = document.createElement("style"); style.textContent = css; document.head.appendChild(style);

  window.STYLEKIT = {
    init: function (o) {
      Object.keys(o || {}).forEach(function (k) { cfg[k] = o[k]; });
      if (cfg.map) watch(cfg.map);
      load();
    },
    decorateRow: decorateRow,
    reapply: function () { reapply(); updateReset(); },
    mountReset: mountReset,
    resetAll: resetAll,
    /** Current saved overrides (read-only copy), for tests and debugging. */
    saved: function () { return JSON.parse(JSON.stringify(saved)); },
  };
})();
