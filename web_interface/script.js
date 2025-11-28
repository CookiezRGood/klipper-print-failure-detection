let imageInterval; 
let currentSettings = {};
let isMaskVisible = false;

const statusBadge = document.getElementById('status-indicator');
const ssimText = document.getElementById('ssim-val');
const retryText = document.getElementById('retry-val');
const confidenceBar = document.getElementById('confidence-bar');
const forceStartBtn = document.getElementById('force-start-btn');
const maskToggleBtn = document.getElementById('mask-toggle-btn');
const settingsModal = document.getElementById('settings-modal');

const cameraGrid = document.getElementById('camera-grid');
const cam1Img = document.getElementById('cam1-img');
const cam2Img = document.getElementById('cam2-img');
const cam1Card = document.getElementById('card-cam1');
const cam2Card = document.getElementById('card-cam2');
const cam1Toggle = document.getElementById('cam1-toggle');
const cam2Toggle = document.getElementById('cam2-toggle');
const cam1View = document.getElementById('cam1-container');
const cam2View = document.getElementById('cam2-container');

const cam1ClearBtn = document.getElementById('cam1-clear-masks');
const cam2ClearBtn = document.getElementById('cam2-clear-masks');

// Disable native image dragging / interaction so containers receive events
[cam1Img, cam2Img].forEach(img => {
    if (!img) return;
    img.draggable = false;
    img.style.pointerEvents = 'none';
    img.style.userSelect = 'none';
    img.style.webkitUserDrag = 'none';
});

// per-camera mask zones, normalized [0–1]
const maskZones = {
    0: [],
    1: []
};

function startImageLoop(rate) {
    if (imageInterval) clearInterval(imageInterval);
    const safeRate = (rate && rate >= 100) ? rate : 500;
    
    imageInterval = setInterval(() => {
        const timestamp = new Date().getTime();
        if (!cam1Card.classList.contains('disabled')) {
            cam1Img.src = `/api/frame/0?t=${timestamp}`;
        }
        if (!cam2Card.classList.contains('disabled')) {
            cam2Img.src = `/api/frame/1?t=${timestamp}`;
        }
    }, safeRate);
}

async function toggleCamera(id, isEnabled) {
    const card = id === 0 ? cam1Card : cam2Card;
    const toggle = id === 0 ? cam1Toggle : cam2Toggle;
    
    toggle.checked = isEnabled;
    
    if (isEnabled) card.classList.remove('disabled');
    else card.classList.add('disabled');
    
    if (currentSettings.cameras) {
        currentSettings.cameras[id].enabled = isEnabled;
        try {
            await fetch('/api/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(currentSettings)
            });
        } catch (e) {}
    }
}

cam1Toggle.addEventListener('change', (e) => toggleCamera(0, e.target.checked));
cam2Toggle.addEventListener('change', (e) => toggleCamera(1, e.target.checked));

function setButtonState(mode) {
    forceStartBtn.classList.remove('btn-success', 'btn-danger', 'btn-primary');
    if (mode === 'start') {
        forceStartBtn.innerText = "▶ Start Monitoring";
        forceStartBtn.classList.add('btn-success'); 
        forceStartBtn.dataset.action = "start";
        forceStartBtn.style.display = 'inline-block';
    } else if (mode === 'stop') {
        forceStartBtn.innerText = "■ Stop Monitoring";
        forceStartBtn.classList.add('btn-danger'); 
        forceStartBtn.dataset.action = "stop";
        forceStartBtn.style.display = 'inline-block';
    }
}

async function updateStatus() {
    try {
        const res = await fetch('/api/status');
        const data = await res.json();
        
        const statusText = data.status.toUpperCase().replace('_', ' ');
        statusBadge.innerText = statusText;
        
        if (data.status === 'failure_detected' || data.status === 'error') {
            statusBadge.style.backgroundColor = '#F44336'; 
            setButtonState('stop');
        } else if (data.status === 'monitoring') {
            statusBadge.style.backgroundColor = '#4CAF50'; 
            setButtonState('stop');
        } else if (data.status === 'idle') {
            statusBadge.style.backgroundColor = '#555555'; 
            setButtonState('start');
        } else {
            statusBadge.style.backgroundColor = '#f39c12'; 
        }

        const failPercent = Math.round(data.score * 100);
        ssimText.innerText = `${failPercent}%`;
        retryText.innerText = `${data.failures}/${data.max_retries}`;
        confidenceBar.style.width = `${failPercent}%`;

        const warnT = (currentSettings.warn_threshold || 0.3) * 100;
        const failT = (currentSettings.ai_threshold || 0.6) * 100;

        if (data.failures > 0 || failPercent >= failT) {
            confidenceBar.style.background = '#FF5722'; 
        } else if (failPercent >= warnT) {
            confidenceBar.style.background = '#FFC107'; 
        } else {
            confidenceBar.style.background = '#4CAF50'; 
        }

    } catch (e) { console.log("Status error", e); }
}
setInterval(updateStatus, 1000);

