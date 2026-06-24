/*
 * Live GB BESS Benchmark — static site shell.
 *
 * Loads the committed JSON artifacts under data/ (relative paths, so the site
 * works from a GitHub Pages project subpath), renders the Latest view, and
 * routes between the nav views. History / Day-types / Methodology are
 * placeholders here and gain real content in later updates.
 */
(function () {
  "use strict";

  var VIEWS = ["latest", "history", "day-types", "methodology"];

  // ----------------------------------------------------------------------- //
  // Fetch layer
  // ----------------------------------------------------------------------- //

  // Fetch and parse a JSON artifact by relative path. Returns null (rather than
  // throwing) on any failure — a missing 404 or an empty/invalid body — so the
  // caller can fall back to the "no data yet" state.
  function fetchJson(relPath) {
    return fetch(relPath, { cache: "no-cache" })
      .then(function (resp) {
        if (!resp.ok) {
          return null;
        }
        return resp.json();
      })
      .catch(function () {
        return null;
      });
  }

  function loadData() {
    return Promise.all([
      fetchJson("data/manifest.json"),
      fetchJson("data/latest.json"),
    ]).then(function (results) {
      return { manifest: results[0], latest: results[1] };
    });
  }

  // ----------------------------------------------------------------------- //
  // Plotly figure renderer
  // ----------------------------------------------------------------------- //

  // Fetch a Plotly figure JSON file and draw it into the element with id divId.
  // The artifacts hold a full Plotly figure ({ data, layout }), so the parsed
  // object is handed straight to Plotly.newPlot. Returns a Promise.
  function renderFig(divId, figJsonUrl) {
    var div = document.getElementById(divId);
    if (!div) {
      return Promise.resolve();
    }
    return fetchJson(figJsonUrl).then(function (fig) {
      if (!fig || !fig.data) {
        div.textContent = "Figure unavailable.";
        return;
      }
      return Plotly.newPlot(div, fig.data, fig.layout || {}, { responsive: true });
    });
  }

  // ----------------------------------------------------------------------- //
  // Rendering helpers
  // ----------------------------------------------------------------------- //

  function isEmpty(value) {
    if (!value || typeof value !== "object") {
      return true;
    }
    return Object.keys(value).length === 0;
  }

  function formatGbp(value) {
    if (typeof value !== "number" || !isFinite(value)) {
      return "—";
    }
    var sign = value < 0 ? "-" : "";
    return sign + "£" + Math.abs(value).toLocaleString("en-GB", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  }

  function formatNumber(value) {
    if (typeof value !== "number" || !isFinite(value)) {
      return "—";
    }
    return value.toLocaleString("en-GB", { maximumFractionDigits: 2 });
  }

  function makeRow(label, valueText, valueClass) {
    var row = document.createElement("div");
    row.className = "kpi-row";

    var labelSpan = document.createElement("span");
    labelSpan.className = "label";
    labelSpan.textContent = label;

    var valueSpan = document.createElement("span");
    valueSpan.className = "value" + (valueClass ? " " + valueClass : "");
    valueSpan.textContent = valueText;

    row.appendChild(labelSpan);
    row.appendChild(valueSpan);
    return row;
  }

  // Build one KPI card per duration from latest.json.
  function renderLatest(latest, manifest) {
    var dateEl = document.getElementById("latest-date");
    if (dateEl) {
      dateEl.textContent = latest.date || "—";
    }

    var grid = document.getElementById("latest-kpis");
    if (!grid) {
      return;
    }
    grid.textContent = "";

    var pnl = latest.cumulative_net_pnl || {};
    var soc = latest.end_soc || {};

    // Prefer the manifest's ordering; otherwise fall back to the keys present.
    var durations = manifest && Array.isArray(manifest.durations) && manifest.durations.length
      ? manifest.durations
      : Object.keys(pnl);

    durations.forEach(function (duration) {
      var card = document.createElement("div");
      card.className = "kpi-card";

      var heading = document.createElement("h3");
      heading.textContent = duration + " battery";
      card.appendChild(heading);

      var pnlValue = pnl[duration];
      var pnlClass = typeof pnlValue === "number" && pnlValue < 0 ? "neg" : "pos";
      card.appendChild(makeRow("Cumulative net PnL", formatGbp(pnlValue), pnlClass));
      card.appendChild(makeRow("End SOC (MWh)", formatNumber(soc[duration])));

      grid.appendChild(card);
    });
  }

  // ----------------------------------------------------------------------- //
  // View routing
  // ----------------------------------------------------------------------- //

  function showView(view) {
    VIEWS.concat(["no-data"]).forEach(function (name) {
      var section = document.getElementById("view-" + name);
      if (section) {
        section.hidden = name !== view;
      }
    });

    var buttons = document.querySelectorAll(".nav-link");
    Array.prototype.forEach.call(buttons, function (button) {
      var isActive = button.getAttribute("data-view") === view;
      button.classList.toggle("active", isActive);
    });
  }

  function wireNav(hasData) {
    var buttons = document.querySelectorAll(".nav-link");
    Array.prototype.forEach.call(buttons, function (button) {
      button.addEventListener("click", function () {
        var view = button.getAttribute("data-view");
        // Without data, only the no-data notice is meaningful.
        showView(hasData ? view : "no-data");
      });
    });
  }

  // ----------------------------------------------------------------------- //
  // Boot
  // ----------------------------------------------------------------------- //

  function init() {
    loadData().then(function (data) {
      var hasLatest = data.latest && !isEmpty(data.latest.cumulative_net_pnl);
      wireNav(hasLatest);

      if (!hasLatest) {
        showView("no-data");
        return;
      }
      renderLatest(data.latest, data.manifest);
      showView("latest");
    });
  }

  // Expose renderFig for the per-day figures wired up in later updates.
  window.benchmarkSite = { renderFig: renderFig };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
