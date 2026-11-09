let token = localStorage.token || "";
let currentTasks = [];
let myMissionsData = []; 
let allClients = [];
let allTaskNames = []; 

// Timer State
let activeTask = null;
let timerInterval = null;
let activeStartTime = null;
let alerted50 = false;
let alerted80 = false;
let alerted100 = false;

const beep = new Audio('data:audio/wav;base64,UklGRl9vT19XQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YV9vT18AAAA=');

async function api(url, opt = {}) {
  opt.headers = Object.assign(
    { "Content-Type": "application/json", "Authorization": "Bearer " + token },
    opt.headers || {}
  );
  const r = await fetch(url, opt);
  if (!r.ok) throw Error(await r.text());
  return r.json();
}

async function doLogin(event) {
  if (event) event.preventDefault();
  try {
    const r = await api("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username: u.value, password: p.value }),
    });
    token = r.token;
    localStorage.token = token;
    who.textContent = r.employee.EmployeeName;
    
    document.getElementById("loginContainer").style.display = "none";
    document.getElementById("app").style.display = "block";
    
    if ("Notification" in window && Notification.permission !== "granted") {
      Notification.requestPermission();
    }
    
    await checkActiveTimer(); 
    loadMe();
  } catch (e) {
    alert("Login failed: " + e.message);
  }
}

async function doLogout() {
  if (activeTask) {
    if (!confirm("You have a running timer. Logging out will stop it. Continue?")) return;
    await stopTimer();
  }
  try { await api("/api/auth/logout", { method: "POST" }); } catch (e) {}
  token = "";
  localStorage.removeItem("token");
  location.reload();
}

function badge(s) {
  const m = { open: "#4caf50", not_started: "#9e9e9e", overdue: "#e53935" };
  return `<span style="background:${m[s]};color:#fff;padding:1px 6px;border-radius:4px;font-size:.8em">${s}</span>`;
}

async function loadMe() {
  const sum = await api("/api/me/summary");
  if (!sum.HasWork) {
    document.getElementById("noWork").style.display = "block";
    document.getElementById("noWorkWho").textContent = sum.EmployeeName + " (" + sum.Username + ")";
    document.getElementById("myH").style.display = "none";
    document.getElementById("filterContainer").style.display = "none";
    document.getElementById("missions").innerHTML = "";
  } else {
    myMissionsData = await api("/api/me/missions");
    
    allClients = [...new Set(myMissionsData.map(m => m.CustomerName))].sort();
    setupClientDropdown();
    
    document.getElementById("filterContainer").style.display = "flex";
    filterMissions(); 
  }
  await loadAllMissions();
}

// --- CUSTOM SEARCHABLE CLIENT DROPDOWN ---
function setupClientDropdown() {
  const input = document.getElementById("clientFilterInput");
  const list = document.getElementById("clientFilterList");

  input.addEventListener("focus", () => showClientOptions(input.value));
  input.addEventListener("click", () => showClientOptions(input.value));
  input.addEventListener("input", (e) => showClientOptions(e.target.value));
  
  document.addEventListener("click", (e) => {
    if (!e.target.closest('.searchable-dropdown')) {
      list.style.display = "none";
    }
  });
}

function showClientOptions(query) {
  const list = document.getElementById("clientFilterList");
  const q = query.toLowerCase();
  const filtered = allClients.filter(c => c.toLowerCase().includes(q));
  
  let html = `<div class="dropdown-item" onclick="selectClient('All Clients')" style="font-weight: bold;">All Clients</div>`;
  if (filtered.length === 0 && q !== "all clients") {
    html += `<div style="padding: 8px 12px; color: #888;">No matching clients</div>`;
  } else {
    html += filtered.map(c => 
      `<div class="dropdown-item" onclick="selectClient('${c.replace(/'/g, "\\'")}')">${c}</div>`
    ).join("");
  }
  list.innerHTML = html;
  list.style.display = "block";
}