forceStartBtn.addEventListener('click', async () => {
    const action = forceStartBtn.dataset.action;
    const method = { method: 'POST' };
    try {
        if(action === "stop") await fetch('/api/action/stop', method);
        else await fetch('/api/action/start', method);
        setTimeout(updateStatus, 100); 
    } catch (e) {}
});

// --- MASK TOGGLE ---
maskToggleBtn.addEventListener('click', async () => {
    isMaskVisible = !isMaskVisible;
    
    if (isMaskVisible) {
        maskToggleBtn.style.backgroundColor = "#2196F3";
        maskToggleBtn.style.color = "white";
    } else {
        maskToggleBtn.style.backgroundColor = "";
        maskToggleBtn.style.color = "";
    }

    await fetch('/api/action/toggle_mask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ show: isMaskVisible })
    });
});

function applyLayout(count) {
    const isSingle = parseInt(count) === 1;
    const cam2Row = document.getElementById('cam2-settings-row');
    
    if (isSingle) {
        cameraGrid.classList.add('single-mode');
        cam2Card.classList.add('hidden');
        cam1Card.querySelector('.cam-controls').style.display = 'none';
        if (cam2Row) cam2Row.style.display = 'none';
        if (cam2ClearBtn) cam2ClearBtn.parentElement.style.display = 'none';
    } else {
        cameraGrid.classList.remove('single-mode');
        cam2Card.classList.remove('hidden');
        cam1Card.querySelector('.cam-controls').style.display = 'flex';
        if (cam2Row) cam2Row.style.display = ''; 
        if (cam2ClearBtn) cam2ClearBtn.parentElement.style.display = '';
    }
}

function syncMasksToServer() {
    if (!currentSettings) return;
    currentSettings.masks = {
        "0": maskZones[0],
        "1": maskZones[1]
    };
    fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(currentSettings)
    }).catch(() => {});
}

function setupMaskDrawing(camId, containerEl) {
    let isDrawing = false;
    let startX = 0, startY = 0;
    let tempRect = null;

    function getRelativePos(e) {
        const rect = containerEl.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        return { x, y, width: rect.width, height: rect.height };
    }

    containerEl.addEventListener('mousedown', (e) => {
        // Left click starts drag-to-draw
        if (e.button !== 0) return;
        e.preventDefault();

        const { x, y, width, height } = getRelativePos(e);
        if (x < 0 || y < 0 || x > width || y > height) return;

        isDrawing = true;
        startX = x;
        startY = y;

        tempRect = document.createElement('div');
        tempRect.className = "temp-mask-rect";
        tempRect.style.position = 'absolute';
        tempRect.style.border = '1px solid #ff00ff';
        tempRect.style.backgroundColor = 'rgba(255, 0, 255, 0.2)';
        tempRect.style.pointerEvents = 'none';
        tempRect.style.left = `${startX}px`;
        tempRect.style.top = `${startY}px`;
        tempRect.style.width = '0px';
        tempRect.style.height = '0px';

        containerEl.appendChild(tempRect);
    });

    window.addEventListener('mousemove', (e) => {
        if (!isDrawing || !tempRect) return;
        e.preventDefault();

        const { x, y } = getRelativePos(e);

        const currX = x;
        const currY = y;
        const rectX = Math.min(startX, currX);
        const rectY = Math.min(startY, currY);
        const rectW = Math.abs(currX - startX);
        const rectH = Math.abs(currY - startY);

        tempRect.style.left = `${rectX}px`;
        tempRect.style.top = `${rectY}px`;
        tempRect.style.width = `${rectW}px`;
        tempRect.style.height = `${rectH}px`;
    });

    window.addEventListener('mouseup', (e) => {
        if (!isDrawing || !tempRect) return;
        e.preventDefault();

        isDrawing = false;

        const { x: endX, y: endY, width, height } = getRelativePos(e);

        const rectX = Math.min(startX, endX);
        const rectY = Math.min(startY, endY);
        const rectW = Math.abs(endX - startX);
        const rectH = Math.abs(endY - startY);

        containerEl.removeChild(tempRect);
        tempRect = null;

        // Ignore very tiny drags
        if (rectW < 10 || rectH < 10) return;

        const normX = rectX / width;
        const normY = rectY / height;
        const normW = rectW / width;
        const normH = rectH / height;

        maskZones[camId].push({
            x: normX,
            y: normY,
            w: normW,
            h: normH
        });

        syncMasksToServer();
    });

    // Right-click delete a zone
    containerEl.addEventListener('contextmenu', (e) => {
        e.preventDefault();
        const { x, y, width, height } = getRelativePos(e);
        const nx = x / width;
        const ny = y / height;

        const zones = maskZones[camId];
        for (let i = zones.length - 1; i >= 0; i--) {
            const z = zones[i];
            if (
                nx >= z.x &&
                ny >= z.y &&
                nx <= z.x + z.w &&
                ny <= z.y + z.h
            ) {
                zones.splice(i, 1);
                syncMasksToServer();
                return;
            }
        }
    });
}

