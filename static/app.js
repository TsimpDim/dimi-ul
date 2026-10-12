const state = {
  config: null,
  active: null,
  lastDone: {},
  currentView: "home",
  workout: null,
  charts: {},
  sheetPool: null,
};

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

function escapeHtml(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function toast(msg) {
  const el = $("#toast");
  el.textContent = msg;
  el.classList.add("is-visible");
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove("is-visible"), 1400);
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (res.status === 401) {
    window.location.href = "/login";
    throw new Error("unauthorized");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || "Request failed");
  return data;
}

function setAccent(el, color) {
  if (!color) return;
  el.style.setProperty("--accent", color);
  el.style.setProperty("--accent-soft", color + "22");
}

/* ------------------------------------------------------------------ */
/* Navigation                                                          */
/* ------------------------------------------------------------------ */
function showView(name) {
  state.currentView = name;
  $$(".view").forEach((v) => v.classList.toggle("is-active", v.id === `view-${name}`));
  $$(".nav-btn").forEach((b) => b.classList.toggle("is-active", b.dataset.view === name));
  window.scrollTo({ top: 0 });
}

/* ------------------------------------------------------------------ */
/* Home                                                                */
/* ------------------------------------------------------------------ */
async function loadHome() {
  const [config, active, lastDone] = await Promise.all([
    api("/api/config"),
    api("/api/workouts/active"),
    api("/api/last-per-template"),
  ]);
  state.config = config;
  state.active = active.active;
  state.lastDone = lastDone;
  renderActiveCard();
  renderTemplates();
}

function renderActiveCard() {
  const el = $("#active-card");
  const w = state.active;
  if (!w) {
    el.innerHTML = "";
    return;
  }
  const pct = w.total ? Math.round((w.done / w.total) * 100) : 0;
  el.innerHTML = `
    <button class="active-card" style="--accent:${w.template_id ? accentFor(w.template_id) : "#7c3aed"}">
      <div class="active-title">${escapeHtml(w.template_name)} — in progress</div>
      <div class="active-sub">Tap to continue your workout</div>
      <div class="active-progress">${w.done} / ${w.total} exercises done · ${pct}%</div>
      <div class="active-progress-bar"><div class="active-progress-fill" style="width:${pct}%"></div></div>
    </button>`;
  el.querySelector(".active-card").addEventListener("click", () => openWorkout(w.id));
}

function accentFor(templateId) {
  const t = (state.config?.templates || []).find((x) => x.id === templateId);
  return t ? t.color : "#7c3aed";
}

function renderTemplates() {
  const el = $("#template-list");
  el.innerHTML = "";
  (state.config?.templates || []).forEach((t) => {
    const last = state.lastDone[t.id];
    const sub = last
      ? `${t.exercises.length} exercises · Last done ${relTime(last)}`
      : `${t.exercises.length} exercises · Not done yet`;
    const btn = document.createElement("button");
    btn.className = "template-card";
    setAccent(btn, t.color);
    btn.innerHTML = `
      <span class="template-icon">${t.emoji || "🏋️"}</span>
      <span class="template-meta">
        <span class="template-name">${escapeHtml(t.name)}</span>
        <span class="template-count">${escapeHtml(sub)}</span>
      </span>
      <span class="material-symbols-rounded template-arrow">chevron_right</span>`;
    btn.addEventListener("click", () => startWorkout(t.id));
    el.appendChild(btn);
  });
}

function relTime(iso) {
  const d = new Date(iso);
  const diff = Date.now() - d.getTime();
  const days = Math.floor(diff / 86400000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 7) return `${days} days ago`;
  if (days < 30) {
    const w = Math.floor(days / 7);
    return `${w} week${w > 1 ? "s" : ""} ago`;
  }
  return d.toLocaleDateString("en", { day: "numeric", month: "short" });
}

async function startWorkout(templateId) {
  try {
    const w = await api("/api/workouts", {
      method: "POST",
      body: JSON.stringify({ template_id: templateId }),
    });
    state.active = w;
    renderActiveCard();
    openWorkout(w.id);
  } catch (e) {
    if (e.message.includes("active workout")) {
      toast("Finish your current workout first");
      await loadHome();
      if (state.active) openWorkout(state.active.id);
    } else {
      toast(e.message);
    }
  }
}

