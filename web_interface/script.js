// Function to load current settings from Python
async function loadSettings() {
    try {
        const response = await fetch('/api/settings');
        const data = await response.json();
        
        // Populate inputs
        document.getElementById('ssim_threshold').value = data.ssim_threshold;
        document.getElementById('stillness_threshold').value = data.stillness_threshold;

        // Load camera if URL is present
        if(data.camera_url) {
            const camContainer = document.getElementById('camera-container');
            // Note: In a real scenario, you might need an MJPEG stream here. 
            // For now, we just show a static image that refreshes.
            camContainer.innerHTML = `<img src="${data.camera_url}" class="live-feed" alt="Camera Feed">`;
        }
    } catch (error) {
        console.error('Error loading settings:', error);
    }
}

// Function to check status
async function checkStatus() {
    try {
        const response = await fetch('/api/failure_status');
        const data = await response.json();
        const badge = document.getElementById('status-indicator');
        
        badge.innerText = data.status.toUpperCase();
        
        if(data.status === 'active') {
            badge.style.backgroundColor = '#4CAF50'; // Green
        } else {
            badge.style.backgroundColor = '#f39c12'; // Orange
        }
    } catch (error) {
        console.error('Error fetching status:', error);
    }
}

// Save button logic
document.getElementById('save-btn').addEventListener('click', async () => {
    const ssim = parseFloat(document.getElementById('ssim_threshold').value);
    const stillness = parseFloat(document.getElementById('stillness_threshold').value);

    try {
        await fetch('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                ssim_threshold: ssim,
                stillness_threshold: stillness
            })
        });
        alert('Settings Saved!');
    } catch (error) {
        alert('Failed to save settings');
    }
});

// Initial Load
loadSettings();
setInterval(checkStatus, 2000); // Check status every 2 seconds