function selectClient(clientName) {
  const input = document.getElementById("clientFilterInput");
  input.value = clientName === "All Clients" ? "" : clientName;
  document.getElementById("clientFilterList").style.display = "none";
  filterMissions();
}

function filterMissions() {
  const query = document.getElementById("clientFilterInput").value.toLowerCase();
  const fiscalYear = document.getElementById("fiscalYearFilter").value.toLowerCase();
  const dateFrom = document.getElementById("missionDateFrom").value;
  const dateTo = document.getElementById("missionDateTo").value;
  
  const filtered = myMissionsData.filter(m => {
    // 1. Client Filter
    const matchesClient = query === "" || m.CustomerName.toLowerCase().includes(query);
    
    // 2. Fiscal Year Filter
    const matchesFiscal = fiscalYear === "" || (m.FiscalYear && m.FiscalYear.toLowerCase().includes(fiscalYear));

    // 3. Date Filter
    let matchesDate = true;
    if (dateFrom && m.WindowEnd < dateFrom) matchesDate = false;
    if (dateTo && m.WindowStart > dateTo) matchesDate = false;
    
    return matchesClient && matchesFiscal && matchesDate;
  });

  if (filtered.length === 0) {
    document.getElementById("missions").innerHTML = `<p class="muted">No missions found.</p>`;
    return;
  }

  document.getElementById("missions").innerHTML = filtered.map(m => `
    <div class="card">
      <div class="row">
        <div>
          <b>${m.CustomerName}</b> <span class="muted">(ID ${m.IDHonorary})</span><br>
          <span class="muted" style="font-size: 0.85em; text-transform: uppercase; color: #FF0000">${m.Service}</span>
          ${m.FiscalYear ? `<span class="muted" style="font-size: 0.85em; margin-left: 10px; font-weight: bold;">FY: ${m.FiscalYear}</span>` : ""}
        </div>
        ${badge(m.WindowStatus)}
        <span class="muted">${m.WindowStart} → ${m.WindowEnd}</span>
      </div>
      <div class="muted">${m.DaysRemaining} days remaining · ${m.TasksTotal} tasks</div>
      <div style="margin:.5em 0">Hours
        <div class="bar">
          <div class="fill ${m.PctConsumed > 100 ? 'warn' : ''}"
               style="width:${Math.min(m.PctConsumed || 0, 100)}%"></div>
        </div>
        <span class="muted">${m.ConsumedHours.toFixed(1)} / ${m.AllocatedHours.toFixed(1)} h
          (${m.PctConsumed || 0}%)</span>
      </div>
      <div>Tasks done: ${m.TasksDone} / ${m.TasksTotal}</div>
      <button onclick="pick(${m.MissionID})">Open mission</button>
      <button onclick="exportMission(${m.MissionID}, '${m.CustomerName.replace(/'/g, "\\'")}')">
        Export to Excel
      </button>
    </div>`).join("");
}

// --- CUSTOM SEARCHABLE TASK DROPDOWN ---
function setupTaskDropdown() {
  const input = document.getElementById("taskSearch");
  const list = document.getElementById("taskSearchList");
  
  if (!input || !list) return;

  input.addEventListener("focus", () => showTaskOptions(input.value));
  input.addEventListener("click", () => showTaskOptions(input.value));
  input.addEventListener("input", (e) => {
    showTaskOptions(e.target.value);
    filterTasks(); 
  });
  
  document.addEventListener("click", (e) => {
    if (!e.target.closest('.searchable-dropdown')) {
      list.style.display = "none";
    }
  });
}

function showTaskOptions(query) {
  const list = document.getElementById("taskSearchList");
  const q = query.toLowerCase();
  const filtered = allTaskNames.filter(t => t.toLowerCase().includes(q));
  
  let html = `<div class="dropdown-item" onclick="selectTask('')" style="font-weight: bold;">Show All Tasks</div>`;
  if (filtered.length === 0 && q !== "") {
    html += `<div style="padding: 8px 12px; color: #888;">No matching tasks</div>`;
  } else {
    html += filtered.slice(0, 50).map(t => 
      `<div class="dropdown-item" onclick="selectTask('${t.replace(/'/g, "\\'")}')">${t}</div>`
    ).join("");
  }
  
  list.innerHTML = html;
  list.style.display = "block";
}