/* ------------------------------------------------------------------ */
/* Workout                                                             */
/* ------------------------------------------------------------------ */
async function openWorkout(id) {
  const w = await api(`/api/workouts/${id}`);
  state.workout = w;
  renderWorkout();
  showView("workout");
}

function renderWorkout() {
  const w = state.workout;
  const accent = accentFor(w.template_id);
  const head = $("#workout-header");
  const pct = w.total ? Math.round((w.done / w.total) * 100) : 0;
  head.innerHTML = `
    <div class="workout-head" style="--accent:${accent}">
      <div class="workout-head-title">${escapeHtml(w.template_name)}</div>
      <div class="workout-head-meta" id="save-status">All changes saved automatically</div>
      <div class="workout-head-progress">${w.done} / ${w.total} done</div>
      <div class="workout-head-bar"><div class="workout-head-fill" style="width:${pct}%"></div></div>
    </div>`;
  setAccent($(".workout-head"), accent);
  renderExercises();
}

function renderExercises() {
  const list = $("#exercise-list");
  list.innerHTML = "";
  state.workout.exercises.forEach((ex) => list.appendChild(buildExerciseCard(ex)));
  updateProgress();
}

function metricLabel(ex) {
  return ex.metric === "seconds" ? "Seconds" : "Reps";
}

function targetHint(ex) {
  if (!ex.sets_reps) return "";
  const parts = ex.sets_reps.split("x");
  if (parts.length < 2) return "";
  return ` · target ${parts[1].trim()}`;
}

function buildExerciseCard(ex) {
  const card = document.createElement("div");
  card.className = "exercise-card" + (ex.completed ? " is-done" : "");
  setAccent(card, accentFor(state.workout.template_id));

  const valueLabel = metricLabel(ex);
  const hint = targetHint(ex);

  card.innerHTML = `
    <div class="exercise-top">
      <button class="exercise-check ${ex.completed ? "is-done" : ""}" title="Mark done">
        <span class="material-symbols-rounded">check</span>
      </button>
      <div class="exercise-info">
        ${ex.block ? `<span class="exercise-badge">${escapeHtml(ex.block)}</span>` : ""}
        <div class="exercise-name">${escapeHtml(ex.name)}${escapeHtml(hint)}</div>
        ${ex.notes ? `<div class="exercise-notes">${escapeHtml(ex.notes)}</div>` : ""}
      </div>
      ${ex.added_from_pool ? `<button class="exercise-remove" title="Remove"><span class="material-symbols-rounded">delete</span></button>` : ""}
    </div>
    <div class="exercise-inputs">
      <label class="input-group">
        <span class="input-label">Sets</span>
        <input class="input" type="number" inputmode="numeric" min="1" step="1" data-field="sets" value="${ex.sets}" />
      </label>
      <label class="input-group">
        <span class="input-label">${escapeHtml(valueLabel)}</span>
        <input class="input" type="number" inputmode="numeric" min="0" step="1" data-field="reps" value="${ex.reps ?? ""}" placeholder="—" />
      </label>
      <label class="input-group">
        <span class="input-label">Weight (kg)</span>
        <input class="input" type="number" inputmode="decimal" min="0" step="0.5" data-field="weight" value="${ex.weight ?? ""}" placeholder="—" />
      </label>
    </div>`;

  card.querySelector(".exercise-check").addEventListener("click", () => {
    saveField(ex.id, { completed: !ex.completed });
  });

  card.querySelectorAll("input").forEach((inp) => {
    const field = inp.dataset.field;
    const debounce = debounceFn((val) => {
      if (field === "sets") {
        if (val === "") return;
        saveField(ex.id, { sets: parseInt(val, 10) });
      } else if (field === "reps") {
        saveField(ex.id, { reps: val === "" ? null : parseInt(val, 10) });
      } else if (field === "weight") {
        saveField(ex.id, { weight: val === "" ? null : parseFloat(val) });
      }
    }, 600);
    inp.addEventListener("input", () => debounce(inp.value));
    inp.addEventListener("change", () => {
      const val = inp.value;
      if (field === "sets" && val !== "") saveField(ex.id, { sets: parseInt(val, 10) });
      else if (field === "reps") saveField(ex.id, { reps: val === "" ? null : parseInt(val, 10) });
      else if (field === "weight") saveField(ex.id, { weight: val === "" ? null : parseFloat(val) });
    });
  });

  const rm = card.querySelector(".exercise-remove");
  if (rm) rm.addEventListener("click", () => removeExercise(ex.id));

  return card;
}

