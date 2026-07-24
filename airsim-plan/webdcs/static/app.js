// ----------------------------------------------------------------------------
// Configuración de visualización del mapa
// ----------------------------------------------------------------------------
let mapScale = 2.5; 
let mapCenter = { x: 0, y: 0 }; 

let activeManifest = null;
let originalManifestString = ''; // Para control de cambios (dirty state)
let savedManifests = [];
let compiledManifestTemp = null; // Temp para fusionar waypoints de LLM
let manifestToDeleteFilename = ''; // Temp para guardar el nombre del archivo a eliminar

// Elementos del DOM
const elNlInstruction = document.getElementById('nl-instruction');
const elBtnCompile = document.getElementById('btn-compile');
const elCompileSpinner = document.getElementById('compile-spinner');
const elSavedList = document.getElementById('saved-manifests-list');
const elJsonEditor = document.getElementById('json-editor');
const elBtnSave = document.getElementById('btn-save');
const elValidationStatus = document.getElementById('validation-status');
const elToast = document.getElementById('toast');
const elHoverX = document.getElementById('hover-x');
const elHoverY = document.getElementById('hover-y');
const elBtnResetMap = document.getElementById('btn-reset-map');

// Elementos de navegación del Sidebar
const elViewManifestsList = document.getElementById('view-manifests-list');
const elViewWaypointsDetail = document.getElementById('view-waypoints-detail');
const elActiveMissionTitle = document.getElementById('active-mission-title');
const elActiveWaypointList = document.getElementById('active-waypoint-list');
const elBtnBackManifests = document.getElementById('btn-back-manifests');
const elBtnNewManifest = document.getElementById('btn-new-manifest');

// Modales y Nuevo Manifiesto con Mapa
const elModalNewMission = document.getElementById('modal-new-mission');
const elNewMissionId = document.getElementById('new-mission-id');
const elNewMissionMap = document.getElementById('new-mission-map');
const elBtnModalCreate = document.getElementById('btn-modal-create');
const elBtnModalCancelCreate = document.getElementById('btn-modal-cancel-create');

// Modales
const elModalSaveConfirm = document.getElementById('modal-save-confirm');
const elBtnModalSave = document.getElementById('btn-modal-save');
const elBtnModalDiscard = document.getElementById('btn-modal-discard');
const elBtnModalCancelSave = document.getElementById('btn-modal-cancel-save');

const elModalMergeStrategy = document.getElementById('modal-merge-strategy');
const elBtnMergeOverwrite = document.getElementById('btn-merge-overwrite');
const elBtnMergeAppend = document.getElementById('btn-merge-append');
const elBtnMergePrepend = document.getElementById('btn-merge-prepend');
const elBtnMergeCancel = document.getElementById('btn-merge-cancel');

const elModalDeleteConfirm = document.getElementById('modal-delete-confirm');
const elDeleteManifestName = document.getElementById('delete-manifest-name');
const elBtnModalDeleteConfirm = document.getElementById('btn-modal-delete-confirm');
const elBtnModalDeleteCancel = document.getElementById('btn-modal-delete-cancel');

// Canvas setup
const canvas = document.getElementById('route-canvas');
const ctx = canvas.getContext('2d');
const mapImage = document.getElementById('map-image');

// ----------------------------------------------------------------------------
// Inicialización
// ----------------------------------------------------------------------------
window.addEventListener('load', () => {
    resizeCanvas();
    loadSavedManifests();
    loadAvailableMaps();
    setupModalListeners();
    setupNewManifestListener();
});

window.addEventListener('resize', resizeCanvas);

function resizeCanvas() {
    canvas.width = canvas.parentElement.clientWidth;
    canvas.height = canvas.parentElement.clientHeight;
    mapCenter.x = canvas.width / 2;
    mapCenter.y = canvas.height / 2;
    drawRoute();
}

// ----------------------------------------------------------------------------
// Control de Dirty State (Cambios sin guardar)
// ----------------------------------------------------------------------------
function isDirty() {
    if (!activeManifest) return false;
    return JSON.stringify(activeManifest) !== originalManifestString;
}

function updateOriginalState() {
    if (activeManifest) {
        originalManifestString = JSON.stringify(activeManifest);
    } else {
        originalManifestString = '';
    }
}

