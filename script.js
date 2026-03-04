// --- Theme Switcher ---
const themes = ['blue', 'dark', 'light'];
const themeConfig = {
    blue: { icon: '🔵', label: 'Blue' },
    dark: { icon: '🌑', label: 'Dark' },
    light: { icon: '☀️', label: 'Light' }
};

function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);
    const iconEl = document.getElementById('themeIcon');
    const labelEl = document.getElementById('themeLabel');
    if (iconEl && labelEl) {
        iconEl.textContent = themeConfig[theme].icon;
        labelEl.textContent = themeConfig[theme].label;
    }
}

function cycleTheme() {
    const current = localStorage.getItem('theme') || 'blue';
    const idx = themes.indexOf(current);
    const next = themes[(idx + 1) % themes.length];
    applyTheme(next);
}

// Apply saved theme on load (before paint)
applyTheme(localStorage.getItem('theme') || 'blue');

// DOM Elements
const clockElement = document.getElementById('clock');
const logContainer = document.getElementById('log-container');
const attendanceBody = document.getElementById('attendance-body');
const serverStatus = document.getElementById('server-status');

// Auth Check & Admin Name Display
fetch('/api/check_auth').then(res => res.json()).then(data => {
    if (!data.authenticated) {
        window.location.href = 'login.html';
    } else {
        // Update Admin Name Display
        const adminNameEl = document.getElementById('adminNameDisplay');
        if (adminNameEl) {
            const displayName = data.full_name || data.user || 'Administrator';
            adminNameEl.textContent = `Welcome, ${displayName}`;
        }
    }
}).catch(() => window.location.href = 'login.html');

// Logout
const logoutBtn = document.getElementById('logoutBtn');
if (logoutBtn) {
    logoutBtn.addEventListener('click', async (e) => {
        e.preventDefault();
        await fetch('/api/logout', { method: 'POST' });
        window.location.href = 'login.html';
    });

}

// Profile Edit Logic
const profileBtn = document.getElementById('profileBtn');
const profileModal = document.getElementById('profileModal');
const profileForm = document.getElementById('profileForm');

if (profileBtn) {
    profileBtn.addEventListener('click', async (e) => {
        e.preventDefault();

        // Fetch current details
        try {
            const res = await fetch('/api/check_auth');
            const data = await res.json();

            if (data.authenticated) {
                const details = data.details || {};

                // Populate Form
                profileForm.elements['full_name'].value = details.full_name || '';
                profileForm.elements['email'].value = details.email || '';
                profileForm.elements['phone'].value = details.phone || '';
                profileForm.elements['staff_id'].value = details.staff_id || '';
                profileForm.elements['age'].value = details.age || '';

                profileModal.style.display = 'block';
            }
        } catch (err) {
            console.error(err);
            Swal.fire('Error', 'Failed to load profile details.', 'error');
        }
    });
}

if (profileForm) {
    profileForm.addEventListener('submit', async (e) => {
        e.preventDefault();

        const formData = new FormData(profileForm);
        const jsonData = Object.fromEntries(formData.entries());

        // 1. Handle Password Change (if requested)
        const currentPass = jsonData['current_password'];
        const newPass = jsonData['new_password'];

        if (newPass) {
            if (!currentPass) {
                return Swal.fire('Error', 'Current password is required to set a new password.', 'warning');
            }

            try {
                const passRes = await fetch('/api/change_password', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        username: 'admin', // Current user
                        temp_password: currentPass,
                        new_password: newPass
                    })
                });

                const passData = await passRes.json();

                if (!passRes.ok) {
                    return Swal.fire('Error', passData.error || 'Failed to change password.', 'error');
                }
            } catch (err) {
                return Swal.fire('Error', 'Connection error during password change.', 'error');
            }
        }

        // Admin username is 'admin'
        try {
            const res = await fetch('/api/staff/admin', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(jsonData)
            });

            if (res.ok) {
                await Swal.fire('Success', 'Profile updated successfully.', 'success');
                profileModal.style.display = 'none';
            } else {
                Swal.fire('Error', 'Failed to update profile.', 'error');
            }
        } catch (err) {
            Swal.fire('Error', 'Connection error.', 'error');
        }
    });
}

