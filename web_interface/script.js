let imageInterval;

// Settings and toggles
let currentSettings = {};
let isMaskVisible = false;
let suppressConfidenceUpdates = false;
let lastConfidence = null;
let lastStatus = null;
let failureHistory = [];
let renderedHistoryKeys = new Set();
let settingsDirty = false;
let settingsCloseArmed = false;
let aiDirty = false;
let aiBackArmed = false;

const statusBadge = document.getElementById('status-indicator');
const ssimText = document.getElementById('ssim-val');
const retryText = document.getElementById('retry-val');
const confidenceBar = document.getElementById('confidence-bar');
const forceStartBtn = document.getElementById('force-start-btn');
const maskToggleBtn = document.getElementById('mask-toggle-btn');
const settingsModal = document.getElementById('settings-modal');
const overlay = document.getElementById('settings-overlay');

const mainContent = document.getElementById('main-content');

const cameraGrid = document.getElementById('camera-grid');

const historyModal = document.getElementById("history-modal");
const openHistoryBtn = document.getElementById("open-history-btn");
const closeHistoryBtn = document.getElementById("close-history-modal");
const historyBody = document.getElementById("history-table-body");
const historyScroll = document.getElementById("history-scroll");
const clearHistoryBtn = document.getElementById("clear-history-btn");

// Camera references
const cam1Img = document.getElementById('cam1-img');
const cam2Img = document.getElementById('cam2-img');

[cam1Img, cam2Img].forEach(img => {
    if (!img) return;

    img.setAttribute('draggable', 'false');
    img.draggable = false;
    img.style.userSelect = 'none';

    img.addEventListener('mousedown', e => e.preventDefault());
});

const cam1Card = document.getElementById('card-cam1');
const cam2Card = document.getElementById('card-cam2');
const cam1Toggle = document.getElementById('cam1-toggle');
const cam2Toggle = document.getElementById('cam2-toggle');
const cam1View = document.getElementById('cam1-container');
const cam2View = document.getElementById('cam2-container');

// Mask clearing
const cam1ClearBtn = document.getElementById('cam1-clear-masks');
const cam2ClearBtn = document.getElementById('cam2-clear-masks');

// Mask zones for each camera
const maskZones = { 0: [], 1: [] };

// Clear masks
if (cam1ClearBtn) {
    cam1ClearBtn.addEventListener('click', () => {
        maskZones[0] = [];
        syncMasksToServer();
    });
}
if (cam2ClearBtn) {
    cam2ClearBtn.addEventListener('click', () => {
        maskZones[1] = [];
        syncMasksToServer();
    });
}

/********************************************************************
 * Image Loop
 ********************************************************************/
function startImageLoop(rate) {
    if (imageInterval) clearInterval(imageInterval);

    const finalRate = (rate && rate >= 100) ? rate : 500;

    imageInterval = setInterval(() => {
        const now = Date.now();

        cam1Img.src = cam1Card.classList.contains('disabled') ? "" : `/api/frame/0?cache_bust=${now}`;
        cam2Img.src = cam2Card.classList.contains('disabled') ? "" : `/api/frame/1?cache_bust=${now}`;

    }, finalRate);
}

/********************************************************************
 * Camera toggle
 ********************************************************************/
async function toggleCamera(camId, enabled) {
    const card = camId === 0 ? cam1Card : cam2Card;
    const toggle = camId === 0 ? cam1Toggle : cam2Toggle;

    toggle.checked = enabled;

    if (enabled) {
        card.classList.remove('disabled');
        viewEl = camId === 0 ? cam1View : cam2View;
        viewEl.classList.add("mask-draw-enabled");
    } else {
        card.classList.add('disabled');
        viewEl = camId === 0 ? cam1View : cam2View;
        viewEl.classList.remove("mask-draw-enabled");
    }

    if (currentSettings.cameras) {
        currentSettings.cameras[camId].enabled = enabled;

        try {
            await fetch('/api/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(currentSettings)
            });
        } catch (err) {}
    }
}

cam1Toggle.addEventListener('change', ev => toggleCamera(0, ev.target.checked));
cam2Toggle.addEventListener('change', ev => toggleCamera(1, ev.target.checked));

/********************************************************************
 * Monitoring button
 ********************************************************************/
function setButtonState(mode) {
    forceStartBtn.classList.remove('btn-success', 'btn-danger');

    if (mode === 'start') {
        forceStartBtn.innerText = "▶ Start Monitoring";
        forceStartBtn.classList.add('btn-success');
        forceStartBtn.dataset.action = "start";
    } else {
        forceStartBtn.innerText = "■ Stop Monitoring";
        forceStartBtn.classList.add('btn-danger');
        forceStartBtn.dataset.action = "stop";
    }
}

forceStartBtn.addEventListener('click', async () => {
    const action = forceStartBtn.dataset.action;

    try {
        await fetch(`/api/action/${action}`, { method: 'POST' });
    } catch (err) {}

    setTimeout(updateStatus, 150);
});

/********************************************************************
 * Status polling
 ********************************************************************/
