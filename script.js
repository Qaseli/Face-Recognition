// DOM Elements
const clockElement = document.getElementById('clock');
const logContainer = document.getElementById('log-container');
const attendanceBody = document.getElementById('attendance-body');
const serverStatus = document.getElementById('server-status');

// Auth Check
fetch('/api/check_auth').then(res => {
    if (res.status === 401) window.location.href = 'login.html';
});

// Logout
const logoutBtn = document.getElementById('logoutBtn');
if (logoutBtn) {
    logoutBtn.addEventListener('click', async (e) => {
        e.preventDefault();
        await fetch('/api/logout', { method: 'POST' });
        window.location.href = 'login.html';
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
async function loadAdminLeaves() {
    const tableBody = document.getElementById('admin-leave-body');
    if (!tableBody) return; // Not on admin page

    try {
        const res = await fetch('/api/leave');
        const leaves = await res.json();

        tableBody.innerHTML = '';
        const pendingLeaves = leaves.filter(l => l.status === 'Pending');

        if (pendingLeaves.length === 0) {
            tableBody.innerHTML = '<tr><td colspan="6" style="padding: 20px; text-align: center; color: var(--text-secondary);">No pending requests.</td></tr>';
            return;
        }

        pendingLeaves.forEach(l => {
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

            const row = document.createElement('tr');
            row.style.borderBottom = '1px solid var(--border-color)';
            row.innerHTML = `
                <td style="padding: 10px; font-weight: 500;">${l.username}</td>
                <td style="padding: 10px;">${l.type}</td>
                <td style="padding: 10px;">
                    <div>${l.start_date} -> ${l.end_date}</div>
                    <div style="font-size: 0.8rem; color: var(--text-secondary);">(${diffDays} days)</div>
                </td>
                <td style="padding: 10px; max-width: 200px;">${l.reason || '-'}</td>
                <td style="padding: 10px;">${attachmentHtml}</td>
                <td style="padding: 10px;">
                    <button class="btn-primary" style="padding: 6px 10px; width: auto; font-size: 0.8rem; background: var(--success-color); margin-right: 5px;" onclick="updateLeave(${l.id}, 'Approved')">Approve</button>
                    <button class="btn-danger" style="padding: 6px 10px; width: auto; font-size: 0.8rem;" onclick="updateLeave(${l.id}, 'Rejected')">Reject</button>
                </td>
            `;
            tableBody.appendChild(row);
        });
    } catch (e) {
        console.error("Error loading leaves", e);
    }
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

        socket.on('result', (data) => {
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

// Function to add log entry
function addLogEntry(data) {
    const logItem = document.createElement('div');
    const now = new Date();
    const timestamp = now.toLocaleTimeString('en-US', { hour12: false });

    let statusClass = 'unknown';
    let statusText = 'Unknown';
    let name = data.name || 'Unknown';
    let confidence = data.distance !== undefined ? ((1 - data.distance) * 100).toFixed(1) + '%' : 'N/A';

    // Determine status based on data
    if (data.status === 'error') {
        statusClass = 'unknown';
        statusText = 'Error';
        name = data.reason || 'Error';
    } else if (name === 'NoFace') {
        statusClass = 'noface';
        statusText = 'No Face';
    } else if (name !== 'Unknown') {
        statusClass = 'recognized';
        statusText = 'Recognized';
    }

    logItem.className = `log-item ${statusClass}`;

    // HTML Structure matching the grid layout
    logItem.innerHTML = `
        <span>${timestamp}</span>
        <span>${data.camera_id || 'Cam 1'}</span>
        <span>${name}</span>
        <span>${confidence}</span>
        <span>${statusText}</span>
    `;

    // Prepend to show latest at top
    logContainer.insertBefore(logItem, logContainer.firstChild);

    // Limit log entries to 50 to prevent memory issues
    if (logContainer.children.length > 50) {
        logContainer.removeChild(logContainer.lastChild);
    }
}

// Fetch Recent Attendance Data
async function fetchAttendance() {
    try {
        const response = await fetch('/api/attendance/recent');
        if (!response.ok) throw new Error('Network response was not ok');
        const data = await response.json();
        updateAttendanceTable(data);
    } catch (error) {
        console.error('Error fetching attendance:', error);
    }
}

function updateAttendanceTable(data) {
    attendanceBody.innerHTML = ''; // Clear existing rows

    data.forEach(row => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>${row.name}</td>
            <td>${row.camera_id}</td>
            <td>${row.timestamp}</td>
            <td>${(row.confidence * 100).toFixed(1)}%</td>
        `;
        attendanceBody.appendChild(tr);
    });
}



// Poll attendance every 5 seconds
setInterval(fetchAttendance, 5000);
fetchAttendance(); // Initial fetch

// Initial load and poll for leaves
if (document.getElementById('admin-leave-body')) {
    loadAdminLeaves();
    setInterval(loadAdminLeaves, 10000);
}
