/* Shareable map links: put the view in the URL hash and restore it on load.
 *
 * Canonical copy lives in docs/permalink.js and is copied to the gated repo,
 * the same way assumptions.json and feedback.js are.
 *
 * Why it exists: a feedback report that says "centre 59.6, 8.5, zoom 8, NT+
 * 2040 planned" makes the reader do the reconstruction by hand. A link does it
 * for them, and it makes any figure in a post or an email checkable at source.
 *
 * How it applies state: it does NOT reimplement either viewer's rendering. It
 * sets the viewer's own controls and dispatches the events the viewer already
 * listens for, so the viewer's handlers update state and re-render exactly as
 * if a person had clicked. One code path, so a permalink can never diverge
 * from what the controls do.
 */
(function () {
  "use strict";

  var cfg = { map: null, controls: {}, state: null, onFeature: null };
  var ready = false;

  function readHash() {
    var h = (location.hash || "").replace(/^#/, "");
    var out = {};
    if (!h) return out;
    h.split("&").forEach(function (pair) {
      var i = pair.indexOf("=");
      if (i < 0) return;
      out[decodeURIComponent(pair.slice(0, i))] = decodeURIComponent(pair.slice(i + 1));
    });
    return out;
  }

  /** Current view as hash parameters. */
  function params(extra) {
    var p = {};
    var m = cfg.map;
    Object.keys(cfg.controls).forEach(function (k) {
      var v = cfg.state ? cfg.state[k] : undefined;
      if (v !== undefined && v !== null && v !== "") p[k] = v;
    });
    if (m) {
      var c = m.getCenter();
      p.lat = c.lat.toFixed(4);
      p.lon = c.lng.toFixed(4);
      p.z = m.getZoom().toFixed(2);
    }
    Object.keys(extra || {}).forEach(function (k) {
      if (extra[k] !== undefined && extra[k] !== null && extra[k] !== "") p[k] = extra[k];
    });
    return p;
  }

  function toHash(p) {
    return "#" + Object.keys(p).map(function (k) {
      return encodeURIComponent(k) + "=" + encodeURIComponent(p[k]);
    }).join("&");
  }

  var pending = null;
  function write() {
    if (!ready) return;                 // never overwrite an incoming link
    if (pending) clearTimeout(pending);
    pending = setTimeout(function () {
      pending = null;
      try {
        // replaceState, not a hash assignment: this must not push a history
        // entry on every pan, or Back becomes unusable.
        history.replaceState(null, "", toHash(params()));
      } catch (e) { /* file:// and some embeds disallow it; harmless */ }
    }, 250);
  }

  /** Set a control to `value` and let the viewer's own handler do the work. */
  function drive(spec, value) {
    if (spec.type === "radio") {
      var r = document.querySelector(
        'input[name="' + spec.name + '"][value="' + String(value).replace(/"/g, "") + '"]');
      if (!r || r.checked) return;
      r.checked = true;
      r.dispatchEvent(new Event("change", { bubbles: true }));
    } else if (spec.type === "range") {
      var s = document.getElementById(spec.id);
      if (!s || String(s.value) === String(value)) return;
      s.value = value;
      s.dispatchEvent(new Event("input", { bubbles: true }));
    }
  }

  function apply(p) {
    Object.keys(cfg.controls).forEach(function (k) {
      if (p[k] !== undefined) drive(cfg.controls[k], p[k]);
    });
    var lat = parseFloat(p.lat), lon = parseFloat(p.lon), z = parseFloat(p.z);
    if (cfg.map && isFinite(lat) && isFinite(lon) && isFinite(z)) {
      cfg.map.jumpTo({ center: [lon, lat], zoom: z });
    }
    if (p.f && cfg.onFeature) {
      try { cfg.onFeature(p.f); } catch (e) { /* focusing is best-effort */ }
    }
  }

  window.PERMALINK = {
    init: function (o) {
      Object.keys(o || {}).forEach(function (k) { cfg[k] = o[k]; });
      var incoming = readHash();
      if (Object.keys(incoming).length) apply(incoming);
      ready = true;
      if (cfg.map) {
        cfg.map.on("moveend", write);
        cfg.map.on("zoomend", write);
      }
      // Someone pasting a link into an already-open tab changes only the hash,
      // which does not reload the page. Apply it rather than doing nothing.
      window.addEventListener("hashchange", function () {
        var p = readHash();
        if (Object.keys(p).length) apply(p);
      });
      // Panel controls: one delegated listener rather than editing every
      // handler in the viewer.
      document.addEventListener("change", write, true);
      document.addEventListener("input", write, true);
      write();
    },
    /** Absolute URL for the current view; pass {f: fid, lat, lon} to override. */
    url: function (extra) {
      return location.origin + location.pathname + location.search + toHash(params(extra));
    },
  };
})();