async function updateStatus() {
    try {
        const resp = await fetch('/api/status');
        const data = await resp.json();
        
        // Per-camera detection & failure counters
        if (data.cam_stats) {
            document.getElementById("cam1-detect-count").innerText =
                data.cam_stats["0"].detections;

            document.getElementById("cam1-fail-count").innerText =
                data.cam_stats["0"].failures;

            document.getElementById("cam2-detect-count").innerText =
                data.cam_stats["1"].detections;

            document.getElementById("cam2-fail-count").innerText =
                data.cam_stats["1"].failures;
        }
        
        // Store for stats modal
        lastCamStats = data.cam_stats;
        refreshStatsModalIfOpen();

        const statusTxt = data.status.toUpperCase().replace('_', ' ');
        
        if (lastStatus !== data.status) {
            statusBadge.classList.add("status-change");
            setTimeout(() => statusBadge.classList.remove("status-change"), 150);
            lastStatus = data.status;
        }
        
        const statusTextEl = document.getElementById("status-text");
        if (statusTextEl) {
            statusTextEl.innerText = statusTxt;
        } else {
            statusBadge.innerText = statusTxt;
        }

        if (data.status === 'failure_detected') {
            suppressConfidenceUpdates = true;
            statusBadge.style.backgroundColor = '#e53935';
            setButtonState('stop');
            
            const tooltip = document.getElementById("status-tooltip");
            const statusText = document.getElementById("status-text");

            if (statusText) statusText.innerText = "FAILURE DETECTED";

            if (data.failure_reason) {
                const camLabel =
                    data.failure_cam === 0 ? "Primary Camera" :
                    data.failure_cam === 1 ? "Secondary Camera" : "Unknown Camera";

                if (tooltip) tooltip.innerHTML =
                    `<strong>Triggered by:</strong> ${data.failure_reason.category} (${Math.round(data.failure_reason.confidence * 100)}%)<br>` +
                    `<strong>Camera:</strong> ${camLabel}`;

                if (tooltip) tooltip.classList.remove("hidden");
            }

            const failCam = data.failure_cam;

            if (failCam === 0 && cam1View) {
                cam1View.classList.add("failure-flash");
                setTimeout(() => cam1View.classList.remove("failure-flash"), 400);
            }

            if (failCam === 1 && cam2View) {
                cam2View.classList.add("failure-flash");
                setTimeout(() => cam2View.classList.remove("failure-flash"), 400);
            }
            
        } else if (data.status === 'monitoring') {
            statusBadge.style.backgroundColor = '#43a047';
            document.getElementById("status-text").innerText = statusTxt;
            document.getElementById("status-tooltip").classList.add("hidden");
            setButtonState('stop');
        } else {
            statusBadge.style.backgroundColor = '#555';
            document.getElementById("status-text").innerText = statusTxt;
            document.getElementById("status-tooltip").classList.add("hidden");
            setButtonState('start');
        }

        // Fade out health UI when not monitoring
        const health = document.querySelector('.health-section');

        if (data.status !== 'monitoring' && data.status !== 'failure_detected') {
            health.classList.add('dimmed');
            health.classList.remove("glow-green", "glow-yellow", "glow-red");
            
            const trendEl = document.getElementById("confidence-trend");
            if (trendEl) trendEl.innerText = "→";
            lastConfidence = null;

            confidenceBar.style.opacity = "0";

            setTimeout(() => {
                confidenceBar.style.width = "0%";
                confidenceBar.style.backgroundColor = "#4CAF50";
                ssimText.innerText = "0%";
                retryText.innerText = `0/${data.max_retries}`;
            }, 400);

            const label = document.getElementById("monitoring-label");
            label.textContent = "Not Monitoring";
            label.style.opacity = "1";

            suppressConfidenceUpdates = true;

        } else {
            health.classList.remove('dimmed');
            confidenceBar.style.opacity = "1";

            const label = document.getElementById("monitoring-label");
            label.style.opacity = "0";

            suppressConfidenceUpdates = false;
        }

        if (!suppressConfidenceUpdates) {
            const failPct = Math.floor(data.score * 100);
            ssimText.innerText = failPct + '%';
            retryText.innerText = `${data.failures}/${data.max_retries}`;
            confidenceBar.style.width = failPct + '%';
            
            // --- Confidence trend arrow ---
            const trendEl = document.getElementById("confidence-trend");
            if (trendEl && lastConfidence !== null) {
                if (failPct > lastConfidence + 2) {
                    trendEl.innerText = "↑";
                } else if (failPct < lastConfidence - 2) {
                    trendEl.innerText = "↓";
                } else {
                    trendEl.innerText = "→";
                }
            }
            lastConfidence = failPct;

            // Find trigger thresholds for categories that can cancel the print
            const cats = currentSettings.ai_categories || {};
            const detectThresholds = [];
            const triggerThresholds = [];

            Object.values(cats).forEach(c => {
                if (!c || !c.enabled) return;

                detectThresholds.push((c.detect_threshold ?? 0.3) * 100);

                if (c.trigger) {
                    triggerThresholds.push((c.trigger_threshold ?? 0.7) * 100);
                }
            });

            // “Warning” point: the lowest detect threshold among enabled categories
            const warnT = detectThresholds.length > 0 ? Math.min(...detectThresholds) : 100;

            // “Failure” point: the lowest trigger threshold among enabled+trigger categories
            const failT = triggerThresholds.length > 0 ? Math.min(...triggerThresholds) : 100;

            // Compute color
            let barColor;

            if (failPct >= failT) {
                barColor = '#F44336'; // red = above failure threshold
            } else {
                const range = failT - warnT;
                const relative = (failPct - warnT) / range;

                if (relative < 0) barColor = '#4CAF50';          // green
                else if (relative < 0.33) barColor = '#4CAF50'; // green
                else if (relative < 0.66) barColor = '#FFEB3B'; // yellow
                else barColor = '#FFB74D';                       // orange
            }

            confidenceBar.style.backgroundColor = barColor;

            const health = document.querySelector('.health-section');

            // Clear glow states
            health.classList.remove("glow-green", "glow-yellow", "glow-red");

            // Apply glow based on state
            if (barColor === '#F44336') {
                health.classList.add("glow-red");
            } else if (barColor === '#FFEB3B' || barColor === '#FFB74D') {
                health.classList.add("glow-yellow");
            } else {
                health.classList.add("glow-green");
            }

        }

    } catch (err) {}
}

