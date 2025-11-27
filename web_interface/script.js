let imageInterval; 
let currentSettings = {};

const statusBadge = document.getElementById('status-indicator');
const ssimText = document.getElementById('ssim-val');
const retryText = document.getElementById('retry-val');
const confidenceBar = document.getElementById('confidence-bar');
const forceStartBtn = document.getElementById('force-start-btn');
const settingsModal = document.getElementById('settings-modal');

const cam1Img = document.getElementById('cam1-img');
const cam2Img = document.getElementById('cam2-img');
const cam1Card = cam1Img.closest('.camera-card');
const cam2Card = cam2Img.closest('.camera-card');
const cam1Toggle = document.getElementById('cam1-toggle');
const cam2Toggle = document.getElementById('cam2-toggle');
const cam1View = document.getElementById('cam1-container');
const cam2View = document.getElementById('cam2-container');

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
    
    if (isEnabled) {
        card.classList.remove('disabled');
    } else {
        card.classList.add('disabled');
    }
    
    // Update Backend
    if (currentSettings.cameras) {
        currentSettings.cameras[id].enabled = isEnabled;
        try {
            await fetch('/api/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(currentSettings)
            });
            // FORCE UI UPDATE after a tiny delay to allow backend to reset
            setTimeout(updateStatus, 200);
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
            statusBadge.style.backgroundColor = '#F44336'; // Red
            setButtonState('stop');
        } else if (data.status === 'monitoring') {
            statusBadge.style.backgroundColor = '#4CAF50'; // Green
            setButtonState('stop');
        } else if (data.status === 'idle') {
            statusBadge.style.backgroundColor = '#555555'; // Grey
            setButtonState('start');
        } else {
            statusBadge.style.backgroundColor = '#f39c12'; // Orange
        }

        const failPercent = Math.round(data.score * 100);
        ssimText.innerText = `${failPercent}%`;
        retryText.innerText = `${data.failures}/${data.max_retries}`;
        confidenceBar.style.width = `${failPercent}%`;

        if (data.failures > 0) confidenceBar.style.background = '#FF5722'; 
        else if (failPercent > 50) confidenceBar.style.background = '#FFC107'; 
        else confidenceBar.style.background = '#4CAF50';

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

async function loadSettings() {
    try {
        const res = await fetch('/api/settings');
        currentSettings = await res.json();
        
        const cam1 = currentSettings.cameras[0];
        const cam2 = currentSettings.cameras[1];
        
        toggleCamera(0, cam1.enabled);
        toggleCamera(1, cam2.enabled);

        document.getElementById('cam1_url_input').value = cam1.url;
        document.getElementById('cam2_url_input').value = cam2.url;
        
        document.getElementById('moonraker_url').value = currentSettings.moonraker_url || "http://127.0.0.1:7125";
        document.getElementById('check_interval').value = currentSettings.check_interval;
        document.getElementById('ai_threshold').value = currentSettings.ai_threshold;
        document.getElementById('consecutive_failures').value = currentSettings.consecutive_failures;
        document.getElementById('on_failure').value = currentSettings.on_failure || "nothing";
        document.getElementById('aspect_ratio').value = currentSettings.aspect_ratio || "16:9";
        document.getElementById('preview_refresh_rate').value = currentSettings.preview_refresh_rate || 500;

        const ratio = (currentSettings.aspect_ratio || "16:9").replace(':', '/');
        cam1View.style.aspectRatio = ratio;
        cam2View.style.aspectRatio = ratio;
        
        startImageLoop(currentSettings.preview_refresh_rate);
    } catch (e) { console.error(e); }
}

document.getElementById('open-settings-btn').addEventListener('click', () => {
    loadSettings();
    settingsModal.showModal();
});

document.getElementById('close-modal-x').addEventListener('click', () => settingsModal.close());

document.getElementById('save-settings-btn').addEventListener('click', async () => {
    const newRate = parseInt(document.getElementById('preview_refresh_rate').value);
    
    currentSettings.cameras[0].url = document.getElementById('cam1_url_input').value;
    currentSettings.cameras[1].url = document.getElementById('cam2_url_input').value;
    
    currentSettings.moonraker_url = document.getElementById('moonraker_url').value;
    currentSettings.check_interval = parseInt(document.getElementById('check_interval').value);
    currentSettings.ai_threshold = parseFloat(document.getElementById('ai_threshold').value);
    currentSettings.consecutive_failures = parseInt(document.getElementById('consecutive_failures').value);
    currentSettings.on_failure = document.getElementById('on_failure').value;
    currentSettings.aspect_ratio = document.getElementById('aspect_ratio').value;
    currentSettings.preview_refresh_rate = newRate;

    await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(currentSettings)
    });
    
    const ratio = currentSettings.aspect_ratio.replace(':', '/');
    cam1View.style.aspectRatio = ratio;
    cam2View.style.aspectRatio = ratio;
    startImageLoop(newRate); 
    
    alert("Configuration Saved!");
    settingsModal.close();
});

loadSettings();
