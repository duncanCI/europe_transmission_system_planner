/* In-map feedback: let a reader flag a branch, an assumption or a view.
 *
 * Canonical copy lives in docs/feedback.js and is copied to the gated repo,
 * the same way assumptions.json is - one source, two viewers, no drift.
 *
 * There is no backend. Both maps are static files, so feedback cannot be
 * POSTed anywhere; instead this builds a structured payload and hands it to a
 * channel the reader already has. The context matters more than the channel:
 * "this line looks wrong" is unactionable, "fid way/12345, NT+ 2040 planned,
 * headroom 2.1 GW, build 130962340a" is a bug report.
 *
 * NON-OPEN DATA. The gated map carries the ENTSO-E TYNDP portfolio and the RTE
 * SDDR works, which are NOT open data. A payload naming those schemes must
 * never be routed to a public issue tracker, so `github` is left unset there
 * and only the private channels are offered. Do not add a GitHub target to the
 * gated viewer.
 */
(function () {
  "use strict";

  var cfg = {
    viewer: "map",       // label shown in the payload
    github: null,        // {owner, repo} - PUBLIC viewer only, see above
    // Address as ["user", "domain"], joined only when someone clicks Email.
    // A plain "user@domain" string in the page source is harvested by the
    // crawlers that trawl for mailto: targets, and the public map is meant to
    // be shared widely. Splitting it keeps the channel without leaving the
    // address sitting in the HTML.
    //
    // This defeats scrapers that read markup, NOT one that executes the page's
    // JavaScript. It lowers the volume; it is not a guarantee.
    email: null,
    getContext: null,    // () => ({...}) supplied by the viewer
  };

  function emailAddress() {
    if (!cfg.email) return null;
    return Array.isArray(cfg.email) ? cfg.email.join("@") : cfg.email;
  }

  var CATEGORIES = [
    ["data", "Something is wrong in the data"],
    ["missing", "A scheme or asset is missing"],
    ["method", "I disagree with the method or an assumption"],
    ["interpret", "This is being read the wrong way"],
    ["suggest", "Suggestion or feature request"],
    ["question", "Question"],
  ];

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function el(tag, attrs, html) {
    var n = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    if (html != null) n.innerHTML = html;
    return n;
  }

  var scope = { kind: "view", id: null, label: null };

  var CSS = [
    "#fbwrap[hidden]{display:none}",
    "#fbwrap{position:fixed;inset:0;background:rgba(15,23,42,.55);z-index:20;",
    "  display:flex;align-items:center;justify-content:center}",
    "#fb{background:#fff;width:min(560px,92vw);max-height:88vh;overflow:auto;",
    "  border-radius:6px;padding:18px 22px;box-shadow:0 10px 40px rgba(0,0,0,.3);",
    "  font:13px/1.45 system-ui,-apple-system,'Segoe UI',sans-serif;color:#0f172a}",
    "#fb h2{margin:0 0 4px;font-size:15px}",
    "#fbclose{float:right;border:0;background:none;font-size:20px;cursor:pointer;",
    "  color:#64748b;line-height:1}",
    "#fb .fbnote{color:#64748b;font-size:12px;margin:0 0 10px}",
    "#fb .fbl{display:block;font-weight:600;font-size:12px;margin:10px 0 3px}",
    "#fb select,#fb textarea,#fb input[type=text]{width:100%;font:inherit;padding:6px 8px;",
    "  border:1px solid #cbd5e1;border-radius:4px;background:#fff;box-sizing:border-box}",
    "#fb textarea{resize:vertical}",
    "#fb .fbctx{margin:12px 0 0;padding:8px 10px;background:#f1f5f9;border-radius:4px;",
    "  font-size:11px;color:#334155;word-break:break-word}",
    "#fb .fbrow{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}",
    "#fb .fbrow button{font:inherit;font-size:12px;padding:7px 12px;cursor:pointer;",
    "  border:1px solid #cbd5e1;border-radius:4px;background:#f8fafc}",
    "#fb .fbrow button:hover{background:#eef2f7}",
    "#fb .fbrow button.fbprimary{background:#1d4ed8;color:#fff;border-color:#1d4ed8}",
    "#fb .fbrow button.fbprimary:hover{background:#1e40af}",
    "a.fbflag,a.fbasm{color:#1d4ed8;cursor:pointer;font-size:11px}",
    "#fbbtn{margin-top:6px;width:100%;padding:6px 8px;font:inherit;font-size:12px;",
    "  cursor:pointer;border:1px solid #cbd5e1;border-radius:4px;background:#f8fafc}",
    "#fbbtn:hover{background:#eef2f7}",
  ].join("");

  // Styles go in at load, not on first open: the panel button is rendered
  // immediately and would otherwise sit unstyled until someone clicked it.
  function ensureCss() {
    if (document.getElementById("fbcss")) return;
    var st = el("style", { id: "fbcss" }, CSS);
    (document.head || document.documentElement).appendChild(st);
  }

  function ensureDom() {
    ensureCss();
    if (document.getElementById("fbwrap")) return;
    var wrap = el("div", { id: "fbwrap", hidden: "hidden" });
    wrap.innerHTML =
      '<div id="fb" role="dialog" aria-modal="true" aria-labelledby="fbtitle">' +
      '<button id="fbclose" type="button" aria-label="Close">&times;</button>' +
      '<h2 id="fbtitle">Send feedback</h2>' +
      '<p class="fbnote" id="fbscope"></p>' +
      '<label class="fbl" for="fbcat">What kind of feedback?</label>' +
      '<select id="fbcat">' +
      CATEGORIES.map(function (c) {
        return '<option value="' + c[0] + '">' + esc(c[1]) + "</option>";
      }).join("") +
      "</select>" +
      '<label class="fbl" for="fbtext">What did you notice?</label>' +
      '<textarea id="fbtext" rows="5" placeholder="Be as specific as you can. If a value looks wrong, say what you would expect and why."></textarea>' +
      '<label class="fbl" for="fbwho">Your name and organisation (optional)</label>' +
      '<input id="fbwho" type="text" autocomplete="organization" placeholder="e.g. A. Planner, National Grid">' +
      '<div class="fbctx"><b>Attached automatically:</b> <span id="fbctxtext"></span></div>' +
      '<div class="fbrow" id="fbactions"></div>' +
      '<p class="fbnote" id="fbstatus" aria-live="polite"></p>' +
      "</div>";
    document.body.appendChild(wrap);

    wrap.addEventListener("click", function (e) { if (e.target === wrap) close(); });
    document.getElementById("fbclose").addEventListener("click", close);
    document.addEventListener("keydown", function (e) {
      if (wrap.hidden) return;
      if (e.key === "Escape") {
        // Claim the key so a modal underneath (the assumptions register, which
        // this can be opened from) does not close at the same time.
        e.stopPropagation();
        e.preventDefault();
        close();
        return;
      }
      if (e.key === "Tab") trapFocus(e);
    }, true);
  }

  /** aria-modal is asserted, so Tab must actually stay inside the dialog. */
  function trapFocus(e) {
    var box = document.getElementById("fb");
    var items = box.querySelectorAll(
      "button, select, textarea, input, a[href]");
    if (!items.length) return;
    var first = items[0], last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault(); last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault(); first.focus();
    }
  }

  var returnFocusTo = null;

  function close() {
    var w = document.getElementById("fbwrap");
    if (w) w.hidden = true;
    if (returnFocusTo && returnFocusTo.focus) {
      try { returnFocusTo.focus(); } catch (e) { /* element may be gone */ }
    }
    returnFocusTo = null;
  }

  function context() {
    var c = {};
    try { c = (cfg.getContext && cfg.getContext()) || {}; } catch (e) { c = {}; }
    c.viewer = cfg.viewer;
    return c;
  }

  /** A link back to exactly what the reader was looking at. */
  function permalink() {
    if (!window.PERMALINK) return null;
    var extra = {};
    if (scope.kind === "feature" && scope.id) {
      extra.f = scope.id;
      // Centre on the branch they clicked, not on wherever the map happened to
      // be pointing - otherwise the link can open with the branch off-screen.
      if (scope.lat && scope.lon) { extra.lat = scope.lat; extra.lon = scope.lon; }
    }
    try { return PERMALINK.url(extra); } catch (e) { return null; }
  }

  function contextLines() {
    var c = context();
    var rows = [];
    if (scope.kind === "feature") {
      rows.push(["about", (scope.what || "feature") + " " + (scope.label || scope.id)]);
    } else if (scope.kind === "assumption") {
      rows.push(["about", "assumption " + scope.id]);
    } else {
      rows.push(["about", "the map as a whole"]);
    }
    if (scope.id && scope.kind === "feature") rows.push(["feature id", scope.id]);
    var link = permalink();
    if (link) rows.push(["open this exact view", link]);
    Object.keys(c).forEach(function (k) {
      if (c[k] !== undefined && c[k] !== null && c[k] !== "") rows.push([k, c[k]]);
    });
    return rows;
  }

  function payload() {
    var lines = contextLines().map(function (r) { return "- " + r[0] + ": " + r[1]; });
    var cat = document.getElementById("fbcat");
    var text = document.getElementById("fbtext").value.trim();
    var who = document.getElementById("fbwho").value.trim();
    var label = CATEGORIES.reduce(function (a, c) { return c[0] === cat.value ? c[1] : a; }, cat.value);
    return (
      text + "\n\n" +
      (who ? "From: " + who + "\n\n" : "") +
      "Category: " + label + "\n" +
      "Context (captured by the map, not typed):\n" +
      lines.join("\n") + "\n"
    );
  }

  function title() {
    var cat = document.getElementById("fbcat").value;
    var c = context();
    var what;
    if (scope.kind === "feature") {
      what = (scope.what || "feature") + " " + (scope.label || scope.id) +
        (scope.id && scope.label ? " (" + scope.id + ")" : "");
    } else if (scope.kind === "assumption") {
      what = "assumption " + scope.id;
    } else {
      // A view-scoped report titled just "map" is indistinguishable from every
      // other one in an issue list, so name where the reader was standing.
      what = "map at " + (c.centre || "?") + (c.zoom ? " z" + c.zoom : "");
    }
    return "[" + cat + "] " + String(what).slice(0, 80);
  }

  function status(msg) { document.getElementById("fbstatus").textContent = msg; }

  function actions() {
    var box = document.getElementById("fbactions");
    box.innerHTML = "";
    var text = document.getElementById("fbtext");

    function guard(fn) {
      return function () {
        if (!text.value.trim()) { status("Add a note first - the context alone does not say what is wrong."); text.focus(); return; }
        fn();
      };
    }

    if (cfg.github) {
      var gh = el("button", { type: "button", class: "fbprimary" }, "Open a GitHub issue");
      gh.addEventListener("click", guard(function () {
        var url = "https://github.com/" + cfg.github.owner + "/" + cfg.github.repo +
          "/issues/new?title=" + encodeURIComponent(title()) +
          "&body=" + encodeURIComponent(payload());
        if (url.length > 7500) { status("Too long for a prefilled issue - use Copy instead and paste it in."); return; }
        window.open(url, "_blank", "noopener");
        status("A GitHub issue was opened in a new tab. It is not submitted until you press Submit there.");
      }));
      box.appendChild(gh);
    }

    var copy = el("button", { type: "button" }, "Copy to clipboard");
    copy.addEventListener("click", guard(function () {
      var body = title() + "\n\n" + payload();
      function fallback() {
        var ta = el("textarea");
        ta.value = body;
        ta.style.position = "fixed";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.select();
        var ok = false;
        try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
        status(ok ? "Copied. Paste it wherever suits you."
                  : "Could not copy automatically - use Email, or select and copy the report by hand.");
        document.body.removeChild(ta);
      }
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(body).then(
          function () { status("Copied. Paste it wherever suits you."); }, fallback);
      } else { fallback(); }
    }));
    box.appendChild(copy);

    if (emailAddress()) {
      var mail = el("button", { type: "button" }, "Email it");
      mail.addEventListener("click", guard(function () {
        var href = "mailto:" + emailAddress() +
          "?subject=" + encodeURIComponent(title()) +
          "&body=" + encodeURIComponent(payload());
        if (href.length > 1900) { status("Too long for an email link - use Copy instead."); return; }
        window.location.href = href;
        status("Your mail client should have opened with the report filled in.");
      }));
      box.appendChild(mail);
    }
  }

  function scopeKey(s) {
    return [s.kind, s.id, s.what].join("|");
  }

  function open(next) {
    ensureDom();
    var previous = scope;
    scope = next || { kind: "view" };
    returnFocusTo = document.activeElement;

    // A note typed about one feature must never be filed against another.
    // Clear the draft whenever the subject changes; keep it when the same
    // subject is reopened, so an accidental close does not lose the text.
    if (scopeKey(previous) !== scopeKey(scope)) {
      document.getElementById("fbtext").value = "";
      document.getElementById("fbcat").selectedIndex = 0;
    }

    var subject = scope.what || "feature";
    var lbl = scope.kind === "feature"
      ? "You are commenting on the " + subject + " “" + (scope.label || scope.id) + "”."
      : scope.kind === "assumption"
        ? "You are commenting on an assumption the model makes."
        : "You are commenting on the map as a whole.";
    document.getElementById("fbscope").textContent = lbl +
      " Nothing is sent until you choose how to send it.";
    document.getElementById("fbctxtext").textContent =
      contextLines().map(function (r) { return r[0] + " " + r[1]; }).join(" · ");
    document.getElementById("fbstatus").textContent = "";
    actions();
    document.getElementById("fbwrap").hidden = false;
    document.getElementById("fbtext").focus();
  }

  window.FEEDBACK = {
    configure: function (o) { Object.keys(o || {}).forEach(function (k) { cfg[k] = o[k]; }); },
    open: open,
    /** Escaped HTML for a "flag this" control inside a popup.
     *  `lngLat` is the click point, so the permalink centres on what was
     *  clicked. `what` names the kind of thing ("branch", "substation",
     *  "power plant") - every popup used to say "branch", so a report about a
     *  substation arrived labelled as a branch. */
    popupLink: function (fid, label, lngLat, what) {
      var pos = "";
      if (lngLat && isFinite(lngLat.lat) && isFinite(lngLat.lng)) {
        pos = ' data-lat="' + lngLat.lat.toFixed(4) + '" data-lon="' + lngLat.lng.toFixed(4) + '"';
      }
      return '<a href="#" class="fbflag" data-fid="' + esc(fid) +
        '" data-label="' + esc(label || fid) + '" data-what="' + esc(what || "feature") +
        '"' + pos + '>Flag this ' + esc(what || "feature") + '</a>';
    },
  };

  // One delegated listener covers popups and assumption entries, both of which
  // are rendered after this script runs.
  document.addEventListener("click", function (e) {
    var a = e.target.closest && e.target.closest(".fbflag");
    if (a) {
      e.preventDefault();
      open({
        kind: "feature",
        id: a.getAttribute("data-fid"),
        label: a.getAttribute("data-label"),
        what: a.getAttribute("data-what") || "feature",
        lat: a.getAttribute("data-lat"),
        lon: a.getAttribute("data-lon"),
      });
      return;
    }
    var b = e.target.closest && e.target.closest(".fbasm");
    if (b) {
      e.preventDefault();
      open({ kind: "assumption", id: b.getAttribute("data-asm") });
    }
  });
})();