// Global Admin Functions (Defined early)
window.updateLeave = async (id, status) => {
    // SweetAlert2 Confirmation
    const result = await Swal.fire({
        title: `Confirm ${status}?`,
        text: `Are you sure you want to ${status.toLowerCase()} this request?`,
        icon: status === 'Approved' ? 'question' : 'warning',
        showCancelButton: true,
        confirmButtonColor: status === 'Approved' ? '#10b981' : '#ef4444',
        cancelButtonColor: '#3085d6',
        confirmButtonText: `Yes, ${status}!`
    });

    if (!result.isConfirmed) return;

    try {
        const res = await fetch(`/api/leave/${id}/status`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status })
        });

        if (res.ok) {
            Swal.fire({
                title: 'Success!',
                text: `Request ${status}.`,
                icon: 'success',
                timer: 1500,
                showConfirmButton: false
            });
            loadAdminLeaves(); // Refresh list
        } else {
            throw new Error('Server returned error');
        }
    } catch (e) {
        Swal.fire('Error', 'Action failed. Check server logs.', 'error');
    }
};

// ... (Clock and Socket Config remains same) ...

// Admin: Load Leave Requests
let allLeaves = []; // Store all leaves for filtering
let currentLeaveFilter = 'Pending';

async function loadAdminLeaves() {
    const tableBody = document.getElementById('admin-leave-body');
    if (!tableBody) return; // Not on admin page

    try {
        const res = await fetch('/api/leave');
        allLeaves = await res.json();

        // Update count badges
        const pendingCount = allLeaves.filter(l => l.status === 'Pending').length;
        const approvedCount = allLeaves.filter(l => l.status === 'Approved').length;
        const rejectedCount = allLeaves.filter(l => l.status === 'Rejected').length;

        const pendingEl = document.getElementById('leavePendingCount');
        const approvedEl = document.getElementById('leaveApprovedCount');
        const rejectedEl = document.getElementById('leaveRejectedCount');
        if (pendingEl) pendingEl.textContent = pendingCount;
        if (approvedEl) approvedEl.textContent = approvedCount;
        if (rejectedEl) rejectedEl.textContent = rejectedCount;

        // Render with current filter
        filterLeaves(currentLeaveFilter);
    } catch (e) {
        console.error("Error loading leaves", e);
    }
}

function filterLeaves(status) {
    currentLeaveFilter = status;
    const tableBody = document.getElementById('admin-leave-body');
    if (!tableBody) return;

    // Update tab styles
    document.querySelectorAll('.leave-tab').forEach(tab => {
        tab.style.background = 'var(--card-bg)';
        tab.style.color = 'var(--text-secondary)';
    });
    const activeTab = document.getElementById(`leaveTab${status}`);
    if (activeTab) {
        activeTab.style.background = 'var(--accent-color)';
        activeTab.style.color = '#fff';
    }

    const filtered = allLeaves.filter(l => l.status === status);
    tableBody.innerHTML = '';

    if (filtered.length === 0) {
        const emptyMessages = {
            'Pending': 'No pending requests.',
            'Approved': 'No approved requests.',
            'Rejected': 'No rejected requests.'
        };
        tableBody.innerHTML = `<tr><td colspan="6" style="padding: 20px; text-align: center; color: var(--text-secondary);">${emptyMessages[status]}</td></tr>`;
        return;
    }

    filtered.forEach(l => {
        // Duration Calculation
        const d1 = new Date(l.start_date);
        const d2 = new Date(l.end_date);
        const diffTime = Math.abs(d2 - d1);
        const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24)) + 1;

        // Attachment
        let attachmentHtml = '<span style="color:var(--text-secondary)">-</span>';
        if (l.attachment_path) {
            const fileUrl = `/uploads/${l.attachment_path}`;
            attachmentHtml = `<a href="#" onclick="viewProof('${fileUrl}'); return false;" style="color: var(--accent-color); text-decoration: underline;">View File</a>`;
        }

        // Actions column based on status
        let actionsHtml = '';
        if (status === 'Pending') {
            actionsHtml = `
                <button class="btn-primary" style="padding: 6px 10px; width: auto; font-size: 0.8rem; background: var(--success-color); margin-right: 5px;" onclick="updateLeave(${l.id}, 'Approved')">Approve</button>
                <button class="btn-danger" style="padding: 6px 10px; width: auto; font-size: 0.8rem;" onclick="updateLeave(${l.id}, 'Rejected')">Reject</button>
            `;
        } else if (status === 'Approved') {
            actionsHtml = `<span style="color: var(--success-color); font-weight: 600;">✅ Approved</span>
                <button class="btn-danger" style="padding: 5px 8px; width: auto; font-size: 0.75rem; margin-left: 8px;" onclick="updateLeave(${l.id}, 'Rejected')">Change to Reject</button>`;
        } else if (status === 'Rejected') {
            actionsHtml = `<span style="color: var(--error-color); font-weight: 600;">❌ Rejected</span>
                <button class="btn-primary" style="padding: 5px 8px; width: auto; font-size: 0.75rem; background: var(--success-color); margin-left: 8px;" onclick="updateLeave(${l.id}, 'Approved')">Change to Approve</button>`;
        }

        const row = document.createElement('tr');
        row.style.borderBottom = '1px solid var(--border-color)';
        row.innerHTML = `
            <td style="padding: 10px; font-weight: 500;">${getDisplayName(l.username)}</td>
            <td style="padding: 10px;">${l.type}</td>
            <td style="padding: 10px;">
                <div>${l.start_date} -> ${l.end_date}</div>
                <div style="font-size: 0.8rem; color: var(--text-secondary);">(${diffDays} days)</div>
            </td>
            <td style="padding: 10px; max-width: 200px;">${l.reason || '-'}</td>
            <td style="padding: 10px;">${attachmentHtml}</td>
            <td style="padding: 10px;">${actionsHtml}</td>
        `;
        tableBody.appendChild(row);
    });
}

