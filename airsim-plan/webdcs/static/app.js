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
const elJsonEditor = document.getElementById('json-viewer-textarea'); // Se sincroniza con el visor del modal
const elBtnSave = document.getElementById('btn-save'); // Botón guardar en el Header
const elToast = document.getElementById('toast');
const elHoverX = document.getElementById('hover-x');
const elHoverY = document.getElementById('hover-y');
const elBtnResetMap = document.getElementById('btn-reset-map');
const elMapSelector = document.getElementById('map-selector');
const elLegendMapName = document.getElementById('legend-map-name');

// Modal Visor JSON
const elModalJsonViewer = document.getElementById('modal-json-viewer');
const elJsonViewerTextarea = document.getElementById('json-viewer-textarea');
const elBtnCloseJsonViewer = document.getElementById('btn-close-json-viewer');

// Elementos de navegación del Sidebar
const elViewManifestsList = document.getElementById('view-manifests-list');
const elViewWaypointsDetail = document.getElementById('view-waypoints-detail');
const elActiveMissionTitle = document.getElementById('active-mission-title');
const elActiveWaypointList = document.getElementById('active-waypoint-list');
const elBtnBackManifests = document.getElementById('btn-back-manifests');
const elBtnNewManifest = document.getElementById('btn-new-manifest');
const elBtnLaunchMission = document.getElementById('btn-launch-mission');
const elChkWatchLoop = document.getElementById('chk-watch-loop');

// Tabs & Nuevos Botones Manual / AI
const elTabBtnManual = document.getElementById('tab-btn-manual');
const elTabBtnAi = document.getElementById('tab-btn-ai');
const elTabContentManual = document.getElementById('tab-content-manual');
const elTabContentAi = document.getElementById('tab-content-ai');
const elBtnClearRoute = document.getElementById('btn-clear-route');

// Toggle JSON
const elBtnToggleJson = document.getElementById('btn-toggle-json');
const elDashboardWorkspace = document.getElementById('dashboard-workspace');
const elPlannerStatusIndicator = document.getElementById('planner-status-indicator');
const elPlannerStatusText = document.getElementById('planner-status-text');

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
    setupInteractiveControls();
});

window.addEventListener('resize', () => {
    resizeCanvas();
    centerMapInViewport();
});

mapImage.addEventListener('load', () => {
    resizeCanvas();
    centerMapInViewport();
});

function resizeCanvas() {
    const naturalWidth = mapImage.naturalWidth || 1000;
    const naturalHeight = mapImage.naturalHeight || 1000;
    
    canvas.width = naturalWidth;
    canvas.height = naturalHeight;
    canvas.style.width = naturalWidth + 'px';
    canvas.style.height = naturalHeight + 'px';
    canvas.style.left = '0px';
    canvas.style.top = '0px';
    
    mapCenter.x = naturalWidth / 2;
    mapCenter.y = naturalHeight / 2;
    drawRoute();
}

