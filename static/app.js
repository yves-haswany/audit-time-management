let token = localStorage.token || "";
let currentTasks = [];
let myMissionsData = [];
let allClients = [];
let allTaskNames = [];
let showAllMissions = false;
let allTeamTasks = [];
let allTimeLogs = [];

// Timer State
let activeTask = null;
let timerInterval = null;
let activeStartTime = null;
let alerted50 = false;
let alerted80 = false;
let alerted100 = false;

// Admin state
let adminTeams = [];
let adminEmployees = [];
let adminClients = [];
let adminModalContext = null;
let adminCurrentTab = null;

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

// ============================================================
// AUTH
// ============================================================

async function doLogin(event) {
  if (event) event.preventDefault();
  try {
    const r = await api("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username: u.value, password: p.value }),
    });
    token = r.token;
    localStorage.token = token;

    const role = (r.employee.Classification || "").toLowerCase();
    who.textContent = r.employee.EmployeeName + (r.employee.Classification ? ` (${r.employee.Classification})` : "");

    const isAdmin = role === "administrator";
    document.getElementById("btnAdminPanel").style.display = isAdmin ? "inline-block" : "none";
    document.getElementById("btnDownloadLogs").style.display =
      (role === "team leader" || isAdmin) ? "inline-block" : "none";

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

// ============================================================
// SHARED HELPERS
// ============================================================

function badge(s) {
  const m = { open: "#4caf50", not_started: "#9e9e9e", overdue: "#e53935" };
  return `<span style="background:${m[s]};color:#fff;padding:1px 6px;border-radius:4px;font-size:.8em">${s.replace('_', ' ')}</span>`;
}

function populateDropdown(id, defaultText, options) {
  const select = document.getElementById(id);
  select.innerHTML = `<option value="all">${defaultText}</option>` +
    options.map(opt => `<option value="${String(opt).replace(/"/g, '&quot;')}">${opt}</option>`).join("");
}

// ============================================================
// DOWNLOAD TIME LOGS
// ============================================================

async function downloadTimeLogs() {
  try {
    const r = await fetch("/api/admin/download-timelogs", {
      headers: { "Authorization": "Bearer " + token },
    });

    if (!r.ok) {
      const err = await r.json();
      throw Error(err.detail || "Failed to download file");
    }

    let filename = "TimeLogs.xlsx";
    const cd = r.headers.get("Content-Disposition") || "";
    const match = cd.match(/filename="([^"]+)"/);
    if (match) filename = match[1];

    const blob = await r.blob();
    const url = URL.createObjectURL(blob);

    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();

    setTimeout(() => {
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    }, 100);
  } catch (e) {
    alert("Download failed: " + e.message);
  }
}

// ============================================================
// TIME LOGS
// ============================================================

async function showTimeLogs() {
  document.getElementById("listView").style.display = "none";
  document.getElementById("missionView").style.display = "none";
  document.getElementById("tableView").style.display = "none";
  document.getElementById("teamTableView").style.display = "none";
  document.getElementById("adminView").style.display = "none";

  document.getElementById("timeLogsView").style.display = "block";
  window.scrollTo({ top: 0, behavior: "smooth" });

  const tbody = document.getElementById("timeLogsTableBody");
  tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding: 2em;">Loading logs...</td></tr>`;

  try {
    const logs = await api("/api/admin/time-logs");
    allTimeLogs = logs;

    if (logs.length === 0) {
      tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding: 2em;">No logs found.</td></tr>`;
      return;
    }

    const dates = [...new Set(logs.map(l => l.Date))].filter(Boolean).sort().reverse();
    const employees = [...new Set(logs.map(l => l.Employee))].filter(Boolean).sort();
    const tasks = [...new Set(logs.map(l => l.TaskName))].filter(Boolean).sort();

    populateDropdown("filterLogDate", "All Dates", dates);
    populateDropdown("filterLogEmployee", "All Employees", employees);
    populateDropdown("filterLogTask", "All Tasks", tasks);

    document.getElementById("filterLogStatus").value = "all";

    renderTimeLogs(logs);
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding: 2em; color: red;">Failed to load: ${e.message}</td></tr>`;
  }
}

