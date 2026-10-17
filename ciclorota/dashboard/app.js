const $ = (id) => document.getElementById(id);
let cachedDumpsters = [];
let cachedPlan = null;

async function api(path, options) {
  const response = await fetch(path, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = body.detail || response.statusText || "Request failed";
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return body;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[char]));
}

function showNotice(message, error) {
  const node = $("notice");
  node.textContent = message;
  node.className = "notice visible" + (error ? " error" : "");
}

function hideNotice() { $("notice").className = "notice"; }

function decisionMap(plan) {
  const result = {};
  for (const item of (plan?.decisions || [])) result[item.dumpster_id] = item;
  return result;
}

function renderSummary(dumpsters, plan) {
  const normal = dumpsters.filter((item) => item.status === "normal");
  const avg = normal.length ? normal.reduce((total, item) => total + (item.latest?.fill_percentage || 0), 0) / normal.length : 0;
  const values = [
    ["Registered dumpsters", dumpsters.length, "Across all configured sites"],
    ["Reporting normally", normal.length, "Based on latest measurement age"],
    ["Average estimated fill", normal.length ? avg.toFixed(1) + "%" : "—", "Fresh readings only"],
    ["Planned stops", plan ? plan.optimized.stop_count : "—", "Next fixed collection day"]
  ];
  $("summary").innerHTML = values.map((item) =>
    '<article class="stat-card"><p class="stat-label">' + escapeHtml(item[0]) +
    '</p><div class="stat-value">' + escapeHtml(item[1]) +
    '</div><div class="stat-note">' + escapeHtml(item[2]) + "</div></article>"
  ).join("");
}

function renderDumpsters(dumpsters, plan) {
  const decisions = decisionMap(plan);
  if (!dumpsters.length) {
    $("dumpster-rows").innerHTML = '<tr><td colspan="5">No dumpsters registered. Run the simulator or add a site below.</td></tr>';
    return;
  }
  $("dumpster-rows").innerHTML = dumpsters.map((item) => {
    const latest = item.latest;
    const fill = latest ? Number(latest.fill_percentage) : null;
    const decision = decisions[item.id];
    let decisionText = decision ? decision.reason : "Plan a route to calculate stop selection.";
    if (decision?.selected) decisionText = "COLLECT · " + decisionText;
    return '<tr><td><span class="site-name">' + escapeHtml(item.name) +
      '</span><span class="site-id">' + escapeHtml(item.id) + '</span></td><td class="fill-cell">' +
      (fill === null ? "—" : '<span class="fill-bar"><i class="' + (fill >= 90 ? "full" : fill >= 70 ? "high" : "") +
      '" style="width:' + Math.max(0, Math.min(100, fill)) + '%"></i></span>' + fill.toFixed(1) + "%") +
      '</td><td><span class="status ' + escapeHtml(item.status) + '">' + escapeHtml(item.status.replace("_", " ")) +
      '</span></td><td>' + escapeHtml(latest ? new Date(latest.measured_at).toLocaleString() : "No report") +
      '</td><td class="decision">' + escapeHtml(decisionText) + "</td></tr>";
  }).join("");
}

function addSvg(parent, tag, attrs, text) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [key, value] of Object.entries(attrs || {})) node.setAttribute(key, value);
  if (text) node.textContent = text;
  parent.appendChild(node);
  return node;
}

function renderMap(plan) {
  const container = $("route-map");
  container.innerHTML = "";
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 700 245");
  container.appendChild(svg);
  if (!plan) {
    addSvg(svg, "text", {x: 350, y: 125, "text-anchor": "middle", fill: "#718078", "font-size": 14}, "Generate a route to see selected stops");
    return;
  }
  const points = [{label: "Depot", latitude: plan.depot.latitude, longitude: plan.depot.longitude, depot: true}]
    .concat(plan.route.map((stop) => ({label: stop.dumpster_id, latitude: stop.latitude, longitude: stop.longitude, depot: false})));
  if (points.length === 1) {
    addSvg(svg, "text", {x: 350, y: 125, "text-anchor": "middle", fill: "#718078", "font-size": 14}, "No fresh dumpsters selected for collection");
    return;
  }
  const lats = points.map((point) => point.latitude), lons = points.map((point) => point.longitude);
  const minLat = Math.min(...lats), maxLat = Math.max(...lats), minLon = Math.min(...lons), maxLon = Math.max(...lons);
  const x = (point) => 42 + (point.longitude - minLon) / Math.max(0.0001, maxLon - minLon) * 616;
  const y = (point) => 25 + (maxLat - point.latitude) / Math.max(0.0001, maxLat - minLat) * 195;
  const pathPoints = [points[0]].concat(points.slice(1), [points[0]]);
  addSvg(svg, "polyline", {
    points: pathPoints.map((point) => x(point) + "," + y(point)).join(" "),
    fill: "none", stroke: "#3d9a70", "stroke-width": 3, "stroke-linecap": "round",
    "stroke-linejoin": "round", "stroke-dasharray": plan.provider === "OSRM" ? "" : "7 6"
  });
  points.forEach((point, index) => {
    addSvg(svg, "circle", {cx: x(point), cy: y(point), r: point.depot ? 9 : 8, fill: point.depot ? "#172824" : "#167454", stroke: "white", "stroke-width": 3});
    addSvg(svg, "text", {x: x(point) + 12, y: y(point) - 10, fill: "#243a30", "font-size": 11, "font-weight": 700}, point.depot ? "Depot" : String(index));
  });
}