function selectTask(taskName) {
  const input = document.getElementById("taskSearch");
  input.value = taskName;
  document.getElementById("taskSearchList").style.display = "none";
  filterTasks();
}

function filterTasks() {
  const query = document.getElementById("taskSearch").value.toLowerCase();
  const dateFrom = document.getElementById("taskDateFrom").value;
  const dateTo = document.getElementById("taskDateTo").value;

  const filtered = currentTasks.filter(t => {
    const section = (t.SectionName || "").toLowerCase();
    const subSection = (t.SubSectionName || "").toLowerCase();
    const subSubSection = (t.SubSubSectionName || "").toLowerCase();
    const matchesText = section.includes(query) || subSection.includes(query) || subSubSection.includes(query);

    // 2. Date Filter using Task's Date1 and Date2
    let matchesDate = true;
    if (dateFrom && t.Date2 && t.Date2 < dateFrom) matchesDate = false;
    if (dateTo && t.Date1 && t.Date1 > dateTo) matchesDate = false;

    return matchesText && matchesDate;
  });
  
  renderTasks(filtered);
}
// --- END CUSTOM DROPDOWNS ---

async function loadAllMissions() {
  try {
    const ms = await api("/api/admin/missions");
    if (!ms.length) return;
    document.getElementById("allMissions").innerHTML = ms.map(m => `
      <div class="card">
        <div class="row">
          <div>
            <b>${m.CustomerName}</b> <span class="muted">(ID ${m.IDHonorary})</span><br>
            <span class="muted" style="font-size: 0.85em; text-transform: uppercase; color: #FF0000;">${m.Service}</span>
            ${m.FiscalYear ? `<span class="muted" style="font-size: 0.85em; margin-left: 10px; font-weight: bold;">FY: ${m.FiscalYear}</span>` : ""}
          </div>
          ${badge(m.WindowStatus)}
          <span class="muted">${m.WindowStart} → ${m.WindowEnd}</span>
          <span class="muted">· ${m.TasksTotal} tasks · ${m.AllocatedHours} h</span>
        </div>
        <button onclick="exportMission(${m.MissionID}, '${m.CustomerName.replace(/'/g, "\\'")}')">
          Export to Excel
        </button>
      </div>`).join("");
    document.getElementById("allMissionsCard").style.display = "block";
  } catch (e) {
    console.error("loadAllMissions:", e);
  }
}

async function exportMission(missionId, customerName) {
  try {
    const r = await fetch(`/api/admin/export/${missionId}`, {
      headers: { "Authorization": "Bearer " + token },
    });
    if (!r.ok) throw Error(await r.text());
    const blob = await r.blob();
    let filename = `${customerName}_${missionId}_mission.xlsx`;
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  } catch (e) {
    alert("Export failed: " + e.message);
  }
}

