const $ = (id) => document.getElementById(id);
const PLACEHOLDER = "/dashboard/images/photo-placeholder.svg";
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
let hasLoaded = false;

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[char]));
}
function statusLabel(status) {
  return ({normal: "Leitura recente", stale: "Leitura atrasada", offline: "Off-line estimado", no_data: "Sem leitura"})[status] || "Situação desconhecida";
}
function statusClass(status) {
  return ["normal", "stale", "offline", "no_data"].includes(status) ? status : "no_data";
}
function weekdayLabel(day) {
  return ({Monday: "segunda-feira", Tuesday: "terça-feira", Wednesday: "quarta-feira", Thursday: "quinta-feira", Friday: "sexta-feira", Saturday: "sábado", Sunday: "domingo"})[day] || day;
}
function formatNumber(value, digits = 1) {
  return new Intl.NumberFormat("pt-BR", {minimumFractionDigits: digits, maximumFractionDigits: digits}).format(value);
}
function formatDistance(value) {
  return typeof value === "number" && Number.isFinite(value) ? formatNumber(value) + " cm" : "—";
}
function fillValue(item) {
  const value = item.latest?.fill_percentage;
  return typeof value === "number" && Number.isFinite(value) ? Math.min(100, Math.max(0, value)) : null;
}
function fillClass(fill) { return fill >= 90 ? "full" : fill >= 70 ? "high" : ""; }
function timestampHtml(value) {
  if (!value || !Number.isFinite(new Date(value).getTime())) return "Sem medição";
  return '<time datetime="' + escapeHtml(value) + '">' + escapeHtml(new Date(value).toLocaleString("pt-BR")) + '</time>';
}
function statusHtml(item) {
  return '<span class="status ' + statusClass(item.status) + '">' + escapeHtml(statusLabel(item.status)) + '</span>';
}
function safePhotoUrl(value) {
  if (!value) return null;
  try {
    const url = new URL(value, window.location.origin);
    if (["http:", "https:"].includes(url.protocol) && !url.username && !url.password) {
      // Local files may be overwritten by camera.py. Refresh their bytes too.
      // Leave external/signed image URLs untouched.
      if (url.origin === window.location.origin && url.pathname.startsWith("/dashboard/images/dumpsters/")) {
        url.searchParams.set("_photo_v", String(Date.now()));
      }
      return url.href;
    }
  } catch (_) { /* Fall back to the local placeholder. */ }
  return null;
}
function translateBackendMessage(message) {
  const exact = {
    "Dumpster ID already exists": "Já existe uma caçamba com esse ID.",
    "Could not create dumpster": "Não foi possível cadastrar a caçamba.",
    "Unknown dumpster_id": "A caçamba não está cadastrada. Atualize a página.",
    "No map location matched that street address": "Nenhum local foi encontrado para esse endereço.",
    "Google Geocoding API key is not configured": "A geocodificação não está configurada. Configure a chave do servidor ou cadastre por coordenadas na API.",
    "Google address lookup service is unavailable": "O serviço de localização de endereços está indisponível."
  };
  return exact[message] || "Não foi possível concluir a solicitação. Confira os campos, a conexão e o servidor.";
}
async function api(path, options = {}) {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 12000);
  try {
    const response = await fetch(path, {...options, signal: controller.signal});
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      let message = typeof body.detail === "string" ? body.detail : "";
      if (Array.isArray(body.detail)) {
        const imageError = body.detail.some((error) => error.loc?.includes("image_url"));
        if (imageError) throw new Error("Use uma URL HTTP(S) ou /dashboard/images/dumpsters/foto.jpg para a fotografia.");
      }
      throw new Error(translateBackendMessage(message));
    }
    return body;
  } finally { window.clearTimeout(timeout); }
}
function showNotice(message, error = false) {
  $("notice").textContent = message;
  $("notice").className = "notice visible" + (error ? " error" : "");
}
function renderSummary(dumpsters) {
  const fresh = dumpsters.filter((item) => item.status === "normal" && fillValue(item) !== null);
  const average = fresh.length ? fresh.reduce((sum, item) => sum + fillValue(item), 0) / fresh.length : null;
  const attention = dumpsters.filter((item) => item.status !== "normal").length;
  const values = [
    ["Caçambas cadastradas", dumpsters.length, "Pontos registrados no sistema"],
    ["Com leitura recente", fresh.length, "Medições dentro do prazo configurado"],
    ["Enchimento médio estimado", average === null ? "—" : formatNumber(average) + "%", "Somente leituras recentes"],
    ["Sensores para verificar", attention, "Atrasados, off-line ou sem leitura"]
  ];
  $("summary").innerHTML = values.map(([label, value, note]) => '<article class="stat-card"><p class="stat-label">' + escapeHtml(label) + '</p><div class="stat-value">' + escapeHtml(value) + '</div><p class="stat-note">' + escapeHtml(note) + '</p></article>').join("");
}
function renderGallery(dumpsters) {
  $("gallery-count").textContent = dumpsters.length + (dumpsters.length === 1 ? " caçamba" : " caçambas");
  $("photo-gallery").innerHTML = dumpsters.length ? dumpsters.map((item) => {
    const fill = fillValue(item);
    const photo = safePhotoUrl(item.image_url);
    return '<article class="dumpster-card" data-dumpster-id="' + escapeHtml(item.id) + '">' +
      '<div class="photo-frame"><img src="' + escapeHtml(photo || PLACEHOLDER) + '" alt="' + escapeHtml(photo ? "Fotografia da caçamba " + item.id + " — " + item.name : "Fotografia não disponível para a caçamba " + item.id) + '" loading="lazy" decoding="async" width="640" height="400"><span class="photo-label"' + (photo ? ' hidden' : '') + '>Sem fotografia</span></div>' +
      '<div class="card-body"><div class="card-heading"><div><span class="site-id">' + escapeHtml(item.id) + '</span><h4>' + escapeHtml(item.name) + '</h4></div>' + statusHtml(item) + '</div>' +
      '<p class="card-address">' + escapeHtml(item.address || item.geocoded_label || "Localização cadastrada por coordenadas") + '</p>' +
      '<div class="level-heading"><span>Enchimento estimado</span><strong>' + (fill === null ? '—' : formatNumber(fill) + '%') + '</strong></div>' +
      (fill === null ? '<p class="no-reading">Aguardando a primeira medição do sensor.</p>' : '<progress class="fill-progress ' + fillClass(fill) + '" max="100" value="' + fill + '" aria-label="Enchimento estimado da caçamba ' + escapeHtml(item.id) + '">' + formatNumber(fill) + '%</progress>') +
      '<dl class="sensor-details"><div><dt>Distância bruta</dt><dd>' + formatDistance(item.latest?.raw_distance_cm) + '</dd></div><div><dt>Distância filtrada</dt><dd>' + formatDistance(item.latest?.distance_cm) + '</dd></div></dl>' +
      '<div class="measurement-time"><span>Última medição</span><div>' + timestampHtml(item.latest?.measured_at) + '</div></div>' +
      (item.latest && item.status !== 'normal' ? '<p class="stale-note">Último valor conhecido; verifique o sensor antes de usar esta leitura.</p>' : '') + '</div></article>';
  }).join("") : '<div class="empty-state"><strong>Nenhuma caçamba cadastrada.</strong><p>Cadastre um ponto para acompanhar suas medições e associar uma fotografia.</p><a href="#registration" id="register-link">Cadastrar primeira caçamba</a></div>';
  for (const img of $("photo-gallery").querySelectorAll("img")) {
    img.addEventListener("error", () => {
      if (img.dataset.fallback) return;
      img.dataset.fallback = "true";
      img.src = PLACEHOLDER;
      img.alt = "Fotografia indisponível";
      const label = img.parentElement.querySelector(".photo-label");
      label.hidden = false;
      label.textContent = "Fotografia indisponível";
    });
  }
}
function renderDumpsters(dumpsters) {
  $("dumpster-rows").innerHTML = dumpsters.length ? dumpsters.map((item) => {
    const fill = fillValue(item);
    return '<tr><th scope="row"><span class="site-name">' + escapeHtml(item.name) + '</span><span class="site-id">' + escapeHtml(item.id) + '</span></th><td class="address-cell">' + escapeHtml(item.address || item.geocoded_label || "Coordenadas cadastradas") + '</td><td>' + (fill === null ? '—' : formatNumber(fill) + '%') + '</td><td>' + formatDistance(item.latest?.raw_distance_cm) + '</td><td>' + formatDistance(item.latest?.distance_cm) + '</td><td>' + timestampHtml(item.latest?.measured_at) + '</td><td>' + statusHtml(item) + '</td></tr>';
  }).join("") : '<tr><td colspan="7">Nenhuma caçamba cadastrada.</td></tr>';
}
function updatePhotoSelector() {
  const select = $("photo-dumpster");
  const selected = select.value;
  const ids = cachedDumpsters.map((item) => item.id);
  if (JSON.stringify([...select.options].map((option) => option.value).filter(Boolean)) !== JSON.stringify(ids)) {
    select.innerHTML = '<option value="">Selecione uma caçamba</option>' + cachedDumpsters.map((item) => '<option value="' + escapeHtml(item.id) + '">' + escapeHtml(item.id + " · " + item.name) + '</option>').join("");
    select.value = selected;
  }
  select.disabled = !cachedDumpsters.length;
  $("photo-form").querySelector("button").disabled = !cachedDumpsters.length;
}
async function refresh() {
  if (refreshInProgress) return;
  refreshInProgress = true;
  $("refresh-button").disabled = true;
  $("refresh-button").textContent = "Atualizando…";
  try {
    const dumpsters = await api("/api/dumpsters");
    if (!Array.isArray(dumpsters)) throw new Error("Invalid API response");
    cachedDumpsters = dumpsters;
    renderSummary(dumpsters);
    renderGallery(dumpsters);
    renderDumpsters(dumpsters);
    updatePhotoSelector();
    void refreshMap();
    hasLoaded = true;
    $("notice").className = "notice";
    $("connection-status").textContent = "Servidor conectado";
    $("connection-status").className = "connection-chip connected";
    $("last-updated").textContent = "Atualizado às " + new Date().toLocaleTimeString("pt-BR") + " · a cada 15 s";
  } catch (_) {
    $("connection-status").textContent = "Servidor indisponível";
    $("connection-status").className = "connection-chip disconnected";
    showNotice(hasLoaded ? "Não foi possível atualizar. Os dados abaixo são da última atualização bem-sucedida e podem estar desatualizados." : "Não foi possível carregar as caçambas. Verifique o servidor e tente atualizar novamente.", true);
    if (!hasLoaded) {
      $("summary").innerHTML = '<p class="empty-state">Indicadores indisponíveis.</p>';
      $("photo-gallery").innerHTML = '<div class="empty-state">Galeria indisponível. Use “Atualizar leituras” para tentar novamente.</div>';
      $("dumpster-rows").innerHTML = '<tr><td colspan="7">Medições indisponíveis.</td></tr>';
      $("gallery-count").textContent = "Indisponível";
    }
  } finally {
    $("summary").setAttribute("aria-busy", "false");
    $("photo-gallery").setAttribute("aria-busy", "false");
    $("refresh-button").disabled = false;
    $("refresh-button").textContent = "Atualizar leituras";
    refreshInProgress = false;
  }
}
$("refresh-button").addEventListener("click", refresh);
$("photo-gallery").addEventListener("click", (event) => {
  if (event.target.closest("#register-link")) $("registration").open = true;
});
$("photo-dumpster").addEventListener("change", (event) => {
  $("photo-url").value = cachedDumpsters.find((item) => item.id === event.target.value)?.image_url || "";
});
$("photo-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button");
  const id = $("photo-dumpster").value;
  if (!id) return;
  button.disabled = true;
  try {
    await api("/api/dumpsters/" + encodeURIComponent(id) + "/photo", {method: "PATCH", headers: {"Content-Type": "application/json"}, body: JSON.stringify({image_url: $("photo-url").value.trim() || null})});
    await refresh();
    showNotice("Associação da fotografia atualizada.");
  } catch (error) { showNotice(error.message, true); }
  finally { button.disabled = !cachedDumpsters.length; }
});
$("register-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button");
  const values = Object.fromEntries(new FormData(form).entries());
  for (const key of ["empty_distance_cm", "full_distance_cm", "fill_threshold_percent", "daily_fill_rate_percent"]) values[key] = Number(values[key]);
  values.image_url = values.image_url.trim() || null;
  button.disabled = true;
  button.textContent = "Cadastrando…";
  try {
    await api("/api/dumpsters", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(values)});
    form.reset();
    await refresh();
    showNotice("Caçamba cadastrada com sucesso.");
  } catch (error) { showNotice(error.message, true); }
  finally { button.disabled = false; button.textContent = "Cadastrar caçamba"; }
});
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

