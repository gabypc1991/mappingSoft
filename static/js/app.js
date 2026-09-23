let state = null;
let selectedFace = -1;
let dragging = -1;
let menuFace = -1;
let projectsModal = null;
let dragSyncInFlight = false;
let dragSyncPending = false;
let lastDragSyncAt = 0;
let activePointerId = null;
let longPressTimer = null;
let longPressTriggered = false;
let touchStartX = 0;
let touchStartY = 0;

const LONG_PRESS_MS = 520;
const LONG_PRESS_MOVE_THRESHOLD = 12;

const canvas = document.getElementById("overlay");
const ctx = canvas.getContext("2d");
const menu = document.getElementById("menu");

function api(url, opts = {}) {
  return fetch(url, opts).then((r) => r.json());
}

async function apiWithProjectGuard(url, opts = {}) {
  const response = await fetch(url, opts);
  const data = await response.json().catch(() => ({}));

  if (!response.ok && data.project_required) {
    openProjectsModal();
    alert(data.error || "Debes abrir o crear un proyecto.");
    throw new Error("project_required");
  }

  if (!response.ok) {
    throw new Error(data.error || "Error en solicitud.");
  }

  return data;
}

async function loadState() {
  state = await api("/api/state");
  syncControls();
  draw();
}

function currentScene() {
  return state.scenes[state.current_scene_index] || null;
}

function syncControls() {
  const scenes = document.getElementById("sceneSelect");
  scenes.innerHTML = "";
  state.scenes.forEach((scene, index) => {
    scenes.add(new Option((index + 1) + " - " + scene.name, index));
  });
  scenes.value = state.current_scene_index;

  const screens = document.getElementById("screenSelect");
  screens.innerHTML = "";
  state.screens.forEach((screen, index) => {
    screens.add(new Option(screen.name, index));
  });

  const scene = currentScene();
  if (scene) {
    screens.value = scene.screen_index;
  }

  const status = document.getElementById("status");
  if (state.execution_mode) {
    status.className = "badge text-bg-warning";
    status.textContent = "Ejecucion";
  } else if (state.web_control_active) {
    status.className = "badge text-bg-primary";
    status.textContent = "Control web";
  } else {
    status.className = "badge text-bg-success";
    status.textContent = "Edicion";
  }

  const projectTag = document.getElementById("projectTag");
  if (projectTag) {
    const projectName = (state.project && state.project.name) ? state.project.name : "Sin proyecto";
    projectTag.textContent = "Proyecto: " + projectName;
  }

  const lanUrlTag = document.getElementById("lanUrlTag");
  if (lanUrlTag) {
    lanUrlTag.textContent = "LAN: " + (state.web_lan_url || "N/A");
  }

  syncProjectControls();
}

function syncProjectControls() {
  const projectSelect = document.getElementById("projectSelect");
  if (!projectSelect) {
    return;
  }

  projectSelect.innerHTML = "";
  const projects = state.projects || [];
  projects.forEach((project) => {
    projectSelect.add(new Option(project.name, project.name));
  });

  if (state.project && state.project.name) {
    projectSelect.value = state.project.name;
  }

  const currentProjectPath = document.getElementById("currentProjectPath");
  if (currentProjectPath) {
    currentProjectPath.textContent = (state.project && state.project.path)
      ? state.project.path
      : "Sin proyecto activo";
  }

  syncSelectedProjectPath();
}

function syncSelectedProjectPath() {
  const projectSelect = document.getElementById("projectSelect");
  const selectedProjectPath = document.getElementById("selectedProjectPath");
  if (!projectSelect || !selectedProjectPath) {
    return;
  }

  const selectedName = projectSelect.value;
  const projects = state.projects || [];
  const selectedProject = projects.find((project) => project.name === selectedName);

  selectedProjectPath.textContent = selectedProject
    ? "Ruta: " + selectedProject.path
    : "";
}

