// script.js
const API_BASE = '/api';

// Palette mirrors the CSS custom properties in style.css — Chart.js can't
// read CSS vars directly for canvas fills, so the same hexes are repeated
// here. Keep these in sync if the theme in style.css ever changes.
const COLOR_INK = '#d9e2ea';
const COLOR_DIM = '#64798c';
const COLOR_SIGNAL = '#21e6a1';   // positive / primary accent
const COLOR_AMBER = '#ffb703';   // secondary accent
const COLOR_ALERT = '#ff4d6d';   // negative / miss
const chartTextColor = COLOR_DIM;
const gridColor = 'rgba(100,121,140,0.18)';
Chart.defaults.color = chartTextColor;
Chart.defaults.borderColor = gridColor;
Chart.defaults.font.family = "'JetBrains Mono', monospace";

let currentCompetition = null; // { competition_id, season_id }
let radarChart, barChart, scatterClutchChart, scatterUsageChart;
let topScorersChart, finishingChart, clutchLeaderboardChart, usageFinishingChart;
let allPlayers = [];
let selectedPlayers = new Set();
let currentSort = { key: 'player_name', asc: true };
let allCompetitions = []; // full list from /api/competitions, used to build leap season pickers

// ---------- Tabs ----------
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById(btn.dataset.tab + '-tab').classList.add('active');
    if (btn.dataset.tab === 'scatter') loadScatterData();
    if (btn.dataset.tab === 'teams') loadTeamStructure();
    if (btn.dataset.tab === 'players') loadPlayers();
    if (btn.dataset.tab === 'leap') loadLeapSeasonPickers();
  });
});

// ---------- Competition picker ----------
async function loadCompetitions() {
  const select = document.getElementById('competition-select');
  try {
    const resp = await fetch(`${API_BASE}/competitions`);
    const comps = await resp.json();
    allCompetitions = comps;
    select.innerHTML = comps.map(c =>
      `<option value="${c.competition_id}|${c.season_id}">${c.label}</option>`
    ).join('');
    if (comps.length) {
      currentCompetition = { competition_id: comps[0].competition_id, season_id: comps[0].season_id };
    }
  } catch (e) {
    select.innerHTML = '<option>Backend not reachable — is app.py running?</option>';
  }
  select.addEventListener('change', () => {
    const [competition_id, season_id] = select.value.split('|').map(Number);
    currentCompetition = { competition_id, season_id };
    selectedPlayers.clear();
    updateCompareButton();
    // Reload all tabs that depend on competition
    if (document.getElementById('players-tab').classList.contains('active')) loadPlayers();
    if (document.getElementById('scatter-tab').classList.contains('active')) loadScatterData();
    if (document.getElementById('teams-tab').classList.contains('active')) loadTeamStructure();
    loadTicker();
  });
  loadTicker();
}