setInterval(updateStatus, 1200);

/********************************************************************
 * Mask toggle
 ********************************************************************/
maskToggleBtn.addEventListener('click', async () => {
    isMaskVisible = !isMaskVisible;

    maskToggleBtn.style.backgroundColor = isMaskVisible ? "#2196F3" : "";
    maskToggleBtn.style.color = isMaskVisible ? "white" : "";

    try {
        await fetch('/api/action/toggle_mask', {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({ show: isMaskVisible })
        });
    } catch (err) {}
});

/********************************************************************
 * Layout switching
 ********************************************************************/
function applyLayout(count) {
    if (parseInt(count) === 1) {
        cameraGrid.classList.add('single-mode');
        cam2Card.classList.add('hidden');
    } else {
        cameraGrid.classList.remove('single-mode');
        cam2Card.classList.remove('hidden');
    }
    updateCam2SettingsVisibility(count);
}

function updateCam2SettingsVisibility(count) {
    const wrap = document.getElementById("cam2-settings");
    if (!wrap) return;

    if (parseInt(count) === 1) wrap.classList.add("hidden");
    else wrap.classList.remove("hidden");
}

/********************************************************************
 * Sync mask zones
 ********************************************************************/
function syncMasksToServer() {
    currentSettings.masks = {
        "0": maskZones[0],
        "1": maskZones[1]
    };

    fetch('/api/settings', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify(currentSettings)
    });
    
    updateMaskIndicators();
}

function isCameraEnabled(camId) {
    const card = camId === 0 ? cam1Card : cam2Card;
    return card && !card.classList.contains('disabled');
}

/********************************************************************
 * Mask drawing
 ********************************************************************/
function setupMaskDrawing(camId, viewEl) {

    viewEl.classList.add("mask-draw-enabled");
    let drawing = false;
    let startX = 0, startY = 0;
    let tempRect = null;

    function posInCam(e) {
        const r = viewEl.getBoundingClientRect();
        return {
            x: e.clientX - r.left,
            y: e.clientY - r.top,
            w: r.width,
            h: r.height
        };
    }

    viewEl.addEventListener('mousedown', (ev) => {
        ev.preventDefault();

        if (!isCameraEnabled(camId)) return;

        if (ev.button !== 0) return;

        const { x, y, w, h } = posInCam(ev);
        if (x < 0 || y < 0 || x > w || y > h) return;

        drawing = true;
        startX = x;
        startY = y;

        tempRect = document.createElement('div');
        tempRect.classList.add('temp-mask-rect');
        Object.assign(tempRect.style, {
            position:'absolute',
            border:'1px solid #ff00ff',
            backgroundColor:'rgba(255,0,255,0.20)',
            left:`${x}px`,
            top:`${y}px`,
            pointerEvents:'none'
        });

        viewEl.appendChild(tempRect);
    });

    window.addEventListener('mousemove', (ev) => {
        if (!drawing || !tempRect) return;
        const { x, y } = posInCam(ev);

        const minX = Math.min(startX, x);
        const minY = Math.min(startY, y);
        const w = Math.abs(x - startX);
        const h = Math.abs(y - startY);

        Object.assign(tempRect.style, {
            left:`${minX}px`,
            top:`${minY}px`,
            width:`${w}px`,
            height:`${h}px`
        });
    });

    window.addEventListener('mouseup', (ev) => {
        if (!drawing || !tempRect) return;

        const { x, y, w, h } = posInCam(ev);

        const rx = Math.min(startX, x);
        const ry = Math.min(startY, y);
        const rw = Math.abs(x - startX);
        const rh = Math.abs(y - startY);

        tempRect.remove();
        drawing = false;
        tempRect = null;

        if (rw < 10 || rh < 10) return;

        maskZones[camId].push({
            x: rx / w,
            y: ry / h,
            w: rw / w,
            h: rh / h
        });

        syncMasksToServer();
        showToast("Mask added");
    });

    viewEl.addEventListener('contextmenu', (ev) => {
        ev.preventDefault();

        if (!isCameraEnabled(camId)) return;

        const { x, y, w, h } = posInCam(ev);
        const nx = x / w;
        const ny = y / h;

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
                showToast("Mask removed");
                return;
            }
        }
    });
}

function updateMaskIndicators() {
    [0, 1].forEach(camId => {
        const view = camId === 0 ? cam1View : cam2View;
        const zones = maskZones[camId] || [];

        if (!view) return;

        if (zones.length > 0) {
            // Add indicator
            if (!view.classList.contains("has-masks")) {
                view.classList.add("has-masks");

                // Trigger pulse animation
                view.classList.add("pulse-mask");
                setTimeout(() => {
                    view.classList.remove("pulse-mask");
                }, 2000);
            }
        } else {
            view.classList.remove("has-masks");
            view.classList.remove("pulse-mask");
        }
    });
}

/********************************************************************
 * Mask Toast
 ********************************************************************/