async function copyLanUrl() {
  const lanUrl = state && state.web_lan_url ? state.web_lan_url : "";
  if (!lanUrl) {
    alert("No hay URL LAN disponible.");
    return;
  }

  try {
    await navigator.clipboard.writeText(lanUrl);
    alert("URL copiada: " + lanUrl);
  } catch {
    alert("No se pudo copiar automaticamente. URL: " + lanUrl);
  }
}

function fit() {
  canvas.width = canvas.clientWidth;
  canvas.height = canvas.clientHeight;
}

function scaleInfo() {
  const width = state.canvas_width || 1280;
  const height = state.canvas_height || 720;
  const scale = Math.min(canvas.width / width, canvas.height / height);
  const offsetX = (canvas.width - width * scale) / 2;
  const offsetY = (canvas.height - height * scale) / 2;
  return { scale, offsetX, offsetY, width, height };
}

function toScreen(point) {
  const f = scaleInfo();
  return [f.offsetX + point[0] * f.scale, f.offsetY + point[1] * f.scale];
}

function toWorld(x, y) {
  const f = scaleInfo();
  return [Math.round((x - f.offsetX) / f.scale), Math.round((y - f.offsetY) / f.scale)];
}

function draw() {
  fit();
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  const scene = currentScene();
  if (!scene) {
    return;
  }

  scene.faces.forEach((face, index) => {
    ctx.beginPath();
    face.points.forEach((point, pointIndex) => {
      const p = toScreen(point);
      if (pointIndex === 0) {
        ctx.moveTo(p[0], p[1]);
      } else {
        ctx.lineTo(p[0], p[1]);
      }
    });
    ctx.closePath();
    ctx.strokeStyle = index === selectedFace ? "#ffe066" : "#49ffd6";
    ctx.lineWidth = 2;
    ctx.stroke();

    if (index === selectedFace) {
      face.points.forEach((point) => {
        const p = toScreen(point);
        ctx.beginPath();
        ctx.arc(p[0], p[1], 8, 0, Math.PI * 2);
        ctx.fillStyle = "#ff5d73";
        ctx.fill();
        ctx.strokeStyle = "#ffffff";
        ctx.stroke();
      });
    }
  });
}

function faceAt(x, y) {
  const scene = currentScene();
  if (!scene) {
    return -1;
  }

  for (let faceIndex = scene.faces.length - 1; faceIndex >= 0; faceIndex -= 1) {
    const points = scene.faces[faceIndex].points.map(toScreen);
    let inside = false;
    let j = points.length - 1;

    for (let i = 0; i < points.length; i += 1) {
      const xi = points[i][0];
      const yi = points[i][1];
      const xj = points[j][0];
      const yj = points[j][1];

      if (((yi > y) !== (yj > y)) && (x < (xj - xi) * (y - yi) / (yj - yi + 0.00001) + xi)) {
        inside = !inside;
      }
      j = i;
    }

    if (inside) {
      return faceIndex;
    }
  }

  return -1;
}

function openFaceMenuAt(clientX, clientY) {
  if (state.execution_mode) {
    return;
  }

  const rect = canvas.getBoundingClientRect();
  menuFace = faceAt(clientX - rect.left, clientY - rect.top);
  if (menuFace < 0) {
    return;
  }

  selectedFace = menuFace;
  draw();

  menu.style.left = clientX + "px";
  menu.style.top = clientY + "px";
  menu.style.display = "block";
}

function clearLongPressTimer() {
  if (longPressTimer) {
    clearTimeout(longPressTimer);
    longPressTimer = null;
  }
}

function beginPointerInteraction(clientX, clientY) {
  menu.style.display = "none";
  if (state.execution_mode) {
    return;
  }

  const scene = currentScene();
  if (!scene) {
    return;
  }

  const rect = canvas.getBoundingClientRect();
  const x = clientX - rect.left;
  const y = clientY - rect.top;

  if (selectedFace >= 0) {
    const face = scene.faces[selectedFace];
    for (let i = 0; i < 4; i += 1) {
      const p = toScreen(face.points[i]);
      if (Math.hypot(x - p[0], y - p[1]) < 18) {
        dragging = i;
        return;
      }
    }
  }

  selectedFace = faceAt(x, y);
  draw();
}