// Global View Proof Function
window.viewProof = (url) => {
    const ext = url.split('.').pop().toLowerCase();
    const imageExts = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp'];

    if (imageExts.includes(ext)) {
        // Show Image in Modal
        Swal.fire({
            imageUrl: url,
            imageAlt: 'Proof of Leave',
            title: 'Attached Proof',
            showCloseButton: true,
            showConfirmButton: false,
            width: 'auto',
            background: '#1a1a1a',
            color: '#fff'
        });
    } else {
        // Open PDF or other files in new tab
        window.open(url, '_blank');
    }
};
// ... (rest) ...

// Update Clock
function updateClock() {
    const now = new Date();
    const headers = now.toLocaleTimeString('en-US', { hour12: false });
    clockElement.textContent = headers;
}
setInterval(updateClock, 1000);
updateClock();

// Socket.IO Connection (Guarded)
try {
    if (typeof io !== 'undefined') {
        const socket = io(); // Connects to the same host that serves the page

        socket.on('connect', () => {
            console.log('Connected to server via WebSocket');
            if (serverStatus) {
                serverStatus.textContent = 'Online';
                serverStatus.className = 'status-value online';
            }
        });

        socket.on('disconnect', () => {
            console.log('Disconnected from server');
            if (serverStatus) {
                serverStatus.textContent = 'Offline';
                serverStatus.className = 'status-value offline';
            }
        });

        // Listen for recognition events broadcast by the server
        socket.on('recognition_event', (data) => {
            addLogEntry(data);
        });

        socket.on("live_frame", data => {
            const img = document.getElementById("liveFeed");
            if (img) {
                img.src = "data:image/jpeg;base64," + data.image;
            }
        });
    } else {
        console.warn("Socket.IO client not loaded. Live features disabled.");
    }
} catch (e) {
    console.error("Socket.IO Error:", e);
}

// --- Staff Name Lookup (maps STF-014 -> display name like 'Daud') ---
let staffNameMap = {};

async function loadStaffNames() {
    try {
        const res = await fetch('/api/staff');
        if (!res.ok) return;
        const staffList = await res.json();
        staffNameMap = {};
        staffList.forEach(s => {
            // Prefer display_name (short name like 'ZIA') over full_name
            const displayName = s.display_name || s.name || s.username;
            staffNameMap[s.username] = displayName;
        });
    } catch (e) {
        console.error('Failed to load staff names:', e);
    }
}