function renderRouteStops() {
  const plan = cachedPlan;
  $("map-status").textContent = plan
    ? "Rota para " + new Date(plan.collection_date + "T12:00:00").toLocaleDateString("pt-BR") + " · agenda fixa preservada"
    : "Nenhuma rota planejada. Todos os pontos cadastrados aparecem no mapa.";
  $("route-stops").innerHTML = (plan?.route || []).map((stop) =>
    '<span class="stop-pill"><b>' + escapeHtml(stop.sequence) + '</b> ' + escapeHtml(stop.dumpster_id) + '</span>'
  ).join("");
}
async function refreshMap() {
  try {
    cachedPlan = await api("/api/routes/latest");
    renderRouteStops();
    renderMap(cachedDumpsters, cachedPlan);
  } catch (_) {
    $("map-status").textContent = "Não foi possível atualizar a rota. As medições continuam disponíveis.";
    renderMap(cachedDumpsters, cachedPlan);
  }
}
$("plan-button").addEventListener("click", async () => {
  const button = $("plan-button");
  button.disabled = true;
  button.textContent = "Planejando…";
  try {
    cachedPlan = await api("/api/routes/plan", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({})});
    renderRouteStops();
    renderMap(cachedDumpsters, cachedPlan);
  } catch (error) {
    $("map-status").textContent = error.message;
  } finally {
    button.disabled = false;
    button.textContent = "Planejar próxima coleta";
  }
});

// Optional map configuration must not block measurement rendering.
api("/api/config").then((config) => {
  $("schedule").textContent = "Coleta fixa: " + config.fixed_collection_weekdays.map(weekdayLabel).join(" · ");
  initializeMap(config).then(() => renderMap(cachedDumpsters, cachedPlan));
}).catch(() => {
  $("schedule").textContent = "Agenda indisponível";
  $("route-map").textContent = "Não foi possível carregar a configuração do mapa. Atualize a página para tentar novamente.";
});
refresh();
window.setInterval(refresh, 15000);