// ----------------------------------------------------------------------------
// Conversión de Coordenadas (NED -> Pixels y viceversa)
// ----------------------------------------------------------------------------
function nedToCanvas(nedX, nedY) {
    return {
        x: mapCenter.x + (nedY * mapScale),
        y: mapCenter.y - (nedX * mapScale)
    };
}

function canvasToNed(canvasX, canvasY) {
    return {
        x: (mapCenter.y - canvasY) / mapScale,
        y: (canvasX - mapCenter.x) / mapScale
    };
}

// ----------------------------------------------------------------------------
// Dibujar Ruta en Canvas
// ----------------------------------------------------------------------------
function drawRoute() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    
    // 1. Dibujar punto de referencia Home (0,0)
    const homePos = nedToCanvas(0, 0);
    ctx.beginPath();
    ctx.arc(homePos.x, homePos.y, 8, 0, 2 * Math.PI);
    ctx.fillStyle = '#f59e0b';
    ctx.shadowBlur = 12;
    ctx.shadowColor = '#f59e0b';
    ctx.fill();
    ctx.shadowBlur = 0; 
    
    ctx.font = 'bold 10px Outfit';
    ctx.fillStyle = '#f59e0b';
    ctx.fillText('HOME (0,0)', homePos.x + 12, homePos.y + 4);

    if (!activeManifest || !activeManifest.waypoints || activeManifest.waypoints.length === 0) {
        return;
    }

    const wps = activeManifest.waypoints;

    // 2. Dibujar líneas de trayectoria
    ctx.beginPath();
    const firstPos = nedToCanvas(wps[0].x, wps[0].y);
    ctx.moveTo(firstPos.x, firstPos.y);

    for (let i = 1; i < wps.length; i++) {
        const pos = nedToCanvas(wps[i].x, wps[i].y);
        ctx.lineTo(pos.x, pos.y);
    }
    
    ctx.strokeStyle = '#06b6d4';
    ctx.lineWidth = 3;
    ctx.setLineDash([5, 5]); 
    ctx.shadowBlur = 8;
    ctx.shadowColor = '#06b6d4';
    ctx.stroke();
    ctx.setLineDash([]); 
    ctx.shadowBlur = 0;

    // 3. Dibujar Waypoints (nodos)
    wps.forEach((wp, idx) => {
        const pos = nedToCanvas(wp.x, wp.y);
        
        ctx.beginPath();
        ctx.arc(pos.x, pos.y, 6, 0, 2 * Math.PI);
        ctx.fillStyle = '#6366f1';
        ctx.shadowBlur = 10;
        ctx.shadowColor = '#6366f1';
        ctx.fill();
        ctx.shadowBlur = 0;

        ctx.strokeStyle = '#ffffff';
        ctx.lineWidth = 1.5;
        ctx.stroke();

        ctx.font = 'bold 11px Outfit';
        ctx.fillStyle = '#ffffff';
        const label = wp.label ? `${idx + 1}: ${wp.label}` : `WP #${idx + 1}`;
        ctx.fillText(label, pos.x + 10, pos.y - 6);
        
        ctx.font = '9px Fira Code';
        ctx.fillStyle = '#a5b4fc';
        ctx.fillText(`[${wp.x.toFixed(1)}, ${wp.y.toFixed(1)}, ${wp.z.toFixed(1)}]`, pos.x + 10, pos.y + 6);
    });
}

// ----------------------------------------------------------------------------
// Interacciones del Mapa
// ----------------------------------------------------------------------------
canvas.addEventListener('mousemove', (e) => {
    const rect = canvas.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    
    const ned = canvasToNed(x, y);
    elHoverX.textContent = ned.x.toFixed(1);
    elHoverY.textContent = ned.y.toFixed(1);
});

canvas.addEventListener('click', (e) => {
    if (!activeManifest) return;
    
    const rect = canvas.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    const ned = canvasToNed(x, y);
    
    let zVal = -10.0;
    if (activeManifest.waypoints && activeManifest.waypoints.length > 0) {
        zVal = activeManifest.waypoints[activeManifest.waypoints.length - 1].z;
    } else if (activeManifest.rules_of_engagement && activeManifest.rules_of_engagement.min_altitude_m !== undefined) {
        zVal = activeManifest.rules_of_engagement.min_altitude_m;
    }
    
    const newWp = {
        x: Math.round(ned.x * 10) / 10,
        y: Math.round(ned.y * 10) / 10,
        z: zVal,
        label: `WP_${activeManifest.waypoints.length + 1}`
    };
    
    activeManifest.waypoints.push(newWp);
    syncManifestToEditor();
    showToast(`Waypoint #${activeManifest.waypoints.length} añadido a la altitud actual: ${zVal}m`, 'success');
});