function getDisplayName(staffId) {
    // Return the mapped display name, or the ID as fallback
    return staffNameMap[staffId] || staffId;
}

// Load staff names immediately
loadStaffNames();

// Function to add log entry from live Socket.IO (only skips NoFace, shows all detections)
function addLogEntry(data) {
    // Don't add live entries while viewing history
    if (viewingHistory) return;

    let name = data.name || 'Unknown';

    // Skip NoFace entries — only show actual staff detections
    if (name === 'NoFace') return;

    // Show toast for every detection
    showToast(data);

    const logItem = document.createElement('div');
    const now = new Date();
    const timestamp = now.toLocaleTimeString('en-US', { hour12: false });

    let statusClass = 'unknown';
    let statusText = 'Unknown';
    let displayName = getDisplayName(name);
    let confidence = data.distance !== undefined ? ((1 - data.distance) * 100).toFixed(1) + '%' : 'N/A';

    if (data.status === 'error') {
        statusClass = 'unknown';
        statusText = 'Error';
        displayName = data.reason || 'Error';
    } else if (name !== 'Unknown') {
        statusClass = 'recognized';
        statusText = 'Recognized';
    }

    logItem.className = `log-item ${statusClass}`;

    logItem.innerHTML = `
        <span>${timestamp}</span>
        <span>${displayName}</span>
        <span>${confidence}</span>
        <span>${statusText}</span>
    `;

    // Prepend to show latest at top
    logContainer.insertBefore(logItem, logContainer.firstChild);
}

// Fetch Recent Attendance Data AND populate Live Recognition Log
async function fetchAttendance() {
    try {
        const response = await fetch('/api/attendance/recent');
        if (!response.ok) throw new Error('Network response was not ok');
        const data = await response.json();
        updateAttendanceTable(data);
        updateLiveLog(data);
    } catch (error) {
        console.error('Error fetching attendance:', error);
    }
}

function updateAttendanceTable(data) {
    attendanceBody.innerHTML = ''; // Clear existing rows

    // Deduplicate: show each staff only once (most recent entry)
    const seen = new Set();
    const unique = [];
    data.forEach(row => {
        if (!seen.has(row.name)) {
            seen.add(row.name);
            unique.push(row);
        }
    });

    unique.forEach(row => {
        const tr = document.createElement('tr');
        const displayName = getDisplayName(row.name);
        const recordTime = new Date(row.timestamp + 'Z');
        const ts = recordTime.toLocaleString('en-US', { hour12: false });
        tr.innerHTML = `
            <td>${displayName}</td>
            <td>${ts}</td>
            <td>${(row.confidence * 100).toFixed(1)}%</td>
        `;
        attendanceBody.appendChild(tr);
    });
}

function updateLiveLog(data) {
    // Don't overwrite while viewing history
    if (viewingHistory) return;

    // Filter: only show records from the last 24 hours
    const now = new Date();
    const cutoff = new Date(now.getTime() - 24 * 60 * 60 * 1000);

    const todayRecords = data.filter(row => {
        if (!row.name || row.name === 'NoFace' || row.name === 'Unknown') return false;
        const recordTime = new Date(row.timestamp + 'Z');
        return recordTime >= cutoff;
    });

    if (todayRecords.length > 0) {
        logContainer.innerHTML = '';
        todayRecords.forEach(row => {
            const logItem = document.createElement('div');
            logItem.className = 'log-item recognized';

            const recordTime = new Date(row.timestamp + 'Z');
            const ts = recordTime.toLocaleTimeString('en-US', { hour12: false });
            const confidence = row.confidence ? (row.confidence * 100).toFixed(1) + '%' : 'N/A';
            const displayName = getDisplayName(row.name);

            logItem.innerHTML = `
                <span>${ts}</span>
                <span>${displayName}</span>
                <span>${confidence}</span>
                <span>Recognized</span>
            `;
            logContainer.appendChild(logItem);
        });
    }
}

// --- Date Picker for Historical Log Browsing ---
let viewingHistory = false;

// Helper: get today's local date as YYYY-MM-DD (avoids UTC timezone offset bug)
function getLocalDateStr() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