function renderTimeLogs(logs) {
  const tbody = document.getElementById("timeLogsTableBody");
  if (logs.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding: 2em;">No logs match your filters.</td></tr>`;
    return;
  }
  tbody.innerHTML = logs.map(l => `
    <tr style="border-bottom: 1px solid #eee;">
      <td style="padding: 0.8em;">${l.Date || '-'}</td>
      <td style="padding: 0.8em;"><b>${l.Employee}</b></td>
      <td style="padding: 0.8em;">${l.TaskName || '-'}</td>
      <td style="padding: 0.8em;">${l.SignIn || '-'}</td>
      <td style="padding: 0.8em;">${l.SignOut || '-'}</td>
      <td style="padding: 0.8em;">${l.Hours || '0'}</td>
      <td style="padding: 0.8em;">${l.Description || '-'}</td>
    </tr>
  `).join("");
}

function filterLogs() {
  const dateF = document.getElementById("filterLogDate").value;
  const empF = document.getElementById("filterLogEmployee").value;
  const taskF = document.getElementById("filterLogTask").value;
  const statF = document.getElementById("filterLogStatus").value;

  const filtered = allTimeLogs.filter(l => {
    if (dateF !== "all" && l.Date !== dateF) return false;
    if (empF !== "all" && l.Employee !== empF) return false;
    if (taskF !== "all" && l.TaskName !== taskF) return false;
    if (statF !== "all" && l.Status !== statF) return false;
    return true;
  });

  renderTimeLogs(filtered);
}

function clearLogFilters() {
  document.getElementById("filterLogDate").value = "all";
  document.getElementById("filterLogEmployee").value = "all";
  document.getElementById("filterLogTask").value = "all";
  document.getElementById("filterLogStatus").value = "all";
  filterLogs();
}

function hideTimeLogs() {
  document.getElementById("timeLogsView").style.display = "none";
  document.getElementById("listView").style.display = "block";
}

// ============================================================
// MISSIONS
// ============================================================

async function loadMe() {
  const role = who.textContent.toLowerCase();
  const isAdmin = role.includes("administrator");

  if (isAdmin) {
    // Admins skip missions entirely — they have no work assigned.
    document.getElementById("noWork").style.display = "none";
    document.getElementById("listView").style.display = "none";
    document.getElementById("myH").style.display = "none";
    document.getElementById("filterContainer").style.display = "none";
    document.getElementById("missions").innerHTML = "";

    // Auto-open the admin panel
    showAdminPanel();
    return;
  }

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

function toggleMissionView() {
  showAllMissions = !showAllMissions;
  const btn = document.getElementById("viewToggleBtn");
  btn.textContent = showAllMissions ? "Show Open Only" : "Show All Missions";
  btn.style.background = showAllMissions ? "#e53935" : "#4caf50";
  filterMissions();
}

async function showTableView() {
  document.getElementById("listView").style.display = "none";
  document.getElementById("tableView").style.display = "block";

  const tbody = document.getElementById("tableBody");
  tbody.innerHTML = "<tr><td colspan='8' style='padding: 1em; text-align: center;'>Loading tasks...</td></tr>";

  const query = document.getElementById("clientFilterInput").value.toLowerCase();
  const fiscalYear = document.getElementById("fiscalYearFilter").value.toLowerCase();
  const dateFrom = document.getElementById("missionDateFrom").value;
  const dateTo = document.getElementById("missionDateTo").value;

  const filtered = myMissionsData.filter(m => {
    const matchesClient = query === "" || m.CustomerName.toLowerCase().includes(query);
    const dbFY = m.FiscalYear ? String(m.FiscalYear).toLowerCase() : "";
    const matchesFiscal = fiscalYear === "" || dbFY.includes(fiscalYear);
    let matchesDate = true;
    if (dateFrom && m.WindowEnd < dateFrom) matchesDate = false;
    if (dateTo && m.WindowStart > dateTo) matchesDate = false;
    return matchesClient && matchesFiscal && matchesDate;
  });

  if (filtered.length === 0) {
    tbody.innerHTML = `<tr><td colspan="8" style="padding: 1em; text-align: center;">No missions found.</td></tr>`;
    return;
  }

  const allRows = [];

  for (const m of filtered) {
    try {
      const tasks = await api(`/api/me/missions/${m.MissionID}/team-tasks`);

      tasks.forEach(t => {
        const empName = t.EmployeeName || t.TeamMemberName || 'Unknown';

        allRows.push(`
          <tr style="border-bottom: 1px solid #eee;">
            <td style="padding: 0.8em; vertical-align: top;">
              <b>${m.CustomerName}</b><br>
              <span class="muted">ID ${m.IDHonorary}</span><br>
              <span class="muted" style="font-size: 0.85em;">FY: ${m.FiscalYear || '-'}</span>
            </td>
            <td style="padding: 0.8em; vertical-align: top; color: #FF0000; text-transform: uppercase; font-size: 0.85em;">
              ${m.ServiceName || m.Service}
            </td>
            <td style="padding: 0.8em; vertical-align: top; font-size: 0.85em; font-weight: bold;">
              ${empName}
            </td>
            <td style="padding: 0.8em; vertical-align: top;">${m.WindowStart} → ${m.WindowEnd}<br>${badge(m.WindowStatus)}</td>
            <td style="padding: 0.8em; vertical-align: top; font-size: 0.85em; color: #555;">
              ${t.TaskDescription || "-"}
            </td>
            <td style="padding: 0.8em; vertical-align: top; font-weight: bold;">
              ${t.TaskName}
            </td>
            <td style="padding: 0.8em; vertical-align: top;">${t.AllocatedHours} h</td>
            <td style="padding: 0.8em; vertical-align: top;">${t.Accomplished ? '✅ Done' : '⏳ Pending'}</td>
          </tr>
        `);
      });
    } catch (err) {
      console.error("Failed to load tasks for mission", m.MissionID, err);
    }
  }

  tbody.innerHTML = allRows.join("") || `<tr><td colspan="8" style="padding: 1em; text-align: center;">No tasks found.</td></tr>`;
}

function hideTableView() {
  document.getElementById("listView").style.display = "block";
  document.getElementById("tableView").style.display = "none";
}

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
    if (!showAllMissions && m.WindowStatus === "overdue") return false;
    const matchesClient = query === "" || m.CustomerName.toLowerCase().includes(query);
    const dbFY = m.FiscalYear ? String(m.FiscalYear).toLowerCase() : "";
    const matchesFiscal = fiscalYear === "" || dbFY.includes(fiscalYear);
    let matchesDate = true;
    if (dateFrom && m.WindowEnd < dateFrom) matchesDate = false;
    if (dateTo && m.WindowStart > dateTo) matchesDate = false;
    return matchesClient && matchesFiscal && matchesDate;
  });

  if (filtered.length === 0) {
    document.getElementById("missions").innerHTML = `<p class="muted">No missions found.</p>`;
    return;
  }

  document.getElementById("missions").innerHTML = filtered.map(m => {
    const isReadOnly = m.WindowStatus === "overdue";
    return `
    <div class="card">
      <div class="row">
        <div>
          <b>${m.CustomerName}</b> <span class="muted">(ID ${m.IDHonorary})</span><br>
          <span class="muted" style="font-size: 0.85em; text-transform: uppercase; color: #FF0000">${m.ServiceName || m.Service}</span>
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

      ${!isReadOnly ? `
        <button onclick="pick(${m.MissionID})">Open mission</button>
      ` : `
        <div style="margin-top: 0.5em; color: #888; font-size: 0.85em; font-style: italic;">
          (Read-only: Mission is overdue)
        </div>
      `}
    </div>`;
  }).join("");
}

