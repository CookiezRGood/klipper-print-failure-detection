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
let themeDirty = false;
let themeBackArmed = false;

const statusBadge = document.getElementById('status-indicator');

function setStatusBadgeState(state) {
    if (!statusBadge) return;
    statusBadge.classList.remove('status-idle', 'status-monitoring', 'status-failure');
    if (state === 'failure') statusBadge.classList.add('status-failure');
    else if (state === 'monitoring') statusBadge.classList.add('status-monitoring');
    else statusBadge.classList.add('status-idle');
}

const ssimText = document.getElementById('ssim-val');
const retryText = document.getElementById('retry-val');
const confidenceBar = document.getElementById('confidence-bar');
const forceStartBtn = document.getElementById('force-start-btn');
const maskToggleBtn = document.getElementById('mask-toggle-btn');
const settingsModal = document.getElementById('settings-modal');
const overlay = document.getElementById('settings-overlay');

// Theme UI
const openThemeBtn = document.getElementById('open-theme-btn');
const saveThemeBtn = document.getElementById('save-theme-btn');
const themeSaveStatus = document.getElementById('theme-save-status');
const backThemeBtn = document.getElementById('back-theme-btn');

let themePreviewPrev = { ui_theme: null, custom_theme: null };
let themeDirtyPreview = false;
let themeModalBound = false;

function getCssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function clearCustomThemeOverrides() {
    const keys = [
        "--bg-main", "--bg-card", "--bg-panel", "--bg-elevated", "--bg-input",
        "--accent", "--accent-soft", "--text-main", "--text-muted", "--text-soft", "--text-inverse",
        "--success", "--warning", "--warning-2", "--danger",
        "--border-subtle", "--border-strong",
        "--mask", "--mask-fill"
    ];
    keys.forEach(k => document.documentElement.style.removeProperty(k));
}

function applyCustomTheme(custom) {
    if (!custom || typeof custom !== "object") return;

    // Backgrounds
    if (custom.bg_main) document.documentElement.style.setProperty("--bg-main", custom.bg_main);
    if (custom.bg_card) document.documentElement.style.setProperty("--bg-card", custom.bg_card);
    if (custom.bg_panel) document.documentElement.style.setProperty("--bg-panel", custom.bg_panel);
    if (custom.bg_elevated) document.documentElement.style.setProperty("--bg-elevated", custom.bg_elevated);
    if (custom.bg_input) document.documentElement.style.setProperty("--bg-input", custom.bg_input);

    // Accents
    if (custom.accent) document.documentElement.style.setProperty("--accent", custom.accent);
    if (custom.accent_soft) document.documentElement.style.setProperty("--accent-soft", custom.accent_soft);

    // Text
    if (custom.text_main) document.documentElement.style.setProperty("--text-main", custom.text_main);
    if (custom.text_muted) document.documentElement.style.setProperty("--text-muted", custom.text_muted);
    if (custom.text_soft) document.documentElement.style.setProperty("--text-soft", custom.text_soft);
    if (custom.text_inverse) document.documentElement.style.setProperty("--text-inverse", custom.text_inverse);

    // Status colors
    if (custom.success) document.documentElement.style.setProperty("--success", custom.success);
    if (custom.warning) document.documentElement.style.setProperty("--warning", custom.warning);
    // Derive secondary warning automatically from primary warning
    const baseWarning = custom.warning || getCssVar("--warning") || "#fbc02d";
    const derivedWarn2 = deriveSecondaryWarning(baseWarning);
    if (derivedWarn2) document.documentElement.style.setProperty("--warning-2", derivedWarn2);
    if (custom.danger) document.documentElement.style.setProperty("--danger", custom.danger);

    // Borders
    if (custom.border_subtle) document.documentElement.style.setProperty("--border-subtle", custom.border_subtle);
    if (custom.border_strong) document.documentElement.style.setProperty("--border-strong", custom.border_strong);

    // Mask
    if (custom.mask) {
        document.documentElement.style.setProperty("--mask", custom.mask);
        if (!custom.mask_fill) {
            document.documentElement.style.setProperty("--mask-fill", hexToRgba(custom.mask, 0.20));
        }
    }
    if (custom.mask_fill) document.documentElement.style.setProperty("--mask-fill", custom.mask_fill);
}

function updateThemeUnsavedWarning() {
    const warn = document.getElementById("theme-unsaved-warning");
    if (warn) {
        warn.style.display = themeDirty ? "block" : "none";
    }
}

function updateAiUnsavedWarning() {
    const warn = document.getElementById("ai-unsaved-warning");
    if (warn) {
        warn.style.display = aiDirty ? "block" : "none";
    }
}