const logDatePicker = document.getElementById('logDatePicker');
if (logDatePicker) {
    // Set today's LOCAL date as default
    const today = getLocalDateStr();
    logDatePicker.value = today;
    logDatePicker.max = today; // Can't pick future dates

    logDatePicker.addEventListener('change', async function () {
        const selectedDate = this.value;
        const todayStr = getLocalDateStr();

        if (selectedDate === todayStr) {
            backToLive();
            return;
        }

        // Switch to history mode
        viewingHistory = true;
        document.getElementById('logTitle').innerHTML = `📋 Attendance Log — ${selectedDate}`;
        document.getElementById('backToLiveBtn').style.display = 'inline-block';

        try {
            const res = await fetch(`/api/attendance/by-date?start=${selectedDate}&end=${selectedDate}`);
            if (!res.ok) throw new Error('Failed to fetch');
            const records = await res.json();

            logContainer.innerHTML = '';

            if (records.length === 0) {
                logContainer.innerHTML = '<div class="log-item" style="justify-content: center; color: var(--text-secondary);">No records found for this date</div>';
                return;
            }

            records.forEach(row => {
                if (!row.name || row.name === 'NoFace' || row.name === 'Unknown') return;
                const logItem = document.createElement('div');
                logItem.className = 'log-item recognized';

                const recordTime = new Date(row.timestamp + 'Z');
                const ts = recordTime.toLocaleTimeString('en-US', { hour12: false });
                const confidence = row.confidence ? (row.confidence * 100).toFixed(1) + '%' : 'N/A';

                logItem.innerHTML = `
                    <span>${ts}</span>
                    <span>${getDisplayName(row.name)}</span>
                    <span>${confidence}</span>
                    <span>Recognized</span>
                `;
                logContainer.appendChild(logItem);
            });
        } catch (e) {
            console.error('Failed to load history:', e);
            logContainer.innerHTML = '<div class="log-item" style="justify-content: center; color: var(--error-color);">Error loading records</div>';
        }
    });
}

function backToLive() {
    viewingHistory = false;
    document.getElementById('logTitle').innerHTML = '📋 Live Recognition Log';
    document.getElementById('backToLiveBtn').style.display = 'none';
    const todayStr = getLocalDateStr();
    document.getElementById('logDatePicker').value = todayStr;
    fetchAttendance(); // Reload live data
}

// Poll attendance every 5 seconds
setInterval(fetchAttendance, 5000);
fetchAttendance(); // Initial fetch (also loads Live Recognition Log)

// Initial load and poll for leaves
if (document.getElementById('admin-leave-body')) {
    loadAdminLeaves();
    setInterval(loadAdminLeaves, 10000);
}

// --- Chart.js Integration ---
let attendanceChart = null;

function initChart() {
    const ctx = document.getElementById('attendanceChart');
    if (!ctx) return; // Only on dashboard

    attendanceChart = new Chart(ctx.getContext('2d'), {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label: 'Attendance Count',
                data: [],
                borderColor: '#3b82f6',
                backgroundColor: 'rgba(59, 130, 246, 0.1)',
                borderWidth: 2,
                fill: true,
                tension: 0.4,
                pointBackgroundColor: '#3b82f6',
                pointRadius: 4,
                pointHoverRadius: 6
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    mode: 'index',
                    intersect: false,
                    backgroundColor: 'rgba(15, 23, 42, 0.9)',
                    titleColor: '#f8fafc',
                    bodyColor: '#94a3b8',
                    borderColor: 'rgba(148, 163, 184, 0.1)',
                    borderWidth: 1
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    grid: { color: 'rgba(148, 163, 184, 0.1)' },
                    ticks: { color: '#94a3b8', stepSize: 1 }
                },
                x: {
                    grid: { display: false },
                    ticks: { color: '#94a3b8' }
                }
            },
            interaction: {
                mode: 'nearest',
                axis: 'x',
                intersect: false
            }
        }
    });
}

function updateChart() {
    if (!attendanceChart) return;

    fetch('/api/attendance/stats')
        .then(res => res.json())
        .then(data => {
            // data is { "2023-10-01": 5, ... }
            if (data.error) return;

            const labels = Object.keys(data).sort(); // Ensure date order
            const values = labels.map(date => data[date]);

            // Format labels to be prettier (e.g. "Oct 27")
            const prettyLabels = labels.map(dateStr => {
                const date = new Date(dateStr);
                return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
            });

            attendanceChart.data.labels = prettyLabels;
            attendanceChart.data.datasets[0].data = values;
            attendanceChart.update();
        })
        .catch(err => console.error("Chart Error:", err));
}