elBtnResetMap.addEventListener('click', () => {
    mapScale = 2.5;
    if (activeManifest && activeManifest.waypoints && activeManifest.waypoints.length > 0) {
        let maxDist = 50;
        activeManifest.waypoints.forEach(wp => {
            const dist = Math.sqrt(wp.x*wp.x + wp.y*wp.y);
            if (dist > maxDist) maxDist = dist;
        });
        mapScale = (Math.min(canvas.width, canvas.height) / 2) / (maxDist * 1.2);
        mapScale = Math.min(mapScale, 5.0);
    }
    drawRoute();
});

// ----------------------------------------------------------------------------
// Compilación por Lenguaje Natural
// ----------------------------------------------------------------------------
elBtnCompile.addEventListener('click', async () => {
    const text = elNlInstruction.value.trim();
    if (!text) {
        showToast('Escribí una instrucción de misión primero.', 'error');
        return;
    }

    elBtnCompile.disabled = true;
    elCompileSpinner.classList.remove('hidden');
    
    try {
        const response = await fetch('/api/compile', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ instruction: text })
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.detail || 'Error en la compilación.');
        }
        
        // Fusión inteligente: Si ya hay un manifiesto activo, preguntar fusión
        if (activeManifest && activeManifest.waypoints && activeManifest.waypoints.length > 0) {
            compiledManifestTemp = data;
            elModalMergeStrategy.classList.remove('hidden');
        } else {
            // Cargar directamente
            loadActiveManifest(data);
            showToast('Misión compilada con éxito por el LLM', 'success');
        }
        
    } catch (err) {
        console.error(err);
        showToast(err.message, 'error');
        elValidationStatus.innerHTML = `<span class="status-text error"><i class="fa-solid fa-triangle-exclamation"></i> Error: ${err.message}</span>`;
    } finally {
        elBtnCompile.disabled = false;
        elCompileSpinner.classList.add('hidden');
    }
});

// ----------------------------------------------------------------------------
// Gestión del Editor JSON y Sincronización
// ----------------------------------------------------------------------------
elJsonEditor.addEventListener('input', () => {
    validateJson(false); 
});

function syncManifestToEditor() {
    elJsonEditor.value = JSON.stringify(activeManifest, null, 2);
    validateJson(true);
}

function validateJson(isInternalUpdate = false) {
    const raw = elJsonEditor.value.trim();
    if (!raw) {
        elValidationStatus.innerHTML = `<span class="status-text muted">Editor vacío</span>`;
        elBtnSave.disabled = true;
        return;
    }
    
    try {
        const parsed = JSON.parse(raw);
        if (!parsed.mission_id || !parsed.waypoints || !Array.isArray(parsed.waypoints)) {
            throw new Error("Estructura inválida. Debe tener 'mission_id' y lista de 'waypoints'.");
        }
        
        activeManifest = parsed;
        elValidationStatus.innerHTML = `<span class="status-text success"><i class="fa-solid fa-circle-check"></i> Estructura JSON válida</span>`;
        elBtnSave.disabled = false;
        
        renderWaypointList();
        drawRoute();
    } catch (err) {
        elValidationStatus.innerHTML = `<span class="status-text error"><i class="fa-solid fa-triangle-exclamation"></i> JSON inválido: ${err.message}</span>`;
        elBtnSave.disabled = true;
    }
}

