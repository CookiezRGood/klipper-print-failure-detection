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

const maskZones = {
    0: [],
    1: []
};

// Disable dragging on images
[cam1Img, cam2Img].forEach(img => {
    if (!img) return;
    img.draggable = false;
    img.style.pointerEvents = 'none';
    img.style.userSelect = 'none';
});

// Start image fetch loop
function startImageLoop(rate) {
    if (imageInterval) clearInterval(imageInterval);
    const safeRate = (rate && rate >= 100) ? rate : 500;

    imageInterval = setInterval(() => {
        const t = Date.now();
        if (!cam1Card.classList.contains('disabled')) {
            cam1Img.src = `/api/frame/0?t=${t}`;
        }
        if (!cam2Card.classList.contains('disabled')) {
            cam2Img.src = `/api/frame/1?t=${t}`;
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

        if (data.status === 'failure_detected') {
            statusBadge.style.backgroundColor = '#e53935';
            setButtonState('stop');
        } else if (data.status === 'monitoring') {
            statusBadge.style.backgroundColor = '#43a047';
            setButtonState('stop');
        } else if (data.status === 'idle') {
            statusBadge.style.backgroundColor = '#555';
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
    } catch (err) {
        // ignore
    }
}

setInterval(updateStatus, 1000);

forceStartBtn.addEventListener('click', async () => {
    const action = forceStartBtn.dataset.action;
    try {
        if (action === "stop") {
            await fetch('/api/action/stop', { method: 'POST' });
        } else {
            await fetch('/api/action/start', { method: 'POST' });
        }
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
    
    try {
        await fetch('/api/action/toggle_mask', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ show: isMaskVisible })
        });
    } catch (e) {}
});

function applyLayout(count) {
    const isSingle = parseInt(count) === 1;
    const cam2Row = document.getElementById('cam2-settings-row');

    if (isSingle) {
        cameraGrid.classList.add('single-mode');
        cam2Card.classList.add('hidden');
        cam2Row.style.display = 'none';
    } else {
        cameraGrid.classList.remove('single-mode');
        cam2Card.classList.remove('hidden');
        cam2Row.style.display = '';
    }
}

function syncMasksToServer() {
    currentSettings.masks = {
        "0": maskZones[0],
        "1": maskZones[1]
    };

    fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(currentSettings)
    }).catch(()=>{});
}