function showToast(msg) {
    let toast = document.getElementById("ui-toast");
    if (!toast) {
        toast = document.createElement("div");
        toast.id = "ui-toast";
        toast.className = "toast";
        document.body.appendChild(toast);
    }

    toast.textContent = msg;
    toast.classList.add("show");

    setTimeout(() => {
        toast.classList.remove("show");
    }, 900);
}

/********************************************************************
 * Load settings
 ********************************************************************/
async function loadSettings() {
    try {
        const resp = await fetch('/api/settings');
        currentSettings = await resp.json();

        const cam1 = currentSettings.cameras[0];
        const cam2 = currentSettings.cameras[1];

        toggleCamera(0, cam1.enabled);
        toggleCamera(1, cam2.enabled);

        // Loop Control
        document.getElementById("infer_every_n_loops").value =
            currentSettings.infer_every_n_loops || 1;
        
        // Camera count
        document.getElementById('camera_count').value =
            currentSettings.camera_count || 2;
            
        updateCam2SettingsVisibility(currentSettings.camera_count || 2);
        
        const camCountEl = document.getElementById("camera_count");
        if (camCountEl) {
            camCountEl.addEventListener("change", () => {
                updateCam2SettingsVisibility(parseInt(camCountEl.value));
            });
        }

        // URLs
        document.getElementById('cam1_url_input').value = cam1.url || "";
        document.getElementById('cam2_url_input').value = cam2.url || "";

        // Moonraker URL
        document.getElementById('moonraker_url').value =
            currentSettings.moonraker_url || "";

        // Check interval
        document.getElementById('check_interval').value =
            currentSettings.check_interval || 500;

        // Load category settings
        const cats = currentSettings.ai_categories || {};

        document.getElementById("cat_spaghetti_enabled").checked =
            cats.spaghetti?.enabled ?? true;
        document.getElementById("cat_spaghetti_trigger").checked =
            cats.spaghetti?.trigger ?? true;
        document.getElementById("cat_spaghetti_detect_threshold").value =
            Math.round((cats.spaghetti?.detect_threshold ?? 0.3) * 100);

        document.getElementById("cat_spaghetti_trigger_threshold").value =
            Math.round((cats.spaghetti?.trigger_threshold ?? 0.7) * 100);

        // Blob
        document.getElementById("cat_blob_enabled").checked =
            cats.blob?.enabled ?? true;
        document.getElementById("cat_blob_trigger").checked =
            cats.blob?.trigger ?? false;
        document.getElementById("cat_blob_detect_threshold").value =
            Math.round((cats.blob?.detect_threshold ?? 0.3) * 100);

        document.getElementById("cat_blob_trigger_threshold").value =
            Math.round((cats.blob?.trigger_threshold ?? 0.7) * 100);

        // Crack
        document.getElementById("cat_crack_enabled").checked =
            cats.crack?.enabled ?? true;
        document.getElementById("cat_crack_trigger").checked =
            cats.crack?.trigger ?? false;
        document.getElementById("cat_crack_detect_threshold").value =
            Math.round((cats.crack?.detect_threshold ?? 0.3) * 100);

        document.getElementById("cat_crack_trigger_threshold").value =
            Math.round((cats.crack?.trigger_threshold ?? 0.7) * 100);

        // Warping
        document.getElementById("cat_warping_enabled").checked =
            cats.warping?.enabled ?? true;
        document.getElementById("cat_warping_trigger").checked =
            cats.warping?.trigger ?? false;
        document.getElementById("cat_warping_detect_threshold").value =
            Math.round((cats.warping?.detect_threshold ?? 0.3) * 100);

        document.getElementById("cat_warping_trigger_threshold").value =
            Math.round((cats.warping?.trigger_threshold ?? 0.7) * 100);

        // Failures
        document.getElementById('consecutive_failures').value =
            currentSettings.consecutive_failures || 3;

        // On failure
        document.getElementById('on_failure').value =
            currentSettings.on_failure || "pause";
            
        // Mobileraker notification
        document.getElementById("notify_mobileraker").checked =
            currentSettings.notify_mobileraker ?? false;

        // Masks
        const m = currentSettings.masks || {};
        maskZones[0] = Array.isArray(m["0"]) ? [...m["0"]] : [];
        maskZones[1] = Array.isArray(m["1"]) ? [...m["1"]] : [];
        updateMaskIndicators();

        // Per-camera aspect ratios
        document.getElementById('cam1_aspect_ratio').value =
            currentSettings.cam1_aspect_ratio || "4:3";

        document.getElementById('cam2_aspect_ratio').value =
            currentSettings.cam2_aspect_ratio || "4:3";

        // Apply aspect ratios to camera views
        const ratio1 = (currentSettings.cam1_aspect_ratio || "4:3").replace(':',' / ');
        const ratio2 = (currentSettings.cam2_aspect_ratio || "4:3").replace(':',' / ');

        cam1View.style.aspectRatio = ratio1;
        cam2View.style.aspectRatio = ratio2;

        applyLayout(currentSettings.camera_count || 2);
        startImageLoop(currentSettings.check_interval || 500);

    } catch (err) {
        console.error(err);
    }
}

/********************************************************************
 * Open / Close Settings panel (blur + overlay)
 ********************************************************************/
