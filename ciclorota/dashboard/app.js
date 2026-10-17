const $ = (id) => document.getElementById(id);
let cachedDumpsters = [];
let cachedPlan = null;
let coverageMap = null;
let GoogleMap = null;
let GoogleInfoWindow = null;
let GoogleLatLngBounds = null;
let GooglePolyline = null;
let AdvancedMarkerElement = null;
let mapInfoWindow = null;
let mapMarkers = [];
let routeLine = null;
let googleMapsScriptPromise = null;
let googleMapsAuthFailed = false;
let refreshInProgress = false;

function statusLabel(status) {
  return ({normal: "Normal", stale: "Atrasado", offline: "Off-line", no_data: "Sem leitura"})[status] || status;
}
function weekdayLabel(day) {
  return ({
    Monday: "segunda-feira", Tuesday: "terça-feira", Wednesday: "quarta-feira",
    Thursday: "quinta-feira", Friday: "sexta-feira", Saturday: "sábado", Sunday: "domingo"
  })[day] || day;
}
function formatNumber(value, digits = 1) {
  return new Intl.NumberFormat("pt-BR", {
    minimumFractionDigits: digits, maximumFractionDigits: digits
  }).format(Number(value));
}
function translateBackendMessage(message) {
  const exact = {
    "Request failed": "Não foi possível concluir a solicitação.",
    "Failed to fetch": "Não foi possível conectar ao servidor. Confira se ele está em execução e tente novamente.",
    "NetworkError when attempting to fetch resource.": "Não foi possível conectar ao servidor. Confira se ele está em execução e tente novamente.",
    "Load failed": "Não foi possível conectar ao servidor. Confira se ele está em execução e tente novamente.",
    "Dumpster ID already exists": "Já existe uma caçamba com esse ID.",
    "Could not create dumpster": "Não foi possível cadastrar a caçamba.",
    "Enter a street address to geocode": "Informe um endereço para localizar a caçamba.",
    "No map location matched that street address": "Nenhum local foi encontrado para esse endereço.",
    "Google Geocoding API key is not configured": "A chave da API de geocodificação não está configurada.",
    "Google address lookup service is unavailable": "O serviço de localização de endereços está indisponível.",
    "Google address lookup service could not resolve the address": "O serviço não conseguiu localizar esse endereço.",
    "Google address lookup returned an invalid response": "O serviço de localização retornou uma resposta inválida.",
    "Google address lookup returned an invalid location": "O serviço de localização retornou coordenadas inválidas.",
    "measured_at cannot be more than five minutes in the future": "O horário da medição não pode estar mais de cinco minutos no futuro.",
    "Unknown dumpster_id": "A caçamba informada não está cadastrada.",
    "fill_percentage does not match dumpster calibration": "O percentual de enchimento não corresponde à calibração da caçamba.",
    "Cannot plan a route for a past collection date": "Não é possível planejar uma rota para uma data de coleta passada."
  };
  if (exact[message]) return exact[message];
  const schedule = message.match(/^Collection date must follow the fixed weekday schedule: (.+)$/);
  if (schedule) {
    const days = schedule[1].split(", ").map(weekdayLabel).join(" e ");
    return "A data precisa respeitar os dias fixos de coleta: " + days + ".";
  }
  if (message.startsWith("Route planning failed:")) return "Não foi possível planejar a rota. Tente novamente.";
  if (message.startsWith("OSRM unavailable")) return "O serviço de rotas está indisponível. Foram usadas distâncias aproximadas.";
  if (message.startsWith("Google Maps JavaScript API failed")) return "Não foi possível carregar o Google Maps. Verifique a conexão e a configuração da chave.";
  if (message.startsWith("[")) return "Os dados enviados são inválidos. Confira os campos e tente novamente.";
  return "Não foi possível concluir a operação. Confira os dados e tente novamente.";
}
function translateDecisionReason(reason) {
  if (reason === "no valid measurement") return "Sem medição válida.";
  const freshness = reason.match(/^(normal|stale|offline|no_data) measurement; manual review required$/);
  if (freshness) return freshness[1] === "offline" ? "Dispositivo off-line; é necessária uma verificação manual." : "Leitura atrasada; é necessária uma verificação manual.";
  if (reason === "projected overflow before the fixed collection date") return "Enchimento pode transbordar antes da próxima coleta programada.";
  let match = reason.match(/^current fill ([\d.]+)% meets ([\d.]+)% threshold$/);
  if (match) return "Enchimento atual de " + formatNumber(match[1]) + "% atingiu o limite de " + formatNumber(match[2]) + "%.";
  match = reason.match(/^projected fill ([\d.]+)% meets threshold by collection date$/);
  if (match) return "Enchimento previsto de " + formatNumber(match[1]) + "% atingirá o limite até a data da coleta.";
  match = reason.match(/^projected fill ([\d.]+)% remains below ([\d.]+)% threshold$/);
  if (match) return "Enchimento previsto de " + formatNumber(match[1]) + "% ficará abaixo do limite de " + formatNumber(match[2]) + "%.";
  return translateBackendMessage(reason);
}