function movePointerInteraction(clientX, clientY) {
  if (dragging < 0 || selectedFace < 0 || state.execution_mode) {
    return;
  }

  const rect = canvas.getBoundingClientRect();
  const worldPoint = toWorld(clientX - rect.left, clientY - rect.top);
  currentScene().faces[selectedFace].points[dragging] = worldPoint;
  draw();
  syncDraggedFacePoints(false);
}

async function endPointerInteraction() {
  if (dragging < 0 || selectedFace < 0) {
    return;
  }

  dragging = -1;
  await syncDraggedFacePoints(true);
}

canvas.addEventListener("pointerdown", (e) => {
  activePointerId = e.pointerId;
  longPressTriggered = false;

  if (canvas.setPointerCapture) {
    canvas.setPointerCapture(e.pointerId);
  }

  if (e.pointerType === "touch") {
    e.preventDefault();
    touchStartX = e.clientX;
    touchStartY = e.clientY;
  }

  beginPointerInteraction(e.clientX, e.clientY);

  if (e.pointerType === "touch" && dragging < 0) {
    clearLongPressTimer();
    longPressTimer = setTimeout(() => {
      longPressTriggered = true;
      openFaceMenuAt(e.clientX, e.clientY);
    }, LONG_PRESS_MS);
  }
});

canvas.addEventListener("pointermove", (e) => {
  if (activePointerId !== null && e.pointerId !== activePointerId) {
    return;
  }

  if (e.pointerType === "touch") {
    e.preventDefault();

    const dx = e.clientX - touchStartX;
    const dy = e.clientY - touchStartY;
    if (Math.hypot(dx, dy) > LONG_PRESS_MOVE_THRESHOLD) {
      clearLongPressTimer();
    }
  }

  movePointerInteraction(e.clientX, e.clientY);
});

canvas.addEventListener("pointerup", async (e) => {
  if (activePointerId !== null && e.pointerId !== activePointerId) {
    return;
  }

  activePointerId = null;
  clearLongPressTimer();

  if (canvas.releasePointerCapture) {
    try {
      canvas.releasePointerCapture(e.pointerId);
    } catch {
      // No action needed when pointer capture is already released.
    }
  }

  if (longPressTriggered) {
    dragging = -1;
    return;
  }

  await endPointerInteraction();
});

canvas.addEventListener("pointercancel", async (e) => {
  if (activePointerId !== null && e.pointerId !== activePointerId) {
    return;
  }

  activePointerId = null;
  clearLongPressTimer();
  dragging = -1;

  if (canvas.releasePointerCapture) {
    try {
      canvas.releasePointerCapture(e.pointerId);
    } catch {
      // No action needed when pointer capture is already released.
    }
  }

  await syncDraggedFacePoints(true);
});

async function syncDraggedFacePoints(force) {
  if (!state || selectedFace < 0 || state.current_scene_index < 0) {
    return;
  }

  const now = Date.now();
  if (!force && now - lastDragSyncAt < 60) {
    return;
  }

  if (dragSyncInFlight) {
    dragSyncPending = true;
    return;
  }

  dragSyncInFlight = true;
  lastDragSyncAt = now;

  try {
    await api(
      "/api/scenes/" + state.current_scene_index + "/faces/" + selectedFace + "/points",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ points: currentScene().faces[selectedFace].points })
      }
    );
  } finally {
    dragSyncInFlight = false;
    if (dragSyncPending) {
      dragSyncPending = false;
      await syncDraggedFacePoints(true);
    }
  }
}

canvas.addEventListener("contextmenu", (e) => {
  e.preventDefault();
  openFaceMenuAt(e.clientX, e.clientY);
});

async function selectScene() {
  await api("/api/scenes/" + document.getElementById("sceneSelect").value + "/select", { method: "POST" });
  selectedFace = -1;
  await loadState();
}

