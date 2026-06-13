/* StreakBoard — frontend logic */

const DAYS    = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
const PALETTE = ['#7c3aed','#06b6d4','#10b981','#f59e0b','#f43f5e','#8b5cf6','#ec4899','#14b8a6','#f97316'];

let dashData      = null;
let monthlyChart  = null;
let sixmonthChart = null;

// ── Utilities ──────────────────────────────────────────────────────────────

function esc(s) {
  if (!s) return '';
  return String(s)
    .replace(/&/g,'&amp;')
    .replace(/</g,'&lt;')
    .replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;');
}

function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

function showToast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), 2400);
}

async function api(method, path, body) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const res = await fetch(path, opts);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Request failed');
  }
  if (res.status === 204) return null;
  return res.json();
}

// ── Boot ───────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  // Date label
  document.getElementById('nav-date').textContent =
    new Date().toLocaleDateString('en-US', { weekday:'long', month:'long', day:'numeric' });

  // Tabs
  document.querySelectorAll('.nav-tab').forEach(btn => {
    btn.addEventListener('click', () => switchTab(btn.dataset.tab));
  });

  // Modal enter key
  document.getElementById('new-section-name').addEventListener('keydown', e => {
    if (e.key === 'Enter') addSection();
  });

  // Close modal on overlay click
  document.getElementById('add-section-modal').addEventListener('click', e => {
    if (e.target === e.currentTarget) closeModal('add-section-modal');
  });

  // Chat enter key
  document.getElementById('chat-input').addEventListener('keydown', e => {
    if (e.key === 'Enter') sendChat();
  });

  // Escape closes modals
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      document.querySelectorAll('.modal-overlay').forEach(m => m.style.display = 'none');
    }
  });

  loadDashboard();
});

// ── Tabs ───────────────────────────────────────────────────────────────────

function switchTab(tab) {
  document.querySelectorAll('.nav-tab').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.toggle('active', p.id === 'tab-' + tab));
  if (tab === 'monthly')   loadMonthlyChart();
  if (tab === 'analytics') loadSixMonthChart();
}

// ── Dashboard ──────────────────────────────────────────────────────────────

async function loadDashboard() {
  document.getElementById('loading').style.display = 'block';
  try {
    dashData = await api('GET', '/api/dashboard');
    renderDashboard(dashData);
  } catch {
    document.getElementById('loading').textContent = 'Failed to load. Is the server running?';
    return;
  }
  document.getElementById('loading').style.display = 'none';
}

function renderDashboard({ sections, trackables }) {
  const container = document.getElementById('sections-container');
  container.innerHTML = '';

  // Group habits by section
  const bySection = {};
  trackables.forEach(t => {
    const k = t.section_id ?? '__none__';
    (bySection[k] ??= []).push(t);
  });

  sections.forEach(s => container.appendChild(buildSection(s, bySection[s.id] ?? [])));

  // Orphaned habits (no section_id) — shown as a non-deletable "Uncategorized" group
  const orphans = bySection['__none__'] ?? [];
  if (orphans.length > 0) {
    container.appendChild(buildSection({ id: '__none__', name: 'Uncategorized' }, orphans, true));
  }

  // Weekly panel
  const panel = document.getElementById('weekly-panel');
  if (trackables.length > 0) {
    renderWeeklyPanel(trackables);
    panel.style.display = '';
  } else {
    panel.style.display = 'none';
  }
}

// ── Section block ──────────────────────────────────────────────────────────

function buildSection(section, habits, isOrphanGroup = false) {
  const wrap = document.createElement('div');
  wrap.className = 'section-block';

  wrap.innerHTML = `
    <div class="section-header">
      <div class="section-name">
        <span class="section-dot"></span>
        ${esc(section.name)}
      </div>
      ${!isOrphanGroup ? `<button class="icon-btn" title="Delete section" data-section-id="${section.id}">&#x2715;</button>` : ''}
    </div>
    <div class="habits-list" id="hl-${section.id}">
      ${habits.length === 0 ? '<div class="empty-section">No habits yet — add one below</div>' : ''}
    </div>
    ${!isOrphanGroup ? `
    <div class="add-habit-row">
      <input class="habit-name-input" id="hi-${section.id}" type="text" placeholder="New habit name…" autocomplete="off" />
      <select class="interval-select" id="iv-${section.id}">
        <option value="daily">Daily</option>
        <option value="weekly">Weekly</option>
      </select>
      <button class="btn-add" data-sid="${section.id}">+ Add</button>
    </div>` : ''}
  `;

  // Populate habits
  const list = wrap.querySelector(`#hl-${section.id}`);
  habits.forEach(h => list.appendChild(buildCard(h)));

  // Delete section
  if (!isOrphanGroup) {
    wrap.querySelector('.icon-btn').addEventListener('click', () => deleteSection(section.id));
  }

  // Add habit button / enter key (not shown for orphan group)
  if (!isOrphanGroup) {
    wrap.querySelector('.btn-add').addEventListener('click', () => addHabit(section.id));
    wrap.querySelector(`#hi-${section.id}`).addEventListener('keydown', e => {
      if (e.key === 'Enter') addHabit(section.id);
    });
  }

  return wrap;
}