async function api(path, options) {
  const response = await fetch(path, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = body.detail || response.statusText || "Request failed";
    throw new Error(translateBackendMessage(typeof detail === "string" ? detail : JSON.stringify(detail)));
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
function fillColor(item) {
  if (item.status !== "normal") return "#e0a33b";
  const fill = Number(item.latest?.fill_percentage);
  if (fill >= 90) return "#c94d43";
  if (fill >= 70) return "#e0a33b";
  return "#269466";
}
function renderSummary(dumpsters, plan) {
  const normal = dumpsters.filter((item) => item.status === "normal");
  const avg = normal.length ? normal.reduce((total, item) => total + (item.latest?.fill_percentage || 0), 0) / normal.length : 0;
  const values = [
    ["Caçambas cadastradas", dumpsters.length, "Em todos os pontos registrados"],
    ["Com leitura recente", normal.length, "Conforme o horário da última medição"],
    ["Enchimento médio estimado", normal.length ? formatNumber(avg) + "%" : "—", "Considera apenas leituras recentes"],
    ["Pontos na rota", plan ? plan.optimized.stop_count : "—", "Próximo dia fixo de coleta"]
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
    $("dumpster-rows").innerHTML = '<tr><td colspan="6">Nenhuma caçamba cadastrada. Execute o simulador ou cadastre um ponto abaixo.</td></tr>';
    return;
  }
  $("dumpster-rows").innerHTML = dumpsters.map((item) => {
    const latest = item.latest, fill = latest ? Number(latest.fill_percentage) : null;
    const decision = decisions[item.id];
    let decisionText = decision ? translateDecisionReason(decision.reason) : (plan ? "Cadastrada após a última rota; planeje novamente para avaliar." : "Planeje uma rota para calcular quais pontos serão coletados.");
    if (decision?.selected) decisionText = "COLETAR · " + decisionText;
    return '<tr><td><span class="site-name">' + escapeHtml(item.name) +
      '</span><span class="site-id">' + escapeHtml(item.id) + '</span></td><td class="address-cell">' +
      escapeHtml(item.address || item.geocoded_label || "Coordenadas informadas pelo dispositivo/API") + '</td><td class="fill-cell">' +
      (fill === null ? "—" : '<span class="fill-bar"><i class="' + (fill >= 90 ? "full" : fill >= 70 ? "high" : "") +
      '" style="width:' + Math.max(0, Math.min(100, fill)) + '%"></i></span>' + formatNumber(fill) + "%") +
      '</td><td><span class="status ' + escapeHtml(item.status) + '">' + escapeHtml(statusLabel(item.status)) +
      '</span></td><td>' + escapeHtml(latest ? new Date(latest.measured_at).toLocaleString("pt-BR") : "Sem envio") +
      '</td><td class="decision">' + escapeHtml(decisionText) + "</td></tr>";
  }).join("");
}
async function loadGoogleMaps(apiKey) {
  if (window.google?.maps?.importLibrary) return;
  if (googleMapsScriptPromise) return googleMapsScriptPromise;
  googleMapsScriptPromise = new Promise((resolve, reject) => {
    window.cicloRotaGoogleMapsCallback = resolve;
    const script = document.createElement("script");
    script.src = "https://maps.googleapis.com/maps/api/js?key=" +
      encodeURIComponent(apiKey) + "&v=weekly&loading=async&language=pt-BR&region=BR&callback=cicloRotaGoogleMapsCallback";
    script.async = true;
    script.onerror = () => reject(new Error("Google Maps JavaScript API failed to load"));
    document.head.appendChild(script);
  });
  return googleMapsScriptPromise;
}
function reportGoogleMapsAuthFailure() {
  googleMapsAuthFailed = true;
  coverageMap = null;
  const container = $("route-map");
  container.textContent = "O Google rejeitou a chave da API Maps JavaScript. Configure uma chave de navegador válida em CICLOROTA_GOOGLE_MAPS_BROWSER_KEY, habilite a Maps JavaScript API no projeto Google Cloud e autorize o endereço deste site.";
  container.setAttribute("role", "alert");
}
window.gm_authFailure = reportGoogleMapsAuthFailure;

async function initializeMap(config) {
  const container = $("route-map");
  if (googleMapsAuthFailed) return false;
  if (coverageMap) return true;
  if (config.google_maps_key_status === "placeholder") {
    container.textContent = "A chave do Google Maps ainda é um exemplo. Defina uma chave real da Maps JavaScript API em CICLOROTA_GOOGLE_MAPS_BROWSER_KEY, reinicie o servidor e recarregue esta página.";
    container.setAttribute("role", "alert");
    return false;
  }
  if (!config.google_maps_browser_key) {
    container.textContent = "O Google Maps não está configurado. Defina CICLOROTA_GOOGLE_MAPS_BROWSER_KEY para ativar o mapa de cobertura.";
    return false;
  }
  container.textContent = "Carregando o Google Maps…";
  try {
    await loadGoogleMaps(config.google_maps_browser_key);
    if (googleMapsAuthFailed) return false;
    const [mapsLibrary, markerLibrary] = await Promise.all([
      window.google.maps.importLibrary("maps"),
      window.google.maps.importLibrary("marker")
    ]);
    if (googleMapsAuthFailed) return false;
    GoogleMap = mapsLibrary.Map;
    GoogleInfoWindow = mapsLibrary.InfoWindow;
    GoogleLatLngBounds = mapsLibrary.LatLngBounds;
    GooglePolyline = mapsLibrary.Polyline;
    AdvancedMarkerElement = markerLibrary.AdvancedMarkerElement;
    coverageMap = new GoogleMap(container, {
      center: {lat: -22.017, lng: -47.895},
      zoom: 12,
      mapId: config.google_maps_map_id || "DEMO_MAP_ID",
      mapTypeControl: false,
      streetViewControl: false
    });
    mapInfoWindow = new GoogleInfoWindow();
    return true;
  } catch (error) {
    if (!googleMapsAuthFailed) {
      container.textContent = "Não foi possível carregar o Google Maps. Confira a chave de navegador, a restrição de site, o faturamento, a Maps JavaScript API e o ID do mapa.";
    }
    return false;
  }
}
function markerPopup(item, decision) {
  const fill = item.latest ? formatNumber(item.latest.fill_percentage) + "%" : "Sem leitura";
  const measured = item.latest ? new Date(item.latest.measured_at).toLocaleString("pt-BR") : "Nunca";
  const address = item.address || item.geocoded_label || "Coordenadas informadas pelo dispositivo/API";
  const routeDecision = decision ? (decision.selected ? "Coletar" : "Não coletar") + " · " + translateDecisionReason(decision.reason) : (cachedPlan ? "Não avaliada na última rota" : "Nenhuma rota planejada");
  const label = item.geocoded_label && item.address && item.geocoded_label !== item.address
    ? '<div><b>Endereço localizado:</b> ' + escapeHtml(item.geocoded_label) + "</div>" : "";
  return '<div class="map-popup"><strong>' + escapeHtml(item.name) + " · " + escapeHtml(item.id) +
    '</strong><div>' + escapeHtml(address) + "</div>" + label +
    '<div><b>Enchimento:</b> ' + escapeHtml(fill) + ' <span class="popup-status">(' + escapeHtml(statusLabel(item.status)) +
    ")</span></div><div><b>Última leitura:</b> " + escapeHtml(measured) +
    '</div><div><b>Próxima coleta:</b> ' + escapeHtml(routeDecision) + "</div></div>";
}
function buildMarkerContent(item, selected) {
  const node = document.createElement("div");
  node.className = "google-map-pin" + (selected ? " selected" : "");
  node.style.setProperty("--pin-color", fillColor(item));
  node.textContent = item.latest ? Math.round(Number(item.latest.fill_percentage)) + "%" : "—";
  node.setAttribute("aria-label", item.name + ", " + (item.latest ? Math.round(Number(item.latest.fill_percentage)) + "% de enchimento" : "sem leitura"));
  return node;
}
function renderMap(dumpsters, plan) {
  if (!coverageMap || googleMapsAuthFailed) return;
  for (const marker of mapMarkers) marker.map = null;
  mapMarkers = [];
  if (routeLine) routeLine.setMap(null);
  routeLine = null;

  const decisions = decisionMap(plan);
  const selected = new Set((plan?.route || []).map((stop) => stop.dumpster_id));
  const points = [];
  for (const item of dumpsters) {
    const position = {lat: Number(item.latitude), lng: Number(item.longitude)};
    if (!Number.isFinite(position.lat) || !Number.isFinite(position.lng)) continue;
    points.push(position);
    const marker = new AdvancedMarkerElement({
      map: coverageMap,
      position,
      title: item.name + " · " + item.id,
      content: buildMarkerContent(item, selected.has(item.id)),
      gmpClickable: true
    });
    marker.addEventListener("gmp-click", () => {
      const content = document.createElement("div");
      content.className = "map-popup";
      content.innerHTML = markerPopup(item, decisions[item.id]);
      mapInfoWindow.setContent(content);
      mapInfoWindow.open({map: coverageMap, anchor: marker});
    });
    mapMarkers.push(marker);
  }

  if (plan?.route?.length) {
    const path = [
      {lat: Number(plan.depot.latitude), lng: Number(plan.depot.longitude)},
      ...plan.route.map((stop) => ({lat: Number(stop.latitude), lng: Number(stop.longitude)})),
      {lat: Number(plan.depot.latitude), lng: Number(plan.depot.longitude)}
    ];
    routeLine = new GooglePolyline({
      map: coverageMap,
      path,
      strokeColor: "#166b4b",
      strokeOpacity: 0.85,
      strokeWeight: 4
    });
    points.push(...path);
  }
  if (!points.length) {
    coverageMap.setCenter({lat: -22.017, lng: -47.895});
    coverageMap.setZoom(12);
    return;
  }
  if (points.length === 1) {
    coverageMap.setCenter(points[0]);
    coverageMap.setZoom(15);
  } else {
    const bounds = new GoogleLatLngBounds();
    points.forEach((point) => bounds.extend(point));
    coverageMap.fitBounds(bounds, 40);
  }
}
function renderPlan(plan) {
  cachedPlan = plan;
  if (!plan) {
    $("route-title").textContent = "Localização das caçambas";
    $("route-provider").textContent = "Todos os pontos cadastrados";
    $("route-stops").textContent = "";
    $("metrics").innerHTML = '<p class="map-caption">Planeje uma rota para um dia fixo de coleta e compare com a rota de referência.</p>';
    renderMap(cachedDumpsters, null);
    return;
  }
  $("route-title").textContent = "Localização das caçambas";
  $("route-provider").textContent = "Rota · " + new Date(plan.collection_date + "T12:00:00").toLocaleDateString("pt-BR");
  if (plan.provider_warning) showNotice(translateBackendMessage(plan.provider_warning), false);
  $("route-stops").innerHTML = plan.route.length ? plan.route.map((stop) =>
    '<span class="stop-pill"><span class="stop-number">' + stop.sequence + "</span>" +
    escapeHtml(stop.dumpster_id) + " · " + formatNumber(stop.fill_percentage, 0) + "%</span>"
  ).join("") : '<span class="map-caption">Nenhuma caçamba com leitura recente foi selecionada. A agenda permanece inalterada.</span>';
  const base = plan.baseline, optimized = plan.optimized;
  const rows = [
    ["Pontos", optimized.stop_count, "referência: " + base.stop_count],
    ["Distância", formatNumber(optimized.distance_km, 2) + " km", "referência: " + formatNumber(base.distance_km, 2) + " km"],
    ["Duração estimada", formatNumber(optimized.duration_minutes, 0) + " min", "referência: " + formatNumber(base.duration_minutes, 0) + " min"],
    ["Combustível estimado", formatNumber(optimized.estimated_fuel_liters, 2) + " L", "referência: " + formatNumber(base.estimated_fuel_liters, 2) + " L"],
    ["CO₂ estimado", formatNumber(optimized.estimated_co2_kg, 2) + " kg", "referência: " + formatNumber(base.estimated_co2_kg, 2) + " kg"],
    ["Custo estimado de combustível", "R$ " + formatNumber(optimized.estimated_fuel_cost_brl, 2), "distância economizada: " + formatNumber(plan.estimated_distance_saved_km, 2) + " km"]
  ];
  $("metrics").innerHTML = rows.map((row) =>
    '<div class="metric-line"><span class="metric-name">' + escapeHtml(row[0]) +
    '</span><span class="metric-value">' + escapeHtml(row[1]) + "<small>" +
    escapeHtml(row[2]) + "</small></span></div>"
  ).join("");
  renderMap(cachedDumpsters, plan);
}
async function refresh() {
  if (refreshInProgress) return;
  refreshInProgress = true;
  hideNotice();
  try {
    const responses = await Promise.all([
      api("/api/config"), api("/api/dumpsters"), api("/api/routes/latest")
    ]);
    cachedDumpsters = responses[1];
    cachedPlan = responses[2];
    if (!coverageMap) await initializeMap(responses[0]);
    $("schedule").textContent = "Coleta fixa: " + responses[0].fixed_collection_weekdays.map(weekdayLabel).join(" · ");
    renderSummary(cachedDumpsters, cachedPlan);
    renderDumpsters(cachedDumpsters, cachedPlan);
    renderPlan(cachedPlan);
  } catch (error) { showNotice(translateBackendMessage(error.message), true); }
  finally { refreshInProgress = false; }
}
$("plan-button").addEventListener("click", async () => {
  const button = $("plan-button");
  button.disabled = true;
  button.textContent = "Planejando…";
  try {
    const plan = await api("/api/routes/plan", {
      method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({})
    });
    renderPlan(plan);
    renderDumpsters(cachedDumpsters, plan);
    renderSummary(cachedDumpsters, plan);
    showNotice("Rota planejada para a próxima data fixa de coleta: " + new Date(plan.collection_date + "T12:00:00").toLocaleDateString("pt-BR"), false);
  } catch (error) { showNotice(translateBackendMessage(error.message), true); }
  finally { button.disabled = false; button.textContent = "Planejar próxima coleta"; }
});
$("refresh-button").addEventListener("click", refresh);
$("register-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const submit = form.querySelector('button[type="submit"]');
  const values = Object.fromEntries(new FormData(form).entries());
  for (const key of ["empty_distance_cm", "full_distance_cm", "fill_threshold_percent", "daily_fill_rate_percent"]) {
    values[key] = Number(values[key]);
  }
  submit.disabled = true;
  submit.textContent = "Localizando endereço…";
  showNotice("Localizando o endereço e cadastrando a caçamba…", false);
  try {
    const response = await api("/api/dumpsters", {
      method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(values)
    });
    form.reset();
    showNotice("Caçamba cadastrada em " + response.dumpster.geocoded_label + ".", false);
    await refresh();
  } catch (error) { showNotice(translateBackendMessage(error.message), true); }
  finally { submit.disabled = false; submit.textContent = "Cadastrar caçamba"; }
});
refresh();
window.setInterval(refresh, 15000);