// ---------- Ticker tape ----------
async function loadTicker() {
  const track = document.getElementById('ticker-track');
  if (!currentCompetition) return;
  const { competition_id, season_id } = currentCompetition;
  let players;
  try {
    const resp = await fetch(`${API_BASE}/players?competition_id=${competition_id}&season_id=${season_id}`);
    players = await resp.json();
  } catch (e) {
    return;
  }
  if (!players || !players.length) {
    track.innerHTML = '<span class="ticker-item"><span class="sym">NO DATA ON FILE</span> — run python run.py to build the database</span>';
    return;
  }

  const items = [];
  const topScorers = [...players].sort((a, b) => (b.goals || 0) - (a.goals || 0)).slice(0, 3);
  topScorers.forEach(p => {
    if (p.goals > 0) items.push({ text: `${p.player_name} — ${p.goals} G (${(p.goals_per90 || 0).toFixed(2)}/90)`, dir: 'up' });
  });

  const topFinishers = [...players].sort((a, b) => (b.finishing_efficiency ?? 0) - (a.finishing_efficiency ?? 0)).slice(0, 3);
  topFinishers.forEach(p => {
    const v = p.finishing_efficiency ?? 0;
    if (v !== 0) items.push({ text: `${p.player_name} G−xG ${v >= 0 ? '+' : ''}${v.toFixed(2)}`, dir: v >= 0 ? 'up' : 'down' });
  });

  const topClutch = [...players].sort((a, b) => (b.net_clutch_score ?? 0) - (a.net_clutch_score ?? 0)).slice(0, 3);
  topClutch.forEach(p => {
    const v = p.net_clutch_score ?? 0;
    if (v !== 0) items.push({ text: `${p.player_name} CLUTCH ${v >= 0 ? '+' : ''}${v.toFixed(2)}`, dir: v >= 0 ? 'up' : 'down' });
  });

  const worstFinisher = [...players].sort((a, b) => (a.finishing_efficiency ?? 0) - (b.finishing_efficiency ?? 0))[0];
  if (worstFinisher && (worstFinisher.finishing_efficiency ?? 0) < 0) {
    items.push({ text: `${worstFinisher.player_name} G−xG ${worstFinisher.finishing_efficiency.toFixed(2)}`, dir: 'down' });
  }

  if (!items.length) {
    track.innerHTML = '<span class="ticker-item"><span class="sym">TRACKING</span> — not enough matches on file yet for standout reads</span>';
    return;
  }

  const renderItems = (arr) => arr.map(it =>
    `<span class="ticker-item ${it.dir}"><span class="sym">${it.dir === 'up' ? '▲' : '▼'}</span> ${it.text}</span>`
  ).join('');

  // Duplicate the list so the CSS animation (translateX -50%) loops seamlessly.
  track.innerHTML = renderItems(items) + renderItems(items);
}

// ---------- Player search ----------
document.getElementById('search-btn').addEventListener('click', searchPlayer);
document.getElementById('player-search').addEventListener('keypress', e => {
  if (e.key === 'Enter') searchPlayer();
});

async function searchPlayer() {
  const name = document.getElementById('player-search').value.trim();
  const errorEl = document.getElementById('player-error');
  errorEl.textContent = '';
  if (!name) return;

  let url = `${API_BASE}/player/${encodeURIComponent(name)}`;
  if (currentCompetition) {
    url += `?competition_id=${currentCompetition.competition_id}&season_id=${currentCompetition.season_id}`;
  }

  try {
    const resp = await fetch(url);
    const data = await resp.json();
    if (!resp.ok) {
      errorEl.textContent = data.error || 'Player not found.';
      document.getElementById('player-profile').classList.add('hidden');
      return;
    }
    displayPlayer(data);
  } catch (e) {
    errorEl.textContent = 'Could not reach the backend. Is app.py running on port 5000?';
  }
}

function buildVerdict(d) {
  const holdUpGood = d.hold_up_success_rate >= 0.70;
  const clutchGood = d.net_clutch_score > 0;
  const usageLow = d.usage_rate < 8;
  const usageHigh = d.usage_rate >= 12;

  if (holdUpGood && clutchGood && !usageHigh) {
    return "Complete target man profile: holds the ball up reliably and delivers in decisive moments without needing to dominate possession.";
  }
  if (usageLow && clutchGood) {
    return "Hidden-gem profile: low involvement, but decisive when the ball does arrive — possibly undervalued on touch-count alone.";
  }
  if (usageHigh && d.net_clutch_score < 0) {
    return "High-usage, negative clutch score — worth checking whether output depends on a system that may not travel.";
  }
  return "No strong pattern match yet — more matches on file would sharpen this read.";
}