function setupMaskDrawing(camId, containerEl) {
    let isDrawing = false;
    let startX, startY;
    let tempRect = null;

    function getRelativePos(e) {
        const rect = containerEl.getBoundingClientRect();
        return {
            x: e.clientX - rect.left,
            y: e.clientY - rect.top,
            width: rect.width,
            height: rect.height
        };
    }

    containerEl.addEventListener('mousedown', (e) => {
        if (e.button !== 0) return;

        const { x, y, width, height } = getRelativePos(e);
        if (x < 0 || y < 0 || x > width || y > height) return;

        isDrawing = true;
        startX = x;
        startY = y;

        tempRect = document.createElement('div');
        tempRect.className = "temp-mask-rect";
        tempRect.style.position = 'absolute';
        tempRect.style.border = '1px solid #ff00ff';
        tempRect.style.backgroundColor = 'rgba(255,0,255,0.2)';
        tempRect.style.pointerEvents = 'none';
        tempRect.style.left = `${x}px`;
        tempRect.style.top = `${y}px`;

        containerEl.appendChild(tempRect);
    });

    window.addEventListener('mousemove', (e) => {
        if (!isDrawing || !tempRect) return;

        const { x, y } = getRelativePos(e);

        const minX = Math.min(startX, x);
        const minY = Math.min(startY, y);
        const width = Math.abs(x - startX);
        const height = Math.abs(y - startY);

        tempRect.style.left = `${minX}px`;
        tempRect.style.top = `${minY}px`;
        tempRect.style.width = `${width}px`;
        tempRect.style.height = `${height}px`;
    });

    window.addEventListener('mouseup', (e) => {
        if (!isDrawing || !tempRect) return;

        const { x, y, width, height } = getRelativePos(e);

        const rectX = Math.min(startX, x);
        const rectY = Math.min(startY, y);
        const rectW = Math.abs(x - startX);
        const rectH = Math.abs(y - startY);

        tempRect.remove();
        tempRect = null;
        isDrawing = false;

        if (rectW < 10 || rectH < 10) return;

        maskZones[camId].push({
            x: rectX / width,
            y: rectY / height,
            w: rectW / width,
            h: rectH / height
        });

        syncMasksToServer();
    });

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

        const camCount = currentSettings.camera_count || 2;
        document.getElementById('camera_count').value = camCount;
        document.getElementById('cam1_url_input').value = cam1.url || "";
        document.getElementById('cam2_url_input').value = cam2.url || "";

        document.getElementById('moonraker_url').value = currentSettings.moonraker_url || "";
        document.getElementById('check_interval').value = currentSettings.check_interval || 500;

        document.getElementById('warn_threshold').value =
            Math.round((currentSettings.warn_threshold || 0.30) * 100);

        document.getElementById('ai_threshold').value =
            Math.round((currentSettings.ai_threshold || 0.50) * 100);

        const masksCfg = currentSettings.masks || {};
        maskZones[0] = Array.isArray(masksCfg["0"]) ? [...masksCfg["0"]] : [];
        maskZones[1] = Array.isArray(masksCfg["1"]) ? [...masksCfg["1"]] : [];

        document.getElementById('consecutive_failures').value =
            currentSettings.consecutive_failures || 2;

        document.getElementById('on_failure').value =
            currentSettings.on_failure || "pause";

        document.getElementById('aspect_ratio').value =
            currentSettings.aspect_ratio || "16:9";

        const ratio = (currentSettings.aspect_ratio || "16:9").replace(':', '/');
        cam1View.style.aspectRatio = ratio;
        cam2View.style.aspectRatio = ratio;

        applyLayout(camCount);
        startImageLoop(currentSettings.check_interval || 500);
    } catch (err) {
        console.error(err);
    }
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
    
    currentSettings.warn_threshold =
        parseInt(document.getElementById('warn_threshold').value) / 100.0;

    currentSettings.ai_threshold =
        parseInt(document.getElementById('ai_threshold').value) / 100.0;

    currentSettings.consecutive_failures =
        parseInt(document.getElementById('consecutive_failures').value);

    currentSettings.on_failure = document.getElementById('on_failure').value;

    currentSettings.masks = {
        "0": maskZones[0],
        "1": maskZones[1]
    };

    currentSettings.aspect_ratio =
        document.getElementById('aspect_ratio').value;

    await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(currentSettings)
    });
    
    const ratio = currentSettings.aspect_ratio.replace(':', '/');
    cam1View.style.aspectRatio = ratio;
    cam2View.style.aspectRatio = ratio;
    
    applyLayout(camCount);
    startImageLoop(newInterval); 
    
    alert("Configuration Saved!");
    settingsModal.close();
});

// ----- Floating log panel -----
let autoScrollLogs = true;
const logPanel = document.getElementById('log-panel');
const logContent = document.getElementById('log-content');
const logToggleBtn = document.getElementById('log-toggle-btn');
const logCloseBtn = document.getElementById('log-close-btn');

if (logToggleBtn && logPanel && logContent && logCloseBtn) {
    logToggleBtn.addEventListener('click', () => {
        logPanel.classList.toggle('hidden');
    });

    logCloseBtn.addEventListener('click', () => {
        logPanel.classList.add('hidden');
    });

    logContent.addEventListener('scroll', () => {
        const atBottom = logContent.scrollHeight - logContent.scrollTop <= logContent.clientHeight + 5;
        autoScrollLogs = atBottom;
    });

    function updateLogView(text) {
        logContent.textContent = text || '';
        if (autoScrollLogs) {
            logContent.scrollTop = logContent.scrollHeight;
        }
    }

    setInterval(async () => {
        try {
            const res = await fetch('/api/logs');
            if (!res.ok) return;
            const data = await res.json();
            updateLogView(data.logs);
        } catch (e) {
            // ignore log fetch failing
        }
    }, 1500);
}

loadSettings();