function centerMapInViewport() {
    const container = document.getElementById('map-container');
    if (!container) return;
    
    const naturalWidth = mapImage.naturalWidth || 1000;
    const naturalHeight = mapImage.naturalHeight || 1000;
    
    container.scrollLeft = (naturalWidth - container.clientWidth) / 2;
    container.scrollTop = (naturalHeight - container.clientHeight) / 2;
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
    
    if (!activeManifest || !activeManifest.waypoints || activeManifest.waypoints.length === 0) {
        return;
    }

    const wps = activeManifest.waypoints;

    // 1. Dibujar punto de inicio / Home (primer waypoint, en amarillo)
    const homeWp = wps[0];
    const homePos = nedToCanvas(homeWp.x, homeWp.y);
    ctx.beginPath();
    ctx.arc(homePos.x, homePos.y, 8, 0, 2 * Math.PI);
    ctx.fillStyle = '#f59e0b';
    ctx.shadowBlur = 12;
    ctx.shadowColor = '#f59e0b';
    ctx.fill();
    ctx.shadowBlur = 0; 
    
    ctx.font = 'bold 10px Outfit';
    ctx.fillStyle = '#f59e0b';
    ctx.fillText(`${homeWp.label || 'START'} (${homeWp.x.toFixed(1)}, ${homeWp.y.toFixed(1)})`, homePos.x + 12, homePos.y + 4);

    // 2. Dibujar líneas de trayectoria si hay más de 1 waypoint
    if (wps.length > 1) {
        ctx.beginPath();
        ctx.moveTo(homePos.x, homePos.y);

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
    }

    // 3. Dibujar Waypoints restantes (nodos azules, a partir del índice 1)
    for (let i = 1; i < wps.length; i++) {
        const wp = wps[i];
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
        const label = wp.label ? `${i + 1}: ${wp.label}` : `WP #${i + 1}`;
        ctx.fillText(label, pos.x + 10, pos.y - 6);
        
        ctx.font = '9px Fira Code';
        ctx.fillStyle = '#a5b4fc';
        ctx.fillText(`[${wp.x.toFixed(1)}, ${wp.y.toFixed(1)}, ${wp.z.toFixed(1)}]`, pos.x + 10, pos.y + 6);
    }
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
    
    const clickedPt = {
        x: Math.round(ned.x * 10) / 10,
        y: Math.round(ned.y * 10) / 10,
        z: zVal,
        label: ''
    };
    
    clickedPt.label = `WP_${(activeManifest.waypoints ? activeManifest.waypoints.length : 0) + 1}`;
    if (!activeManifest.waypoints) {
        activeManifest.waypoints = [];
    }
    activeManifest.waypoints.push(clickedPt);
    showToast(`Waypoint #${activeManifest.waypoints.length} añadido a la trayectoria.`, 'success');
    
    syncManifestToEditor();
});