document.getElementById('open-settings-btn').addEventListener('click', () => {
    const statusEl = document.getElementById("settings-save-status");
    if (statusEl) {
        statusEl.textContent = "";
        statusEl.className = "save-status";
    }

    const warnEl = document.getElementById("settings-unsaved-warning");
    if (warnEl) warnEl.textContent = "";

    settingsDirty = false;
    settingsCloseArmed = false;

    loadSettings();

    // Mark dirty when ANY input/select changes
    settingsModal.querySelectorAll("input, select").forEach(el => {
        el.addEventListener("change", () => {
            settingsDirty = true;
            settingsCloseArmed = false;
            if (warnEl) warnEl.textContent = "";
        });
        el.addEventListener("input", () => {
            settingsDirty = true;
            settingsCloseArmed = false;
            if (warnEl) warnEl.textContent = "";
        });
    });

    settingsModal.showModal();
    settingsModal.classList.add('show');
    overlay.classList.add('active');
    mainContent.classList.add('blurred');
});

// ===============================
// TWO-PAGE SETTINGS SYSTEM
// ===============================
const settingsPages = document.getElementById("settings-pages");
const openAiBtn = document.getElementById("open-ai-cat-btn");
const backAiBtn = document.getElementById("back-ai-btn");

// Open AI Category Page
openAiBtn.addEventListener("click", () => {
    const aiStatus = document.getElementById("category-save-status");
    const aiErr = document.getElementById("category-error-text");
    if (aiStatus) {
        aiStatus.textContent = "";
        aiStatus.className = "save-status";
    }
    if (aiErr) aiErr.textContent = "";

    aiDirty = false;
    aiBackArmed = false;

    const aiWarn = document.getElementById("ai-unsaved-warning");
    if (aiWarn) aiWarn.textContent = "";

    const aiPage = document.getElementById("ai-page");
    if (aiPage) {
        aiPage.querySelectorAll("input, select").forEach(el => {
            el.addEventListener("change", () => {
                aiDirty = true;
                aiBackArmed = false;
                if (aiWarn) aiWarn.textContent = "";
            });
            el.addEventListener("input", () => {
                aiDirty = true;
                aiBackArmed = false;
                if (aiWarn) aiWarn.textContent = "";
            });
        });
    }

    settingsPages.classList.add("show-ai");
});

// Go back to main settings page
backAiBtn.addEventListener("click", () => {
    const warn = document.getElementById("ai-unsaved-warning");

    if (aiDirty && !aiBackArmed) {
        if (warn) {
            warn.textContent = "You have unsaved changes. Press Back again to discard.";
        }
        aiBackArmed = true;
        return;
    }

    aiDirty = false;
    aiBackArmed = false;
    if (warn) warn.textContent = "";
    
    loadSettings();

    settingsPages.classList.remove("show-ai");
});

document.getElementById('close-modal-x').addEventListener('click', () => {
    const warnEl = document.getElementById("settings-unsaved-warning");

    if (settingsDirty && !settingsCloseArmed) {
        if (warnEl) {
            warnEl.textContent = "You have unsaved changes. Click × again to discard.";
        }
        settingsCloseArmed = true;
        return;
    }

    settingsDirty = false;
    settingsCloseArmed = false;

    if (warnEl) warnEl.textContent = "";
    
    aiDirty = false;
    aiBackArmed = false;

    const aiWarn = document.getElementById("ai-unsaved-warning");
    if (aiWarn) aiWarn.textContent = "";

    settingsModal.classList.remove('show');
    settingsPages.classList.remove("show-ai");
    settingsModal.close();
    overlay.classList.remove('active');
    mainContent.classList.remove('blurred');
});

// Prevent ESC from breaking UI; route through close logic
settingsModal.addEventListener("cancel", (e) => {
    e.preventDefault();
    document.getElementById("close-modal-x").click();
});

settingsModal.addEventListener("close", () => {
    settingsDirty = false;
    settingsCloseArmed = false;

    const warnEl = document.getElementById("settings-unsaved-warning");
    if (warnEl) warnEl.textContent = "";

    aiDirty = false;
    aiBackArmed = false;

    const aiWarn = document.getElementById("ai-unsaved-warning");
    if (aiWarn) aiWarn.textContent = "";
    
    overlay.classList.remove('active');
    mainContent.classList.remove('blurred');
});

/********************************************************************
 * Per-Category Detection Stats Modal
 ********************************************************************/

// Store latest cam_stats from /api/status
let lastCamStats = null;

// Reference to detection boxes on main dashboard
const cam1StatsCard = document.getElementById("cam1-stats");
const cam2StatsCard = document.getElementById("cam2-stats");

// Stats modal DOM
const statsModal = document.getElementById("stats-modal");
const statsModalTitle = document.getElementById("stats-modal-title");
const statsModalClose = document.getElementById("close-stats-modal");

function fillStatsModal(camId) {
    if (!lastCamStats) return;

    const camKey = String(camId);
    const stats = lastCamStats[camKey];
    if (!stats || !stats.per_category) return;

    statsModalTitle.textContent =
        camId === 0 ? "Primary Camera Detection Breakdown" :
                      "Secondary Camera Detection Breakdown";

    const perCat = stats.per_category;

    function setCounts(key, detId, failId) {
        const detEl = document.getElementById(detId);
        const failEl = document.getElementById(failId);
        if (!detEl || !failEl) return;

        detEl.textContent  = perCat[key]?.detections ?? 0;
        failEl.textContent = perCat[key]?.failures ?? 0;
    }

    setCounts("spaghetti", "stat-det-spaghetti", "stat-fail-spaghetti");
    setCounts("blob",      "stat-det-blob",      "stat-fail-blob");
    setCounts("warping",   "stat-det-warping",   "stat-fail-warping");
    setCounts("crack",     "stat-det-crack",     "stat-fail-crack");
}