function renderPlan(plan) {
  cachedPlan = plan;
  if (!plan) {
    $("route-title").textContent = "Route overview";
    $("route-provider").textContent = "No route yet";
    $("route-stops").textContent = "";
    $("metrics").innerHTML = '<p class="map-caption">Plan a fixed-day route to compare it with the baseline.</p>';
    renderMap(null);
    return;
  }
  $("route-title").textContent = "Collection run · " + plan.collection_date;
  $("route-provider").textContent = plan.provider;
  if (plan.provider_warning) showNotice(plan.provider_warning, false);
  $("route-stops").innerHTML = plan.route.length ? plan.route.map((stop) =>
    '<span class="stop-pill"><span class="stop-number">' + stop.sequence + "</span>" +
    escapeHtml(stop.dumpster_id) + " · " + Number(stop.fill_percentage).toFixed(0) + "%</span>"
  ).join("") : '<span class="map-caption">No fresh dumpsters selected. Schedule is unchanged.</span>';
  const base = plan.baseline, optimized = plan.optimized;
  const rows = [
    ["Stops", optimized.stop_count, "baseline: " + base.stop_count],
    ["Distance", optimized.distance_km.toFixed(2) + " km", "baseline: " + base.distance_km.toFixed(2) + " km"],
    ["Estimated duration", optimized.duration_minutes.toFixed(0) + " min", "baseline: " + base.duration_minutes.toFixed(0) + " min"],
    ["Estimated fuel", optimized.estimated_fuel_liters.toFixed(2) + " L", "baseline: " + base.estimated_fuel_liters.toFixed(2) + " L"],
    ["Estimated CO₂", optimized.estimated_co2_kg.toFixed(2) + " kg", "baseline: " + base.estimated_co2_kg.toFixed(2) + " kg"],
    ["Estimated fuel cost", "R$ " + optimized.estimated_fuel_cost_brl.toFixed(2), "distance saved: " + plan.estimated_distance_saved_km.toFixed(2) + " km"]
  ];
  $("metrics").innerHTML = rows.map((row) =>
    '<div class="metric-line"><span class="metric-name">' + escapeHtml(row[0]) +
    '</span><span class="metric-value">' + escapeHtml(row[1]) + '<small>' +
    escapeHtml(row[2]) + "</small></span></div>"
  ).join("");
  renderMap(plan);
}

async function refresh() {
  hideNotice();
  try {
    const responses = await Promise.all([
      api("/api/config"), api("/api/dumpsters"), api("/api/routes/latest").catch(() => null)
    ]);
    cachedDumpsters = responses[1];
    $("schedule").textContent = "Fixed collection: " + responses[0].fixed_collection_weekdays.join(" · ");
    renderSummary(cachedDumpsters, responses[2]);
    renderDumpsters(cachedDumpsters, responses[2]);
    renderPlan(responses[2]);
  } catch (error) { showNotice(error.message, true); }
}

$("plan-button").addEventListener("click", async () => {
  const button = $("plan-button");
  button.disabled = true;
  button.textContent = "Planning…";
  try {
    const plan = await api("/api/routes/plan", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({})});
    renderPlan(plan);
    renderDumpsters(cachedDumpsters, plan);
    renderSummary(cachedDumpsters, plan);
    showNotice("Route planned for the next fixed collection date: " + plan.collection_date, false);
  } catch (error) { showNotice(error.message, true); }
  finally { button.disabled = false; button.textContent = "Plan next scheduled run"; }
});

$("refresh-button").addEventListener("click", refresh);
$("register-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const values = Object.fromEntries(new FormData(form).entries());
  for (const key of ["latitude", "longitude", "empty_distance_cm", "full_distance_cm", "fill_threshold_percent", "daily_fill_rate_percent"]) values[key] = Number(values[key]);
  try {
    await api("/api/dumpsters", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(values)});
    form.reset();
    showNotice("Dumpster registered. Add readings through the simulator or device.", false);
    await refresh();
  } catch (error) { showNotice(error.message, true); }
});

refresh();
