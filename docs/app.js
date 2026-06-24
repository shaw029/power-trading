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

  // Resolve the most recent settled date: latest.json's own date, else the last
  // entry in the manifest's available_dates.
  function pickLatestDate(latest, manifest) {
    if (latest && latest.date) {
      return latest.date;
    }
    if (manifest && Array.isArray(manifest.available_dates) && manifest.available_dates.length) {
      return manifest.available_dates[manifest.available_dates.length - 1];
    }
    return null;
  }

  // The durations to expose, preferring the manifest's ordering and falling back
  // to whatever keys the day artifact / latest.json happen to carry.
  function pickDurations(manifest, day, latest) {
    if (manifest && Array.isArray(manifest.durations) && manifest.durations.length) {
      return manifest.durations;
    }
    if (day && day.assets) {
      return Object.keys(day.assets);
    }
    if (latest && latest.cumulative_net_pnl) {
      return Object.keys(latest.cumulative_net_pnl);
    }
    return [];
  }

  // Render the day's labels (e.g. "windy", "volatile") as simple tags.
  function renderLabels(container, labels) {
    if (!container) {
      return;
    }
    container.textContent = "";
    if (!Array.isArray(labels) || !labels.length) {
      return;
    }
    labels.forEach(function (label) {
      var tag = document.createElement("span");
      tag.className = "tag";
      tag.textContent = label;
      container.appendChild(tag);
    });
  }

  function kpiTile(label, valueText, valueClass) {
    var card = document.createElement("div");
    card.className = "kpi-card";

    var heading = document.createElement("h3");
    heading.textContent = label;
    card.appendChild(heading);

    var value = document.createElement("div");
    value.className = "kpi-value" + (valueClass ? " " + valueClass : "");
    value.textContent = valueText;
    card.appendChild(value);

    return card;
  }

  // KPI tiles for one duration: net PnL, cycles and capture, sourced from the
  // day artifact, with net PnL falling back to latest.json's cumulative figure
  // when the per-day artifact is unavailable.
  function renderKpis(grid, day, latest, duration) {
    if (!grid) {
      return;
    }
    grid.textContent = "";

    var asset = day && day.assets && day.assets[duration] ? day.assets[duration] : null;
    var metrics = asset && asset.metrics ? asset.metrics : {};
    var netPnl = asset && asset.pnl && typeof asset.pnl.net_pnl === "number"
      ? asset.pnl.net_pnl
      : (latest && latest.cumulative_net_pnl ? latest.cumulative_net_pnl[duration] : undefined);

    var pnlClass = typeof netPnl === "number" ? (netPnl < 0 ? "neg" : "pos") : "";
    grid.appendChild(kpiTile("Net PnL", formatGbp(netPnl), pnlClass));
    grid.appendChild(kpiTile("Cycles", formatNumber(metrics.cycles)));
    grid.appendChild(kpiTile("Capture", formatNumber(metrics.capture)));
  }

  // The dispatch / waterfall figures are exported for a single default duration,
  // so they stay fixed; only the KPI tiles react to the duration selector.
  function renderDurationSelector(container, durations, current, onSelect) {
    if (!container) {
      return;
    }
    container.textContent = "";
    durations.forEach(function (duration) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "duration-btn" + (duration === current ? " active" : "");
      btn.textContent = duration;
      btn.setAttribute("data-duration", duration);
      btn.addEventListener("click", function () {
        var siblings = container.querySelectorAll(".duration-btn");
        Array.prototype.forEach.call(siblings, function (b) {
          b.classList.toggle("active", b === btn);
        });
        onSelect(duration);
      });
      container.appendChild(btn);
    });
  }

  // Build the Latest view: labels, duration selector, KPI tiles, and the two
  // reused figures for the most recent settled day.
  function renderLatest(latest, manifest, day) {
    var date = pickLatestDate(latest, manifest);
    var dateEl = document.getElementById("latest-date");
    if (dateEl) {
      dateEl.textContent = date || "—";
    }

    renderLabels(document.getElementById("latest-labels"), day && day.labels);

    var durations = pickDurations(manifest, day, latest);
    var current = durations.length ? durations[0] : null;
    var grid = document.getElementById("latest-kpis");

    renderDurationSelector(
      document.getElementById("duration-buttons"),
      durations,
      current,
      function (duration) {
        renderKpis(grid, day, latest, duration);
      }
    );

    if (current) {
      renderKpis(grid, day, latest, current);
    }

    if (date) {
      renderFig("fig-dispatch", "data/figs/" + date + "/dispatch.json");
      renderFig("fig-waterfall", "data/figs/" + date + "/waterfall.json");
    }
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

      // The per-day artifact carries the per-duration metrics and labels; it may
      // not be present yet, in which case the KPIs fall back to latest.json.
      var date = pickLatestDate(data.latest, data.manifest);
      var dayPromise = date
        ? fetchJson("data/days/" + date + ".json")
        : Promise.resolve(null);

      dayPromise.then(function (day) {
        renderLatest(data.latest, data.manifest, day);
        showView("latest");
      });
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