function refreshStatsModalIfOpen() {
    if (!statsModal.open) return;

    // Determine which camera modal is showing
    if (statsModalTitle.textContent.includes("Primary")) {
        fillStatsModal(0);
    } else if (statsModalTitle.textContent.includes("Secondary")) {
        fillStatsModal(1);
    }
}

let activeStatsCamId = null;

function openStatsModal(camId) {
    activeStatsCamId = camId;
    fillStatsModal(camId);
    statsModal.showModal();
    statsModal.classList.add("show");
    mainContent.classList.add("blurred");
}

// Make dashboard detection boxes clickable
if (cam1StatsCard) cam1StatsCard.addEventListener("click", () => openStatsModal(0));
if (cam2StatsCard) cam2StatsCard.addEventListener("click", () => openStatsModal(1));

if (statsModalClose) {
    statsModalClose.addEventListener("click", () => {
    statsModal.close();
    setTimeout(() => statsModal.close(), 150);
    mainContent.classList.remove("blurred");
});
}

statsModal.addEventListener("cancel", (e) => {
    e.preventDefault();
    statsModal.close();
    mainContent.classList.remove("blurred");
});

const resetStatsBtn = document.getElementById("reset-stats-btn");

if (resetStatsBtn) {
    resetStatsBtn.addEventListener("click", async () => {
        if (activeStatsCamId === null) return;

        try {
            await fetch(`/api/stats/reset/${activeStatsCamId}`, {
                method: "POST"
            });
        } catch (err) {
            console.error("Failed to reset stats", err);
            return;
        }

        // Immediately refresh local copy
        if (lastCamStats && lastCamStats[String(activeStatsCamId)]) {
            lastCamStats[String(activeStatsCamId)] = {
                detections: 0,
                failures: 0,
                per_category: {}
            };
        }

        fillStatsModal(activeStatsCamId);
    });
}

/********************************************************************
 * Clear Failure History
 ********************************************************************/

if (clearHistoryBtn) {
    clearHistoryBtn.addEventListener("click", async () => {
        try {
            await fetch("/api/failure_history/clear", { method: "POST" });
            failureHistory = [];
            renderedHistoryKeys.clear();
            renderFailureHistory();
        } catch (e) {}
    });
}

/********************************************************************
 * Save settings
 ********************************************************************/
document.getElementById('save-settings-btn').addEventListener('click', async () => {

    currentSettings.camera_count =
        parseInt(document.getElementById('camera_count').value);

    currentSettings.cameras[0].url =
        document.getElementById('cam1_url_input').value;

    currentSettings.cameras[1].url =
        document.getElementById('cam2_url_input').value;

    currentSettings.moonraker_url =
        document.getElementById('moonraker_url').value;

    currentSettings.check_interval =
        parseInt(document.getElementById('check_interval').value);

    currentSettings.consecutive_failures =
        parseInt(document.getElementById('consecutive_failures').value);

    currentSettings.on_failure =
        document.getElementById('on_failure').value;
        
    currentSettings.notify_mobileraker =
        document.getElementById("notify_mobileraker").checked;
        
    currentSettings.infer_every_n_loops =
        parseInt(document.getElementById("infer_every_n_loops").value);
        
    // Save category settings
    currentSettings.ai_categories = {
    spaghetti: {
        enabled: document.getElementById("cat_spaghetti_enabled").checked,
        trigger: document.getElementById("cat_spaghetti_trigger").checked,
        detect_threshold: document.getElementById("cat_spaghetti_detect_threshold").value / 100,
        trigger_threshold: document.getElementById("cat_spaghetti_trigger_threshold").value / 100
    },
    blob: {
        enabled: document.getElementById("cat_blob_enabled").checked,
        trigger: document.getElementById("cat_blob_trigger").checked,
        detect_threshold: document.getElementById("cat_blob_detect_threshold").value / 100,
        trigger_threshold: document.getElementById("cat_blob_trigger_threshold").value / 100
    },
    crack: {
        enabled: document.getElementById("cat_crack_enabled").checked,
        trigger: document.getElementById("cat_crack_trigger").checked,
        detect_threshold: document.getElementById("cat_crack_detect_threshold").value / 100,
        trigger_threshold: document.getElementById("cat_crack_trigger_threshold").value / 100
    },
    warping: {
        enabled: document.getElementById("cat_warping_enabled").checked,
        trigger: document.getElementById("cat_warping_trigger").checked,
        detect_threshold: document.getElementById("cat_warping_detect_threshold").value / 100,
        trigger_threshold: document.getElementById("cat_warping_trigger_threshold").value / 100
    }
};

    currentSettings.masks = {
        "0": maskZones[0],
        "1": maskZones[1]
    };

    currentSettings.cam1_aspect_ratio =
    document.getElementById("cam1_aspect_ratio").value;

    currentSettings.cam2_aspect_ratio =
        document.getElementById("cam2_aspect_ratio").value;

    await fetch('/api/settings', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify(currentSettings)
    });

    // CAM 1 aspect ratio
    if (currentSettings.cam1_aspect_ratio) {
        const ratio1 = currentSettings.cam1_aspect_ratio.replace(':',' / ');
        cam1View.style.aspectRatio = ratio1;
    }

    // CAM 2 aspect ratio
    if (currentSettings.cam2_aspect_ratio) {
        const ratio2 = currentSettings.cam2_aspect_ratio.replace(':',' / ');
        cam2View.style.aspectRatio = ratio2;
    }

    applyLayout(currentSettings.camera_count);
    startImageLoop(currentSettings.check_interval);

    const statusEl = document.getElementById("settings-save-status");
    if (statusEl) {
        statusEl.textContent = "Saved ✓";
        statusEl.className = "save-status success";
    }
    
    settingsDirty = false;
    settingsCloseArmed = false;

    const warnEl = document.getElementById("settings-unsaved-warning");
    if (warnEl) warnEl.textContent = "";

    setTimeout(() => {
        settingsModal.classList.remove('show');
        settingsModal.close();
        overlay.classList.remove('active');
        mainContent.classList.remove('blurred');
    }, 700);
});