// Initialize Chart
document.addEventListener('DOMContentLoaded', () => {
    initChart();
    updateChart();
    // Refresh chart every minute
    setInterval(updateChart, 60000);

    // Poll System Status (RPi Connection)
    setInterval(pollSystemStatus, 5000);
    pollSystemStatus();
});

function pollSystemStatus() {
    const piStatusEl = document.getElementById('pi-status');
    const serverStatusEl = document.getElementById('server-status');

    fetch('/api/health')
        .then(res => res.json())
        .then(data => {
            // Update RPi Status
            if (piStatusEl) {
                if (data.rpi_connected) {
                    piStatusEl.textContent = 'Connected';
                    piStatusEl.className = 'status-value connected';
                } else {
                    piStatusEl.textContent = 'Disconnected';
                    piStatusEl.className = 'status-value disconnected'; // Ensure CSS exists for this
                }
            }

            // Server is implicitly online if fetch succeeds
            if (serverStatusEl) {
                serverStatusEl.textContent = 'Online';
                serverStatusEl.className = 'status-value online';
            }
        })
        .catch(err => {
            // Server offline
            if (serverStatusEl) {
                serverStatusEl.textContent = 'Offline';
                serverStatusEl.className = 'status-value offline';
            }
        });
}

// --- Toast Notification (only for actual staff detections) ---
function showToast(data) {
    const container = document.getElementById('toast-container');
    if (!container) return;

    // Skip NoFace toasts entirely
    if (data.name === 'NoFace') return;

    const toast = document.createElement('div');

    // Determine type
    let type = 'unknown';
    let icon = '❓';
    let title = 'Unknown';

    if (data.name !== 'Unknown' && data.name) {
        type = 'recognized';
        icon = '✅';
        title = `Welcome, ${getDisplayName(data.name)}!`;
    } else {
        type = 'unknown';
        icon = '❌';
        title = 'Unknown Person';
    }

    toast.className = `toast ${type}`;
    toast.innerHTML = `
        <span style="font-size: 1.2rem;">${icon}</span>
        <div style="display: flex; flex-direction: column;">
            <span style="font-weight: 600; font-size: 0.95rem;">${title}</span>
            <span style="font-size: 0.8rem; opacity: 0.8;">${data.camera_id || 'Camera'} • ${(data.distance !== undefined ? ((1 - data.distance) * 100).toFixed(0) + '%' : '')}</span>
        </div>
    `;

    container.appendChild(toast);

    // Remove after 4 seconds
    setTimeout(() => {
        toast.classList.add('hiding');
        toast.addEventListener('animationend', () => toast.remove());
    }, 4000);
}

// --- Attendance Flags & Late Appeals (Admin Dashboard) ---

async function loadAttendanceFlags() {
    try {
        const res = await fetch('/api/attendance-flags');
        if (!res.ok) return;
        const flags = await res.json();
        const tbody = document.getElementById('flags-body');
        const countEl = document.getElementById('flagCount');
        if (!tbody) return;

        countEl.textContent = flags.length;

        if (flags.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" style="text-align:center; color: var(--text-secondary); padding: 20px;">✅ No staff needing attention this month</td></tr>';
            return;
        }

        tbody.innerHTML = flags.map(f => {
            const levelBadge = f.current_warning_level === 0
                ? '<span style="color: var(--success-color);">None</span>'
                : `<span style="color: var(--warning-color); font-weight: 600;">Level ${f.current_warning_level}</span>`;

            const nextLevel = f.current_warning_level + 1;
            const actionBtn = nextLevel <= 3
                ? `<button onclick="issueWarning('${f.username}', '${f.display_name}', ${nextLevel}, ${f.unexcused_late}, '${f.month}')" class="btn-primary" style="padding: 4px 10px; font-size: 0.75rem; width: auto; background: var(--warning-color); color: #000;">⚠️ Issue Warning ${nextLevel}</button>`
                : '<span style="color: var(--error-color); font-weight: 600;">Max warnings reached</span>';

            return `<tr>
                <td>${f.display_name} <span style="color: var(--text-secondary); font-size: 0.8rem;">(${f.staff_id || f.username})</span></td>
                <td style="color: var(--success-color);">${f.on_time}</td>
                <td style="color: var(--error-color); font-weight: 600;">${f.late}</td>
                <td style="color: var(--accent-color);">${f.excused}</td>
                <td style="color: var(--warning-color); font-weight: 700;">${f.unexcused_late}</td>
                <td>${levelBadge}</td>
                <td>${actionBtn}</td>
            </tr>`;
        }).join('');
    } catch (err) {
        console.error('Failed to load attendance flags:', err);
    }
}