elBtnResetMap.addEventListener('click', () => {
    centerMapInViewport();
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
function syncManifestToEditor() {
    if (activeManifest) {
        elJsonEditor.value = JSON.stringify(activeManifest, null, 2);
        elBtnSave.disabled = false;
    } else {
        elJsonEditor.value = '';
        elBtnSave.disabled = true;
    }
    renderWaypointList();
    drawRoute();
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
                <span class="waypoint-item-coords">N:${wp.x.toFixed(1)} E:${wp.y.toFixed(1)}</span>
                <div class="waypoint-alt-edit" style="display: flex; align-items: center; gap: 0.2rem; margin-top: 0.2rem;">
                    <label style="font-size: 0.75rem; color: var(--text-muted);">Alt:</label>
                    <input type="number" class="wp-alt-input" value="${wp.z}" step="0.5" style="width: 55px; background: rgba(0,0,0,0.4); border: 1px solid var(--border-color); color: var(--text-main); border-radius: 4px; padding: 0.1rem 0.3rem; font-size: 0.75rem; font-family: inherit;">
                    <span style="font-size: 0.75rem; color: var(--text-muted);">m</span>
                </div>
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

        const altInput = item.querySelector('.wp-alt-input');
        altInput.addEventListener('change', (e) => {
            const val = parseFloat(e.target.value);
            if (!isNaN(val)) {
                wp.z = val;
                syncManifestToEditor();
            }
        });

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
    elMapSelector.value = mapFile;
    elLegendMapName.textContent = mapFile;
    
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
        
        // Llenar selectores de mapas (modal y cabecera del mapa)
        elNewMissionMap.innerHTML = '';
        elMapSelector.innerHTML = '';
        availableMaps.forEach(mapFile => {
            const opt = document.createElement('option');
            opt.value = mapFile;
            opt.textContent = mapFile;
            elNewMissionMap.appendChild(opt.cloneNode(true));
            elMapSelector.appendChild(opt);
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

// ----------------------------------------------------------------------------
// Rediseño: Inicializar Controles Interactivos de Pestañas y Modos
// ----------------------------------------------------------------------------
function setupInteractiveControls() {
    // 1. Manejo de Pestañas (Manual vs AI)
    elTabBtnManual.addEventListener('click', () => {
        elTabBtnManual.classList.add('active');
        elTabBtnAi.classList.remove('active');
        elTabContentManual.classList.add('active-content');
        elTabContentAi.classList.remove('active-content');
    });

    elTabBtnAi.addEventListener('click', () => {
        elTabBtnManual.classList.remove('active');
        elTabBtnAi.classList.add('active');
        elTabContentManual.classList.remove('active-content');
        elTabContentAi.classList.add('active-content');
    });

    // 2. Modos de Diseño Manual (Removidos Inicio y Waypoints)

    // 3. Limpiar Trayectoria
    elBtnClearRoute.addEventListener('click', () => {
        if (!activeManifest) return;
        activeManifest.waypoints = [];
        syncManifestToEditor();
        showToast('Se han eliminado todos los puntos de la trayectoria.', 'warning');
    });

    // 4. Mostrar/Ocultar Editor JSON (Modal Read-only)
    elBtnToggleJson.addEventListener('click', () => {
        if (!activeManifest) {
            showToast('No hay una misión activa para mostrar.', 'error');
            return;
        }
        elJsonViewerTextarea.value = JSON.stringify(activeManifest, null, 2);
        elModalJsonViewer.classList.remove('hidden');
    });

    elBtnCloseJsonViewer.addEventListener('click', () => {
        elModalJsonViewer.classList.add('hidden');
    });

    // 5. Selector de Mapas Global
    elMapSelector.addEventListener('change', () => {
        const selectedMap = elMapSelector.value;
        mapImage.src = `/maps/${selectedMap}`;
        elLegendMapName.textContent = selectedMap;
        if (activeManifest) {
            activeManifest.map = selectedMap;
            syncManifestToEditor();
        } else {
            // Si no hay misión, redimensionar de todos modos al cargar el nuevo mapa
            resizeCanvas();
        }
        showToast(`Mapa cambiado a: ${selectedMap}`, 'success');
    });

    // 6. Lanzamiento de Misión
    elBtnLaunchMission.addEventListener('click', async () => {
        if (!activeManifest) {
            showToast('No hay una misión activa para lanzar.', 'error');
            return;
        }

        elBtnLaunchMission.disabled = true;
        showToast('Guardando y lanzando misión en AirSim...', 'info');

        try {
            const response = await fetch('/api/launch', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    manifest: activeManifest,
                    watch: elChkWatchLoop.checked
                })
            });

            const data = await response.json();
            if (!response.ok) {
                throw new Error(data.detail || 'Error al lanzar la misión.');
            }

            showToast(data.message, 'success');
            if (data.manifest) {
                activeManifest = data.manifest;
                updateOriginalState();
            }
        } catch (err) {
            console.error(err);
            showToast(err.message, 'error');
        } finally {
            elBtnLaunchMission.disabled = false;
        }
    });

    // 7. Controles del Panel de Live Perception Feed
    const elLiveFeedPanel = document.getElementById('live-feed-panel');
    const elBtnToggleFeedSize = document.getElementById('btn-toggle-feed-size');
    const elIconFeedSize = document.getElementById('icon-feed-size');
    const elBtnEmergencyStop = document.getElementById('btn-emergency-stop');

    if (elBtnToggleFeedSize && elLiveFeedPanel) {
        let feedState = 0; // 0: normal, 1: expanded, 2: minimized
        elBtnToggleFeedSize.addEventListener('click', () => {
            feedState = (feedState + 1) % 3;
            if (feedState === 1) {
                elLiveFeedPanel.classList.add('expanded');
                elLiveFeedPanel.classList.remove('minimized');
                elIconFeedSize.className = 'fa-solid fa-compress';
            } else if (feedState === 2) {
                elLiveFeedPanel.classList.remove('expanded');
                elLiveFeedPanel.classList.add('minimized');
                elIconFeedSize.className = 'fa-solid fa-window-maximize';
            } else {
                elLiveFeedPanel.classList.remove('expanded');
                elLiveFeedPanel.classList.remove('minimized');
                elIconFeedSize.className = 'fa-solid fa-expand';
            }
        });
    }

    if (elBtnEmergencyStop) {
        elBtnEmergencyStop.addEventListener('click', async () => {
            elBtnEmergencyStop.disabled = true;
            try {
                const res = await fetch('/api/stop', { method: 'POST' });
                const data = await res.json();
                showToast(data.message || 'Misión detenida.', 'warning');
            } catch (err) {
                console.error(err);
                showToast('Error al detener la misión.', 'error');
            } finally {
                elBtnEmergencyStop.disabled = false;
            }
        });
    }
}

// ----------------------------------------------------------------------------
// Monitoreo del estado del Planificador LLM
// ----------------------------------------------------------------------------
async function updatePlannerStatus() {
    try {
        const response = await fetch('/api/planner/status');
        if (!response.ok) throw new Error();
        const data = await response.json();
        
        if (data.status === 'online') {
            elPlannerStatusIndicator.classList.remove('offline');
            elPlannerStatusIndicator.classList.add('online');
            elPlannerStatusText.textContent = 'AirSim Planner Connected';
        } else {
            elPlannerStatusIndicator.classList.remove('online');
            elPlannerStatusIndicator.classList.add('offline');
            elPlannerStatusText.textContent = 'AirSim Planner Disconnected';
        }
    } catch (err) {
        elPlannerStatusIndicator.classList.remove('online');
        elPlannerStatusIndicator.classList.add('offline');
        elPlannerStatusText.textContent = 'AirSim Planner Disconnected';
    }
}

// ----------------------------------------------------------------------------
// Polling en tiempo real de Telemetría y Percepción del Dron
// ----------------------------------------------------------------------------
async function pollLiveTelemetry() {
    try {
        const response = await fetch('/api/stream/telemetry');
        if (!response.ok) return;
        const tel = await response.json();

        const elDot = document.getElementById('live-indicator-dot');
        const elValAction = document.getElementById('hud-val-action');
        const elValTtc = document.getElementById('hud-val-ttc');
        const elValXor = document.getElementById('hud-val-xor');
        const elFlightStatus = document.getElementById('tel-flight-status');
        const elVel = document.getElementById('tel-vel');
        const elDetections = document.getElementById('tel-detections-count');
        const elBadgeAct = document.getElementById('hud-badge-act');

        if (tel.active) {
            if (elDot) elDot.classList.add('active');
        } else {
            if (elDot) elDot.classList.remove('active');
        }

        if (elValAction) elValAction.textContent = tel.decision || 'MANTENER_RUMBO';
        if (elValTtc) {
            elValTtc.textContent = (tel.estimated_ttc != null && tel.estimated_ttc < 999) ? `${Number(tel.estimated_ttc).toFixed(1)}s` : 'inf';
        }
        if (elValXor) {
            const xorPct = ((tel.xor_change_ratio || 0) * 100).toFixed(1);
            elValXor.textContent = `${xorPct}%`;
        }
        if (elFlightStatus) {
            let statusText = tel.flight_status || 'En espera';
            if (statusText === 'completada_en_tierra') {
                statusText = 'Completada (En Tierra)';
            } else if (statusText === 'aterrizando') {
                statusText = 'Aterrizando...';
            } else if (statusText === 'vuelo_waypoint') {
                statusText = 'En Vuelo (Waypoint)';
            } else if (statusText === 'mision_completada') {
                statusText = 'Misión Completada';
            }
            elFlightStatus.textContent = statusText;
        }
        if (elVel && tel.velocity) {
            const vx = Number(tel.velocity.vx || 0).toFixed(1);
            const vy = Number(tel.velocity.vy || 0).toFixed(1);
            const vz = Number(tel.velocity.vz || 0).toFixed(1);
            elVel.textContent = `vx:${vx} vy:${vy} vz:${vz}`;
        }
        if (elDetections) {
            const count = (tel.detections && Array.isArray(tel.detections)) ? tel.detections.length : 0;
            elDetections.textContent = `${count}`;
        }
    } catch (err) {
        // Silencioso para polling
    }
}

// Iniciar monitoreo
updatePlannerStatus();
setInterval(updatePlannerStatus, 10000);
setInterval(pollLiveTelemetry, 500);