// Save AI Category Settings
document.getElementById("save-ai-cat-btn").addEventListener("click", async () => {
    
    const saveBtn = document.getElementById("save-ai-cat-btn");
    const errEl = document.getElementById("category-error-text");
    const statusEl = document.getElementById("category-save-status");

    if (errEl) errEl.textContent = "";
    if (statusEl) {
        statusEl.textContent = "";
        statusEl.className = "save-status";
    }
    if (saveBtn) saveBtn.disabled = false;

    // Validation: detect must be STRICTLY less than trigger (failure)
    const pairs = [
        ["Spaghetti", "cat_spaghetti_detect_threshold", "cat_spaghetti_trigger_threshold"],
        ["Blob", "cat_blob_detect_threshold", "cat_blob_trigger_threshold"],
        ["Bed Adhesion Failure", "cat_bed_adhesion_failure_detect_threshold", "cat_bed_adhesion_failure_trigger_threshold"],
        ["Crack", "cat_crack_detect_threshold", "cat_crack_trigger_threshold"],
    ];

    const invalid = [];
    for (const [label, detectId, trigId] of pairs) {
        const dEl = document.getElementById(detectId);
        const tEl = document.getElementById(trigId);
        if (!dEl || !tEl) continue;

        const detect = parseFloat(dEl.value);
        const trigger = parseFloat(tEl.value);

        if (!(detect < trigger)) invalid.push(label);
    }

    if (invalid.length) {
        if (errEl) errEl.textContent = `Detection must be lower than failure for: ${invalid.join(", ")}.`;
        if (saveBtn) saveBtn.disabled = true;

        // Re-enable button when user edits anything (no live validation; next save click re-checks)
        const reenable = () => {
            if (saveBtn) saveBtn.disabled = false;
            if (errEl) errEl.textContent = "";
            pairs.forEach(([_, dId, tId]) => {
                const d = document.getElementById(dId);
                const t = document.getElementById(tId);
                if (d) d.removeEventListener("input", reenable);
                if (t) t.removeEventListener("input", reenable);
            });
        };
        pairs.forEach(([_, dId, tId]) => {
            const d = document.getElementById(dId);
            const t = document.getElementById(tId);
            if (d) d.addEventListener("input", reenable);
            if (t) t.addEventListener("input", reenable);
        });

        return;
    }
    
    currentSettings.ai_categories = {
        spaghetti: {
            enabled: document.getElementById("cat_spaghetti_enabled").checked,
            trigger: document.getElementById("cat_spaghetti_trigger").checked,
            detect_threshold: document.getElementById("cat_spaghetti_detect_threshold").value / 100,
            trigger_threshold: document.getElementById("cat_spaghetti_trigger_threshold").value / 100
        },
        blob: {
            enabled: document.getElementById("cat_blob_enabled").checked,
            trigger: document.getElementById("cat_blob_trigger").checked,
            detect_threshold: document.getElementById("cat_blob_detect_threshold").value / 100,
            trigger_threshold: document.getElementById("cat_blob_trigger_threshold").value / 100
        },
        crack: {
            enabled: document.getElementById("cat_crack_enabled").checked,
            trigger: document.getElementById("cat_crack_trigger").checked,
            detect_threshold: document.getElementById("cat_crack_detect_threshold").value / 100,
            trigger_threshold: document.getElementById("cat_crack_trigger_threshold").value / 100
        },
        warping: {
            enabled: document.getElementById("cat_warping_enabled").checked,
            trigger: document.getElementById("cat_warping_trigger").checked,
            detect_threshold: document.getElementById("cat_warping_detect_threshold").value / 100,
            trigger_threshold: document.getElementById("cat_warping_trigger_threshold").value / 100
        }
    };

    await fetch('/api/settings', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify(currentSettings)
    });

    if (statusEl) {
        statusEl.textContent = "Saved ✓";
        statusEl.className = "save-status success";
    }
    
    aiDirty = false;
    aiBackArmed = false;

    const aiWarn = document.getElementById("ai-unsaved-warning");
    if (aiWarn) aiWarn.textContent = "";
    
    setTimeout(() => {
        settingsPages.classList.remove("show-ai");
    }, 700);
});

/********************************************************************
 * Mask drawing setup
 ********************************************************************/
setupMaskDrawing(0, cam1View);
setupMaskDrawing(1, cam2View);

/********************************************************************
 * FAILURE HISTORY MODAL
 ********************************************************************/

if (openHistoryBtn && historyModal) {
    openHistoryBtn.addEventListener("click", () => {
        historyModal.showModal();
        historyModal.classList.add("show");
        mainContent.classList.add("blurred");
        renderFailureHistory();
        fetchFailureHistory();
    });
}

