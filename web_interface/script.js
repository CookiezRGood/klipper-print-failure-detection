let imageInterval; 

const liveImage = document.getElementById('live-image');
const debugToggle = document.getElementById('debug-toggle');
const statusBadge = document.getElementById('status-indicator');
const settingsModal = document.getElementById('settings-modal');
const ssimText = document.getElementById('ssim-val');
const retryText = document.getElementById('retry-val');
const confidenceBar = document.getElementById('confidence-bar');
const camContainer = document.getElementById('camera-container');
const forceStartBtn = document.getElementById('force-start-btn');

// Helper: Start the image refresh loop
function startImageLoop(rate) {
    if (imageInterval) clearInterval(imageInterval);
    const safeRate = (rate && rate >= 100) ? rate : 500;
    
    imageInterval = setInterval(() => {
        const timestamp = new Date().getTime();
        const endpoint = debugToggle.checked ? '/api/debug_frame' : '/api/latest_frame';
        liveImage.src = `${endpoint}?t=${timestamp}`;
    }, safeRate);
}

startImageLoop(500);

// Helper: Manage Button Visuals
function setButtonState(mode) {
    // Clear all state classes
    forceStartBtn.classList.remove('btn-success', 'btn-danger', 'btn-primary');
    
    if (mode === 'start') {
        forceStartBtn.innerText = "▶ Start Monitoring";
        forceStartBtn.classList.add('btn-success'); // Green
        forceStartBtn.dataset.action = "start";     // Logic flag
        forceStartBtn.style.display = 'inline-block';
    } else if (mode === 'stop') {
        forceStartBtn.innerText = "■ Stop Monitoring";
        forceStartBtn.classList.add('btn-danger');  // Red
        forceStartBtn.dataset.action = "stop";      // Logic flag
        forceStartBtn.style.display = 'inline-block';
    } else if (mode === 'force') {
        forceStartBtn.innerText = "▶ Force Start";
        forceStartBtn.classList.add('btn-primary'); // Blue
        forceStartBtn.dataset.action = "start";
        forceStartBtn.style.display = 'inline-block';
    } else {
        forceStartBtn.style.display = 'none'; 
    }
}

// Main Status Loop
async function updateStatus() {
    try {
        const res = await fetch('/api/status');
        const data = await res.json();
        
        const statusText = data.status.toUpperCase().replace('_', ' ');
        statusBadge.innerText = statusText;
        
        // Update Badge Color & Button State
        if (data.status === 'failure_detected' || data.status === 'error') {
            statusBadge.style.backgroundColor = '#F44336'; 
            setButtonState('stop');

        } else if (data.status === 'monitoring' || data.status === 'checking') {
            statusBadge.style.backgroundColor = '#4CAF50'; 
            setButtonState('stop');
            
        } else if (data.status === 'idle') {
            statusBadge.style.backgroundColor = '#555555'; 
            setButtonState('start');

        } else if (data.status === 'awaiting_macro') {
            statusBadge.style.backgroundColor = '#2196F3'; 
            setButtonState('force');
            
        } else if (data.status === 'connection_error') {
            statusBadge.style.backgroundColor = '#9E9E9E'; 
            setButtonState('hide');
        } else {
            statusBadge.style.backgroundColor = '#f39c12'; 
        }

        // Update Bars
        const ssimPercent = Math.round(data.ssim * 100);
        ssimText.innerText = `${ssimPercent}%`;
        retryText.innerText = `${data.failures}/${data.max_retries}`;
        confidenceBar.style.width = `${ssimPercent}%`;

        if (data.failures > 0) confidenceBar.style.background = '#FF5722'; 
        else if (data.ssim < 0.90) confidenceBar.style.background = '#FFC107'; 
        else confidenceBar.style.background = 'linear-gradient(90deg, #4CAF50, #8BC34A)';

    } catch (e) { console.log("Status error", e); }
}
setInterval(updateStatus, 1000);

// --- FIXED BUTTON CLICK HANDLER ---
forceStartBtn.addEventListener('click', async () => {
    const action = forceStartBtn.dataset.action; // Read the logic flag we set earlier
    
    // Use POST to prevent caching
    const method = { method: 'POST' };
    
    try {
        if(action === "stop") {
            await fetch('/api/action/stop', method);
        } else {
            await fetch('/api/action/start', method);
        }
        // Force an immediate status update so UI feels snappy
        setTimeout(updateStatus, 100); 
    } catch (e) {
        console.error("Failed to toggle monitoring", e);
    }
});

// --- SETTINGS (Unchanged) ---
document.getElementById('open-settings-btn').addEventListener('click', async () => {
    const res = await fetch('/api/settings');
    const data = await res.json();
    
    document.getElementById('camera_url').value = data.camera_url;
    document.getElementById('moonraker_url').value = data.moonraker_url || "http://127.0.0.1:7125";
    document.getElementById('check_interval').value = data.check_interval;
    document.getElementById('ssim_threshold').value = data.ssim_threshold;
    document.getElementById('mask_margin').value = data.mask_margin;
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
        ssim_threshold: parseFloat(document.getElementById('ssim_threshold').value),
        mask_margin: parseInt(document.getElementById('mask_margin').value),
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