async function loadLateAppeals() {
    try {
        const res = await fetch('/api/late-appeals');
        if (!res.ok) return;
        const appeals = await res.json();
        const tbody = document.getElementById('appeals-body');
        const countEl = document.getElementById('appealCount');
        if (!tbody) return;

        const pending = appeals.filter(a => a.status === 'Pending');
        countEl.textContent = pending.length;

        if (appeals.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" style="text-align:center; color: var(--text-secondary); padding: 20px;">No late excuse appeals submitted</td></tr>';
            return;
        }

        tbody.innerHTML = appeals.map(a => {
            const statusColor = a.status === 'Approved' ? 'var(--success-color)'
                : a.status === 'Rejected' ? 'var(--error-color)'
                    : 'var(--warning-color)';

            const proofBtn = a.attachment_path
                ? `<a href="/uploads/${a.attachment_path}" target="_blank" style="color: var(--accent-color); text-decoration: underline;">View</a>`
                : '<span style="color: var(--text-secondary);">None</span>';

            const actions = a.status === 'Pending'
                ? `<button onclick="updateAppealStatus(${a.id}, 'Approved')" class="btn-primary" style="padding: 3px 8px; font-size: 0.7rem; width: auto; background: var(--success-color); margin-right: 4px;">✅ Approve</button>
                   <button onclick="updateAppealStatus(${a.id}, 'Rejected')" class="btn-primary" style="padding: 3px 8px; font-size: 0.7rem; width: auto; background: var(--error-color);">❌ Reject</button>`
                : `<span style="color: ${statusColor}; font-weight: 600;">${a.status}</span>`;

            return `<tr>
                <td>${a.display_name || a.username}</td>
                <td>${a.date}</td>
                <td>${a.arrival_time || '-'}</td>
                <td style="max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${a.reason}">${a.reason}</td>
                <td>${proofBtn}</td>
                <td><span style="color: ${statusColor}; font-weight: 600;">${a.status}</span></td>
                <td>${actions}</td>
            </tr>`;
        }).join('');
    } catch (err) {
        console.error('Failed to load late appeals:', err);
    }
}

