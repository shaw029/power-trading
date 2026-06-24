/*
 * Live GB BESS Benchmark — static site shell.
 *
 * Loads the committed JSON artifacts under data/ (relative paths, so the site
 * works from a GitHub Pages project subpath), renders the Latest view, and
 * routes between the nav views. History and Day-types are placeholders here
 * and gain real content in later updates.
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
      fetchJson("data/history.json"),
    ]).then(function (results) {
      return { manifest: results[0], latest: results[1], history: results[2] };
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
  // History view
  // ----------------------------------------------------------------------- //

  // Plotly reports a datetime x value as a string like "2026-06-23" or
  // "2026-06-23 00:00:00"; keep just the calendar date so it matches the day
  // artifact filenames under data/days/.
  function asDate(value) {
    return String(value).slice(0, 10);
  }

  // Build a grouped daily-PnL bar chart client-side from the history rows: one
  // group per date, one bar per duration carrying that day's net PnL.
  function dailyPnlFigure(rows, durations) {
    var dates = rows.map(function (row) {
      return row.date;
    });
    var traces = durations.map(function (duration) {
      return {
        type: "bar",
        name: duration,
        x: dates,
        y: rows.map(function (row) {
          var value = row.net_pnl ? row.net_pnl[duration] : undefined;
          return typeof value === "number" ? value : null;
        }),
      };
    });
    var layout = {
      title: "Daily Net PnL by Duration",
      barmode: "group",
      xaxis: { title: "Date" },
      yaxis: { title: "Net PnL (£)" },
      template: "plotly_white",
      height: 400,
      legend: { orientation: "h", x: 0, y: 1.12 },
    };
    return { data: traces, layout: layout };
  }

  // Wire a Plotly click on a graph div so clicking a point/bar loads that day.
  function wireDayClick(div, onDate) {
    if (!div || typeof div.on !== "function") {
      return;
    }
    div.on("plotly_click", function (event) {
      var point = event && event.points && event.points[0];
      if (point && point.x != null) {
        onDate(asDate(point.x));
      }
    });
  }

  // Tracks the most recently requested detail day so that out-of-order fetch
  // responses from rapid clicks can be discarded.
  var pendingDayDetail = null;

  // Fetch a single day's artifact and show its labels and per-duration net PnL
  // in the detail panel.
  function showDayDetail(date, manifest) {
    var panel = document.getElementById("hist-detail");
    var dateEl = document.getElementById("hist-detail-date");
    if (dateEl) {
      dateEl.textContent = date;
    }
    if (panel) {
      panel.hidden = false;
    }

    pendingDayDetail = date;
    fetchJson("data/days/" + date + ".json").then(function (day) {
      // Ignore a response that has been superseded by a newer click.
      if (pendingDayDetail !== date) {
        return;
      }

      renderLabels(document.getElementById("hist-detail-labels"), day && day.labels);

      var grid = document.getElementById("hist-detail-kpis");
      if (!grid) {
        return;
      }
      grid.textContent = "";

      if (!day || !day.assets) {
        grid.appendChild(kpiTile("Net PnL", "—", ""));
        return;
      }

      var durations = pickDurations(manifest, day, null);
      durations.forEach(function (duration) {
        var asset = day.assets[duration];
        var netPnl = asset && asset.pnl ? asset.pnl.net_pnl : undefined;
        var pnlClass = typeof netPnl === "number" ? (netPnl < 0 ? "neg" : "pos") : "";
        grid.appendChild(kpiTile(duration + " net PnL", formatGbp(netPnl), pnlClass));
      });
    });
  }

  // Build the History view: the equity curve and duration-comparison figures,
  // a client-side daily-PnL bar chart, and click-through to a day's detail.
  function renderHistory(history, manifest) {
    var empty = document.getElementById("history-empty");
    var content = document.getElementById("history-content");
    var rows = history && Array.isArray(history.rows) ? history.rows : [];

    if (!rows.length) {
      if (empty) {
        empty.hidden = false;
      }
      if (content) {
        content.hidden = true;
      }
      return;
    }

    if (empty) {
      empty.hidden = true;
    }
    if (content) {
      content.hidden = false;
    }

    var durations = pickDurations(manifest, null, null);
    if (!durations.length) {
      durations = Object.keys(rows[0].net_pnl || {});
    }

    var onDate = function (date) {
      showDayDetail(date, manifest);
    };

    renderFig("hist-fig-equity", "data/figs/_history/equity.json").then(function () {
      wireDayClick(document.getElementById("hist-fig-equity"), onDate);
    });
    renderFig("hist-fig-duration", "data/figs/_history/duration_comparison.json");

    var dailyDiv = document.getElementById("hist-fig-daily");
    if (dailyDiv) {
      var fig = dailyPnlFigure(rows, durations);
      Plotly.newPlot(dailyDiv, fig.data, fig.layout, { responsive: true }).then(function () {
        wireDayClick(dailyDiv, onDate);
      });
    }
  }

  // ----------------------------------------------------------------------- //
  // Day-types view
  // ----------------------------------------------------------------------- //

  // The fixed label vocabulary the day artifacts tag days with. The scatter and
  // profile figures carry one Plotly trace per day-type (its trace name), so the
  // filter just toggles trace visibility by name.
  var DAYTYPE_TAGS = ["windy", "sunny", "volatile", "calm", "high_demand", "low_demand"];

  // The subset of the fixed tags that actually appears across the history rows'
  // labels, preserving the canonical DAYTYPE_TAGS order.
  function presentTags(rows) {
    var seen = {};
    rows.forEach(function (row) {
      (row.labels || []).forEach(function (label) {
        seen[label] = true;
      });
    });
    return DAYTYPE_TAGS.filter(function (tag) {
      return seen[tag];
    });
  }

  // Restyle one rendered figure so a trace is hidden when its day-type is a
  // de-selected fixed tag; traces named outside the fixed set (e.g. "untagged")
  // are always shown. Subsetting via `visible` lets the axes rescale to the kept
  // points/lines.
  function applyDaytypeFilter(divId, selected) {
    var div = document.getElementById(divId);
    if (!div || !Array.isArray(div.data)) {
      return;
    }
    var visible = div.data.map(function (trace) {
      var name = trace.name;
      if (DAYTYPE_TAGS.indexOf(name) !== -1 && !selected[name]) {
        return false;
      }
      return true;
    });
    Plotly.restyle(div, { visible: visible });
  }

  // Build the Day-types view: a label filter, the DA-spread-vs-net-PnL scatter
  // and the average-profile comparison, plus a windy-vs-calm focus toggle. The
  // filter and toggle re-style both figures client-side.
  function renderDayTypes(history) {
    var empty = document.getElementById("daytype-empty");
    var content = document.getElementById("daytype-content");
    var rows = history && Array.isArray(history.rows) ? history.rows : [];

    if (!rows.length) {
      if (empty) {
        empty.hidden = false;
      }
      if (content) {
        content.hidden = true;
      }
      return;
    }

    if (empty) {
      empty.hidden = true;
    }
    if (content) {
      content.hidden = false;
    }

    var tags = presentTags(rows);
    if (!tags.length) {
      tags = DAYTYPE_TAGS.slice();
    }

    var selected = {};
    var inputs = {};
    tags.forEach(function (tag) {
      selected[tag] = true;
    });

    var toggleBtn = document.getElementById("daytype-compare");
    var comparing = false;

    function apply() {
      applyDaytypeFilter("dt-fig-scatter", selected);
      applyDaytypeFilter("dt-fig-profiles", selected);
    }

    function setCompareVisual(on) {
      comparing = on;
      if (toggleBtn) {
        toggleBtn.classList.toggle("active", on);
      }
    }

    // Force the selection (and its checkboxes) to exactly `active`, e.g. the
    // windy/calm pair for the comparison focus.
    function setOnly(active) {
      tags.forEach(function (tag) {
        var on = active.indexOf(tag) !== -1;
        selected[tag] = on;
        if (inputs[tag]) {
          inputs[tag].checked = on;
        }
      });
    }

    function setAll(value) {
      tags.forEach(function (tag) {
        selected[tag] = value;
        if (inputs[tag]) {
          inputs[tag].checked = value;
        }
      });
    }

    var filterEl = document.getElementById("daytype-filters");
    if (filterEl) {
      filterEl.textContent = "";
      tags.forEach(function (tag) {
        var label = document.createElement("label");
        label.className = "filter-chip";

        var input = document.createElement("input");
        input.type = "checkbox";
        input.checked = true;
        input.value = tag;
        input.addEventListener("change", function () {
          selected[tag] = input.checked;
          // A manual edit leaves the windy-vs-calm focus, visually.
          setCompareVisual(false);
          apply();
        });

        var text = document.createElement("span");
        text.textContent = tag;

        label.appendChild(input);
        label.appendChild(text);
        filterEl.appendChild(label);
        inputs[tag] = input;
      });
    }

    if (toggleBtn) {
      var canCompare = tags.indexOf("windy") !== -1 && tags.indexOf("calm") !== -1;
      toggleBtn.disabled = !canCompare;
      toggleBtn.addEventListener("click", function () {
        if (comparing) {
          setAll(true);
          setCompareVisual(false);
        } else {
          setOnly(["windy", "calm"]);
          setCompareVisual(true);
        }
        apply();
      });
    }

    // Render both figures, then apply the current filter once they exist so the
    // trace-visibility restyle has data to act on.
    Promise.all([
      renderFig("dt-fig-scatter", "data/figs/_history/daytype_scatter.json"),
      renderFig("dt-fig-profiles", "data/figs/_history/daytype_profiles.json"),
    ]).then(function () {
      apply();
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

  function wireNav(hasData, onShow) {
    var buttons = document.querySelectorAll(".nav-link");
    Array.prototype.forEach.call(buttons, function (button) {
      button.addEventListener("click", function () {
        var view = button.getAttribute("data-view");
        // Without data, only the no-data notice is meaningful.
        var resolved = hasData ? view : "no-data";
        showView(resolved);
        if (onShow) {
          onShow(resolved);
        }
      });
    });
  }

  // ----------------------------------------------------------------------- //
  // Boot
  // ----------------------------------------------------------------------- //

  function init() {
    loadData().then(function (data) {
      var hasLatest = data.latest && !isEmpty(data.latest.cumulative_net_pnl);

      // Render the History view lazily on first navigation, so its figures size
      // against a visible (non-zero-width) container.
      var historyRendered = false;
      var daytypesRendered = false;
      wireNav(hasLatest, function (view) {
        if (view === "history" && !historyRendered) {
          historyRendered = true;
          renderHistory(data.history, data.manifest);
        }
        if (view === "day-types" && !daytypesRendered) {
          daytypesRendered = true;
          renderDayTypes(data.history);
        }
      });

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