function debounceFn(fn, ms) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

async function saveField(exId, payload) {
  const status = $("#save-status");
  if (status) status.textContent = "Saving…";
  try {
    const updated = await api(`/api/workouts/${state.workout.id}/exercises/${exId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    const ex = state.workout.exercises.find((e) => e.id === exId);
    if (ex) Object.assign(ex, updated);
    updateProgress();
    if (status) {
      status.textContent = "Saved ✓";
      setTimeout(() => (status.textContent = "All changes saved automatically"), 1200);
    }
  } catch (e) {
    toast(e.message);
    if (status) status.textContent = "Save failed";
  }
}

function updateProgress() {
  const w = state.workout;
  if (!w) return;
  const done = w.exercises.filter((e) => e.completed).length;
  w.done = done;
  const pct = w.total ? Math.round((done / w.total) * 100) : 0;
  const head = $("#workout-header .workout-head");
  if (head) {
    head.querySelector(".workout-head-progress").textContent = `${done} / ${w.total} done`;
    head.querySelector(".workout-head-fill").style.width = `${pct}%`;
  }
  $$(".exercise-card").forEach((card, i) => {
    const ex = w.exercises[i];
    card.classList.toggle("is-done", ex ? ex.completed : false);
    const check = card.querySelector(".exercise-check");
    if (check) check.classList.toggle("is-done", ex ? ex.completed : false);
  });
}

async function removeExercise(exId) {
  if (!confirm("Remove this exercise?")) return;
  try {
    await api(`/api/workouts/${state.workout.id}/exercises/${exId}`, { method: "DELETE" });
    state.workout.exercises = state.workout.exercises.filter((e) => e.id !== exId);
    state.workout.total = state.workout.exercises.length;
    renderExercises();
  } catch (e) {
    toast(e.message);
  }
}

/* Add-exercise bottom sheet */
function openSheet() {
  const sheet = $("#sheet");
  state.sheetPool = state.config.pools[0]?.id || null;
  renderSheetTabs();
  renderSheetBody();
  sheet.hidden = false;
}

function closeSheet() {
  $("#sheet").hidden = true;
}

function renderSheetTabs() {
  const tabs = $("#sheet-tabs");
  tabs.innerHTML = "";
  state.config.pools.forEach((p) => {
    const b = document.createElement("button");
    b.className = "sheet-tab" + (p.id === state.sheetPool ? " is-active" : "");
    b.textContent = p.name;
    b.addEventListener("click", () => {
      state.sheetPool = p.id;
      renderSheetTabs();
      renderSheetBody();
    });
    tabs.appendChild(b);
  });
}

function renderSheetBody() {
  const body = $("#sheet-body");
  body.innerHTML = "";
  const pool = state.config.pools.find((p) => p.id === state.sheetPool);
  if (!pool) return;
  pool.exercises.forEach((ex) => {
    const b = document.createElement("button");
    b.className = "sheet-item";
    b.innerHTML = `<span>${escapeHtml(ex.name)}</span><span class="material-symbols-rounded">add_circle</span>`;
    b.addEventListener("click", () => addExercise(pool.id, ex.name));
    body.appendChild(b);
  });
}

async function addExercise(poolId, name) {
  try {
    const ex = await api(`/api/workouts/${state.workout.id}/exercises`, {
      method: "POST",
      body: JSON.stringify({ pool_id: poolId, exercise_name: name }),
    });
    state.workout.exercises.push(ex);
    state.workout.total = state.workout.exercises.length;
    closeSheet();
    renderExercises();
    toast(`${name} added`);
  } catch (e) {
    toast(e.message);
  }
}

async function finishWorkout() {
  const w = state.workout;
  const remaining = w.exercises.filter((e) => !e.completed).length;
  if (remaining > 0 && !confirm(`You still have ${remaining} unfinished exercises. Finish anyway?`)) {
    return;
  }
  try {
    await api(`/api/workouts/${w.id}/finish`, { method: "POST" });
    state.active = null;
    state.workout = null;
    toast("Workout saved 🎉");
    await loadHome();
    showView("home");
  } catch (e) {
    toast(e.message);
  }
}

async function discardWorkout() {
  if (!confirm("Discard this workout? This cannot be undone.")) return;
  try {
    await api(`/api/workouts/${state.workout.id}`, { method: "DELETE" });
    state.active = null;
    state.workout = null;
    toast("Workout discarded");
    await loadHome();
    showView("home");
  } catch (e) {
    toast(e.message);
  }
}

/* ------------------------------------------------------------------ */
/* Log                                                                 */
/* ------------------------------------------------------------------ */
async function loadLog() {
  const workouts = await api("/api/log");
  const el = $("#log-list");
  el.innerHTML = "";
  if (!workouts.length) {
    el.innerHTML = `<div class="empty"><span class="material-symbols-rounded">history</span>No workouts yet.<br>Finish a workout and it'll appear here.</div>`;
    return;
  }
  workouts.forEach((w) => el.appendChild(buildLogCard(w)));
}

function buildLogCard(w) {
  const card = document.createElement("div");
  card.className = "log-card";
  const d = new Date(w.completed_at);
  const day = d.getDate();
  const mon = d.toLocaleString("en", { month: "short" });
  const time = d.toLocaleTimeString("en", { hour: "2-digit", minute: "2-digit" });
  const pct = w.total ? Math.round((w.done / w.total) * 100) : 0;
  const accent = accentFor(w.template_id);

  card.innerHTML = `
    <div class="log-head">
      <div class="log-date-badge"><span class="d">${day}</span><span class="m">${mon}</span></div>
      <div class="log-meta">
        <div class="log-name">${escapeHtml(w.template_name)}</div>
        <div class="log-sub">${time} · ${w.done}/${w.total} exercises · ${pct}%</div>
      </div>
      <span class="log-badge">${w.done}/${w.total}</span>
    </div>
    <div class="log-body">
      ${w.exercises
        .map((ex) => {
          const val =
            ex.metric === "seconds"
              ? `${ex.sets} × ${ex.reps ?? "—"}s`
              : `${ex.sets} × ${ex.reps ?? "—"}`;
          const wt = ex.weight != null ? ` · ${ex.weight}kg` : "";
          return `<div class="log-ex">
            <span class="log-ex-name ${ex.completed ? "done" : ""}">${escapeHtml(ex.name)}</span>
            <span class="log-ex-val">${val}${wt}</span>
          </div>`;
        })
        .join("")}
    </div>`;
  card.style.setProperty("--accent", accent);
  card.querySelector(".log-head").addEventListener("click", () => card.classList.toggle("is-open"));
  return card;
}

/* ------------------------------------------------------------------ */
/* Analytics                                                           */
/* ------------------------------------------------------------------ */
async function loadAnalytics() {
  const a = await api("/api/analytics");
  renderAnalytics(a);
}

function renderAnalytics(a) {
  const body = $("#analytics-body");
  Object.values(state.charts).forEach((c) => c.destroy());
  state.charts = {};

  const totalVolume = a.volume.reduce((s, v) => s + (v.tonnage || 0), 0);
  const bestE1rm = a.prs.reduce((s, p) => Math.max(s, p.best_e1rm || 0), 0);
  const weeks = a.frequency.length;

  body.innerHTML = `
    <div class="stat-grid">
      <div class="stat-card accent1"><div class="stat-num">${a.totals.workouts}</div><div class="stat-label">Workouts</div></div>
      <div class="stat-card accent2"><div class="stat-num">${a.totals.exercises}</div><div class="stat-label">Exercises logged</div></div>
      <div class="stat-card accent3"><div class="stat-num">${Math.round(totalVolume).toLocaleString()}</div><div class="stat-label">Volume (kg)</div></div>
      <div class="stat-card accent4"><div class="stat-num">${bestE1rm ? bestE1rm.toLocaleString() : "—"}</div><div class="stat-label">Best e1RM (kg)</div></div>
    </div>

    <div class="chart-card">
      <div class="chart-title">Strength trends</div>
      <div class="chart-sub">Pick an exercise to see 1RM and weight over time.</div>
      <select class="select" id="ex-select"></select>
      <div class="chart-box"><canvas id="chart-1rm"></canvas></div>
    </div>

    <div class="chart-card">
      <div class="chart-title">Weight progression</div>
      <div class="chart-sub">Heaviest working weight each session.</div>
      <div class="chart-box"><canvas id="chart-weight"></canvas></div>
    </div>

    <div class="chart-card">
      <div class="chart-title">Volume per workout</div>
      <div class="chart-sub">Sets × reps × weight (tonnage).</div>
      <div class="chart-box"><canvas id="chart-volume"></canvas></div>
    </div>

    <div class="chart-card">
      <div class="chart-title">Workout frequency</div>
      <div class="chart-sub">Sessions per week.</div>
      <div class="chart-box"><canvas id="chart-frequency"></canvas></div>
    </div>

    <div class="chart-card">
      <div class="chart-title">Workouts by template</div>
      <div class="chart-sub">Where you spend your time.</div>
      <div class="chart-box" style="height:200px"><canvas id="chart-templates"></canvas></div>
    </div>

    <h2 class="section-title">Personal records</h2>
    <div class="pr-list" id="pr-list"></div>`;

  const select = $("#ex-select");
  const names = (a.exercises || []).map((e) => e.name);
  select.innerHTML = names.length
    ? names.map((n) => `<option>${escapeHtml(n)}</option>`).join("")
    : `<option>No exercises yet</option>`;
  select.addEventListener("change", () => renderStrengthCharts(a));

  renderStrengthCharts(a);
  renderVolumeChart(a);
  renderFrequencyChart(a);
  renderTemplateChart(a);
  renderPRs(a);
}

function renderStrengthCharts(a) {
  const select = $("#ex-select");
  if (!select) return;
  const name = select.value;
  if (!name) return;

  destroyChart("chart-1rm");
  destroyChart("chart-weight");

  const rm = a.one_rm[name] || [];
  const wt = a.weight[name] || [];
  const labels = rm.map((p) => p.date);

  if (typeof Chart !== "undefined" && rm.length) {
    state.charts["chart-1rm"] = new Chart($("#chart-1rm"), {
      type: "line",
      data: {
        labels,
        datasets: [{ label: "e1RM (kg)", data: rm.map((p) => p.e1rm), borderColor: "#7c3aed", backgroundColor: "#7c3aed22", tension: 0.35, pointRadius: 4 }],
      },
      options: baseLineOpts(),
    });
  }

  if (typeof Chart !== "undefined" && wt.length) {
    state.charts["chart-weight"] = new Chart($("#chart-weight"), {
      type: "line",
      data: {
        labels: wt.map((p) => p.date),
        datasets: [{ label: "Weight (kg)", data: wt.map((p) => p.weight), borderColor: "#ff5c7a", backgroundColor: "#ff5c7a22", tension: 0.35, pointRadius: 4, fill: true }],
      },
      options: baseLineOpts(),
    });
  }
}

function renderVolumeChart(a) {
  destroyChart("chart-volume");
  if (typeof Chart === "undefined" || !a.volume.length) return;
  state.charts["chart-volume"] = new Chart($("#chart-volume"), {
    type: "bar",
    data: {
      labels: a.volume.map((v) => v.date),
      datasets: [{ label: "Tonnage (kg)", data: a.volume.map((v) => v.tonnage), backgroundColor: a.volume.map((_, i) => PALETTE[i % PALETTE.length]) }],
    },
    options: baseBarOpts(),
  });
}

function renderFrequencyChart(a) {
  destroyChart("chart-frequency");
  if (typeof Chart === "undefined" || !a.frequency.length) return;
  state.charts["chart-frequency"] = new Chart($("#chart-frequency"), {
    type: "bar",
    data: {
      labels: a.frequency.map((f) => f.label),
      datasets: [{ label: "Workouts", data: a.frequency.map((f) => f.count), backgroundColor: "#00bfa6" }],
    },
    options: baseBarOpts(),
  });
}

function renderTemplateChart(a) {
  destroyChart("chart-templates");
  if (typeof Chart === "undefined" || !a.template_counts.length) return;
  state.charts["chart-templates"] = new Chart($("#chart-templates"), {
    type: "doughnut",
    data: {
      labels: a.template_counts.map((t) => t.name),
      datasets: [{ data: a.template_counts.map((t) => t.count), backgroundColor: a.template_counts.map((t) => accentForTemplateName(t.name)) }],
    },
    options: { plugins: { legend: { position: "bottom", labels: { boxWidth: 12 } } }, maintainAspectRatio: false },
  });
}

function accentForTemplateName(name) {
  const t = (state.config?.templates || []).find((x) => x.name === name);
  return t ? t.color : "#7c3aed";
}

function renderPRs(a) {
  const el = $("#pr-list");
  el.innerHTML = "";
  if (!a.prs.length) {
    el.innerHTML = `<div class="empty"><span class="material-symbols-rounded">emoji_events</span>No personal records yet.</div>`;
    return;
  }
  a.prs.forEach((p) => {
    const row = document.createElement("div");
    row.className = "pr-row";
    const unit = p.metric === "seconds" ? "s" : "reps";
    row.innerHTML = `
      <span class="pr-emoji">🏆</span>
      <span class="pr-name">${escapeHtml(p.name)}</span>
      <span class="pr-stats">
        <span class="pr-stat"><b>${p.max_weight != null ? p.max_weight + "kg" : "—"}</b>max</span>
        <span class="pr-stat"><b>${p.max_value != null ? p.max_value + unit : "—"}</b>${p.metric === "seconds" ? "best" : "reps"}</span>
        ${p.best_e1rm != null ? `<span class="pr-stat"><b>${p.best_e1rm}kg</b>e1RM</span>` : ""}
      </span>`;
    el.appendChild(row);
  });
}

const PALETTE = ["#ff5c7a", "#00bfa6", "#448aff", "#9c4dff", "#ff9f1c", "#26c6da"];

function baseLineOpts() {
  return {
    plugins: { legend: { display: false } },
    maintainAspectRatio: false,
    scales: {
      y: { beginAtZero: false, grid: { color: "#f0e8df" }, ticks: { font: { family: "Outfit" } } },
      x: { grid: { display: false }, ticks: { font: { family: "Outfit" }, maxRotation: 45, autoSkip: true } },
    },
  };
}
function baseBarOpts() {
  return {
    plugins: { legend: { display: false } },
    maintainAspectRatio: false,
    scales: {
      y: { beginAtZero: true, grid: { color: "#f0e8df" }, ticks: { font: { family: "Outfit" } } },
      x: { grid: { display: false }, ticks: { font: { family: "Outfit" }, maxRotation: 45, autoSkip: true } },
    },
  };
}

function destroyChart(id) {
  if (state.charts[id]) {
    state.charts[id].destroy();
    delete state.charts[id];
  }
}

/* ------------------------------------------------------------------ */
/* Bootstrapping                                                       */
/* ------------------------------------------------------------------ */
function bindEvents() {
  $$(".nav-btn").forEach((b) => {
    b.addEventListener("click", () => {
      const v = b.dataset.view;
      showView(v);
      if (v === "home") loadHome();
      else if (v === "log") loadLog();
      else if (v === "analytics") loadAnalytics();
    });
  });

  $("#add-exercise-btn").addEventListener("click", openSheet);
  $("#finish-btn").addEventListener("click", finishWorkout);
  $("#discard-btn").addEventListener("click", discardWorkout);
  $("#sheet").addEventListener("click", (e) => {
    if (e.target.id === "sheet") closeSheet();
  });
}

async function boot() {
  bindEvents();
  await loadHome();
  showView("home");
}

boot().catch((e) => {
  console.error(e);
  toast("Something went wrong");
});