async function pick(mid) {
  try {
    const r = await api(`/api/me/missions/${mid}/start`, { method: "POST" });
    if (r.outside_window) alert("Started outside mission window; logged as exception.");
  } catch (e) {
    if (confirm("Outside mission window. Force start?")) {
      await api(`/api/me/missions/${mid}/start?force=true`, { method: "POST" });
    } else return;
  }

  document.getElementById("myH").style.display = "none";
  document.getElementById("filterContainer").style.display = "none"; 
  document.getElementById("missions").style.display = "none";
  document.getElementById("allMissionsCard").style.display = "none";
  document.getElementById("missionView").style.display = "block";
  
  document.getElementById("taskSearch").value = "";
  document.getElementById("taskSearchList").style.display = "none";
  document.getElementById("taskDateFrom").value = "";
  document.getElementById("taskDateTo").value = "";

  currentTasks = await api(`/api/missions/${mid}/tasks`);
  
  const taskNamesSet = new Set();
  currentTasks.forEach(t => {
    if (t.SubSubSectionName) taskNamesSet.add(t.SubSubSectionName);
    if (t.SubSectionName) taskNamesSet.add(t.SubSectionName);
    if (t.SectionName) taskNamesSet.add(t.SectionName);
  });
  allTaskNames = Array.from(taskNamesSet).sort();
  
  setupTaskDropdown();
  
  renderTasks(currentTasks);
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function renderTasks(tasks) {
  const container = document.getElementById("taskList");
  if (tasks.length === 0) {
    container.innerHTML = `<p class="muted">No tasks found.</p>`;
    return;
  }
  container.innerHTML = tasks.map(t => `
    <div class="card" style="${activeTask && activeTask.TaskID === t.TaskID ? 'border-color: #2b6cb0; border-width: 2px;' : ''}">
      <div class="muted">${t.SectionName || ""} / ${t.SubSectionName || ""}</div>
      <b>${t.SubSubSectionName}</b><br>
      Allocated: ${t.AllocatedHours} h
      ${t.Signindate ? `<br><span class="muted">Sign in ${t.Signindate} ${t.Signintime || ""}`
        + (t.Signoutdate ? ` · out ${t.Signoutdate} ${t.Signouttime || ""}` : " · still open")
        + `</span>` : ""}
      <div>
        ${activeTask && activeTask.TaskID === t.TaskID 
          ? `<button onclick="stopTimer()" style="background:#e53935;">Stop Timer</button>`
          : `<button onclick='startTask(${JSON.stringify(t).replace(/'/g, "&#39;")})'>Start timer</button>`
        }
        <label><input type="checkbox" ${t.Launched ? "checked" : ""}
          onchange="upd(${t.TaskID}, 'Launched', this.checked)"> Launched</label>
        <label><input type="checkbox" ${t.Suspended ? "checked" : ""}
          onchange="upd(${t.TaskID}, 'Suspended', this.checked)"> Suspended</label>
        <label><input type="checkbox" ${t.Accomplished ? "checked" : ""}
          onchange="upd(${t.TaskID}, 'Accomplished', this.checked)"> Accomplished</label>
      </div>
    </div>`).join("");
}

async function checkActiveTimer() {
  try {
    const res = await api("/api/tasks/active");
    if (res.active) {
      activeTask = res;
      const startTimeObj = new Date(res.LoginTime + "Z");
      const elapsedMs = Date.now() - startTimeObj.getTime();
      activeStartTime = Date.now() - elapsedMs;

      alerted50 = false;
      alerted80 = false;
      alerted100 = false;

      const bar = document.getElementById("activeTimerBar");
      bar.style.display = "block";
      bar.className = "card";
      document.getElementById("timerTaskName").textContent = res.SubSubSectionName;
      
      tickTimer();
      timerInterval = setInterval(tickTimer, 1000);
    }
  } catch (e) {
    console.error("Failed to check active timer:", e);
  }
}

async function startTask(task) {
  if (activeTask) {
    if (!confirm("Another task timer is running. Stop it and start this one?")) return;
    await stopTimer();
  }

  await api(`/api/tasks/${task.TaskID}/start`, { method: "POST" });

  try {
    const res = await api("/api/tasks/active");
    task.PreviousHours = res.PreviousHours || 0;
  } catch(e) {
    task.PreviousHours = 0;
  }

  activeTask = task;
  activeStartTime = Date.now();
  alerted50 = false;
  alerted80 = false;
  alerted100 = false;

  const bar = document.getElementById("activeTimerBar");
  bar.style.display = "block";
  bar.className = "card";
  document.getElementById("timerTaskName").textContent = task.SubSubSectionName;
  document.getElementById("timerAlert").style.display = "none";
  
  renderTasks(currentTasks); 

  tickTimer();
  timerInterval = setInterval(tickTimer, 1000);
}

async function stopTimer() {
  if (!activeTask) return;
  
  const jobDesc = prompt("Please enter a brief description of the work you completed on this task:");
  if (jobDesc === null) return;

  clearInterval(timerInterval);
  
  await api(`/api/tasks/${activeTask.TaskID}/stop`, { 
    method: "POST",
    body: JSON.stringify({ JobDesc: jobDesc })
  });
  
  activeTask = null;
  activeStartTime = null;
  document.getElementById("activeTimerBar").style.display = "none";
  
  if (currentTasks.length > 0) {
    const mid = currentTasks[0].MissionID;
    currentTasks = await api(`/api/missions/${mid}/tasks`);
    renderTasks(currentTasks);
  }
}

function formatTime(ms) {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000)); 
  const h = Math.floor(totalSeconds / 3600).toString().padStart(2, '0');
  const m = Math.floor((totalSeconds % 3600) / 60).toString().padStart(2, '0');
  const s = (totalSeconds % 60).toString().padStart(2, '0');
  return `${h}:${m}:${s}`;
}

function tickTimer() {
  if (!activeStartTime || !activeTask) return;

  const elapsedMs = Date.now() - activeStartTime;
  const previousMs = (activeTask.PreviousHours || 0) * 3600 * 1000;
  const allocatedMs = (activeTask.AllocatedHours * 3600 * 1000) - previousMs;
  
  const remainingMs = allocatedMs - elapsedMs;
  const totalAllocatedMs = activeTask.AllocatedHours * 3600 * 1000;
  const pct = totalAllocatedMs > 0 ? ((elapsedMs + previousMs) / totalAllocatedMs) : 0;

  if (remainingMs > 0) {
    document.getElementById("timerDisplay").textContent = formatTime(remainingMs);
  } else {
    document.getElementById("timerDisplay").textContent = "+" + formatTime(Math.abs(remainingMs));
  }

  const bar = document.getElementById("activeTimerBar");
  const alertDiv = document.getElementById("timerAlert");

  if (pct >= 0.5 && !alerted50) {
    alerted50 = true;
    triggerAlert("50% of allocated time reached", "You have half of the allocated time remaining for this task.");
  }
  if (pct >= 0.8 && !alerted80) {
    alerted80 = true;
    bar.classList.add("timer-warning"); 
    triggerAlert("80% of allocated time reached", "You have 20% of the allocated time left for this task.");
  }
  if (pct >= 1.0 && !alerted100) {
    alerted100 = true;
    triggerAlert("Time limit reached!", "You have exceeded the allocated time for this task. Overtime is being tracked.");
  }

  if (pct >= 1.0) {
    bar.classList.add("timer-overtime");
    alertDiv.style.display = "block";
    alertDiv.innerHTML = `<b>⚠ OVERTIME:</b> You are ${formatTime(Math.abs(remainingMs))} past the allocated duration.`;
  } else {
    bar.classList.remove("timer-overtime");
    alertDiv.style.display = "none";
  }
}

function triggerAlert(title, body) {
  beep.play().catch(() => {}); 
  if ("Notification" in window && Notification.permission === "granted") {
    new Notification(title, { body: body });
  } else {
    alert(`${title}\n\n${body}`);
  }
}

function goBack() {
  document.getElementById("missionView").style.display = "none";
  document.getElementById("myH").style.display = "block";
  document.getElementById("filterContainer").style.display = "flex"; 
  document.getElementById("missions").style.display = "block";
  document.getElementById("allMissionsCard").style.display = "block";
  window.scrollTo({ top: 0, behavior: "smooth" });
}

if (token) {
  api("/api/me")
    .then(user => {
      who.textContent = user.EmployeeName;
      document.getElementById("loginContainer").style.display = "none";
      document.getElementById("app").style.display = "block";
      return checkActiveTimer().then(() => loadMe());
    })
    .catch(() => {
      localStorage.removeItem("token");
      token = "";
    });
}