async function updateAppealStatus(id, status) {
    const action = status === 'Approved' ? 'approve' : 'reject';
    const result = await Swal.fire({
        title: `${action.charAt(0).toUpperCase() + action.slice(1)} this appeal?`,
        input: 'textarea',
        inputLabel: 'Admin note (optional)',
        inputPlaceholder: 'Add a note for the staff member...',
        showCancelButton: true,
        confirmButtonText: status === 'Approved' ? '✅ Approve' : '❌ Reject',
        confirmButtonColor: status === 'Approved' ? '#10b981' : '#ef4444',
        background: 'var(--card-bg)',
        color: 'var(--text-primary)',
    });

    if (!result.isConfirmed) return;

    try {
        const res = await fetch(`/api/late-appeal/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status, admin_note: result.value || '' })
        });
        if (res.ok) {
            Swal.fire({ icon: 'success', title: `Appeal ${status}`, timer: 1500, showConfirmButton: false, background: 'var(--card-bg)', color: 'var(--text-primary)' });
            loadLateAppeals();
            loadAttendanceFlags();
        } else {
            Swal.fire('Error', 'Failed to update appeal', 'error');
        }
    } catch (err) {
        Swal.fire('Error', 'Connection error', 'error');
    }
}

async function issueWarning(username, displayName, level, unexcusedCount, month) {
    const levelLabels = { 1: '1st Warning', 2: '2nd Warning', 3: 'Final Warning' };
    const defaultReason = `You have accumulated ${unexcusedCount} unexcused late arrivals for the month of ${month}. This is a ${levelLabels[level]} under the company attendance policy. Please ensure timely attendance going forward.`;

    const result = await Swal.fire({
        title: `⚠️ Issue ${levelLabels[level]}`,
        html: `
            <p style="text-align: left; margin-bottom: 12px; color: var(--text-secondary);">
                <strong>Staff:</strong> ${displayName}<br>
                <strong>Month:</strong> ${month}<br>
                <strong>Unexcused Lates:</strong> ${unexcusedCount}
            </p>
            <label style="display: block; text-align: left; margin-bottom: 6px; font-weight: 600; color: var(--text-primary);">Warning Message:</label>
            <textarea id="warningReason" rows="5" style="width: 100%; padding: 10px; background: var(--input-bg); color: var(--text-primary); border: 1px solid var(--border-color); border-radius: 8px; resize: vertical;">${defaultReason}</textarea>
        `,
        showCancelButton: true,
        confirmButtonText: '⚠️ Issue Warning',
        confirmButtonColor: '#f59e0b',
        background: 'var(--card-bg)',
        color: 'var(--text-primary)',
        width: '550px',
        preConfirm: () => {
            const reason = document.getElementById('warningReason').value;
            if (!reason.trim()) {
                Swal.showValidationMessage('Warning reason is required');
                return false;
            }
            return reason;
        }
    });

    if (!result.isConfirmed) return;

    try {
        const res = await fetch('/api/warning', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, level, reason: result.value, month })
        });
        if (res.ok) {
            Swal.fire({ icon: 'success', title: `${levelLabels[level]} Issued`, text: `Warning sent to ${displayName}`, timer: 2000, showConfirmButton: false, background: 'var(--card-bg)', color: 'var(--text-primary)' });
            loadAttendanceFlags();
        } else {
            Swal.fire('Error', 'Failed to issue warning', 'error');
        }
    } catch (err) {
        Swal.fire('Error', 'Connection error', 'error');
    }
}

// Load flags and appeals on page load + auto-refresh
loadAttendanceFlags();
loadLateAppeals();
loadStaffLeaveBalances();
setInterval(() => { loadAttendanceFlags(); loadLateAppeals(); loadStaffLeaveBalances(); }, 30000);

// --- Staff Leave Balances (Admin Dashboard) ---
async function loadStaffLeaveBalances() {
    const tbody = document.getElementById('leave-balance-body');
    if (!tbody) return;

    try {
        const res = await fetch('/api/staff-leave-balances');
        if (!res.ok) return;
        const data = await res.json();
        const staffList = data.staff || [];

        if (staffList.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" style="padding: 20px; text-align: center; color: var(--text-secondary);">No staff registered.</td></tr>';
            return;
        }

        tbody.innerHTML = staffList.map(s => {
            const balanceColor = s.leave_balance <= 3 ? 'var(--error-color)' : s.leave_balance <= 7 ? 'var(--warning-color)' : 'var(--success-color)';
            const cfBadge = s.carried_forward > 0
                ? `<span style="background: var(--accent-color); color: #fff; padding: 2px 8px; border-radius: 12px; font-size: 0.75rem;">+${s.carried_forward} days</span>`
                : '<span style="color: var(--text-secondary);">0</span>';
            const usedDisplay = Math.max(s.used, 0);

            return `<tr style="border-bottom: 1px solid var(--border-color);">
                <td style="padding: 10px; font-weight: 500;">${s.name}</td>
                <td style="padding: 10px; color: var(--text-secondary);">${s.staff_id}</td>
                <td style="padding: 10px;">${s.annual_entitlement} days</td>
                <td style="padding: 10px;">${cfBadge}</td>
                <td style="padding: 10px;"><span style="color: ${balanceColor}; font-weight: 700; font-size: 1.1rem;">${s.leave_balance}</span> <span style="color: var(--text-secondary); font-size: 0.8rem;">days</span></td>
                <td style="padding: 10px;">${usedDisplay} days</td>
            </tr>`;
        }).join('');
    } catch (e) {
        console.error('Error loading leave balances:', e);
    }
}