function displayPlayer(data) {
  // Switch to player tab
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  document.querySelector('[data-tab="player"]').classList.add('active');
  document.getElementById('player-tab').classList.add('active');

  document.getElementById('player-profile').classList.remove('hidden');
  document.getElementById('player-name').textContent = data.player_name;
  document.getElementById('player-team').textContent = data.team_name || 'Unknown club';
  document.getElementById('player-verdict').textContent = buildVerdict(data);

  document.getElementById('p-usage').textContent = (data.usage_rate ?? 0).toFixed(1) + '%';
  document.getElementById('p-hold-up').textContent = data.hold_up_attempts
    ? (data.hold_up_success_rate * 100).toFixed(0) + '%'
    : 'n/a';
  document.getElementById('p-hold-up-att').textContent = data.hold_up_attempts || 0;
  document.getElementById('p-clutch').textContent = (data.net_clutch_score ?? 0).toFixed(2);
  document.getElementById('p-wall').textContent = (data.wall_count ?? 0).toFixed(2);

  document.getElementById('p-minutes').textContent = Math.round(data.minutes_played ?? 0);
  document.getElementById('p-matches').textContent = data.matches_played ?? 0;
  document.getElementById('p-goals-per90').textContent = (data.goals_per90 ?? 0).toFixed(2);
  document.getElementById('p-goals-total').textContent = data.goals ?? 0;
  const finishing = data.finishing_efficiency ?? 0;
  const finishingEl = document.getElementById('p-finishing');
  finishingEl.textContent = (finishing >= 0 ? '+' : '') + finishing.toFixed(2);
  finishingEl.style.color = finishing >= 0 ? COLOR_SIGNAL : COLOR_ALERT;
  document.getElementById('p-xg').textContent = (data.xg ?? 0).toFixed(2);

  const ctx1 = document.getElementById('clutchRadar').getContext('2d');
  if (radarChart) radarChart.destroy();
  radarChart = new Chart(ctx1, {
    type: 'radar',
    data: {
      labels: ['Opponent Difficulty', 'Moment Importance', 'Net Clutch', 'Usage Rate', 'Hold-Up %'],
      datasets: [{
        label: data.player_name,
        data: [
          data.avg_goal_difficulty || 0,
          (data.avg_goal_importance || 0) * 10,
          data.net_clutch_score || 0,
          data.usage_rate || 0,
          (data.hold_up_success_rate || 0) * 10,
        ],
        backgroundColor: 'rgba(33,230,161,0.15)',
        borderColor: COLOR_SIGNAL,
        pointBackgroundColor: COLOR_SIGNAL,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: { r: { min: 0, suggestedMax: 10, grid: { color: gridColor }, angleLines: { color: gridColor } } },
      plugins: { legend: { display: false } },
    },
  });

  const ctx2 = document.getElementById('usageBar').getContext('2d');
  if (barChart) barChart.destroy();
  barChart = new Chart(ctx2, {
    type: 'bar',
    data: {
      labels: ['This player', 'League avg (approx.)'],
      datasets: [{
        label: 'Usage Rate (%)',
        data: [data.usage_rate || 0, 6.0],
        backgroundColor: [COLOR_SIGNAL, COLOR_AMBER],
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: { y: { beginAtZero: true, grid: { color: gridColor } }, x: { grid: { display: false } } },
    },
  });
}

// ---------- Players Table ----------
let playersFilterBound = false;

async function loadPlayers() {
  if (!currentCompetition) return;
  const { competition_id, season_id } = currentCompetition;
  const resp = await fetch(`${API_BASE}/players?competition_id=${competition_id}&season_id=${season_id}`);
  allPlayers = await resp.json();
  renderTable();
  // Bind the filter input listener once — re-binding on every tab switch
  // (the original bug) stacked duplicate listeners and made renderTable
  // fire multiple times per keystroke the longer a session ran.
  if (!playersFilterBound) {
    document.getElementById('player-filter').addEventListener('input', renderTable);
    playersFilterBound = true;
  }
}

function renderTable() {
  const filter = document.getElementById('player-filter').value.toLowerCase();
  let filtered = allPlayers.filter(p =>
    p.player_name.toLowerCase().includes(filter) ||
    (p.team_name && p.team_name.toLowerCase().includes(filter))
  );

  // Sort
  const { key, asc } = currentSort;
  filtered.sort((a, b) => {
    let va = a[key] ?? 0, vb = b[key] ?? 0;
    if (typeof va === 'string') va = va.toLowerCase();
    if (typeof vb === 'string') vb = vb.toLowerCase();
    if (va < vb) return asc ? -1 : 1;
    if (va > vb) return asc ? 1 : -1;
    return 0;
  });

  const tbody = document.querySelector('#players-table tbody');
  tbody.innerHTML = filtered.map(p => {
    const checked = selectedPlayers.has(p.player_name) ? 'checked' : '';
    return `<tr data-player="${p.player_name}">
      <td><input type="checkbox" class="player-check" ${checked}></td>
      <td class="clickable">${p.player_name}</td>
      <td>${p.team_name || '-'}</td>
      <td>${p.matches_played}</td>
      <td>${Math.round(p.minutes_played || 0)}</td>
      <td>${p.goals}</td>
      <td>${(p.goals_per90 || 0).toFixed(2)}</td>
      <td>${(p.finishing_efficiency ?? 0) >= 0 ? '+' : ''}${(p.finishing_efficiency ?? 0).toFixed(2)}</td>
      <td>${(p.usage_rate || 0).toFixed(1)}%</td>
      <td>${p.hold_up_success_rate ? (p.hold_up_success_rate * 100).toFixed(0) + '%' : '-'}</td>
      <td>${(p.net_clutch_score || 0).toFixed(2)}</td>
      <td>${(p.shot_creating_actions || 0).toFixed(2)}</td>
    </tr>`;
  }).join('');

  // Click row to load player profile
  tbody.querySelectorAll('tr').forEach(row => {
    row.addEventListener('click', (e) => {
      if (e.target.type === 'checkbox') return;
      const name = row.dataset.player;
      document.getElementById('player-search').value = name;
      searchPlayer();
    });
  });

  // Checkbox handling
  tbody.querySelectorAll('.player-check').forEach(cb => {
    cb.addEventListener('change', (e) => {
      e.stopPropagation();
      const name = e.target.closest('tr').dataset.player;
      if (e.target.checked) selectedPlayers.add(name);
      else selectedPlayers.delete(name);
      updateCompareButton();
    });
  });

  // Select all
  const selectAll = document.getElementById('select-all');
  selectAll.checked = filtered.length > 0 && filtered.every(p => selectedPlayers.has(p.player_name));
  selectAll.addEventListener('change', () => {
    const checked = selectAll.checked;
    filtered.forEach(p => {
      if (checked) selectedPlayers.add(p.player_name);
      else selectedPlayers.delete(p.player_name);
    });
    renderTable(); // re-render to update checkboxes
  });

  updateCompareButton();
}

function updateCompareButton() {
  const count = selectedPlayers.size;
  document.getElementById('selection-count').textContent = `${count} selected`;
  document.getElementById('compare-btn').disabled = count !== 2;
}

// Table sorting
document.querySelector('#players-table thead').addEventListener('click', (e) => {
  const th = e.target.closest('th[data-sort]');
  if (!th) return;
  const key = th.dataset.sort;
  if (currentSort.key === key) currentSort.asc = !currentSort.asc;
  else { currentSort.key = key; currentSort.asc = true; }
  renderTable();
});

// Compare button
document.getElementById('compare-btn').addEventListener('click', () => {
  if (selectedPlayers.size !== 2) return;
  const [p1, p2] = [...selectedPlayers];
  const data1 = allPlayers.find(p => p.player_name === p1);
  const data2 = allPlayers.find(p => p.player_name === p2);
  if (!data1 || !data2) return;
  showCompareModal(data1, data2);
});

function showCompareModal(p1, p2) {
  const container = document.getElementById('compare-container');
  const metrics = [
    { key: 'matches_played', label: 'Matches' },
    { key: 'minutes_played', label: 'Minutes', fmt: v => Math.round(v || 0) },
    { key: 'goals', label: 'Goals' },
    { key: 'goals_per90', label: 'Goals/90', fmt: v => (v || 0).toFixed(2) },
    { key: 'xg', label: 'xG', fmt: v => (v || 0).toFixed(2) },
    { key: 'finishing_efficiency', label: 'Finishing (G−xG)', fmt: v => ((v ?? 0) >= 0 ? '+' : '') + (v ?? 0).toFixed(2) },
    { key: 'usage_rate', label: 'Usage %', fmt: v => (v || 0).toFixed(1) + '%' },
    { key: 'hold_up_success_rate', label: 'Hold-Up %', fmt: v => v ? (v * 100).toFixed(0) + '%' : '-' },
    { key: 'net_clutch_score', label: 'Clutch Score', fmt: v => (v || 0).toFixed(2) },
    { key: 'shot_creating_actions', label: 'SCA/90', fmt: v => (v || 0).toFixed(2) },
    { key: 'avg_goal_difficulty', label: 'Avg Difficulty', fmt: v => (v || 0).toFixed(2) },
    { key: 'avg_goal_importance', label: 'Avg Importance', fmt: v => (v || 0).toFixed(2) },
    { key: 'weighted_goals', label: 'Weighted Goals', fmt: v => (v || 0).toFixed(2) },
    { key: 'wall_count', label: 'Wall Actions', fmt: v => (v || 0).toFixed(2) },
  ];

  let html = `<table class="compare-table">
    <thead><tr><th>Metric</th><th>${p1.player_name}</th><th>${p2.player_name}</th></tr></thead><tbody>`;
  metrics.forEach(m => {
    const v1 = m.fmt ? m.fmt(p1[m.key]) : p1[m.key];
    const v2 = m.fmt ? m.fmt(p2[m.key]) : p2[m.key];
    html += `<tr><td>${m.label}</td><td>${v1}</td><td>${v2}</td></tr>`;
  });
  html += `</tbody></table>`;
  container.innerHTML = html;
  document.getElementById('compare-modal').classList.remove('hidden');
}

// Close modal
document.querySelector('.close-modal').addEventListener('click', () => {
  document.getElementById('compare-modal').classList.add('hidden');
});
window.addEventListener('click', (e) => {
  if (e.target === document.getElementById('compare-modal')) {
    document.getElementById('compare-modal').classList.add('hidden');
  }
});

// ---------- League scatter + leaderboards ----------
async function loadScatterData() {
  if (!currentCompetition) return;
  const { competition_id, season_id } = currentCompetition;
  const resp = await fetch(`${API_BASE}/league_scatter?competition_id=${competition_id}&season_id=${season_id}`);
  const data = await resp.json();
  renderScatter(data);
  renderTopScorers(data);
  renderFinishingLeaderboard(data);
  renderClutchLeaderboard(data);
  renderUsageFinishingBubble(data);
}

function renderScatter(data) {
  const ctx1 = document.getElementById('scatterClutch').getContext('2d');
  if (scatterClutchChart) scatterClutchChart.destroy();
  scatterClutchChart = new Chart(ctx1, {
    type: 'scatter',
    data: {
      datasets: [{
        label: 'Players',
        data: data.map(p => ({ x: p.avg_difficulty, y: p.avg_importance })),
        backgroundColor: 'rgba(33,230,161,0.65)',
        pointRadius: 6,
        pointHoverRadius: 9,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: { title: { display: true, text: 'Avg Opponent Difficulty (1-7)' }, min: 0, max: 7, grid: { color: gridColor } },
        y: { title: { display: true, text: 'Avg Moment Importance' }, grid: { color: gridColor } },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => {
              const p = data[ctx.dataIndex];
              return `${p.player} (${p.team}) — net clutch ${p.net_clutch.toFixed(2)}`;
            },
          },
        },
      },
    },
  });

  const ctx2 = document.getElementById('scatterUsage').getContext('2d');
  if (scatterUsageChart) scatterUsageChart.destroy();
  scatterUsageChart = new Chart(ctx2, {
    type: 'scatter',
    data: {
      datasets: [{
        label: 'Usage vs Goals',
        data: data.map(p => ({ x: p.usage_rate, y: p.goals })),
        backgroundColor: 'rgba(255,183,3,0.75)',
        pointRadius: 6,
        pointHoverRadius: 9,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: { title: { display: true, text: 'Usage Rate (%)' }, grid: { color: gridColor } },
        y: { title: { display: true, text: 'Goals' }, grid: { color: gridColor } },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => {
              const p = data[ctx.dataIndex];
              return `${p.player} (${p.team})`;
            },
          },
        },
      },
    },
  });
}

// Top Scorers — horizontal bar, top 10 by goals.
function renderTopScorers(data) {
  const top = [...data].sort((a, b) => b.goals - a.goals).slice(0, 10);
  const ctx = document.getElementById('topScorersChart').getContext('2d');
  if (topScorersChart) topScorersChart.destroy();
  topScorersChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: top.map(p => p.player),
      datasets: [{
        label: 'Goals',
        data: top.map(p => p.goals),
        backgroundColor: COLOR_SIGNAL,
        borderRadius: 2,
      }],
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { afterLabel: ctx => `Team: ${top[ctx.dataIndex].team}` } },
      },
      scales: {
        x: { beginAtZero: true, grid: { color: gridColor }, ticks: { precision: 0 } },
        y: { grid: { display: false } },
      },
    },
  });
}

