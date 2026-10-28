const $ = (id) => document.getElementById(id);
// Set window.TRENDLENS_API_BASE in config.js when the frontend and API use different hosts.
const API_BASE = String(window.TRENDLENS_API_BASE || '').replace(/\/$/, '');
let locations = {};
let latestReport = null;
let chart = null;
const fmt = (n, digits=3) => Number.isFinite(Number(n)) ? Number(n).toFixed(digits) : '—';
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

function setBusy(busy, message='Retrieving NASA observations') {
  $('loading-overlay').hidden = !busy;
  $('run-button').disabled = busy;
  $('run-button').querySelector('span:last-child').textContent = busy ? 'Analyzing…' : 'Run comparison';
  $('loading-status').textContent = message;
}
function showError(message) {
  $('error-message').textContent = message;
  $('error-panel').hidden = false;
  $('error-panel').scrollIntoView({behavior:'smooth', block:'center'});
}
function clearError() { $('error-panel').hidden = true; }
function fillLocation(side, name) {
  const loc = locations[name];
  if (!loc) return;
  $(`lat-min-${side}`).value = loc.latitude_min;
  $(`lat-max-${side}`).value = loc.latitude_max;
  $(`lon-min-${side}`).value = loc.longitude_min;
  $(`lon-max-${side}`).value = loc.longitude_max;
}
function makeYearOptions() {
  const latest = new Date().getFullYear()-1;
  for (const id of ['start-year','end-year']) {
    const select = $(id);
    for (let y=latest; y>=1981; y--) {
      const option = document.createElement('option'); option.value = y; option.textContent = y; select.append(option);
    }
  }
  $('start-year').value = '2001'; $('end-year').value = String(Math.min(2024, latest));
}
async function init() {
  makeYearOptions();
  try {
    const res = await fetch(`${API_BASE}/api/datasets`);
    if (!res.ok) throw new Error('Could not load dataset metadata.');
    const payload = await res.json(); locations = payload.locations || {};
    for (const id of ['place-a','place-b']) {
      const select = $(id);
      Object.entries(locations).forEach(([name, loc]) => {
        const option = document.createElement('option'); option.value = name; option.textContent = name; select.append(option);
      });
    }
    $('place-a').value = 'Kuala Lumpur, Malaysia'; $('place-b').value = 'Dhaka, Bangladesh';
    fillLocation('a', $('place-a').value); fillLocation('b', $('place-b').value);
  } catch (err) { showError(err.message || 'Could not initialize the app. Refresh and try again.'); }
}
$('place-a').addEventListener('change', () => fillLocation('a', $('place-a').value));
$('place-b').addEventListener('change', () => fillLocation('b', $('place-b').value));
$('dismiss-error').addEventListener('click', clearError);
$('analysis-form').addEventListener('submit', async (event) => {
  event.preventDefault(); clearError();
  const start = Number($('start-year').value), end = Number($('end-year').value);
  if (start >= end) { showError('The start year must be earlier than the end year.'); return; }
  const payload = {
    location_a: {name: $('place-a').value || 'Study area A', latitude_min: Number($('lat-min-a').value), latitude_max: Number($('lat-max-a').value), longitude_min: Number($('lon-min-a').value), longitude_max: Number($('lon-max-a').value)},
    location_b: {name: $('place-b').value || 'Study area B', latitude_min: Number($('lat-min-b').value), latitude_max: Number($('lat-max-b').value), longitude_min: Number($('lon-min-b').value), longitude_max: Number($('lon-max-b').value)},
    start_year: start, end_year: end
  };
  setBusy(true);
  try {
    const res = await fetch(`${API_BASE}/api/analyze`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || `Analysis request failed (${res.status}).`);
    latestReport = data;
    renderResults(data);
  } catch (err) { showError(err.message || 'The analysis could not be completed. Check the connection and try again.'); }
  finally { setBusy(false); }
});
function trendDirection(slope) { return slope > 0 ? 'Increasing' : slope < 0 ? 'Decreasing' : 'No estimated change'; }
function renderResults(data) {
  $('welcome-panel').hidden = true; $('results').hidden = false;
  $('result-subtitle').textContent = `${data.period.requested_start_year}–${data.period.requested_end_year} · NASA POWER corrected precipitation · ${data.comparison.overlapping_years.length} overlapping annual observations`;
  const a = data.location_a.trend, b = data.location_b.trend, d = data.comparison;
  $('summary-grid').innerHTML = `
    <div class="summary-card accent-a"><div class="summary-label">LOCATION A · ${esc(data.location_a.name.toUpperCase())}</div><div class="summary-value">${fmt(a.slope,4)}</div><div class="summary-caption">mm/day per year · ${trendDirection(a.slope)}</div></div>
    <div class="summary-card accent-b"><div class="summary-label">LOCATION B · ${esc(data.location_b.name.toUpperCase())}</div><div class="summary-value">${fmt(b.slope,4)}</div><div class="summary-caption">mm/day per year · ${trendDirection(b.slope)}</div></div>
    <div class="summary-card accent-diff"><div class="summary-label">DIRECT SLOPE DIFFERENCE · A − B</div><div class="summary-value">${d.slope_a_minus_b > 0 ? '+' : ''}${fmt(d.slope_a_minus_b,4)}</div><div class="summary-caption">95% interval ${fmt(d.ci_low,4)} to ${fmt(d.ci_high,4)}</div></div>`;
  renderChart(data);
  $('trend-details').innerHTML = [renderTrendRow(data.location_a, 'A', '#70e1d0'), renderTrendRow(data.location_b, 'B', '#7ba8ff')].join('');
  $('difference-details').innerHTML = `<span class="status-chip ${d.interval_excludes_zero?'clear':'uncertain'}">${d.interval_excludes_zero?'INTERVAL EXCLUDES ZERO':'INTERVAL INCLUDES ZERO'}</span><div class="difference-number">${d.slope_a_minus_b>0?'+':''}${fmt(d.slope_a_minus_b,4)}</div><div class="difference-unit">${esc(d.unit)}</div><div class="interval-track"><span class="interval-zero"></span></div><div class="trend-ci">95% bootstrap interval: [${fmt(d.ci_low,4)}, ${fmt(d.ci_high,4)}]</div><p class="difference-interpretation">${esc(d.interpretation)}</p><div class="trend-description">Direction: ${esc(d.direction)}. This is an estimate of how much the slopes differ, not a statement about causes.</div>`;
  const m = data.methodology;
  $('method-details').innerHTML = `
    <div class="method-item"><b>DATA SOURCE & VARIABLE</b><p>${esc(data.dataset.name)}<br>Parameter: ${esc(data.dataset.id)}<br>Units: ${esc(data.dataset.units)}<br>Retrieved: ${esc(data.dataset.retrieved_at)}<br><a href="${esc(data.dataset.source_url)}" target="_blank" rel="noreferrer" style="color:#70e1d0">Open source endpoint ↗</a></p></div>
    <div class="method-item"><b>ANNUAL AGGREGATION</b><p>${esc(m.annualization)}</p></div>
    <div class="method-item"><b>STATISTICAL METHOD</b><p>${esc(m.trend_estimator)} ${esc(m.single_location_test)} ${esc(m.uncertainty)}</p></div>
    <div class="caution-list"><b>Read before interpreting</b><ul>${m.cautions.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></div>`;
  $('raw-json').textContent = JSON.stringify(data, null, 2);
  $('results').scrollIntoView({behavior:'smooth', block:'start'});
}
function renderTrendRow(location, label, color) {
  const t = location.trend;
  const p = t.p_value == null ? 'not available' : (t.p_value < 0.001 ? '< 0.001' : fmt(t.p_value,3));
  const bounds = location.bounds || {};
  const regionText = `Lat ${fmt(bounds.latitude_min,2)}–${fmt(bounds.latitude_max,2)}°, lon ${fmt(bounds.longitude_min,2)}–${fmt(bounds.longitude_max,2)}°`;
  return `<div class="trend-row"><div class="trend-row-head"><span><span style="color:${color}">●</span> ${esc(location.name)}</span><span>${trendDirection(t.slope)}</span></div><div class="trend-description" style="margin-top:3px">${esc(regionText)} · ${Number(location.grid_cells_with_data || 0)} grid cells with data</div><div class="trend-value">${t.slope>0?'+':''}${fmt(t.slope,4)} <span style="font:500 10px var(--font);color:#8297ae">mm/day/year</span></div><div class="trend-ci">95% bootstrap interval: [${fmt(t.ci_low,4)}, ${fmt(t.ci_high,4)}]</div><div class="trend-meta"><span class="mini-tag">n = ${t.n_years} years</span><span class="mini-tag">Kendall τ = ${fmt(t.tau,3)}</span><span class="mini-tag">p = ${p}</span></div><div class="trend-description">${t.ci_low>0?'The estimated slope interval is above zero.':t.ci_high<0?'The estimated slope interval is below zero.':'The estimated slope interval includes zero.'} Individual p-values do not establish a difference between locations.</div></div>`;
}
function renderChart(data) {
  const a = data.location_a.trend, b = data.location_b.trend;
  const datasets = [
    {label:data.location_a.name, data:a.years.map((year,i)=>({x:year,y:a.values[i]})), borderColor:'#70e1d0', backgroundColor:'#70e1d0', borderWidth:2, pointRadius:1.5, tension:.15},
    {label:`${data.location_a.name} trend`, data:a.years.map(year=>({x:year,y:a.intercept+a.slope*year})), borderColor:'#70e1d0', borderDash:[5,5], borderWidth:1.5, pointRadius:0},
    {label:data.location_b.name, data:b.years.map((year,i)=>({x:year,y:b.values[i]})), borderColor:'#7ba8ff', backgroundColor:'#7ba8ff', borderWidth:2, pointRadius:1.5, tension:.15},
    {label:`${data.location_b.name} trend`, data:b.years.map(year=>({x:year,y:b.intercept+b.slope*year})), borderColor:'#7ba8ff', borderDash:[5,5], borderWidth:1.5, pointRadius:0}
  ];
  $('chart-legend').innerHTML = `<span><i style="background:#70e1d0"></i>${esc(data.location_a.name)}</span><span><i style="background:#7ba8ff"></i>${esc(data.location_b.name)}</span>`;
  if (chart) chart.destroy();
  chart = new Chart($('trend-chart'), {type:'line',data:{datasets},options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'nearest',intersect:false},plugins:{legend:{display:false},tooltip:{backgroundColor:'#0b1625',borderColor:'#344960',borderWidth:1,titleColor:'#edf5ff',bodyColor:'#b6c8db',callbacks:{label:(ctx)=>`${ctx.dataset.label}: ${Number(ctx.parsed.y).toFixed(3)} mm/day`}}},scales:{x:{type:'linear',title:{display:true,text:'Year',color:'#8297ae',font:{family:'DM Sans',size:10}},ticks:{color:'#8297ae',maxTicksLimit:10},grid:{color:'#203047'},border:{color:'#31445a'}},y:{title:{display:true,text:'Precipitation (mm/day)',color:'#8297ae',font:{family:'DM Sans',size:10}},ticks:{color:'#8297ae'},grid:{color:'#203047'},border:{color:'#31445a'}}}}});
}
$('export-button').addEventListener('click', () => {
  if (!latestReport) return;
  const blob = new Blob([JSON.stringify(latestReport,null,2)], {type:'application/json'});
  const url = URL.createObjectURL(blob); const link = document.createElement('a');
  link.href = url; link.download = `trendlens-investigation-${latestReport.period.requested_start_year}-${latestReport.period.requested_end_year}.json`;
  document.body.appendChild(link); link.click(); link.remove(); URL.revokeObjectURL(url);
});
init();