// ── Habit card ─────────────────────────────────────────────────────────────

function buildCard(t) {
  const today = dashData.today;
  const ci    = t.today_checkin;

  const card = document.createElement('div');
  card.className = 'card';

  const intervalLabel = t.interval === 'weekly' ? 'Weekly' : 'Daily';
  const streakText    = t.current_streak > 0 ? `🔥 ${t.current_streak}` : '—';
  const bestText      = `⭐ ${t.best_streak}`;

  // Build day-dots HTML
  const todayD = new Date();
  const dotItems = t.last_7_days.map((status, i) => {
    const d = new Date(todayD);
    d.setDate(todayD.getDate() - (6 - i));
    const dayLabel = DAYS[d.getDay()];
    const sym = status === 'completed' ? '✓' : status === 'missed' ? '✗' : '○';
    return `<div class="day-dot ${status}" title="${dayLabel}">${sym}</div>`;
  }).join('');

  card.innerHTML = `
    <div class="card-top">
      <button class="check-btn ${ci.completed ? 'checked' : ''}" title="${ci.completed ? 'Mark incomplete' : 'Mark complete'}">✓</button>
      <span class="card-name">${esc(t.name)}</span>
      <div class="card-badges">
        <span class="badge badge-interval">${intervalLabel}</span>
        <span class="badge badge-streak">${streakText}</span>
        <span class="badge badge-best">${bestText}</span>
      </div>
      <button class="delete-btn" title="Remove habit">&#x00D7;</button>
    </div>
    <div class="day-dots">${dotItems}</div>
    <textarea class="notes-input" placeholder="Add a note for today…">${esc(ci.notes || '')}</textarea>
  `;

  card.querySelector('.check-btn').addEventListener('click', () => toggleCheckin(t, !ci.completed));
  card.querySelector('.delete-btn').addEventListener('click', () => deleteHabit(t.id));
  card.querySelector('.notes-input').addEventListener('input', debounce(e => saveNotes(t, e.target.value), 700));

  return card;
}

// ── Checkin actions ────────────────────────────────────────────────────────

async function toggleCheckin(t, newCompleted) {
  try {
    await api('POST', '/api/checkins', {
      trackable_id: t.id,
      date: dashData.today,
      completed: newCompleted,
      notes: t.today_checkin.notes || '',
    });
    loadDashboard();
  } catch {
    showToast('Could not save. Try again.');
  }
}

async function saveNotes(t, notes) {
  try {
    await api('POST', '/api/checkins', {
      trackable_id: t.id,
      date: dashData.today,
      completed: t.today_checkin.completed,
      notes,
    });
    showToast('Note saved');
  } catch {
    showToast('Could not save note.');
  }
}

// ── Add / delete habit ─────────────────────────────────────────────────────

async function addHabit(sectionId) {
  const nameInput  = document.getElementById(`hi-${sectionId}`);
  const ivSelect   = document.getElementById(`iv-${sectionId}`);
  const name       = nameInput.value.trim();
  if (!name) return;
  try {
    await api('POST', '/api/trackables', {
      name,
      section_id: sectionId,
      interval: ivSelect.value,
    });
    nameInput.value = '';
    loadDashboard();
    showToast(`"${name}" added!`);
  } catch {
    showToast('Could not add habit.');
  }
}

async function deleteHabit(id) {
  const t = dashData.trackables.find(x => x.id === id);
  if (!t || !confirm(`Remove "${t.name}"?`)) return;
  try {
    await api('DELETE', `/api/trackables/${id}`);
    loadDashboard();
    showToast('Habit removed.');
  } catch {
    showToast('Could not remove habit.');
  }
}

// ── Add / delete section ───────────────────────────────────────────────────

function showModal(id) {
  document.getElementById(id).style.display = 'flex';
  const input = document.querySelector(`#${id} input`);
  if (input) setTimeout(() => input.focus(), 60);
}

function closeModal(id) {
  document.getElementById(id).style.display = 'none';
}

async function addSection() {
  const input = document.getElementById('new-section-name');
  const name  = input.value.trim();
  if (!name) return;
  try {
    await api('POST', '/api/sections', { name });
    input.value = '';
    closeModal('add-section-modal');
    loadDashboard();
    showToast('Section created!');
  } catch {
    showToast('Could not create section.');
  }
}

async function deleteSection(id) {
  const s = dashData.sections.find(x => x.id === id);
  if (!s || !confirm(`Delete section "${s.name}" and all its habits?`)) return;
  try {
    await api('DELETE', `/api/sections/${id}`);
    loadDashboard();
    showToast('Section deleted.');
  } catch {
    showToast('Could not delete section.');
  }
}

// ── Weekly panel ───────────────────────────────────────────────────────────