// Finishing leaderboard — diverging bar of G - xG, biggest over/under performers.
function renderFinishingLeaderboard(data) {
  const sorted = [...data].sort((a, b) => b.finishing_efficiency - a.finishing_efficiency);
  const top = sorted.slice(0, 5);
  const bottom = sorted.slice(-5).reverse();
  // Avoid double-counting players who'd land in both slices on tiny datasets.
  const combined = [...top, ...bottom.filter(p => !top.includes(p))];

  const ctx = document.getElementById('finishingChart').getContext('2d');
  if (finishingChart) finishingChart.destroy();
  finishingChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: combined.map(p => p.player),
      datasets: [{
        label: 'G − xG',
        data: combined.map(p => p.finishing_efficiency),
        backgroundColor: combined.map(p => p.finishing_efficiency >= 0 ? COLOR_SIGNAL : COLOR_ALERT),
        borderRadius: 2,
      }],
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => `G−xG: ${ctx.raw >= 0 ? '+' : ''}${ctx.raw.toFixed(2)}`,
            afterLabel: ctx => `Team: ${combined[ctx.dataIndex].team}`,
          },
        },
      },
      scales: {
        x: { grid: { color: gridColor } },
        y: { grid: { display: false } },
      },
    },
  });
}

// Clutch leaderboard — top 10 by net clutch score, colored by sign.
function renderClutchLeaderboard(data) {
  const top = [...data].sort((a, b) => b.net_clutch - a.net_clutch).slice(0, 10);
  const ctx = document.getElementById('clutchLeaderboardChart').getContext('2d');
  if (clutchLeaderboardChart) clutchLeaderboardChart.destroy();
  clutchLeaderboardChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: top.map(p => p.player),
      datasets: [{
        label: 'Net Clutch',
        data: top.map(p => p.net_clutch),
        backgroundColor: top.map(p => p.net_clutch >= 0 ? COLOR_AMBER : COLOR_ALERT),
        borderRadius: 2,
      }],
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { afterLabel: ctx => `Team: ${top[ctx.dataIndex].team}` } },
      },
      scales: {
        x: { grid: { color: gridColor } },
        y: { grid: { display: false } },
      },
    },
  });
}

