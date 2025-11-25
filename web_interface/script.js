let imageInterval; // Store the interval ID so we can stop/start it

const liveImage = document.getElementById('live-image');
const debugToggle = document.getElementById('debug-toggle');
const statusBadge = document.getElementById('status-indicator');
const settingsModal = document.getElementById('settings-modal');
const ssimText = document.getElementById('ssim-val');
const retryText = document.getElementById('retry-val');
const confidenceBar = document.getElementById('confidence-bar');
const camContainer = document.getElementById('camera-container');

// --- DYNAMIC IMAGE REFRESH LOOP ---
function startImageLoop(rate) {
    if (imageInterval) clearInterval(imageInterval);
    
    // Default to 500ms if invalid
    const safeRate = (rate && rate >= 100) ? rate : 500;
    
    imageInterval = setInterval(() => {
        const timestamp = new Date().getTime();
        const endpoint = debugToggle.checked ? '/api/debug_frame' : '/api/latest_frame';
        liveImage.src = `${endpoint}?t=${timestamp}`;
    }, safeRate);
}

// Start with default, will update when settings load
startImageLoop(500);

// --- STATUS LOOP (Always 1s) ---
async function updateStatus() {
    try {
        const res = await fetch('/api/status');
        const data = await res.json();
        
        statusBadge.innerText = data.status.toUpperCase();
        
        if (data.status === 'failure_detected' || data.status === 'error') {
            statusBadge.style.backgroundColor = '#F44336'; 
        } else if (data.status === 'monitoring') {
            statusBadge.style.backgroundColor = '#4CAF50'; 
        } else if (data.status === 'idle') {
            statusBadge.style.backgroundColor = '#555555'; 
        } else if (data.status === 'connection_error') {
            statusBadge.style.backgroundColor = '#9E9E9E'; 
        } else {
            statusBadge.style.backgroundColor = '#f39c12'; 
        }

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

// --- SETTINGS MANAGEMENT ---
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
        check_interval: parseFloat(document.getElementById('check_interval').value),
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
    
    // Apply visual changes immediately
    camContainer.style.aspectRatio = payload.aspect_ratio.replace(':', '/');
    startImageLoop(newRate); // <--- Update the refresh rate immediately!
    
    alert("Configuration Saved!");
    settingsModal.close();
});

// INITIAL LOAD
fetch('/api/settings').then(r => r.json()).then(data => {
    if(data.aspect_ratio) camContainer.style.aspectRatio = data.aspect_ratio.replace(':', '/');
    if(data.preview_refresh_rate) startImageLoop(data.preview_refresh_rate);
});