// ----------------------------------------------------------------------------
// Render del listado de Waypoints en el Sidebar
// ----------------------------------------------------------------------------
function renderWaypointList() {
    if (!activeManifest || !activeManifest.waypoints) {
        elActiveWaypointList.innerHTML = `<div class="list-placeholder">No hay puntos.</div>`;
        return;
    }

    const wps = activeManifest.waypoints;
    if (wps.length === 0) {
        elActiveWaypointList.innerHTML = `<div class="list-placeholder">No hay puntos.</div>`;
        return;
    }

    elActiveWaypointList.innerHTML = '';
    wps.forEach((wp, idx) => {
        const item = document.createElement('div');
        item.className = 'waypoint-item';
        
        item.innerHTML = `
            <div class="waypoint-item-info">
                <span class="waypoint-item-title">${wp.label ? `${idx+1}: ${wp.label}` : `WP #${idx+1}`}</span>
                <span class="waypoint-item-coords">N:${wp.x.toFixed(1)} E:${wp.y.toFixed(1)} Alt:${wp.z.toFixed(1)}m</span>
            </div>
            <div class="waypoint-actions">
                <button class="btn-mini btn-up" title="Subir" ${idx === 0 ? 'disabled' : ''}>
                    <i class="fa-solid fa-chevron-up"></i>
                </button>
                <button class="btn-mini btn-down" title="Bajar" ${idx === wps.length - 1 ? 'disabled' : ''}>
                    <i class="fa-solid fa-chevron-down"></i>
                </button>
                <button class="btn-mini btn-delete" title="Eliminar">
                    <i class="fa-solid fa-xmark"></i>
                </button>
            </div>
        `;

        item.querySelector('.btn-up').addEventListener('click', (e) => {
            e.stopPropagation();
            swapWaypoints(idx, idx - 1);
        });

        item.querySelector('.btn-down').addEventListener('click', (e) => {
            e.stopPropagation();
            swapWaypoints(idx, idx + 1);
        });

        item.querySelector('.btn-delete').addEventListener('click', (e) => {
            e.stopPropagation();
            deleteWaypoint(idx);
        });

        elActiveWaypointList.appendChild(item);
    });
}

function swapWaypoints(idxA, idxB) {
    if (!activeManifest) return;
    const wps = activeManifest.waypoints;
    const temp = wps[idxA];
    wps[idxA] = wps[idxB];
    wps[idxB] = temp;
    syncManifestToEditor();
}

function deleteWaypoint(idx) {
    if (!activeManifest) return;
    activeManifest.waypoints.splice(idx, 1);
    syncManifestToEditor();
    showToast(`Waypoint #${idx + 1} eliminado de la trayectoria`, 'warning');
}

// ----------------------------------------------------------------------------
// Carga y Visualización de Manifiestos
// ----------------------------------------------------------------------------
function loadActiveManifest(manifest) {
    activeManifest = manifest;
    updateOriginalState();
    
    elActiveMissionTitle.textContent = manifest.mission_id;
    
    // Cargar mapa correspondiente (por defecto map.png si no tiene)
    const mapFile = manifest.map || "map.png";
    mapImage.src = `/maps/${mapFile}`;
    
    elViewManifestsList.classList.add('hidden');
    elViewWaypointsDetail.classList.remove('hidden');
    
    syncManifestToEditor();
    elBtnResetMap.click();
}

// Retroceder al listado general
elBtnBackManifests.addEventListener('click', () => {
    if (isDirty()) {
        elModalSaveConfirm.classList.remove('hidden');
    } else {
        goBackToManifestsList();
    }
});

function goBackToManifestsList() {
    activeManifest = null;
    updateOriginalState();
    
    elViewWaypointsDetail.classList.add('hidden');
    elViewManifestsList.classList.remove('hidden');
    
    elJsonEditor.value = '';
    elValidationStatus.innerHTML = `<span class="status-text muted">Esperando compilación...</span>`;
    elBtnSave.disabled = true;
    
    loadSavedManifests();
    drawRoute();
}

// ----------------------------------------------------------------------------
let availableMaps = [];

async function loadAvailableMaps() {
    try {
        const response = await fetch('/api/maps');
        if (!response.ok) return;
        availableMaps = await response.json();
        
        // Llenar selector de mapas
        elNewMissionMap.innerHTML = '';
        availableMaps.forEach(mapFile => {
            const opt = document.createElement('option');
            opt.value = mapFile;
            opt.textContent = mapFile;
            elNewMissionMap.appendChild(opt);
        });
    } catch (err) {
        console.error('Error cargando mapas disponibles:', err);
    }
}

function setupNewManifestListener() {
    elBtnNewManifest.addEventListener('click', () => {
        if (isDirty()) {
            if (!confirm("Tenés cambios sin guardar en la misión actual. ¿Deseás continuar e iniciar una nueva misión vacía?")) {
                return;
            }
        }
        
        // Reiniciar campos y abrir modal
        elNewMissionId.value = 'NUEVA_MISION_' + (savedManifests.length + 1);
        elModalNewMission.classList.remove('hidden');
    });

    elBtnModalCancelCreate.addEventListener('click', () => {
        elModalNewMission.classList.add('hidden');
    });

    elBtnModalCreate.addEventListener('click', () => {
        const newId = elNewMissionId.value.trim();
        if (!newId) {
            showToast("ID de misión inválido.", "error");
            return;
        }

        const mapFile = elNewMissionMap.value;
        if (!mapFile) {
            showToast("Debes seleccionar un mapa.", "error");
            return;
        }

        const newManifest = {
            mission_id: newId.toUpperCase().replace(/[^A-Z0-9_]/g, '_'),
            summary: "Manifiesto de vuelo vacío creado manualmente.",
            waypoints: [],
            rules_of_engagement: {
                ignore_objects: ["person", "car"],
                return_to_launch_battery_threshold: 20.0,
                max_speed_mps: 5.0,
                min_altitude_m: -10.0
            },
            map: mapFile
        };

        elModalNewMission.classList.add('hidden');
        loadActiveManifest(newManifest);
        showToast(`Manifiesto vacío ${newManifest.mission_id} creado con el mapa ${mapFile}. ¡Hacé click en la carta satelital para agregar puntos!`, 'success');
    });
}

// ----------------------------------------------------------------------------
// Ventanas Modales de Confirmación
// ----------------------------------------------------------------------------
function setupModalListeners() {
    // 1. Modal Confirmación de Guardado
    elBtnModalSave.addEventListener('click', async () => {
        elModalSaveConfirm.classList.add('hidden');
        await saveManifestAction();
        goBackToManifestsList();
    });

    elBtnModalDiscard.addEventListener('click', () => {
        elModalSaveConfirm.classList.add('hidden');
        goBackToManifestsList();
    });

    elBtnModalCancelSave.addEventListener('click', () => {
        elModalSaveConfirm.classList.add('hidden');
    });

    // 2. Modal Estrategia de Fusión LLM
    elBtnMergeOverwrite.addEventListener('click', () => {
        elModalMergeStrategy.classList.add('hidden');
        loadActiveManifest(compiledManifestTemp);
        showToast('Trayectoria sobrescrita con los nuevos waypoints', 'success');
        compiledManifestTemp = null;
    });

    elBtnMergeAppend.addEventListener('click', () => {
        elModalMergeStrategy.classList.add('hidden');
        if (activeManifest && compiledManifestTemp) {
            activeManifest.waypoints = activeManifest.waypoints.concat(compiledManifestTemp.waypoints);
            syncManifestToEditor();
            showToast('Nuevos waypoints agregados al final de la trayectoria', 'success');
        }
        compiledManifestTemp = null;
    });

    elBtnMergePrepend.addEventListener('click', () => {
        elModalMergeStrategy.classList.add('hidden');
        if (activeManifest && compiledManifestTemp) {
            activeManifest.waypoints = compiledManifestTemp.waypoints.concat(activeManifest.waypoints);
            syncManifestToEditor();
            showToast('Nuevos waypoints agregados al principio de la trayectoria', 'success');
        }
        compiledManifestTemp = null;
    });

    elBtnMergeCancel.addEventListener('click', () => {
        elModalMergeStrategy.classList.add('hidden');
        compiledManifestTemp = null;
    });

    // 3. Modal Confirmación de Eliminación
    elBtnModalDeleteConfirm.addEventListener('click', async () => {
        elModalDeleteConfirm.classList.add('hidden');
        if (!manifestToDeleteFilename) return;
        
        try {
            const response = await fetch(`/api/manifests/${manifestToDeleteFilename}`, {
                method: 'DELETE'
            });
            const data = await response.json();
            if (!response.ok) {
                throw new Error(data.detail || 'Error al eliminar.');
            }
            
            showToast(`Manifiesto eliminado con éxito.`, 'success');
            
            // Si el que eliminamos era el que estaba cargado, volver atrás
            if (activeManifest && activeManifest.mission_id.toLowerCase() === manifestToDeleteFilename.replace('.json', '')) {
                goBackToManifestsList();
            } else {
                loadSavedManifests();
            }
        } catch (err) {
            console.error(err);
            showToast(err.message, 'error');
        } finally {
            manifestToDeleteFilename = '';
        }
    });

    elBtnModalDeleteCancel.addEventListener('click', () => {
        elModalDeleteConfirm.classList.add('hidden');
        manifestToDeleteFilename = '';
    });
}

// ----------------------------------------------------------------------------
// API de Guardado
// ----------------------------------------------------------------------------
elBtnSave.addEventListener('click', async () => {
    await saveManifestAction();
});

async function saveManifestAction() {
    if (!activeManifest) return;
    
    elBtnSave.disabled = true;
    try {
        const response = await fetch('/api/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ manifest: activeManifest })
        });
        
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.detail || 'Error al guardar.');
        }
        
        showToast(`Manifiesto ${data.filename} guardado con éxito.`, 'success');
        activeManifest = data.manifest;
        updateOriginalState(); 
        
    } catch (err) {
        console.error(err);
        showToast(err.message, 'error');
    } finally {
        elBtnSave.disabled = false;
    }
}