// Usage vs Finishing — bubble scatter, radius scaled by goals scored.
function renderUsageFinishingBubble(data) {
  const ctx = document.getElementById('usageFinishingChart').getContext('2d');
  if (usageFinishingChart) usageFinishingChart.destroy();
  usageFinishingChart = new Chart(ctx, {
    type: 'bubble',
    data: {
      datasets: [{
        label: 'Players',
        data: data.map(p => ({
          x: p.usage_rate,
          y: p.finishing_efficiency,
          r: Math.max(4, Math.min(18, 4 + p.goals * 2.5)),
        })),
        backgroundColor: 'rgba(33,230,161,0.45)',
        borderColor: COLOR_SIGNAL,
        borderWidth: 1,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: ctx => {
              const p = data[ctx.dataIndex];
              return `${p.player} (${p.team}) — ${p.goals} G, G−xG ${p.finishing_efficiency >= 0 ? '+' : ''}${p.finishing_efficiency.toFixed(2)}`;
            },
          },
        },
      },
      scales: {
        x: { title: { display: true, text: 'Usage Rate (%)' }, grid: { color: gridColor } },
        y: { title: { display: true, text: 'Finishing (G − xG)' }, grid: { color: gridColor } },
      },
    },
  });
}

// ---------- Team structure ----------
async function loadTeamStructure() {
  if (!currentCompetition) return;
  const { competition_id, season_id } = currentCompetition;
  const resp = await fetch(`${API_BASE}/team_structure?competition_id=${competition_id}&season_id=${season_id}`);
  const data = await resp.json();
  const tbody = document.querySelector('#team-table tbody');
  tbody.innerHTML = data.map(team => `
    <tr>
      <td>${team.team_name}</td>
      <td>${team.top_usage_player}</td>
      <td>${team.heliocentricity.toFixed(2)}</td>
      <td>${team.creativity_gap.toFixed(2)}</td>
      <td>${team.heliocentricity > 10 ? 'Star-dependent' : 'Distributed system'}</td>
    </tr>
  `).join('');
}