async function newScene() {
  const name = prompt("Nombre de escena", "Escena " + (state.scenes.length + 1));
  if (!name) {
    return;
  }

  try {
    await apiWithProjectGuard("/api/scenes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name })
    });
  } catch {
    return;
  }
  await loadState();
}

function pickFaceForNew() {
  document.getElementById("newFaceInput").click();
}

async function addFaceFromUpload() {
  const input = document.getElementById("newFaceInput");
  const file = input.files[0];
  if (!file) {
    return;
  }

  const fd = new FormData();
  fd.append("file", file);

  try {
    await apiWithProjectGuard(
      "/api/scenes/" + state.current_scene_index + "/faces",
      {
        method: "POST",
        body: fd
      }
    );
  } catch (e) {
    if (e.message !== "project_required") {
      alert(e.message || "Error subiendo archivo.");
    }
  }

  input.value = "";
  await loadState();
}

async function deleteScene() {
  if (!confirm("Eliminar escena?")) {
    return;
  }

  await api("/api/scenes/" + state.current_scene_index, { method: "DELETE" });
  selectedFace = -1;
  await loadState();
}

async function assignScreen() {
  await api("/api/scenes/" + state.current_scene_index + "/screen", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ screen_index: +document.getElementById("screenSelect").value })
  });
  await loadState();
}

async function addFace() {
  pickFaceForNew();
}

async function deleteFace() {
  if (menuFace < 0 || !confirm("Eliminar cara?")) {
    return;
  }

  await api("/api/scenes/" + state.current_scene_index + "/faces/" + menuFace, { method: "DELETE" });
  menu.style.display = "none";
  selectedFace = -1;
  await loadState();
}

async function flipFace(axis) {
  if (menuFace < 0) {
    return;
  }

  await api("/api/scenes/" + state.current_scene_index + "/faces/" + menuFace + "/flip", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ axis })
  });
  menu.style.display = "none";
  await loadState();
}

async function rotateFace(degrees) {
  if (menuFace < 0) {
    return;
  }

  await api("/api/scenes/" + state.current_scene_index + "/faces/" + menuFace + "/rotate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ degrees })
  });
  menu.style.display = "none";
  await loadState();
}

function pickFile() {
  document.getElementById("fileInput").click();
}

async function uploadFile() {
  const file = document.getElementById("fileInput").files[0];
  if (!file || menuFace < 0) {
    return;
  }

  const formData = new FormData();
  formData.append("file", file);

  await fetch(
    "/api/scenes/" + state.current_scene_index + "/faces/" + menuFace + "/file",
    {
      method: "POST",
      body: formData
    }
  );
  menu.style.display = "none";
  await loadState();
}

async function takeControl() {
  await api("/api/control/take", { method: "POST" });
  setTimeout(loadState, 300);
}

async function releaseControl() {
  await api("/api/control/release", { method: "POST" });
  setTimeout(loadState, 300);
}

async function executeAll() {
  try {
    await apiWithProjectGuard("/api/control/execute", { method: "POST" });
  } catch {
    return;
  }
  setTimeout(loadState, 300);
}

async function exitExecution() {
  await api("/api/control/exit", { method: "POST" });
  setTimeout(loadState, 300);
}

function openProjectsModal() {
  if (!projectsModal) {
    projectsModal = new bootstrap.Modal(document.getElementById("projectsModal"));
  }
  syncProjectControls();
  projectsModal.show();
}

async function createProject() {
  const name = document.getElementById("projectNameInput").value.trim();
  if (!name) {
    alert("Ingresa nombre de proyecto.");
    return;
  }

  await api("/api/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name })
  });

  document.getElementById("projectNameInput").value = "";
  await loadState();
  if (projectsModal) {
    projectsModal.hide();
  }
}

async function openSelectedProject() {
  const projectName = document.getElementById("projectSelect").value;
  if (!projectName) {
    alert("Selecciona un proyecto.");
    return;
  }

  await api("/api/projects/open", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: projectName })
  });

  await loadState();
  if (projectsModal) {
    projectsModal.hide();
  }
}

window.addEventListener("resize", draw);
setInterval(loadState, 1500);
loadState();
