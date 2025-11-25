let imageInterval; 

const liveImage = document.getElementById('live-image');
const statusBadge = document.getElementById('status-indicator');
const settingsModal = document.getElementById('settings-modal');
const ssimText = document.getElementById('ssim-val');
const retryText = document.getElementById('retry-val');
const confidenceBar = document.getElementById('confidence-bar');
const camContainer = document.getElementById('camera-container');
const forceStartBtn = document.getElementById('force-start-btn');

// --- IMAGE LOOP ---
function startImageLoop(rate) {
    if (imageInterval) clearInterval(imageInterval);
    const safeRate = (rate && rate >= 100) ? rate : 500;
    
    imageInterval = setInterval(() => {
        const timestamp = new Date().getTime();
        // AI mode always uses the same endpoint (no debug mask toggle needed)
        const endpoint = '/api/latest_frame'; 
        liveImage.src = `${endpoint}?t=${timestamp}`;
    }, safeRate);
}

startImageLoop(500);

// --- BUTTON VISUALS ---
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
    } else if (mode === 'force') {
        forceStartBtn.innerText = "▶ Force Start";
        forceStartBtn.classList.add('btn-primary'); 
        forceStartBtn.dataset.action = "start";
        forceStartBtn.style.display = 'inline-block';
    } else {
        forceStartBtn.style.display = 'none'; 
    }
}

// --- STATUS LOOP ---
async function updateStatus() {
    try {
        const res = await fetch('/api/status');
        const data = await res.json();
        
        const statusText = data.status.toUpperCase().replace('_', ' ');
        statusBadge.innerText = statusText;
        
        // Badge Color & Button Logic
        if (data.status === 'failure_detected' || data.status === 'error') {
            statusBadge.style.backgroundColor = '#F44336'; 
            setButtonState('stop');
        } else if (data.status === 'monitoring') {
            statusBadge.style.backgroundColor = '#4CAF50'; 
            setButtonState('stop');
        } else if (data.status === 'idle') {
            statusBadge.style.backgroundColor = '#555555'; 
            setButtonState('start');
        } else if (data.status === 'connection_error') {
            statusBadge.style.backgroundColor = '#9E9E9E'; 
            setButtonState('hide');
        } else {
            statusBadge.style.backgroundColor = '#f39c12'; 
        }

        // AI BAR LOGIC (Inverted: 0% is Good, 100% is Bad)
        const failPercent = Math.round(data.score * 100);
        ssimText.innerText = `${failPercent}%`;
        retryText.innerText = `${data.failures}/${data.max_retries}`;
        confidenceBar.style.width = `${failPercent}%`;

        if (data.failures > 0) {
             confidenceBar.style.background = '#FF5722'; // Warning
        } else if (failPercent > 50) {
             confidenceBar.style.background = '#FFC107'; // Yellow (Caution)
        } else {
             confidenceBar.style.background = '#4CAF50'; // Green (Safe)
        }

    } catch (e) { console.log("Status error", e); }
}
setInterval(updateStatus, 1000);

// --- BUTTON CLICK ---
forceStartBtn.addEventListener('click', async () => {
    const action = forceStartBtn.dataset.action;
    const method = { method: 'POST' };
    
    try {
        if(action === "stop") {
            await fetch('/api/action/stop', method);
        } else {
            await fetch('/api/action/start', method);
        }
        setTimeout(updateStatus, 100); 
    } catch (e) { console.error(e); }
});

// --- SETTINGS ---
document.getElementById('open-settings-btn').addEventListener('click', async () => {
    const res = await fetch('/api/settings');
    const data = await res.json();
    
    document.getElementById('camera_url').value = data.camera_url;
    document.getElementById('moonraker_url').value = data.moonraker_url || "http://127.0.0.1:7125";
    document.getElementById('check_interval').value = data.check_interval;
    // Use AI Threshold
    document.getElementById('ai_threshold').value = data.ai_threshold || 0.6;
    document.getElementById('consecutive_failures').value = data.consecutive_failures;
    document.getElementById('on_failure').value = data.on_failure || "nothing";
    document.getElementById('aspect_ratio').value = data.aspect_ratio || "16:9";
    document.getElementById('preview_refresh_rate').value = data.preview_refresh_rate || 500;
    
    if(data.aspect_ratio) camContainer.style.aspectRatio = data.aspect_ratio.replace(':', '/');

    settingsModal.showModal();
});

document.getElementById('close-modal-x').addEventListener('click', () => settingsModal.close());

document.getElementById('save-settings-btn').addEventListener('click', async () => {
    const newRate = parseInt(document.getElementById('preview_refresh_rate').value);
    const payload = {
        camera_url: document.getElementById('camera_url').value,
        moonraker_url: document.getElementById('moonraker_url').value,
        check_interval: parseInt(document.getElementById('check_interval').value),
        // Save AI Threshold
        ai_threshold: parseFloat(document.getElementById('ai_threshold').value),
        consecutive_failures: parseInt(document.getElementById('consecutive_failures').value),
        on_failure: document.getElementById('on_failure').value,
        aspect_ratio: document.getElementById('aspect_ratio').value,
        preview_refresh_rate: newRate
    };
    
    await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    
    camContainer.style.aspectRatio = payload.aspect_ratio.replace(':', '/');
    startImageLoop(newRate); 
    alert("Configuration Saved!");
    settingsModal.close();
});

// Init
fetch('/api/settings').then(r => r.json()).then(data => {
    if(data.aspect_ratio) camContainer.style.aspectRatio = data.aspect_ratio.replace(':', '/');
    if(data.preview_refresh_rate) startImageLoop(data.preview_refresh_rate);
});