// ---------- Player Leap ----------
function loadLeapSeasonPickers() {
  const s1 = document.getElementById('leap-season1');
  const s2 = document.getElementById('leap-season2');
  if (!allCompetitions.length) return;

  // Only offer seasons from the SAME competition_id as the one currently
  // selected up top, since player_leap only ever compares within a league.
  const competitionId = currentCompetition ? currentCompetition.competition_id : allCompetitions[0].competition_id;
  const sameLeague = allCompetitions
    .filter(c => c.competition_id === competitionId)
    .sort((a, b) => a.season_id - b.season_id);

  const options = sameLeague.map(c =>
    `<option value="${c.season_id}">${c.label}</option>`
  ).join('');
  s1.innerHTML = options;
  s2.innerHTML = options;

  if (sameLeague.length >= 2) {
    s1.value = sameLeague[0].season_id;
    s2.value = sameLeague[sameLeague.length - 1].season_id;
  }

  s1.onchange = loadLeapData;
  s2.onchange = loadLeapData;
  loadLeapData();
}

async function loadLeapData() {
  const s1 = document.getElementById('leap-season1');
  const s2 = document.getElementById('leap-season2');
  const emptyMsg = document.getElementById('leap-empty');
  if (!s1.value || !s2.value || !currentCompetition) return;

  const competitionId = currentCompetition.competition_id;
  const resp = await fetch(
    `${API_BASE}/player_leap?competition_id=${competitionId}&season1=${s1.value}&season2=${s2.value}`
  );
  const data = await resp.json();

  const tbody = document.querySelector('#leap-table tbody');
  if (!data.length) {
    tbody.innerHTML = '';
    emptyMsg.classList.remove('hidden');
    return;
  }
  emptyMsg.classList.add('hidden');

  data.sort((a, b) => (b.delta_usage ?? 0) - (a.delta_usage ?? 0));
  tbody.innerHTML = data.map(p => `
    <tr>
      <td>${p.player_name}</td>
      <td>${(p.usage_1 ?? 0).toFixed(1)}% → ${(p.usage_2 ?? 0).toFixed(1)}%</td>
      <td>${(p.delta_usage ?? 0) >= 0 ? '+' : ''}${(p.delta_usage ?? 0).toFixed(1)}</td>
      <td>${(p.sca_1 ?? 0).toFixed(2)} → ${(p.sca_2 ?? 0).toFixed(2)}</td>
      <td>${(p.delta_sca ?? 0) >= 0 ? '+' : ''}${(p.delta_sca ?? 0).toFixed(2)}</td>
      <td>${p.leap_category}</td>
    </tr>
  `).join('');
}

// ---------- Init ----------
window.addEventListener('DOMContentLoaded', loadCompetitions);