function updateSettingsUnsavedWarning() {
    const warn = document.getElementById("settings-page-unsaved-warning");
    if (warn) {
        if (settingsDirty && settingsCloseArmed) {
            warn.textContent = "⚠ Unsaved changes";
            warn.style.display = "inline";
        } else {
            warn.textContent = "";
            warn.style.display = "none";
        }
    }
}

function revertTheme() {
    // Revert theme to the saved state (stored in themePreviewPrev)
    if (themePreviewPrev.ui_theme) {
        const saved = themePreviewPrev.ui_theme;
        const custom = themePreviewPrev.custom_theme || {};
        if (saved === "custom") {
            setTheme("custom", custom);
        } else {
            setTheme(saved, null);
        }
    }
}

function setTheme(themeName, customTheme = null) {
    const base = themeName === "custom" ? "dark" : themeName;

    document.documentElement.dataset.theme = base || "dark";
    clearCustomThemeOverrides();

    if (themeName === "custom") {
        applyCustomTheme(customTheme || {});
    }
}

function hexToRgba(hex, alpha) {
    if (!hex) return "";
    const h = hex.replace("#", "").trim();
    if (h.length !== 6) return "";
    const r = parseInt(h.slice(0,2), 16);
    const g = parseInt(h.slice(2,4), 16);
    const b = parseInt(h.slice(4,6), 16);
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

// Color derivation utilities
function hexToRgb(hex) {
    const h = hex.replace("#", "").trim();
    if (h.length !== 6) return null;
    return {
        r: parseInt(h.slice(0,2), 16),
        g: parseInt(h.slice(2,4), 16),
        b: parseInt(h.slice(4,6), 16)
    };
}

function rgbToHex(r, g, b) {
    return "#" + [r, g, b].map(x => {
        const hex = Math.round(Math.max(0, Math.min(255, x))).toString(16);
        return hex.length === 1 ? "0" + hex : hex;
    }).join("");
}

function adjustBrightness(hex, factor) {
    const rgb = hexToRgb(hex);
    if (!rgb) return hex;
    return rgbToHex(rgb.r * factor, rgb.g * factor, rgb.b * factor);
}

function blendWithGray(hex, grayAmount) {
    const rgb = hexToRgb(hex);
    if (!rgb) return hex;
    const gray = (rgb.r + rgb.g + rgb.b) / 3;
    return rgbToHex(
        rgb.r * (1 - grayAmount) + gray * grayAmount,
        rgb.g * (1 - grayAmount) + gray * grayAmount,
        rgb.b * (1 - grayAmount) + gray * grayAmount
    );
}

// Auto-derive text-muted and text-soft from text-main
function deriveTextColors(textMain) {
    return {
        muted: blendWithGray(textMain, 0.35),
        soft: blendWithGray(textMain, 0.20)
    };
}

// Auto-derive accent-soft from accent
function deriveAccentSoft(accent) {
    return adjustBrightness(accent, 1.25);
}

// Auto-derive secondary warning (slightly darker than primary warning)
function deriveSecondaryWarning(warning) {
    if (!warning) return "";
    return adjustBrightness(warning, 0.9);
}

function getThemeChoiceFromUI() {
    const checked = document.querySelector('input[name="theme-choice"]:checked');
    return checked ? checked.value : "dark";
}

function getCustomThemeFromUI() {
    const bgMain = document.getElementById("custom-bg-main")?.value;
    const bgCard = document.getElementById("custom-bg-card")?.value;
    const bgPanel = document.getElementById("custom-bg-panel")?.value;
    const bgElevated = document.getElementById("custom-bg-elevated")?.value;
    const bgInput = document.getElementById("custom-bg-input")?.value;
    const accent = document.getElementById("custom-accent")?.value;
    const accentSoft = document.getElementById("custom-accent-soft")?.value;
    const textMain = document.getElementById("custom-text-main")?.value;
    const textMuted = document.getElementById("custom-text-muted")?.value;
    const textSoft = document.getElementById("custom-text-soft")?.value;
    const textInverse = document.getElementById("custom-text-inverse")?.value;
    const btnPrimaryText = document.getElementById("custom-btn-primary-text")?.value;
    const btnSecondaryText = document.getElementById("custom-btn-secondary-text")?.value;
    const success = document.getElementById("custom-success")?.value;
    const warning = document.getElementById("custom-warning")?.value;
    const danger = document.getElementById("custom-danger")?.value;
    const borderSubtle = document.getElementById("custom-border-subtle")?.value;
    const borderStrong = document.getElementById("custom-border-strong")?.value;
    const mask = document.getElementById("custom-mask")?.value;

    return {
        bg_main: bgMain,
        bg_card: bgCard,
        bg_panel: bgPanel,
        bg_elevated: bgElevated,
        bg_input: bgInput,
        accent,
        accent_soft: accentSoft,
        text_main: textMain,
        text_muted: textMuted,
        text_soft: textSoft,
        text_inverse: textInverse,
        btn_primary_text: btnPrimaryText,
        btn_secondary_text: btnSecondaryText,
        success,
        warning,
        danger,
        border_subtle: borderSubtle,
        border_strong: borderStrong,
        mask,
        mask_fill: hexToRgba(mask, 0.20)
    };
}

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
        showToast("Masks cleared");
    });
}
if (cam2ClearBtn) {
    cam2ClearBtn.addEventListener('click', () => {
        maskZones[1] = [];
        syncMasksToServer();
        showToast("Masks cleared");
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

        const maskParam = isMaskVisible ? `&mask_color=${encodeURIComponent(getCssVar('--mask'))}` : '';
        cam1Img.src = cam1Card.classList.contains('disabled') ? "" : `/api/frame/0?cache_bust=${now}${maskParam}`;
        cam2Img.src = cam2Card.classList.contains('disabled') ? "" : `/api/frame/1?cache_bust=${now}${maskParam}`;

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
            setStatusBadgeState('failure');
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
            setStatusBadgeState('monitoring');
            document.getElementById("status-text").innerText = statusTxt;
            document.getElementById("status-tooltip").classList.add("hidden");
            setButtonState('stop');
        } else {
            setStatusBadgeState('idle');
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
                confidenceBar.style.backgroundColor = getCssVar("--health-green");
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

            // Compute color (theme-driven)
            let barVar;

            if (failPct >= failT) {
                barVar = "--health-red";
            } else {
                const range = failT - warnT;
                const relative = range > 0 ? (failPct - warnT) / range : 0;

                if (relative < 0) barVar = "--health-green";
                else if (relative < 0.33) barVar = "--health-green";
                else if (relative < 0.66) barVar = "--health-yellow";
                else barVar = "--health-orange";
            }

            const barColor = getCssVar(barVar) || getCssVar("--health-green");
            confidenceBar.style.backgroundColor = barColor;

            const health = document.querySelector('.health-section');

            // Clear glow states
            health.classList.remove("glow-green", "glow-yellow", "glow-red");

            // Apply glow based on state bucket
            if (barVar === "--health-red") {
                health.classList.add("glow-red");
            } else if (barVar === "--health-yellow" || barVar === "--health-orange") {
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

    maskToggleBtn.classList.toggle('is-active', isMaskVisible);
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
            border:`1px solid ${getCssVar('--mask')}`,
            backgroundColor:getCssVar('--mask-fill') || 'rgba(255,0,255,0.20)',
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

        // Apply UI theme early
        setTheme(currentSettings.ui_theme || "dark", currentSettings.custom_theme || {});


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

    // Clear all page-specific warnings
    const settingsWarn = document.getElementById("settings-page-unsaved-warning");
    if (settingsWarn) {
        settingsWarn.textContent = "⚠ Unsaved changes";
        settingsWarn.style.display = "none";
    }

    const themeWarn = document.getElementById("theme-unsaved-warning");
    if (themeWarn) {
        themeWarn.textContent = "⚠ Unsaved changes";
        themeWarn.style.display = "none";
    }

    const aiWarn = document.getElementById("ai-unsaved-warning");
    if (aiWarn) {
        aiWarn.textContent = "⚠ Unsaved changes";
        aiWarn.style.display = "none";
    }

    settingsDirty = false;
    settingsCloseArmed = false;

    // Only load settings if we're opening the modal fresh (no pages are currently shown)
    // This preserves unsaved changes when switching between pages
    const isFirstOpen = !settingsPages.classList.contains("show-theme") && 
                        !settingsPages.classList.contains("show-ai");
    if (isFirstOpen) {
        loadSettings();
    }

    // Mark dirty only for main settings page inputs (not theme or AI pages)
    const settingsPage = document.getElementById("settings-page");
    if (settingsPage) {
        settingsPage.querySelectorAll("input, select").forEach(el => {
            el.addEventListener("change", () => {
                settingsDirty = true;
                // Reset X priming and hide warning if it was showing
                if (settingsCloseArmed) {
                    const settingsWarn = document.getElementById("settings-page-unsaved-warning");
                    if (settingsWarn) {
                        settingsWarn.textContent = "";
                        settingsWarn.style.display = "none";
                    }
                }
                settingsCloseArmed = false;
            });
            el.addEventListener("input", () => {
                settingsDirty = true;
                // Reset X priming and hide warning if it was showing
                if (settingsCloseArmed) {
                    const settingsWarn = document.getElementById("settings-page-unsaved-warning");
                    if (settingsWarn) {
                        settingsWarn.textContent = "";
                        settingsWarn.style.display = "none";
                    }
                }
                settingsCloseArmed = false;
            });
        });
    }

    settingsPages.classList.remove("show-ai", "show-theme");
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
    settingsCloseArmed = false; // reset close priming on page switch
    updateSettingsUnsavedWarning(); // clear main settings warning if showing
    
    const aiStatus = document.getElementById("category-save-status");
    const aiErr = document.getElementById("category-error-text");
    if (aiStatus) {
        aiStatus.textContent = "";
        aiStatus.className = "save-status";
    }
    if (aiErr) aiErr.textContent = "";

    aiDirty = false;
    aiBackArmed = false;

    // Reload AI form fields from saved settings to ensure clean state
    const cats = currentSettings.ai_categories || {};
    document.getElementById("cat_spaghetti_enabled").checked = cats.spaghetti?.enabled ?? true;
    document.getElementById("cat_spaghetti_trigger").checked = cats.spaghetti?.trigger ?? true;
    document.getElementById("cat_spaghetti_detect_threshold").value = Math.round((cats.spaghetti?.detect_threshold ?? 0.3) * 100);
    document.getElementById("cat_spaghetti_trigger_threshold").value = Math.round((cats.spaghetti?.trigger_threshold ?? 0.7) * 100);
    
    document.getElementById("cat_blob_enabled").checked = cats.blob?.enabled ?? true;
    document.getElementById("cat_blob_trigger").checked = cats.blob?.trigger ?? false;
    document.getElementById("cat_blob_detect_threshold").value = Math.round((cats.blob?.detect_threshold ?? 0.3) * 100);
    document.getElementById("cat_blob_trigger_threshold").value = Math.round((cats.blob?.trigger_threshold ?? 0.7) * 100);
    
    document.getElementById("cat_crack_enabled").checked = cats.crack?.enabled ?? true;
    document.getElementById("cat_crack_trigger").checked = cats.crack?.trigger ?? true;
    document.getElementById("cat_crack_detect_threshold").value = Math.round((cats.crack?.detect_threshold ?? 0.3) * 100);
    document.getElementById("cat_crack_trigger_threshold").value = Math.round((cats.crack?.trigger_threshold ?? 0.7) * 100);
    
    document.getElementById("cat_warping_enabled").checked = cats.warping?.enabled ?? true;
    document.getElementById("cat_warping_trigger").checked = cats.warping?.trigger ?? true;
    document.getElementById("cat_warping_detect_threshold").value = Math.round((cats.warping?.detect_threshold ?? 0.3) * 100);
    document.getElementById("cat_warping_trigger_threshold").value = Math.round((cats.warping?.trigger_threshold ?? 0.7) * 100);

    const aiWarn = document.getElementById("ai-unsaved-warning");
    if (aiWarn) { aiWarn.textContent = ""; aiWarn.style.display = "none"; }

    const aiPage = document.getElementById("ai-page");
    if (aiPage) {
        aiPage.querySelectorAll("input, select").forEach(el => {
            el.addEventListener("change", () => {
                aiDirty = true;
                // Reset Back and X priming, hide warning if it was showing
                if (aiBackArmed || settingsCloseArmed) {
                    const aiWarn = document.getElementById("ai-unsaved-warning");
                    if (aiWarn) {
                        aiWarn.textContent = "";
                        aiWarn.style.display = "none";
                    }
                }
                aiBackArmed = false;
                settingsCloseArmed = false;
            });
            el.addEventListener("input", () => {
                aiDirty = true;
                // Reset Back and X priming, hide warning if it was showing
                if (aiBackArmed || settingsCloseArmed) {
                    const aiWarn = document.getElementById("ai-unsaved-warning");
                    if (aiWarn) {
                        aiWarn.textContent = "";
                        aiWarn.style.display = "none";
                    }
                }
                aiBackArmed = false;
                settingsCloseArmed = false;
            });
        });
    }

    settingsPages.classList.add("show-ai");
});

// Go back to main settings page
backAiBtn.addEventListener("click", () => {
    settingsCloseArmed = false; // reset X priming when hitting Back
    const aiWarn = document.getElementById("ai-unsaved-warning");
    if (aiDirty && !aiBackArmed) {
        if (aiWarn) {
            aiWarn.textContent = "⚠ You have unsaved changes. Click Back again to discard.";
            aiWarn.style.display = "inline";
        }
        aiBackArmed = true;
        return;
    }
    // Second click (or not dirty): hide warning, reload to revert changes, and go back
    if (aiWarn) {
        aiWarn.textContent = "";
        aiWarn.style.display = "none";
    }
    aiDirty = false;
    aiBackArmed = false;
    updateAiUnsavedWarning();

    settingsPages.classList.remove("show-ai");
});

document.getElementById('close-modal-x').addEventListener('click', () => {
    // Determine which page is active
    const themePageActive = settingsPages.classList.contains("show-theme");
    const aiPageActive = settingsPages.classList.contains("show-ai");
    
    const themeWarn = document.getElementById("theme-unsaved-warning");
    const aiWarn = document.getElementById("ai-unsaved-warning");
    const settingsWarn = document.getElementById("settings-page-unsaved-warning");

    // Check if ANY page has unsaved changes
    const hasUnsavedChanges = settingsDirty || themeDirty || aiDirty;

    // Show warning if there are unsaved changes and we haven't already armed
    if (hasUnsavedChanges && !settingsCloseArmed) {
        // Show warning on the currently active page
        if (themePageActive && themeWarn) {
            themeWarn.textContent = "⚠ You have unsaved changes. Click × again to discard.";
            themeWarn.style.display = "inline";
        } else if (aiPageActive && aiWarn) {
            aiWarn.textContent = "⚠ You have unsaved changes. Click × again to discard.";
            aiWarn.style.display = "inline";
        } else if (settingsWarn) {
            settingsWarn.textContent = "⚠ You have unsaved changes. Click × again to discard.";
            settingsWarn.style.display = "inline";
        }
        settingsCloseArmed = true;
        return;
    }

    // Revert theme if it was dirty before closing
    if (themeDirty) {
        revertTheme();
    }

    // Clear all dirty flags, priming, and warnings
    settingsDirty = false;
    themeDirty = false;
    aiDirty = false;
    settingsCloseArmed = false;
    aiBackArmed = false;
    themeBackArmed = false;

    if (settingsWarn) {
        settingsWarn.textContent = "";
        settingsWarn.style.display = "none";
    }
    if (themeWarn) {
        themeWarn.textContent = "";
        themeWarn.style.display = "none";
    }
    if (aiWarn) {
        aiWarn.textContent = "";
        aiWarn.style.display = "none";
    }

    settingsModal.classList.remove('show');
    settingsPages.classList.remove("show-ai", "show-theme");
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
    aiDirty = false;
    aiBackArmed = false;
    themeDirty = false;
    themeBackArmed = false;

    const settingsWarn = document.getElementById("settings-page-unsaved-warning");
    if (settingsWarn) {
        settingsWarn.textContent = "";
        settingsWarn.style.display = "none";
    }

    const themeWarn = document.getElementById("theme-unsaved-warning");
    if (themeWarn) {
        themeWarn.textContent = "";
        themeWarn.style.display = "none";
    }

    const aiWarn = document.getElementById("ai-unsaved-warning");
    if (aiWarn) {
        aiWarn.textContent = "";
        aiWarn.style.display = "none";
    }

    // Revert theme preview if not saved
    if (themePreviewPrev.ui_theme) {
        const saved = themePreviewPrev.ui_theme;
        const custom = themePreviewPrev.custom_theme || {};
        if (saved === "custom") {
            setTheme("custom", custom);
        } else {
            setTheme(saved, null);
        }
    }
    
    overlay.classList.remove('active');
    mainContent.classList.remove('blurred');
});

/********************************************************************
 * Theme Page (inside Settings modal) — live preview + save
 ********************************************************************/
function syncThemeModalUIFromSettings() {
    const themeName = (currentSettings && currentSettings.ui_theme) ? currentSettings.ui_theme : "dark";
    const custom = (currentSettings && currentSettings.custom_theme) ? currentSettings.custom_theme : {};

    // Track what to revert to if user backs out
    themePreviewPrev.ui_theme = themeName;
    themePreviewPrev.custom_theme = custom;
    themeDirtyPreview = false;

    // Check correct radio
    const radio = document.querySelector(`input[name="theme-choice"][value="${themeName}"]`);
    if (radio) radio.checked = true;

    // Populate custom pickers
    const useDarkDefaults = !custom || Object.keys(custom).length === 0;
    const setVal = (id, v) => {
        const el = document.getElementById(id);
        if (el && v) el.value = v;
    };

    const pick = (value, cssVarName, darkDefault) => value || (useDarkDefaults ? darkDefault : (getCssVar(cssVarName) || darkDefault));

    setVal("custom-bg-main", pick(custom.bg_main, "--bg-main", "#0d0d0d"));
    setVal("custom-bg-card", pick(custom.bg_card, "--bg-card", "#1b1b1b"));
    setVal("custom-bg-panel", pick(custom.bg_panel, "--bg-panel", "#1a1a1a"));
    setVal("custom-bg-elevated", pick(custom.bg_elevated, "--bg-elevated", "#181818"));
    setVal("custom-bg-input", pick(custom.bg_input, "--bg-input", "#111111"));
    setVal("custom-accent", pick(custom.accent, "--accent", "#2196F3"));
    setVal("custom-accent-soft", pick(custom.accent_soft, "--accent-soft", "#64b5f6"));
    setVal("custom-text-main", pick(custom.text_main, "--text-main", "#f5f5f5"));
    setVal("custom-text-muted", pick(custom.text_muted, "--text-muted", "#aaaaaa"));
    setVal("custom-text-soft", pick(custom.text_soft, "--text-soft", "#bbbbbb"));
    setVal("custom-text-inverse", pick(custom.text_inverse, "--text-inverse", "#111111"));
    setVal("custom-btn-primary-text", pick(custom.btn_primary_text, "--btn-primary-text", "#f5f5f5"));
    setVal("custom-btn-secondary-text", pick(custom.btn_secondary_text, "--btn-secondary-text", "#f5f5f5"));
    setVal("custom-success", pick(custom.success, "--success", "#43a047"));
    setVal("custom-warning", pick(custom.warning, "--warning", "#fbc02d"));
    setVal("custom-danger", pick(custom.danger, "--danger", "#e53935"));
    setVal("custom-border-subtle", pick(custom.border_subtle, "--border-subtle", "#333333"));
    setVal("custom-border-strong", pick(custom.border_strong, "--border-strong", "#555555"));
    setVal("custom-mask", pick(custom.mask, "--mask", "#ff00ff"));

    if (themeSaveStatus) {
        themeSaveStatus.textContent = "";
        themeSaveStatus.className = "save-status";
    }
}

function applyThemeChoiceFromUI() {
    const choice = getThemeChoiceFromUI();
    themeDirty = true;
    themeDirtyPreview = true;
    
    // Reset X and Back priming and hide warning if it was showing
    if (settingsCloseArmed || themeBackArmed) {
        const themeWarn = document.getElementById("theme-unsaved-warning");
        if (themeWarn) {
            themeWarn.textContent = "";
            themeWarn.style.display = "none";
        }
    }
    settingsCloseArmed = false;
    themeBackArmed = false;

    if (choice === "custom") {
        const custom = getCustomThemeFromUI();
        setTheme("custom", custom);
    } else {
        setTheme(choice, null);
    }
}

function bindThemeModalLivePreview() {
    if (themeModalBound) return;
    themeModalBound = true;

    // Clicking a theme card selects + previews it
    document.querySelectorAll(".theme-card").forEach(card => {
        card.addEventListener("click", () => {
            const choice = card.dataset.themeChoice;
            if (!choice) return;

            const radio = card.querySelector(`input[name="theme-choice"][value="${choice}"]`);
            if (radio) radio.checked = true;

            applyThemeChoiceFromUI();
        });
    });

    // Live preview custom fields
    const customIds = [
        "custom-bg-main",
        "custom-bg-card",
        "custom-bg-panel",
        "custom-bg-elevated",
        "custom-bg-input",
        "custom-accent",
        "custom-accent-soft",
        "custom-text-main",
        "custom-text-muted",
        "custom-text-soft",
        "custom-text-inverse",
        "custom-btn-primary-text",
        "custom-btn-secondary-text",
        "custom-success",
        "custom-warning",
        "custom-danger",
        "custom-border-subtle",
        "custom-border-strong",
        "custom-mask",
    ];

    customIds.forEach(id => {
        const el = document.getElementById(id);
        if (!el) return;
        el.addEventListener("input", () => {
            const customRadio = document.querySelector(`input[name="theme-choice"][value="custom"]`);
            if (customRadio) customRadio.checked = true;

            applyThemeChoiceFromUI();
        });
    });

    // Apply theme immediately when selecting a radio option (including Custom)
    document.querySelectorAll('input[name="theme-choice"]').forEach(r => {
        r.addEventListener('change', () => {
            applyThemeChoiceFromUI();
        });
    });

    // Make clicking the custom panel itself select and apply the custom theme
    const customPanel = document.querySelector('.custom-theme-panel');
    if (customPanel) {
        customPanel.addEventListener('click', (e) => {
            const radio = document.querySelector('input[name="theme-choice"][value="custom"]');
            if (radio) radio.checked = true;
            applyThemeChoiceFromUI();
        });
    }

    // Add section toggle functionality
    document.querySelectorAll(".section-toggle").forEach(btn => {
        btn.addEventListener("click", (e) => {
            e.stopPropagation();
            const targetId = btn.dataset.target;
            const targetBody = document.getElementById(targetId);
            if (targetBody) {
                targetBody.classList.toggle("collapsed");
                btn.textContent = targetBody.classList.contains("collapsed") ? "▶" : "▼";
            }
        });
    });

    // Initialize toggle arrows to reflect current collapsed state
    document.querySelectorAll(".section-toggle").forEach(btn => {
        const targetId = btn.dataset.target;
        const targetBody = document.getElementById(targetId);
        if (targetBody) {
            btn.textContent = targetBody.classList.contains("collapsed") ? "▶" : "▼";
        }
    });

    // Also toggle on header click
    document.querySelectorAll(".custom-section-header").forEach(header => {
        header.addEventListener("click", () => {
            const btn = header.querySelector(".section-toggle");
            if (btn) btn.click();
        });
    });

    // Auto-derive text-muted and text-soft from text-main
    const textMainInput = document.getElementById("custom-text-main");
    const textMutedInput = document.getElementById("custom-text-muted");
    const textSoftInput = document.getElementById("custom-text-soft");

    if (textMainInput && textMutedInput && textSoftInput) {
        textMainInput.addEventListener("input", () => {
            const derived = deriveTextColors(textMainInput.value);
            textMutedInput.value = derived.muted;
            textSoftInput.value = derived.soft;
        });
    }

    // Auto-derive accent-soft from accent
    const accentInput = document.getElementById("custom-accent");
    const accentSoftInput = document.getElementById("custom-accent-soft");

    if (accentInput && accentSoftInput) {
        accentInput.addEventListener("input", () => {
            accentSoftInput.value = deriveAccentSoft(accentInput.value);
        });
    }
}

function openThemePage() {
    syncThemeModalUIFromSettings();
    bindThemeModalLivePreview();

    // Ensure AI page isn't active
    settingsPages.classList.remove("show-ai");
    settingsCloseArmed = false; // reset close priming on page switch
    updateSettingsUnsavedWarning(); // clear main settings warning if showing

    // Hide any lingering theme warning
    const themeWarn = document.getElementById("theme-unsaved-warning");
    if (themeWarn) { themeWarn.textContent = ""; themeWarn.style.display = "none"; }

    // Slide to Theme page
    settingsPages.classList.add("show-theme");
}

function closeThemePage(revert = true) {
    // Revert if user backed out without saving
    if (revert && (themeDirtyPreview || themeDirty)) {
        const prevTheme = themePreviewPrev.ui_theme || "dark";
        const prevCustom = themePreviewPrev.custom_theme || {};
        setTheme(prevTheme, prevCustom);
    }

    themeDirtyPreview = false;
    themeDirty = false;
    updateThemeUnsavedWarning();

    // Clear save status
    if (themeSaveStatus) {
        themeSaveStatus.textContent = "";
        themeSaveStatus.className = "save-status";
    }

    // Return to main settings page
    settingsPages.classList.remove("show-theme");
}

if (openThemeBtn) {
    openThemeBtn.addEventListener("click", openThemePage);
}

if (backThemeBtn) {
    backThemeBtn.addEventListener("click", () => {
        settingsCloseArmed = false; // reset X priming when hitting Back
        const themeWarn = document.getElementById("theme-unsaved-warning");
        if (themeDirty && !themeBackArmed) {
            if (themeWarn) {
                themeWarn.textContent = "⚠ You have unsaved changes. Click Back again to discard.";
                themeWarn.style.display = "inline";
            }
            themeBackArmed = true;
            return;
        }
        // Second click (or not dirty): hide warning, revert preview and go back
        if (themeWarn) {
            themeWarn.textContent = "";
            themeWarn.style.display = "none";
        }
        closeThemePage(true);
        themeBackArmed = false;
    });
}

if (saveThemeBtn) {
    saveThemeBtn.addEventListener("click", async () => {
        const choice = getThemeChoiceFromUI();

        currentSettings.ui_theme = choice;

        currentSettings.custom_theme = getCustomThemeFromUI();

        // Immediately clear unsaved warning so it's obvious we saved
        themeDirtyPreview = false;
        themeDirty = false;
        updateThemeUnsavedWarning();

        try {
            await fetch('/api/settings', {
                method:'POST',
                headers:{'Content-Type':'application/json'},
                body:JSON.stringify(currentSettings)
            });

            // Update revert baseline to the newly saved theme
            themePreviewPrev.ui_theme = currentSettings.ui_theme;
            themePreviewPrev.custom_theme = currentSettings.custom_theme;

            if (themeSaveStatus) {
                themeSaveStatus.textContent = "Saved ✓";
                themeSaveStatus.className = "save-status success";
            }

            // Return to main settings page after saving
            setTimeout(() => {
                closeThemePage(false);
            }, 600);
            
            // Auto-hide the saved text after a moment (fixes your “stays forever” issue)
            setTimeout(() => {
                if (themeSaveStatus) {
                    themeSaveStatus.textContent = "";
                    themeSaveStatus.className = "save-status";
                }
            }, 1200);

        } catch (err) {
            if (themeSaveStatus) {
                themeSaveStatus.textContent = "Save failed";
                themeSaveStatus.className = "save-status error";
            }
        }
    });
}

/********************************************************************
 * Preview mode (pure preview)
 ********************************************************************/
const previewBtn = document.getElementById("preview-theme-btn");
const previewDock = document.getElementById("theme-preview-dock");
const exitPreviewBtn = document.getElementById("exit-preview-btn");

let previewReturnToThemePage = false;

function enterPurePreview() {
    // We only support preview from the Theme page
    previewReturnToThemePage = settingsPages.classList.contains("show-theme");

    // Close settings modal entirely so dashboard is visible
    if (settingsModal?.open) {
        settingsModal.classList.remove("show");
        settingsModal.close();
    }

    // Remove overlay + blur
    overlay?.classList.remove("active");
    mainContent?.classList.remove("blurred");

    // Show dock on dashboard
    previewDock?.classList.remove("hidden");

    // Pure preview: block dashboard interaction
    document.body.classList.add("theme-preview-active");
}

function exitPurePreview() {
    previewDock?.classList.add("hidden");
    document.body.classList.remove("theme-preview-active");

    // If a theme was changed during preview, mark it as dirty
    if (themeDirtyPreview) {
        themeDirty = true;
        themeDirtyPreview = false;
        updateThemeUnsavedWarning();
    }

    // Return to settings modal, back on Theme page
    settingsModal?.showModal();
    settingsModal?.classList.add("show");
    overlay?.classList.add("active");
    mainContent?.classList.add("blurred");

    settingsPages.classList.remove("show-ai");
    settingsPages.classList.toggle("show-theme", !!previewReturnToThemePage);
}

if (previewBtn && previewDock) {
    previewBtn.addEventListener("click", enterPurePreview);
}

if (exitPreviewBtn) {
    exitPreviewBtn.addEventListener("click", exitPurePreview);
}

// Dock theme clicks
document.querySelectorAll(".preview-theme").forEach(el => {
    el.addEventListener("click", () => {
        const theme = el.dataset.theme;
        if (!theme) return;

        // Also update radio selection (when user returns)
        const radio = document.querySelector(`input[name="theme-choice"][value="${theme}"]`);
        if (radio) radio.checked = true;

        if (theme === "custom") {
            setTheme("custom", currentSettings.custom_theme || getCustomThemeFromUI());
        } else {
            setTheme(theme, null);
        }

        themeDirtyPreview = true;
    });
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
    // Immediately hide unsaved warnings to reflect that we're saving now
    settingsDirty = false;
    aiDirty = false;
    updateSettingsUnsavedWarning();
    updateAiUnsavedWarning();

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

    // Clear dirty state for main settings page
    settingsDirty = false;
    updateSettingsUnsavedWarning();

    const statusEl = document.getElementById("settings-save-status");
    if (statusEl) {
        statusEl.textContent = "Saved ✓";
        statusEl.className = "save-status success";
    }
    
    setTimeout(() => {
        const statusEl2 = document.getElementById("settings-save-status");
        if (statusEl2) {
            statusEl2.textContent = "";
            statusEl2.className = "save-status";
        }
    }, 700);
    
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
        ["Warping", "cat_warping_detect_threshold", "cat_warping_trigger_threshold"],
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
setStatusBadgeState('idle');
bindThemeModalLivePreview();
loadSettings();
updateStatus();