async function loadSettings() {
    try {
        const res = await fetch('/api/settings');
        currentSettings = await res.json();
        
        const cam1 = currentSettings.cameras[0];
        const cam2 = currentSettings.cameras[1];
        
        toggleCamera(0, cam1.enabled);
        toggleCamera(1, cam2.enabled);

        document.getElementById('camera_count').value = currentSettings.camera_count || 2;
        document.getElementById('cam1_url_input').value = cam1.url;
        document.getElementById('cam2_url_input').value = cam2.url;
        
        document.getElementById('moonraker_url').value = currentSettings.moonraker_url || "http://127.0.0.1:7125";
        document.getElementById('check_interval').value = currentSettings.check_interval;
        
        document.getElementById('warn_threshold').value = Math.round((currentSettings.warn_threshold || 0.30) * 100);
        document.getElementById('ai_threshold').value = Math.round((currentSettings.ai_threshold || 0.50) * 100);
        
        // LOAD MASK ZONES PER CAMERA
        const masksCfg = currentSettings.masks || {};
        maskZones[0] = Array.isArray(masksCfg["0"]) ? [...masksCfg["0"]] : [];
        maskZones[1] = Array.isArray(masksCfg["1"]) ? [...masksCfg["1"]] : [];
        
        document.getElementById('consecutive_failures').value = currentSettings.consecutive_failures;
        document.getElementById('on_failure').value = currentSettings.on_failure || "nothing";
        document.getElementById('aspect_ratio').value = currentSettings.aspect_ratio || "16:9";

        const ratio = (currentSettings.aspect_ratio || "16:9").replace(':','/');
        cam1View.style.aspectRatio = ratio;
        cam2View.style.aspectRatio = ratio;
        document.documentElement.style.setProperty("--aspect-ratio", ratio);

        
        applyLayout(currentSettings.camera_count || 2);
        startImageLoop(currentSettings.check_interval);
    } catch (e) { console.error(e); }
}

document.getElementById('open-settings-btn').addEventListener('click', () => {
    loadSettings();
    settingsModal.showModal();
});

document.getElementById('close-modal-x').addEventListener('click', () => settingsModal.close());

document.getElementById('save-settings-btn').addEventListener('click', async () => {
    const newInterval = parseInt(document.getElementById('check_interval').value);
    const camCount = parseInt(document.getElementById('camera_count').value);
    
    currentSettings.camera_count = camCount;
    currentSettings.cameras[0].url = document.getElementById('cam1_url_input').value;
    if (camCount === 1) currentSettings.cameras[0].enabled = true;
    currentSettings.cameras[1].url = document.getElementById('cam2_url_input').value;
    currentSettings.moonraker_url = document.getElementById('moonraker_url').value;
    currentSettings.check_interval = newInterval;
    
    currentSettings.warn_threshold = parseInt(document.getElementById('warn_threshold').value) / 100.0;
    currentSettings.ai_threshold = parseInt(document.getElementById('ai_threshold').value) / 100.0;
    
    // Include current masks in settings
    currentSettings.masks = {
        "0": maskZones[0],
        "1": maskZones[1]
    };
    
    currentSettings.consecutive_failures = parseInt(document.getElementById('consecutive_failures').value);
    currentSettings.on_failure = document.getElementById('on_failure').value;
    currentSettings.aspect_ratio = document.getElementById('aspect_ratio').value;

    await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(currentSettings)
    });
    
    const ratio = currentSettings.aspect_ratio.replace(':','/');
    cam1View.style.aspectRatio = ratio;
    cam2View.style.aspectRatio = ratio;
    
    applyLayout(camCount);
    startImageLoop(newInterval); 
    
    alert("Configuration Saved!");
    settingsModal.close();
});

// Clear masks buttons
cam1ClearBtn.addEventListener('click', () => {
    maskZones[0] = [];
    syncMasksToServer();
});
cam2ClearBtn.addEventListener('click', () => {
    maskZones[1] = [];
    syncMasksToServer();
});

// Setup drag drawing for each camera
setupMaskDrawing(0, cam1View);
setupMaskDrawing(1, cam2View);

// Initial load
loadSettings();
