/* StreakBoard — frontend logic */

let dashboardData = null;

const DAY_LABELS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

// ── Toast ──────────────────────────────────────────────────────────────────

const toast = (() => {
  const el = document.createElement('div');
  el.className = 'toast';
  document.body.appendChild(el);
  let timer;
  return (msg) => {
    el.textContent = msg;
    el.classList.add('show');
    clearTimeout(timer);
    timer = setTimeout(() => el.classList.remove('show'), 2000);
  };
})();

// ── API helpers ────────────────────────────────────────────────────────────

async function api(method, path, body) {
  const opts = {
    method,
    headers: { 'Content-Type': 'application/json' },
  };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const res = await fetch(path, opts);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || 'Request failed');
  }
  if (res.status === 204) return null;
  return res.json();
}

// ── Load & render dashboard ────────────────────────────────────────────────

async function loadDashboard() {
  try {
    dashboardData = await api('GET', '/api/dashboard');
    render(dashboardData);
    document.getElementById('loading').style.display = 'none';
    document.getElementById('main').style.display = '';
  } catch (e) {
    document.getElementById('loading').textContent = 'Failed to load dashboard. Is the server running?';
  }
}

function render(data) {
  // Header date
  const d = new Date(data.today + 'T00:00:00');
  document.getElementById('today-label').textContent =
    d.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' });

  const goals  = data.trackables.filter(t => t.type === 'daily_goal');
  const deep   = data.trackables.filter(t => t.type === 'deep_work');
  const habits = data.trackables.filter(t => t.type === 'habit');

  renderList('daily-goal-list', goals, false);
  renderList('deep-work-list',  deep,  false);
  renderList('habits-list',     habits, true);

  renderWeeklySummary(data.weekly_summary, data.trackables, data.today);
}

// ── Trackable list ─────────────────────────────────────────────────────────

function renderList(containerId, trackables, canDelete) {
  const container = document.getElementById(containerId);
  container.innerHTML = '';
  if (trackables.length === 0) {
    container.innerHTML = '<p class="loading" style="padding:0.5rem 0">None yet.</p>';
    return;
  }
  trackables.forEach(t => container.appendChild(buildCard(t, canDelete)));
}

function buildCard(t, canDelete) {
  const today = dashboardData.today;
  const ci = t.today_checkin;

  const card = document.createElement('div');
  card.className = 'card';
  card.dataset.id = t.id;

  // ── Top row ──
  const top = document.createElement('div');
  top.className = 'card-top';

  // Check button
  const checkBtn = document.createElement('button');
  checkBtn.className = 'check-btn' + (ci.completed ? ' checked' : '');
  checkBtn.innerHTML = ci.completed ? '✓' : '';
  checkBtn.title = ci.completed ? 'Mark incomplete' : 'Mark complete';
  checkBtn.addEventListener('click', () => toggleCheckin(t, !ci.completed));

  // Name
  const name = document.createElement('span');
  name.className = 'card-name' + (ci.completed ? ' done' : '');
  name.textContent = t.name;

  // Streaks
  const streaks = document.createElement('div');
  streaks.className = 'streaks';
  streaks.innerHTML =
    `<span class="streak-badge streak-badge--current">🔥 ${t.current_streak} day${t.current_streak !== 1 ? 's' : ''}</span>` +
    `<span class="streak-badge streak-badge--best">🏆 ${t.best_streak}</span>`;

  top.appendChild(checkBtn);
  top.appendChild(name);
  top.appendChild(streaks);

  if (canDelete) {
    const del = document.createElement('button');
    del.className = 'delete-btn';
    del.title = 'Remove habit';
    del.innerHTML = '✕';
    del.addEventListener('click', () => deleteHabit(t.id));
    top.appendChild(del);
  }

  card.appendChild(top);

  // ── 7-day row ──
  const weekRow = document.createElement('div');
  weekRow.className = 'week-row';
  t.last_7_days.forEach(day => {
    const dot = document.createElement('div');
    const dayLabel = DAY_LABELS[new Date(day.date + 'T00:00:00').getDay()];
    if (day.status === 'completed') {
      dot.className = 'day-dot day-dot--completed';
      dot.textContent = '✓';
    } else if (day.status === 'today_pending') {
      dot.className = 'day-dot day-dot--pending';
      dot.textContent = '○';
    } else {
      dot.className = 'day-dot day-dot--missed';
      dot.textContent = '✗';
    }
    const lbl = document.createElement('span');
    lbl.className = 'dot-label';
    lbl.textContent = dayLabel;
    dot.appendChild(lbl);
    weekRow.appendChild(dot);
  });
  card.appendChild(weekRow);

  // ── Notes ──
  const notesWrap = document.createElement('div');
  notesWrap.className = 'notes-wrap';
  const notesInput = document.createElement('textarea');
  notesInput.className = 'notes-input';
  notesInput.placeholder = 'Add a note for today (optional)…';
  notesInput.value = ci.notes || '';
  let noteTimer;
  notesInput.addEventListener('input', () => {
    clearTimeout(noteTimer);
    noteTimer = setTimeout(() => saveNotes(t, notesInput.value), 700);
  });
  notesWrap.appendChild(notesInput);
  card.appendChild(notesWrap);

  return card;
}