// ============================================================
// TASK DROPDOWN / FILTER
// ============================================================

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
    const taskName = (t.TaskName || "").toLowerCase();
    const taskDesc = (t.TaskDescription || "").toLowerCase();
    const matchesText = taskName.includes(query) || taskDesc.includes(query);

    let matchesDate = true;
    if (dateFrom && t.Date2 && t.Date2 < dateFrom) matchesDate = false;
    if (dateTo && t.Date1 && t.Date1 > dateTo) matchesDate = false;

    return matchesText && matchesDate;
  });

  renderTasks(filtered);
}

// ============================================================
// ALL MISSIONS
// ============================================================

async function loadAllMissions() {
  try {
    const ms = await api("/api/admin/missions");
    if (!ms.length) return;
    document.getElementById("allMissions").innerHTML = ms.map(m => `
      <div class="card">
        <div class="row">
          <div>
            <b>${m.CustomerName}</b> <span class="muted">(ID ${m.IDHonorary})</span><br>
            <span class="muted" style="font-size: 0.85em; text-transform: uppercase; color: #FF0000;">${m.ServiceName || m.Service}</span>
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

// ============================================================
// OPEN MISSION / TASKS
// ============================================================

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
  document.getElementById("listView").style.display = "none";
  document.getElementById("allMissionsCard").style.display = "none";
  document.getElementById("adminView").style.display = "none";
  document.getElementById("missionView").style.display = "block";

  document.getElementById("btnViewLogs").style.display = "none";
  document.getElementById("btnDownloadLogs").style.display = "none";
  document.getElementById("btnAdminPanel").style.display = "none";

  document.getElementById("taskSearch").value = "";
  document.getElementById("taskSearchList").style.display = "none";
  document.getElementById("taskDateFrom").value = "";
  document.getElementById("taskDateTo").value = "";

  const userRole = who.textContent.toLowerCase();
  if (userRole.includes("team leader") || userRole.includes("administrator")) {
    document.getElementById("btnViewTeamTasks").style.display = "inline-block";
  } else {
    document.getElementById("btnViewTeamTasks").style.display = "none";
  }

  currentTasks = await api(`/api/me/missions/${mid}/tasks`);

  const taskNamesSet = new Set();
  currentTasks.forEach(t => {
    if (t.TaskName) taskNamesSet.add(t.TaskName);
    if (t.TaskDescription) taskNamesSet.add(t.TaskDescription);
  });
  allTaskNames = Array.from(taskNamesSet).sort();

  setupTaskDropdown();

  renderTasks(currentTasks);
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function renderTasks(tasks) {
  const container = document.getElementById("taskList");
  const activeTasks = tasks.filter(t => !t.Accomplished);

  if (activeTasks.length === 0) {
    container.innerHTML = `<p class="muted">No active tasks found.</p>`;
    return;
  }

  container.innerHTML = activeTasks.map(t => `
    <div class="card" style="${activeTask && activeTask.TaskID === t.TaskID ? 'border-color: #2b6cb0; border-width: 2px;' : ''}">
      <div class="muted">${t.TaskDescription || ""}</div>
      <b>${t.TaskName}</b><br>
      Allocated: ${t.AllocatedHours} h
      ${t.Signindate ? `<br><span class="muted">Sign in ${t.Signindate} ${t.Signintime || ""}`
        + (t.Signoutdate ? ` · out ${t.Signoutdate} ${t.Signouttime || ""}` : " · still open")
        + `</span>` : ""}
      <div style="margin-top: 0.5em;">
        ${activeTask && activeTask.TaskID === t.TaskID
          ? `<button onclick="stopTimer()" style="background:#e53935;">Stop Timer</button>`
          : `<button onclick='startTask(${JSON.stringify(t).replace(/'/g, "&#39;")})'>Start timer</button>`
        }
        <label style="margin-left: 1em;"><input type="checkbox"
          onchange="confirmAccomplished(${t.TaskID}, this)"> Accomplished</label>
      </div>
    </div>`).join("");
}

async function confirmAccomplished(tid, checkbox) {
  if (checkbox.checked) {
    if (confirm("Are you sure this task is fully accomplished?")) {
      await upd(tid, 'Accomplished', true);
    } else {
      checkbox.checked = false;
    }
  }
}

async function upd(tid, field, value) {
  await api("/api/tasks/" + tid, {
    method: "PATCH",
    body: JSON.stringify({ [field]: value }),
  });

  if (field === "Accomplished" && value === true) {
    currentTasks = currentTasks.map(t =>
      t.TaskID === tid ? { ...t, Accomplished: true } : t
    );
    renderTasks(currentTasks);
  }
}

// ============================================================
// TIMER
// ============================================================

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
      document.getElementById("timerTaskName").textContent = res.TaskName;

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
  } catch (e) {
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
  document.getElementById("timerTaskName").textContent = task.TaskName;
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
    body: JSON.stringify({ JobDesc: jobDesc }),
  });

  activeTask = null;
  activeStartTime = null;
  document.getElementById("activeTimerBar").style.display = "none";

  if (currentTasks.length > 0) {
    const mid = currentTasks[0].MissionID;
    currentTasks = await api(`/api/me/missions/${mid}/tasks`);
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

// ============================================================
// NAVIGATION
// ============================================================

function goBack() {
  document.getElementById("missionView").style.display = "none";
  document.getElementById("myH").style.display = "block";
  document.getElementById("filterContainer").style.display = "flex";
  document.getElementById("listView").style.display = "block";
  document.getElementById("allMissionsCard").style.display = "block";

  document.getElementById("btnViewLogs").style.display = "inline-block";

  const role = who.textContent.toLowerCase();
  const isAdmin = role.includes("administrator");
  if (role.includes("team leader") || isAdmin) {
    document.getElementById("btnDownloadLogs").style.display = "inline-block";
  }
  document.getElementById("btnAdminPanel").style.display = isAdmin ? "inline-block" : "none";

  document.getElementById("timeLogsView").style.display = "none";
  document.getElementById("teamTableView").style.display = "none";

  window.scrollTo({ top: 0, behavior: "smooth" });
}

// ============================================================
// TEAM TASKS TABLE
// ============================================================

async function showTeamTable() {
  const mid = currentTasks[0].MissionID;

  document.getElementById("missionView").style.display = "none";
  document.getElementById("teamTableView").style.display = "block";

  const tbody = document.getElementById("teamTableBody");
  tbody.innerHTML = "<tr><td colspan='5' style='padding: 1em; text-align: center;'>Loading tasks...</td></tr>";

  try {
    const tasks = await api(`/api/me/missions/${mid}/team-tasks`);
    allTeamTasks = tasks;

    const employees = [...new Set(tasks.map(t => t.EmployeeName || t.TeamMemberName || 'Unknown'))].sort();
    const sections = [...new Set(tasks.map(t => t.TaskDescription || '-'))].filter(Boolean).sort();
    const taskNames = [...new Set(tasks.map(t => t.TaskName || '-'))].filter(Boolean).sort();

    populateDropdown("filterTeamEmployee", "All Employees", employees);
    populateDropdown("filterTeamSection", "All Sections", sections);
    populateDropdown("filterTeamTaskName", "All Tasks", taskNames);

    document.getElementById("filterTeamStatus").value = "all";

    renderTeamTasks(tasks);
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="5" style="padding: 1em; text-align: center; color: red;">Failed to load tasks: ${err.message}</td></tr>`;
  }
}

function renderTeamTasks(tasks) {
  const tbody = document.getElementById("teamTableBody");
  if (tasks.length === 0) {
    tbody.innerHTML = `<tr><td colspan="5" style="padding: 1em; text-align: center;">No tasks match your filters.</td></tr>`;
    return;
  }

  tbody.innerHTML = tasks.map(t => {
    const empName = t.EmployeeName || t.TeamMemberName || 'Unknown';
    return `
      <tr style="border-bottom: 1px solid #eee;">
        <td style="padding: 0.8em; vertical-align: top; font-size: 0.85em; font-weight: bold;">
          ${empName}
        </td>
        <td style="padding: 0.8em; vertical-align: top; font-size: 0.85em; color: #555;">
          ${t.TaskDescription || "-"}
        </td>
        <td style="padding: 0.8em; vertical-align: top; font-weight: bold;">
          ${t.TaskName}
        </td>
        <td style="padding: 0.8em; vertical-align: top;">${t.AllocatedHours} h</td>
        <td style="padding: 0.8em; vertical-align: top;">${t.Accomplished ? '✅ Done' : '⏳ Pending'}</td>
      </tr>
    `;
  }).join("");
}

function filterTeamTasks() {
  const empFilter = document.getElementById("filterTeamEmployee").value;
  const sectionFilter = document.getElementById("filterTeamSection").value;
  const taskFilter = document.getElementById("filterTeamTaskName").value;
  const statusFilter = document.getElementById("filterTeamStatus").value;

  const filtered = allTeamTasks.filter(t => {
    const empName = t.EmployeeName || t.TeamMemberName || 'Unknown';
    const taskDesc = t.TaskDescription || '-';
    const taskName = t.TaskName || '-';

    if (empFilter !== "all" && empName !== empFilter) return false;
    if (sectionFilter !== "all" && taskDesc !== sectionFilter) return false;
    if (taskFilter !== "all" && taskName !== taskFilter) return false;

    if (statusFilter === 'done' && !t.Accomplished) return false;
    if (statusFilter === 'pending' && t.Accomplished) return false;

    return true;
  });

  renderTeamTasks(filtered);
}

function clearTeamFilters() {
  document.getElementById("filterTeamEmployee").value = "all";
  document.getElementById("filterTeamSection").value = "all";
  document.getElementById("filterTeamTaskName").value = "all";
  document.getElementById("filterTeamStatus").value = "all";
  filterTeamTasks();
}

function hideTeamTable() {
  document.getElementById("teamTableView").style.display = "none";
  document.getElementById("missionView").style.display = "block";
}

// ============================================================
// ADMIN PANEL
// ============================================================

function showAdminPanel() {
  // Hide every non-admin view
  const hideIds = [
    "listView", "missionView", "tableView", "teamTableView",
    "timeLogsView", "allMissionsCard", "noWork", "myH", "filterContainer"
  ];
  hideIds.forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.display = "none";
  });

  document.getElementById("adminView").style.display = "block";

  // Hide "Back to App" for admins (they live in the admin panel)
  const role = who.textContent.toLowerCase();
  const isAdmin = role.includes("administrator");
  const backBtn = document.querySelector("#adminView button[onclick='hideAdminPanel()']");
  if (backBtn) backBtn.style.display = isAdmin ? "none" : "inline-block";

  showAdminTab("teams");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function hideAdminPanel() {
  // Admins shouldn't be able to leave the admin panel
  const role = who.textContent.toLowerCase();
  if (role.includes("administrator")) return;

  document.getElementById("adminView").style.display = "none";

  if (!myMissionsData || myMissionsData.length === 0) {
    document.getElementById("noWork").style.display = "block";
    document.getElementById("listView").style.display = "none";
  } else {
    document.getElementById("listView").style.display = "block";
    document.getElementById("myH").style.display = "block";
    document.getElementById("filterContainer").style.display = "flex";
    document.getElementById("allMissionsCard").style.display = "block";
  }

  document.getElementById("btnViewLogs").style.display = "inline-block";
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function showAdminTab(tab) {
  adminCurrentTab = tab;
  const tabs = ["teams", "employees", "clients"];
  tabs.forEach(t => {
    const el = document.getElementById("adminTab" + t[0].toUpperCase() + t.slice(1));
    if (el) el.style.display = (t === tab) ? "block" : "none";
    const btn = document.getElementById("tabBtn" + t[0].toUpperCase() + t.slice(1));
    if (btn) btn.style.background = (t === tab) ? "#1a4f82" : "#2b6cb0";
  });

  if (tab === "teams") loadAdminTeams();
  if (tab === "employees") loadAdminEmployees();
  if (tab === "clients") loadAdminClients();
}

// ---------- TEAMS ----------

async function loadAdminTeams() {
  const tbody = document.getElementById("adminTeamsBody");
  tbody.innerHTML = `<tr><td colspan="4" style="text-align:center; padding:1em;">Loading...</td></tr>`;
  try {
    adminTeams = await api("/api/admin/teams");
    tbody.innerHTML = adminTeams.map(t => `
      <tr style="border-bottom: 1px solid #eee;">
        <td style="padding:.6em;"><b>${t.TeamName}</b></td>
        <td style="padding:.6em;">${t.LeaderName || '<i>none</i>'}</td>
        <td style="padding:.6em;">${t.MemberCount ?? '-'}</td>
        <td style="padding:.6em;">
          <button onclick="openTeamForm(${t.LeaderID})">Edit</button>
          <button onclick="deleteTeam(${t.LeaderID})" style="background:#e53935;">Delete</button>
        </td>
      </tr>
    `).join("") || `<tr><td colspan="4" style="text-align:center; padding:1em;">No teams.</td></tr>`;
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="4" style="color:red; padding:1em;">${e.message}</td></tr>`;
  }
}

async function openTeamForm(leaderId = null) {
  const editing = leaderId != null;
  const team = editing ? adminTeams.find(t => t.LeaderID === leaderId) : {};
  const emps = await api("/api/admin/employees");
  adminEmployees = emps;

  const empOptions = emps.map(e =>
    `<option value="${e.EmployeeID}" ${team.LeaderID === e.EmployeeID ? "selected" : ""}>${e.EmployeeName} (${e.Username})</option>`
  ).join("");

  const memberIds = team.member_ids || [];
  const memberChecks = emps.map(e =>
    `<label style="display:block;">
       <input type="checkbox" class="teamMemberChk" value="${e.EmployeeID}"
         ${memberIds.includes(e.EmployeeID) ? "checked" : ""}/>
       ${e.EmployeeName}
     </label>`
  ).join("");

  document.getElementById("adminModalTitle").textContent = editing ? "Edit Team" : "New Team";
  document.getElementById("adminModalFields").innerHTML = `
    <label style="display:block; margin-bottom:.5em;">Team Name
      <input id="tmName" value="${team.TeamName || ''}" style="width:100%">
    </label>
    <label style="display:block; margin-bottom:.5em;">Leader
      <select id="tmLeader" style="width:100%">
        <option value="">— none —</option>${empOptions}
      </select>
    </label>
    <div style="margin-top:.5em;"><b>Members</b>
      <div style="max-height:200px; overflow:auto; border:1px solid #ddd; padding:.4em; border-radius:4px;">
        ${memberChecks}
      </div>
    </div>
  `;
  adminModalContext = { type: "team", mode: editing ? "edit" : "create", id: leaderId };
  document.getElementById("adminModal").style.display = "block";
}

async function deleteTeam(leaderId) {
  if (!confirm("Detach all members from this team?")) return;
  try {
    await api(`/api/admin/teams/${leaderId}`, { method: "DELETE" });
    loadAdminTeams();
  } catch (e) { alert("Delete failed: " + e.message); }
}

// ---------- EMPLOYEES ----------

async function loadAdminEmployees() {
  const tbody = document.getElementById("adminEmployeesBody");
  tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding:1em;">Loading...</td></tr>`;
  try {
    adminEmployees = await api("/api/admin/employees");
    tbody.innerHTML = adminEmployees.map(e => `
      <tr style="border-bottom: 1px solid #eee;">
        <td style="padding:.6em;"><b>${e.EmployeeName}</b></td>
        <td style="padding:.6em;">${e.Username}</td>
        <td style="padding:.6em;">${e.Classification || '-'}</td>
        <td style="padding:.6em;">${e.TeamLeader || '<i>none</i>'}</td>
        <td style="padding:.6em;">
          <button onclick="openEmployeeForm(${e.EmployeeID})">Edit</button>
          <button onclick="deleteEmployee(${e.EmployeeID})" style="background:#e53935;">Delete</button>
        </td>
      </tr>
    `).join("") || `<tr><td colspan="5" style="text-align:center; padding:1em;">No employees.</td></tr>`;
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="5" style="color:red; padding:1em;">${e.message}</td></tr>`;
  }
}

async function openEmployeeForm(empId = null) {
  const editing = empId != null;
  const emp = editing ? adminEmployees.find(e => e.EmployeeID === empId) : {};

  // Leaders we can assign this employee to (everyone except themselves)
  const teams = adminTeams.length ? adminTeams : await api("/api/admin/teams");
  adminTeams = teams;
  const leaderOptions = teams
    .filter(t => !editing || t.LeaderID !== empId)
    .map(t => `<option value="${t.LeaderName}" ${emp.TeamLeader === t.LeaderName ? "selected" : ""}>${t.LeaderName}</option>`)
    .join("");

  document.getElementById("adminModalTitle").textContent = editing ? "Edit Employee" : "New Employee";
  document.getElementById("adminModalFields").innerHTML = `
    <label style="display:block; margin-bottom:.5em;">Name
      <input id="empName" value="${emp.EmployeeName || ''}" style="width:100%">
    </label>
    <label style="display:block; margin-bottom:.5em;">Username
      <input id="empUser" value="${emp.Username || ''}" style="width:100%" ${editing ? "readonly" : ""}>
    </label>
    <label style="display:block; margin-bottom:.5em;">Password
      <input id="empPass" type="password" placeholder="${editing ? "(leave blank to keep)" : ""}" style="width:100%">
    </label>
    <label style="display:block; margin-bottom:.5em;">Classification
      <select id="empClass" style="width:100%">
        ${["Member", "Team Leader", "Administrator"].map(c =>
          `<option ${emp.Classification === c ? "selected" : ""}>${c}</option>`).join("")}
      </select>
    </label>
    <label style="display:block; margin-bottom:.5em;">Reports to (Team Leader)
      <select id="empTeam" style="width:100%">
        <option value="">— none —</option>${leaderOptions}
      </select>
    </label>
  `;
  adminModalContext = { type: "employee", mode: editing ? "edit" : "create", id: empId };
  document.getElementById("adminModal").style.display = "block";
}

async function deleteEmployee(empId) {
  if (!confirm("Delete this employee?")) return;
  try {
    await api(`/api/admin/employees/${empId}`, { method: "DELETE" });
    loadAdminEmployees();
  } catch (e) { alert("Delete failed: " + e.message); }
}

// ---------- CLIENTS ----------

async function loadAdminClients() {
  const tbody = document.getElementById("adminClientsBody");
  tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:1em;">Loading...</td></tr>`;
  try {
    adminClients = await api("/api/admin/clients");
    tbody.innerHTML = adminClients.map(c => `
      <tr style="border-bottom: 1px solid #eee;">
        <td style="padding:.6em;"><b>${c.CustomerName}</b></td>
        <td style="padding:.6em;">${c.IDHonorary || '-'}</td>
        <td style="padding:.6em;">${c.Contact || '-'}</td>
        <td style="padding:.6em;">${c.Email || '-'}</td>
        <td style="padding:.6em;">${c.Phone || '-'}</td>
        <td style="padding:.6em;">
          ${c.ClientID != null ? `
            <button onclick="openClientForm(${c.ClientID})">Edit</button>
            <button onclick="deleteClient(${c.ClientID})" style="background:#e53935;">Delete</button>
          ` : `<span class="muted" style="font-size:.85em; font-style:italic;">from missions</span>`}
        </td>
      </tr>
    `).join("") || `<tr><td colspan="6" style="text-align:center; padding:1em;">No clients.</td></tr>`;
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="6" style="color:red; padding:1em;">${e.message}</td></tr>`;
  }
}

async function openClientForm(clientId = null) {
  const editing = clientId != null;
  const c = editing ? adminClients.find(x => x.ClientID === clientId) : {};

  document.getElementById("adminModalTitle").textContent = editing ? "Edit Client" : "New Client";
  document.getElementById("adminModalFields").innerHTML = `
    <label style="display:block; margin-bottom:.5em;">Customer Name
      <input id="clName" value="${c.CustomerName || ''}" style="width:100%">
    </label>
    <label style="display:block; margin-bottom:.5em;">ID Honorary
      <input id="clID" value="${c.IDHonorary || ''}" style="width:100%">
    </label>
    <label style="display:block; margin-bottom:.5em;">Contact
      <input id="clContact" value="${c.Contact || ''}" style="width:100%">
    </label>
    <label style="display:block; margin-bottom:.5em;">Email
      <input id="clEmail" value="${c.Email || ''}" style="width:100%">
    </label>
    <label style="display:block; margin-bottom:.5em;">Phone
      <input id="clPhone" value="${c.Phone || ''}" style="width:100%">
    </label>
    <label style="display:block; margin-bottom:.5em;">Address
      <input id="clAddr" value="${c.Address || ''}" style="width:100%">
    </label>
  `;
  adminModalContext = { type: "client", mode: editing ? "edit" : "create", id: clientId };
  document.getElementById("adminModal").style.display = "block";
}

async function deleteClient(clientId) {
  if (!confirm("Delete this client?")) return;
  try {
    await api(`/api/admin/clients/${clientId}`, { method: "DELETE" });
    loadAdminClients();
  } catch (e) { alert("Delete failed: " + e.message); }
}

// ---------- MODAL SUBMIT ----------

async function submitAdminModal() {
  const ctx = adminModalContext;
  if (!ctx) return;
  const isEdit = ctx.mode === "edit";
  const url = {
    team: "/api/admin/teams" + (isEdit ? `/${ctx.id}` : ""),
    employee: "/api/admin/employees" + (isEdit ? `/${ctx.id}` : ""),
    client: "/api/admin/clients" + (isEdit ? `/${ctx.id}` : ""),
  }[ctx.type];
  const method = isEdit ? "PATCH" : "POST";

  let payload = {};
  try {
    if (ctx.type === "team") {
      payload = {
        TeamName: document.getElementById("tmName").value.trim(),
        LeaderEmployeeID: Number(document.getElementById("tmLeader").value) || null,
        MemberIDs: [...document.querySelectorAll(".teamMemberChk:checked")]
          .map(c => Number(c.value)),
      };
    } else if (ctx.type === "employee") {
      payload = {
        EmployeeName: document.getElementById("empName").value.trim(),
        Username: document.getElementById("empUser").value.trim(),
        Password: document.getElementById("empPass").value || undefined,
        Classification: document.getElementById("empClass").value,
        TeamLeader: document.getElementById("empTeam").value || null,
      };
      if (isEdit && !payload.Password) delete payload.Password;
    } else if (ctx.type === "client") {
      payload = {
        CustomerName: document.getElementById("clName").value.trim(),
        IDHonorary: document.getElementById("clID").value.trim() || null,
        Contact: document.getElementById("clContact").value.trim() || null,
        Email: document.getElementById("clEmail").value.trim() || null,
        Phone: document.getElementById("clPhone").value.trim() || null,
        Address: document.getElementById("clAddr").value.trim() || null,
      };
    }

    await api(url, { method, body: JSON.stringify(payload) });
    closeAdminModal();

    if (ctx.type === "team") loadAdminTeams();
    if (ctx.type === "employee") loadAdminEmployees();
    if (ctx.type === "client") loadAdminClients();
  } catch (e) {
    alert("Save failed: " + e.message);
  }
}

function closeAdminModal() {
  document.getElementById("adminModal").style.display = "none";
  document.getElementById("adminModalFields").innerHTML = "";
  adminModalContext = null;
}

// ============================================================
// BOOTSTRAP
// ============================================================

if (token) {
  api("/api/me")
    .then(user => {
      who.textContent = user.EmployeeName + (user.Classification ? ` (${user.Classification})` : "");
      const role = (user.Classification || "").toLowerCase();
      const isAdmin = role === "administrator";
      document.getElementById("btnAdminPanel").style.display = isAdmin ? "inline-block" : "none";
      document.getElementById("btnDownloadLogs").style.display =
        (role === "team leader" || isAdmin) ? "inline-block" : "none";
      document.getElementById("loginContainer").style.display = "none";
      document.getElementById("app").style.display = "block";
      return checkActiveTimer().then(() => loadMe());
    })
    .catch(() => {
      localStorage.removeItem("token");
      token = "";
    });
}