if (closeHistoryBtn && historyModal) {
    closeHistoryBtn.addEventListener("click", () => {
        historyModal.classList.remove("show");
        historyModal.close();
        mainContent.classList.remove("blurred");
    });
}

historyModal.addEventListener("cancel", (e) => {
    e.preventDefault();
    historyModal.close();
    mainContent.classList.remove("blurred");
});

async function fetchFailureHistory() {
    try {
        const res = await fetch("/api/failure_history");
        if (!res.ok) return;

        const data = await res.json();
        const newHistory = data.events || [];

        if (newHistory.length !== failureHistory.length) {
            failureHistory = newHistory;
            renderFailureHistory();
        }
    } catch (e) {}
}

function renderFailureHistory() {
    if (!historyBody) return;

    historyBody.innerHTML = "";

    if (failureHistory.length === 0) {
        historyBody.innerHTML =
            `<div class="history-empty">No failures this session</div>`;
        return;
    }

    [...failureHistory].reverse().forEach(evt => {

        // --- FULL FAILURE DIVIDER ROW ---
        if (evt.severity === "failure") {
            const divider = document.createElement("div");
            divider.className = "history-divider";
            divider.textContent = "— PRINT FAILURE TRIGGERED —";
            historyBody.appendChild(divider);
            return; // IMPORTANT: do not render a normal row
        }

        // --- NORMAL HISTORY ROW ---
        const row = document.createElement("div");

        const key = `${evt.time}-${evt.camera}-${evt.category}-${evt.confidence}`;

        if (!renderedHistoryKeys.has(key)) {
            row.className = "history-row enter";
            renderedHistoryKeys.add(key);
        } else {
            row.className = "history-row";
        }

        const camLabel = evt.camera === 0 ? "Primary" : "Secondary";

        row.innerHTML = `
            <span class="history-time">${evt.time}</span>
            <span class="history-cam">${camLabel}</span>
            <span class="history-cat">${evt.category}</span>
            <span class="history-conf ${evt.severity}">
                ${evt.confidence}%
            </span>
        `;

        historyBody.appendChild(row);
    });
    
}

/********************************************************************
 * LOGS MODAL
 ********************************************************************/
let autoScrollLogs = true;

let accumulatedLogLines = [];

function mergeLogsIntoBuffer(logText) {
    const newLines = (logText || "").split("\n");

    if (accumulatedLogLines.length === 0) {
        accumulatedLogLines = newLines;
        return;
    }

    // Find overlap: suffix of accumulated that matches prefix of new
    const maxOverlap = Math.min(accumulatedLogLines.length, newLines.length);
    let overlap = 0;

    for (let k = maxOverlap; k > 0; k--) {
        let match = true;
        for (let i = 0; i < k; i++) {
            if (accumulatedLogLines[accumulatedLogLines.length - k + i] !== newLines[i]) {
                match = false;
                break;
            }
        }
        if (match) {
            overlap = k;
            break;
        }
    }

    accumulatedLogLines.push(...newLines.slice(overlap));
}

const logsModal = document.getElementById("logs-modal");
const logContent = document.getElementById("log-content");
const openLogsBtn = document.getElementById("open-logs-btn");
const closeLogsBtn = document.getElementById("close-logs-modal");

if (openLogsBtn && logsModal) {
    openLogsBtn.addEventListener("click", () => {
        logsModal.showModal();
        logsModal.classList.add("show");
        mainContent.classList.add("blurred");
    });
}

if (closeLogsBtn && logsModal) {
    closeLogsBtn.addEventListener("click", () => {
        logsModal.classList.remove("show");
        logsModal.close();
        mainContent.classList.remove("blurred");
    });
}

logsModal.addEventListener("cancel", (e) => {
    e.preventDefault();
    logsModal.close();
    mainContent.classList.remove("blurred");
});

const downloadLogsBtn = document.getElementById("download-logs-btn");

if (downloadLogsBtn) {
    downloadLogsBtn.addEventListener("click", () => {
        const text = accumulatedLogLines.join("\n");
        const blob = new Blob([text], { type: "text/plain" });
        const url = URL.createObjectURL(blob);

        const a = document.createElement("a");
        const ts = new Date().toISOString().replace(/[:.]/g, "-");
        a.href = url;
        a.download = `failure_logs_${ts}.log`;
        a.click();

        URL.revokeObjectURL(url);
    });
}

if (logContent) {
    logContent.addEventListener("scroll", () => {
        const atBottom =
            logContent.scrollHeight - logContent.scrollTop <= logContent.clientHeight + 5;
        autoScrollLogs = atBottom;
    });
}

function updateLogView(logText) {
    if (!logContent) return;

    const selection = window.getSelection();
    if (
        selection &&
        !selection.isCollapsed &&
        logContent.contains(selection.anchorNode)
    ) {
        return;
    }

    mergeLogsIntoBuffer(logText);
    logContent.textContent = logText || "";

    if (autoScrollLogs) {
        logContent.scrollTop = logContent.scrollHeight;
    }
}

// Poll failure history
setInterval(() => {
    if (
        historyModal &&
        historyModal.open &&
        (lastStatus === "monitoring" || lastStatus === "failure_detected")
    ) {
        fetchFailureHistory();
    }
}, 2000);

// Poll logs
setInterval(async () => {
    try {
        const res = await fetch("/api/logs");
        if (!res.ok) return;
        const data = await res.json();
        updateLogView(data.logs);
    } catch (err) {}
}, 1500);


/********************************************************************
 * Load settings at startup
 ********************************************************************/
setButtonState('start');
loadSettings();
updateStatus();