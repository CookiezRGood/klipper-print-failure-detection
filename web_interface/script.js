// Configuration
const REFRESH_RATE = 1000; // Refresh image every 1 second

// Elements
const liveImage = document.getElementById('live-image');
const debugToggle = document.getElementById('debug-toggle');
const statusBadge = document.getElementById('status-indicator');
const settingsModal = document.getElementById('settings-modal');

// --- 1. Image Auto-Refresh Loop ---
function refreshImage() {
    const timestamp = new Date().getTime();
    // Choose endpoint based on toggle: Normal or Debug (Mask)
    const endpoint = debugToggle.checked ? '/api/debug_frame' : '/api/latest_frame';
    
    // We add ?t=... to force the browser to ignore cache and get a new image
    liveImage.src = `${endpoint}?t=${timestamp}`;
}

// Start the loop
setInterval(refreshImage, REFRESH_RATE);

// --- 2. Status Loop ---
async function updateStatus() {
    try {
        const res = await fetch('/api/status');
        const data = await res.json();
        statusBadge.innerText = data.status.toUpperCase();
        
        if (data.status === 'monitoring') statusBadge.style.backgroundColor = '#4CAF50';
        else if (data.status === 'error') statusBadge.style.backgroundColor = '#F44336';
        else statusBadge.style.backgroundColor = '#f39c12';
    } catch (e) {
        console.log("Status fetch error", e);
    }
}
setInterval(updateStatus, 2000);

// --- 3. Settings Modal Logic ---
document.getElementById('open-settings-btn').addEventListener('click', async () => {
    // Fetch current settings before opening
    const res = await fetch('/api/settings');
    const data = await res.json();
    
    document.getElementById('ssim_threshold').value = data.ssim_threshold;
    document.getElementById('stillness_threshold').value = data.stillness_threshold;
    document.getElementById('check_interval').value = data.check_interval || 1.0;
    
    settingsModal.showModal();
});

document.getElementById('close-modal-x').addEventListener('click', () => {
    settingsModal.close();
});

document.getElementById('save-settings-btn').addEventListener('click', async () => {
    const payload = {
        ssim_threshold: parseFloat(document.getElementById('ssim_threshold').value),
        stillness_threshold: parseFloat(document.getElementById('stillness_threshold').value),
        check_interval: parseFloat(document.getElementById('check_interval').value)
    };
    
    await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    
    settingsModal.close();
    alert("Settings Saved!");
});

// Close modal if clicking outside
settingsModal.addEventListener('click', (event) => {
    if (event.target === settingsModal) {
        settingsModal.close();
    }
});
