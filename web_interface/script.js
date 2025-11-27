let imageInterval; 
let currentSettings = {};

const statusBadge = document.getElementById('status-indicator');
const ssimText = document.getElementById('ssim-val');
const retryText = document.getElementById('retry-val');
const confidenceBar = document.getElementById('confidence-bar');
const forceStartBtn = document.getElementById('force-start-btn');
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

function startImageLoop(rate) {
    if (imageInterval) clearInterval(imageInterval);
    const safeRate = (rate && rate >= 100) ? rate : 500;
    
    imageInterval = setInterval(() => {
        const timestamp = new Date().getTime();
        // Update Cam 1 if enabled
        if (!cam1Card.classList.contains('disabled')) {
            cam1Img.src = `/api/frame/0?t=${timestamp}`;
        }
        // Update Cam 2 only if enabled AND visible
        if (!cam2Card.classList.contains('disabled') && !cam2Card.classList.contains('hidden')) {
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

// --- LAYOUT MANAGER ---
function applyLayout(count) {
    const isSingle = parseInt(count) === 1;
    
    if (isSingle) {
        cameraGrid.classList.add('single-mode');
        cam2Card.classList.add('hidden');
        
        // Hide toggle, but force enable visually (logic handles backend)
        cam1Card.querySelector('.cam-controls').style.display = 'none';
        document.getElementById('cam2-settings-row').style.display = 'none';
    } else {
        cameraGrid.classList.remove('single-mode');
        cam2Card.classList.remove('hidden');
        cam1Card.querySelector('.cam-controls').style.display = 'flex';
        document.getElementById('cam2-settings-row').style.display = 'flex';
    }
}

async function loadSettings() {
    try {
        const res = await fetch('/api/settings');
        currentSettings = await res.json();
        
        const cam1 = currentSettings.cameras[0];
        const cam2 = currentSettings.cameras[1];
        
        toggleCamera(0, cam1.enabled);
        toggleCamera(1, cam2.enabled);

        // Populate UI
        document.getElementById('camera_count').value = currentSettings.camera_count || 2;
        document.getElementById('cam1_url_input').value = cam1.url;
        document.getElementById('cam2_url_input').value = cam2.url;
        
        document.getElementById('moonraker_url').value = currentSettings.moonraker_url || "http://127.0.0.1:7125";
        document.getElementById('check_interval').value = currentSettings.check_interval;
        
        document.getElementById('warn_threshold').value = Math.round((currentSettings.warn_threshold || 0.30) * 100);
        document.getElementById('ai_threshold').value = Math.round((currentSettings.ai_threshold || 0.50) * 100);
        
        document.getElementById('consecutive_failures').value = currentSettings.consecutive_failures;
        document.getElementById('on_failure').value = currentSettings.on_failure || "nothing";
        document.getElementById('aspect_ratio').value = currentSettings.aspect_ratio || "16:9";

        const ratio = (currentSettings.aspect_ratio || "16:9").replace(':', '/');
        cam1View.style.aspectRatio = ratio;
        cam2View.style.aspectRatio = ratio;
        
        // Apply Camera Count Layout
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
    
    // Force Enable Cam 1 if single mode
    if (camCount === 1) {
        currentSettings.cameras[0].enabled = true;
    }
    
    currentSettings.cameras[1].url = document.getElementById('cam2_url_input').value;
    
    currentSettings.moonraker_url = document.getElementById('moonraker_url').value;
    currentSettings.check_interval = newInterval;
    
    currentSettings.warn_threshold = parseInt(document.getElementById('warn_threshold').value) / 100.0;
    currentSettings.ai_threshold = parseInt(document.getElementById('ai_threshold').value) / 100.0;
    
    currentSettings.consecutive_failures = parseInt(document.getElementById('consecutive_failures').value);
    currentSettings.on_failure = document.getElementById('on_failure').value;
    currentSettings.aspect_ratio = document.getElementById('aspect_ratio').value;

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

loadSettings();