// ── Actions ────────────────────────────────────────────────────────────────

async function toggleCheckin(t, newCompleted) {
  const today = dashboardData.today;
  try {
    await api('POST', '/api/checkins', {
      trackable_id: t.id,
      date: today,
      completed: newCompleted,
      notes: t.today_checkin.notes || '',
    });
    await loadDashboard();
  } catch (e) {
    toast('Could not save. Try again.');
  }
}

async function saveNotes(t, notes) {
  const today = dashboardData.today;
  try {
    await api('POST', '/api/checkins', {
      trackable_id: t.id,
      date: today,
      completed: t.today_checkin.completed,
      notes,
    });
    toast('Note saved');
  } catch (e) {
    toast('Could not save note.');
  }
}

async function addHabit(name) {
  try {
    await api('POST', '/api/trackables', { name, type: 'habit' });
    await loadDashboard();
    toast(`"${name}" added!`);
  } catch (e) {
    toast('Could not add habit.');
  }
}

async function deleteHabit(id) {
  const t = dashboardData.trackables.find(x => x.id === id);
  if (!t) return;
  if (!confirm(`Remove "${t.name}"? You can always restart today.`)) return;
  try {
    await api('DELETE', `/api/trackables/${id}`);
    await loadDashboard();
    toast('Habit removed.');
  } catch (e) {
    toast('Could not remove habit.');
  }
}

// ── Weekly summary ─────────────────────────────────────────────────────────

function renderWeeklySummary(summary, trackables, today) {
  const wrap = document.getElementById('weekly-summary');
  wrap.innerHTML = `
    <div class="weekly-stats">
      <div class="stat-pill green">
        <span class="stat-value">${summary.total_completed}</span>
        <span class="stat-label">Completed</span>
      </div>
      <div class="stat-pill">
        <span class="stat-value">${summary.total_possible}</span>
        <span class="stat-label">Possible</span>
      </div>
      <div class="stat-pill blue">
        <span class="stat-value">${summary.completion_pct}%</span>
        <span class="stat-label">This week</span>
      </div>
    </div>
  `;

  // Build heatmap table
  const tableWrap = document.getElementById('weekly-table-wrap');
  const todayD = new Date(today + 'T00:00:00');
  const dateHeaders = [];
  for (let i = 6; i >= 0; i--) {
    const d = new Date(todayD);
    d.setDate(d.getDate() - i);
    dateHeaders.push({
      date: d.toISOString().slice(0, 10),
      label: DAY_LABELS[d.getDay()],
    });
  }

  const table = document.createElement('table');
  table.className = 'week-table';

  // Header row
  const thead = table.createTHead();
  const hRow = thead.insertRow();
  const thName = document.createElement('th');
  thName.textContent = 'Habit / Goal';
  hRow.appendChild(thName);
  dateHeaders.forEach(h => {
    const th = document.createElement('th');
    th.textContent = h.label;
    hRow.appendChild(th);
  });

  // Data rows
  const tbody = table.createTBody();
  trackables.forEach(t => {
    const row = tbody.insertRow();
    const nameCell = row.insertCell();
    nameCell.textContent = t.name;

    const dayMap = {};
    t.last_7_days.forEach(d => { dayMap[d.date] = d.status; });

    dateHeaders.forEach(h => {
      const cell = row.insertCell();
      const status = dayMap[h.date] || 'missed';
      if (status === 'completed') {
        cell.innerHTML = '<span class="cell-done">✓</span>';
      } else if (status === 'today_pending') {
        cell.innerHTML = '<span class="cell-pending">○</span>';
      } else {
        cell.innerHTML = '<span class="cell-missed">✗</span>';
      }
    });
  });

  tableWrap.innerHTML = '';
  tableWrap.appendChild(table);
}

// ── Add habit form ─────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  loadDashboard();

  document.getElementById('add-habit-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const input = document.getElementById('new-habit-name');
    const name = input.value.trim();
    if (!name) return;
    input.value = '';
    await addHabit(name);
  });
});