// ----------------------------------------------------------------------------
// Listar Manifiestos
// ----------------------------------------------------------------------------
async function loadSavedManifests() {
    try {
        const response = await fetch('/api/manifests');
        if (!response.ok) return;
        
        savedManifests = await response.json();
        renderSavedList();
    } catch (err) {
        console.error('Error cargando manifiestos guardados:', err);
    }
}

function renderSavedList() {
    if (savedManifests.length === 0) {
        elSavedList.innerHTML = `<div class="list-placeholder">No hay misiones cargadas.</div>`;
        return;
    }
    
    elSavedList.innerHTML = '';
    savedManifests.forEach(item => {
        const wrapper = document.createElement('div');
        wrapper.style.position = 'relative';
        
        const button = document.createElement('button');
        button.className = 'manifest-item';
        if (activeManifest && activeManifest.mission_id === item.manifest.mission_id) {
            button.className += ' active';
        }
        
        button.innerHTML = `
            <i class="fa-solid fa-route"></i>
            <div class="manifest-item-info">
                <span class="manifest-item-name">${item.manifest.mission_id}</span>
                <span class="manifest-item-desc">${item.manifest.summary || 'Sin descripción.'}</span>
            </div>
        `;
        
        // Botón de eliminar
        const deleteBtn = document.createElement('button');
        deleteBtn.className = 'manifest-item-delete';
        deleteBtn.title = 'Eliminar Manifiesto';
        deleteBtn.innerHTML = `<i class="fa-solid fa-trash-can"></i>`;
        
        deleteBtn.addEventListener('click', (e) => {
            e.stopPropagation(); // Detener propagación para no abrir el manifiesto
            manifestToDeleteFilename = item.filename;
            elDeleteManifestName.textContent = item.manifest.mission_id;
            elModalDeleteConfirm.classList.remove('hidden');
        });
        
        button.addEventListener('click', () => {
            loadActiveManifest(item.manifest);
            showToast(`Cargada la misión ${activeManifest.mission_id}`, 'success');
        });
        
        wrapper.appendChild(button);
        wrapper.appendChild(deleteBtn);
        elSavedList.appendChild(wrapper);
    });
}

// ----------------------------------------------------------------------------
// Sistema de Notificaciones Toast
// ----------------------------------------------------------------------------
let toastTimeout = null;
function showToast(message, type = 'info') {
    elToast.className = 'toast';
    elToast.classList.add(`toast-${type}`);
    
    const icon = elToast.querySelector('i');
    if (type === 'success') {
        icon.className = 'toast-icon fa-solid fa-circle-check';
    } else if (type === 'error') {
        icon.className = 'toast-icon fa-solid fa-circle-xmark';
    } else {
        icon.className = 'toast-icon fa-solid fa-circle-info';
    }
    
    elToast.querySelector('.toast-message').textContent = message;
    
    clearTimeout(toastTimeout);
    toastTimeout = setTimeout(() => {
        elToast.classList.add('hidden');
    }, 4000);
}