function renderWeeklyPanel(trackables) {
  const todayD = new Date();
  const headers = Array.from({ length: 7 }, (_, i) => {
    const d = new Date(todayD);
    d.setDate(todayD.getDate() - (6 - i));
    return { label: DAYS[d.getDay()] };
  });

  let done = 0, possible = 0;
  trackables.forEach(t => {
    t.last_7_days.forEach(s => {
      if (s !== 'future') {
        possible++;
        if (s === 'completed') done++;
      }
    });
  });
  const pct = possible ? Math.round(done / possible * 100) : 0;

  document.getElementById('stat-pills').innerHTML = `
    <div class="stat-pill"><span class="pill-value">${done}</span><span class="pill-label">Completed</span></div>
    <div class="stat-pill"><span class="pill-value">${possible}</span><span class="pill-label">Possible</span></div>
    <div class="stat-pill"><span class="pill-value">${pct}%</span><span class="pill-label">Rate</span></div>
  `;

  let html = '<thead><tr><th>Habit</th>';
  headers.forEach(h => { html += `<th>${h.label}</th>`; });
  html += '</tr></thead><tbody>';
  trackables.forEach(t => {
    html += `<tr><td>${esc(t.name)}</td>`;
    t.last_7_days.forEach(s => {
      if (s === 'completed') html += '<td class="wc-done">✓</td>';
      else if (s === 'missed') html += '<td class="wc-miss">✗</td>';
      else html += '<td class="wc-pend">○</td>';
    });
    html += '</tr>';
  });
  html += '</tbody>';
  document.getElementById('week-table').innerHTML = html;
}

// ── Charts ─────────────────────────────────────────────────────────────────

const chartDefaults = {
  plugins: {
    legend: { labels: { color: '#94a3b8', font: { family: 'Plus Jakarta Sans', size: 13 }, padding: 20 } }
  },
  scales: {
    x: { ticks: { color: '#94a3b8' }, grid: { color: 'rgba(255,255,255,0.05)' } },
    y: { ticks: { color: '#94a3b8', stepSize: 1 }, grid: { color: 'rgba(255,255,255,0.05)' }, beginAtZero: true }
  }
};

async function loadMonthlyChart() {
  try {
    const data = await api('GET', '/api/analytics/monthly');
    if (monthlyChart) monthlyChart.destroy();
    monthlyChart = new Chart(
      document.getElementById('monthly-chart').getContext('2d'),
      {
        type: 'bar',
        data: {
          labels: data.labels,
          datasets: data.habits.map((h, i) => ({
            label: h.name,
            data: h.counts,
            backgroundColor: PALETTE[i % PALETTE.length] + 'aa',
            borderColor:     PALETTE[i % PALETTE.length],
            borderWidth: 2,
            borderRadius: 8,
          })),
        },
        options: { responsive: true, ...chartDefaults },
      }
    );
  } catch {
    showToast('Error loading monthly chart.');
  }
}

async function loadSixMonthChart() {
  try {
    const data = await api('GET', '/api/analytics/sixmonth');
    if (sixmonthChart) sixmonthChart.destroy();
    sixmonthChart = new Chart(
      document.getElementById('sixmonth-chart').getContext('2d'),
      {
        type: 'line',
        data: {
          labels: data.labels,
          datasets: data.habits.map((h, i) => ({
            label: h.name,
            data: h.counts,
            borderColor:     PALETTE[i % PALETTE.length],
            backgroundColor: PALETTE[i % PALETTE.length] + '22',
            borderWidth: 2,
            pointRadius: 5,
            pointHoverRadius: 7,
            tension: 0.4,
            fill: true,
          })),
        },
        options: { responsive: true, ...chartDefaults },
      }
    );
  } catch {
    showToast('Error loading analytics chart.');
  }
}

// ── Chatbot ────────────────────────────────────────────────────────────────

function toggleChat() {
  const panel = document.getElementById('chat-panel');
  panel.style.display = panel.style.display === 'none' || !panel.style.display ? 'flex' : 'none';
}

async function sendChat() {
  const input = document.getElementById('chat-input');
  const msg   = input.value.trim();
  if (!msg) return;
  input.value = '';

  appendBubble(msg, 'user');
  const typing = appendBubble('StreakBot is thinking…', 'typing');

  try {
    const data = await api('POST', '/api/chat', { message: msg });
    typing.remove();
    appendBubble(data.reply, 'bot');
  } catch (e) {
    typing.remove();
    const errMsg = e.message.includes('GROQ_API_KEY')
      ? 'GROQ_API_KEY is not set on the server.'
      : 'Something went wrong. Please try again.';
    appendBubble(errMsg, 'bot');
  }
}

function appendBubble(text, type) {
  const messages = document.getElementById('chat-messages');
  const el = document.createElement('div');
  el.className = `bubble ${type}`;
  el.textContent = text;
  messages.appendChild(el);
  messages.scrollTop = messages.scrollHeight;
  return el;
}
