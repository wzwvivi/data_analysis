// ==================== State ====================
let allDatasets = [];
let currentDatasetId = null;
let currentColumns = [];
let selectedColumnIndices = new Set();
let currentPage = 0;
const PAGE_SIZE = 200;
let totalRows = 0;
let uploadedFiles = null;
let tableMode = 'all'; // 'all' = all columns, 'selected' = filtered
let ndChart = null;
let vdChart = null;
let ndTrajectory = null; // cached traj data for linked highlighting

// ==================== Theme ====================
function initTheme() {
    const saved = localStorage.getItem('theme') || 'light';
    applyTheme(saved);
}

function toggleSidebar() {
    document.getElementById('sidebar').classList.toggle('collapsed');
    // Resize charts after sidebar transition completes (250ms)
    setTimeout(() => {
        if (ndChart) ndChart.resize();
        if (vdChart) vdChart.resize();
    }, 300);
}

function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme') || 'dark';
    const next = current === 'dark' ? 'light' : 'dark';
    applyTheme(next);
    localStorage.setItem('theme', next);
}

function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    const btn = document.getElementById('btn-theme');
    if (btn) btn.textContent = theme === 'dark' ? 'Light' : 'Dark';
    // Re-render charts with matching theme if they exist
    if (ndChart) ndChart.dispose(); ndChart = null;
    if (vdChart) vdChart.dispose(); vdChart = null;
    // Trigger re-render if analysis panel is visible
    const batchName = document.getElementById('batch-select').value;
    if (batchName) loadAnalysis(batchName);
}

function getEchartsTheme() {
    return document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : null;
}

// ==================== Init ====================
document.addEventListener('DOMContentLoaded', () => {
    initTheme();
    loadDatasets();
    initDragScroll();
});

// ==================== Drag-to-Scroll ====================
function initDragScroll() {
    const wrapper = document.querySelector('.table-wrapper');
    if (!wrapper) return;

    let isDragging = false;
    let startX, startY, scrollLeft, scrollTop;

    wrapper.addEventListener('mousedown', (e) => {
        // Don't interfere with text selection on cells if user clicks without moving
        isDragging = true;
        wrapper.classList.add('dragging');
        startX = e.pageX;
        startY = e.pageY;
        scrollLeft = wrapper.scrollLeft;
        scrollTop = wrapper.scrollTop;
    });

    document.addEventListener('mousemove', (e) => {
        if (!isDragging) return;
        e.preventDefault();
        const dx = e.pageX - startX;
        const dy = e.pageY - startY;
        wrapper.scrollLeft = scrollLeft - dx;
        wrapper.scrollTop = scrollTop - dy;
    });

    document.addEventListener('mouseup', () => {
        if (isDragging) {
            isDragging = false;
            wrapper.classList.remove('dragging');
        }
    });
}

// ==================== Time Parsing ====================
function parseTimeInput(value) {
    // Supports both "HH:MM:SS.ms" and "seconds.ms" formats
    if (!value || value.trim() === '') return null;
    value = value.trim();
    if (value.includes(':')) {
        const parts = value.split(':');
        let h = 0, m = 0, s = 0;
        if (parts.length >= 3) {
            h = parseFloat(parts[0]) || 0;
            m = parseFloat(parts[1]) || 0;
            s = parseFloat(parts[2]) || 0;
        } else if (parts.length === 2) {
            m = parseFloat(parts[0]) || 0;
            s = parseFloat(parts[1]) || 0;
        }
        return h * 3600 + m * 60 + s;
    }
    const num = parseFloat(value);
    return isNaN(num) ? null : num;
}

function getTimeParams() {
    const minVal = parseTimeInput(document.getElementById('time-min').value);
    const maxVal = parseTimeInput(document.getElementById('time-max').value);
    let params = '';
    if (minVal !== null) params += `&time_min=${minVal}`;
    if (maxVal !== null) params += `&time_max=${maxVal}`;
    return params;
}

// ==================== Upload ====================
function toggleUploadPanel() {
    const modal = document.getElementById('upload-modal');
    modal.classList.toggle('hidden');
    if (!modal.classList.contains('hidden')) {
        document.getElementById('upload-info').classList.add('hidden');
        document.getElementById('upload-progress').classList.add('hidden');
        document.getElementById('upload-result').classList.add('hidden');
        document.getElementById('folder-input').value = '';
        uploadedFiles = null;
    }
}

function handleFolderSelect(event) {
    const files = event.target.files;
    const csvFiles = Array.from(files).filter(f => f.name.toLowerCase().endsWith('.csv'));
    if (csvFiles.length === 0) {
        alert('No CSV files found in the selected folder');
        return;
    }
    uploadedFiles = csvFiles;
    document.getElementById('upload-file-count').textContent = `Found ${csvFiles.length} CSV files`;
    document.getElementById('upload-info').classList.remove('hidden');
    const firstPath = files[0].webkitRelativePath || '';
    const folderName = firstPath.split('/')[0] || '';
    if (folderName) document.getElementById('batch-name').placeholder = folderName;
}

async function startUpload() {
    if (!uploadedFiles || uploadedFiles.length === 0) return;

    const batchName = document.getElementById('batch-name').value ||
        document.getElementById('batch-name').placeholder || '';

    document.getElementById('upload-info').classList.add('hidden');
    document.getElementById('upload-progress').classList.remove('hidden');
    document.getElementById('progress-text').textContent = 'Uploading files to server...';
    document.getElementById('progress-detail').textContent = '';
    document.getElementById('progress-fill').style.width = '0%';

    const formData = new FormData();
    formData.append('batch_name', batchName);
    for (const file of uploadedFiles) formData.append('files', file, file.name);

    try {
        const taskInfo = await new Promise((resolve, reject) => {
            const xhr = new XMLHttpRequest();
            xhr.open('POST', '/api/upload');
            xhr.upload.onprogress = (e) => {
                if (e.lengthComputable) {
                    const pct = Math.round((e.loaded / e.total) * 40);
                    document.getElementById('progress-fill').style.width = pct + '%';
                    document.getElementById('progress-text').textContent =
                        `Uploading: ${Math.round(e.loaded / 1024 / 1024)}MB / ${Math.round(e.total / 1024 / 1024)}MB`;
                    document.getElementById('progress-detail').textContent = 'Transferring files...';
                }
            };
            xhr.onload = () => {
                if (xhr.status === 200) resolve(JSON.parse(xhr.responseText));
                else {
                    try { reject(new Error(JSON.parse(xhr.responseText).error)); }
                    catch { reject(new Error('Upload failed')); }
                }
            };
            xhr.onerror = () => reject(new Error('Network error'));
            xhr.send(formData);
        });

        document.getElementById('progress-fill').style.width = '42%';
        document.getElementById('progress-text').textContent = 'Server is processing data...';
        document.getElementById('progress-detail').textContent = 'Starting merge...';
        await pollProgress(taskInfo.task_id);
    } catch (err) {
        document.getElementById('upload-progress').classList.add('hidden');
        document.getElementById('upload-result').classList.remove('hidden');
        document.getElementById('upload-result').innerHTML =
            `<div class="error-msg"><p>Error: ${err.message}</p></div>`;
    }
}

async function pollProgress(taskId) {
    const poll = async () => {
        try {
            const resp = await fetch(`/api/upload/progress/${taskId}`);
            const task = await resp.json();

            if (task.status === 'processing') {
                const pct = 42 + Math.round(((task.processed || 0) / (task.total || 1)) * 48);
                document.getElementById('progress-fill').style.width = pct + '%';
                document.getElementById('progress-text').textContent =
                    `Processing: ${task.processed || 0} / ${task.total || 0} datasets`;
                const stale = task.seconds_since_update || 0;
                let detail = task.current_name ? `Current: ${task.current_name}` : (task.phase || '');
                if (stale > 60) {
                    detail += ` (no update for ${Math.floor(stale)}s - may be processing a large file)`;
                }
                if (stale > 300) {
                    detail = `WARNING: No progress update for ${Math.floor(stale/60)} minutes. Server may be stuck.`;
                }
                document.getElementById('progress-detail').textContent = detail;
                setTimeout(poll, stale > 60 ? 2000 : 500);
            } else if (task.status === 'done') {
                document.getElementById('progress-fill').style.width = '100%';
                document.getElementById('progress-text').textContent = 'Complete!';
                document.getElementById('progress-detail').textContent = '';
                setTimeout(() => {
                    document.getElementById('upload-progress').classList.add('hidden');
                    document.getElementById('upload-result').classList.remove('hidden');
                    document.getElementById('upload-result').innerHTML = buildUploadSummary(task);
                }, 500);
            } else if (task.status === 'error') {
                document.getElementById('upload-progress').classList.add('hidden');
                document.getElementById('upload-result').classList.remove('hidden');
                document.getElementById('upload-result').innerHTML =
                    `<div class="error-msg"><p>Error: ${task.error}</p></div>`;
            } else {
                document.getElementById('progress-detail').textContent = task.phase || '';
                setTimeout(poll, 500);
            }
        } catch (err) {
            document.getElementById('upload-progress').classList.add('hidden');
            document.getElementById('upload-result').classList.remove('hidden');
            document.getElementById('upload-result').innerHTML =
                `<div class="error-msg"><p>Progress check failed: ${err.message}</p></div>`;
        }
    };
    poll();
}

// ==================== Clear View ====================
function clearView() {
    currentDatasetId = null;
    currentColumns = [];
    selectedColumnIndices.clear();
    currentPage = 0;
    totalRows = 0;
    tableMode = 'all';

    document.getElementById('col-search').value = '';
    document.getElementById('column-list').innerHTML = '';
    document.getElementById('time-min').value = '';
    document.getElementById('time-max').value = '';
    document.getElementById('time-min').placeholder = 'HH:MM:SS.ms or seconds';
    document.getElementById('time-max').placeholder = 'HH:MM:SS.ms or seconds';
    document.getElementById('time-min-label').textContent = '';
    document.getElementById('time-max-label').textContent = '';

    document.getElementById('table-head').innerHTML = '';
    document.getElementById('table-body').innerHTML = '';
    document.getElementById('table-info').textContent = '';
    document.getElementById('page-info').textContent = '';
    document.getElementById('current-ds-name').textContent = '';
    document.getElementById('btn-prev').disabled = true;
    document.getElementById('btn-next').disabled = true;
    document.getElementById('btn-export').disabled = true;
    document.getElementById('table-placeholder').classList.remove('hidden');
}

// ==================== Datasets ====================
async function loadDatasets() {
    try {
        const resp = await fetch('/api/datasets');
        allDatasets = await resp.json();
    } catch (e) { allDatasets = []; }

    const batches = [...new Set(allDatasets.map(d => d.batch_name))];
    const batchSelect = document.getElementById('batch-select');
    const prev = batchSelect.value;
    batchSelect.innerHTML = '<option value="">-- Select Batch --</option>';
    batches.forEach(b => {
        const opt = document.createElement('option');
        opt.value = b;
        opt.textContent = `${b} (${allDatasets.filter(d => d.batch_name === b).length} datasets)`;
        batchSelect.appendChild(opt);
    });

    if (prev && batches.includes(prev)) {
        batchSelect.value = prev;
        onBatchChange();
    } else if (batches.length === 1) {
        batchSelect.value = batches[0];
        onBatchChange();
    } else {
        onBatchChange();
    }
}

function onBatchChange() {
    const batchName = document.getElementById('batch-select').value;
    const list = document.getElementById('dataset-list');
    list.innerHTML = '';

    document.getElementById('btn-delete-batch').style.display = batchName ? 'inline-block' : 'none';
    clearView();

    if (batchName) {
        loadAnalysis(batchName);
    } else {
        document.getElementById('analysis-panel').classList.add('hidden');
    }

    const datasets = allDatasets.filter(d => d.batch_name === batchName);
    datasets.forEach(ds => {
        const item = document.createElement('div');
        item.className = 'dataset-item';
        item.dataset.id = ds.id;
        item.onclick = () => selectDataset(ds.id);

        // Build tooltip: full name + time range + rows/cols + source files
        let tooltip = ds.name;
        tooltip += `\nTime: ${ds.time_min_str} ~ ${ds.time_max_str}`;
        tooltip += `\nRows: ${ds.row_count}  Cols: ${ds.col_count}`;
        if (ds.source_files && ds.source_files.length > 0) {
            tooltip += `\n\nMerged from ${ds.source_files.length} file(s):\n` + ds.source_files.map(f => '  ' + f).join('\n');
        }

        item.setAttribute('title', tooltip);
        item.innerHTML = `<span class="ds-name">${shortenName(ds.name)}</span>`;
        list.appendChild(item);
    });
}

function shortenName(name) {
    return name.replace(/_\d{9,}$/, '');
}

async function deleteBatch() {
    const batchName = document.getElementById('batch-select').value;
    if (!batchName) return;
    const count = allDatasets.filter(d => d.batch_name === batchName).length;
    if (!confirm(`Delete batch "${batchName}"?\n${count} dataset(s) and analysis will be removed.`)) return;

    try {
        await fetch(`/api/batches/${encodeURIComponent(batchName)}`, { method: 'DELETE' });
        clearView();
        document.getElementById('dataset-list').innerHTML = '';
        document.getElementById('analysis-panel').classList.add('hidden');
        await loadDatasets();
    } catch (e) { alert('Delete failed: ' + e.message); }
}

async function selectDataset(datasetId) {
    document.querySelectorAll('.dataset-item').forEach(el => {
        el.classList.toggle('active', parseInt(el.dataset.id) === datasetId);
    });

    currentDatasetId = datasetId;
    currentPage = 0;

    try {
        const resp = await fetch(`/api/datasets/${datasetId}/columns`);
        currentColumns = await resp.json();
    } catch (e) { currentColumns = []; }

    const ds = allDatasets.find(d => d.id === datasetId);
    if (ds) {
        document.getElementById('time-min').value = '';
        document.getElementById('time-max').value = '';
        document.getElementById('time-min').placeholder = ds.time_min_str + ' (' + ds.time_min_seconds.toFixed(2) + 's)';
        document.getElementById('time-max').placeholder = ds.time_max_str + ' (' + ds.time_max_seconds.toFixed(2) + 's)';
        document.getElementById('time-min-label').textContent = '';
        document.getElementById('time-max-label').textContent = '';
        document.getElementById('current-ds-name').textContent = '- ' + shortenName(ds.name);
    }

    // Default: select all columns
    selectedColumnIndices.clear();
    currentColumns.forEach(c => selectedColumnIndices.add(c.index));
    renderColumnList();

    // Auto-load table with all columns
    tableMode = 'all';
    document.getElementById('table-placeholder').classList.add('hidden');
    await loadTablePage();
}

// ==================== Columns ====================
function renderColumnList() {
    const list = document.getElementById('column-list');
    const search = document.getElementById('col-search').value.toLowerCase();
    list.innerHTML = '';

    currentColumns.forEach(col => {
        if (search && !col.display_name.toLowerCase().includes(search)) return;
        const item = document.createElement('label');
        item.className = 'col-item';
        const typeTag = col.type === 'numeric'
            ? '<span class="tag tag-num">N</span>'
            : '<span class="tag tag-text">T</span>';
        item.innerHTML = `
            <input type="checkbox" data-index="${col.index}"
                   ${selectedColumnIndices.has(col.index) ? 'checked' : ''}
                   onchange="toggleColumn(${col.index}, this.checked)">
            ${typeTag}
            <span class="col-name" title="${col.original_name}">${col.display_name}</span>
        `;
        list.appendChild(item);
    });
}

function filterColumns() { renderColumnList(); }
function toggleColumn(index, checked) {
    if (checked) selectedColumnIndices.add(index);
    else selectedColumnIndices.delete(index);
}

function selectAllCols() {
    currentColumns.forEach(c => selectedColumnIndices.add(c.index));
    renderColumnList();
}
function deselectAllCols() { selectedColumnIndices.clear(); renderColumnList(); }
function selectNumericCols() {
    selectedColumnIndices.clear();
    currentColumns.filter(c => c.type === 'numeric').forEach(c => selectedColumnIndices.add(c.index));
    renderColumnList();
}
function resetTimeRange() {
    document.getElementById('time-min').value = '';
    document.getElementById('time-max').value = '';
}

// ==================== Data Loading ====================
function applyFilters() {
    if (!currentDatasetId) { alert('Please select a dataset first'); return; }
    if (selectedColumnIndices.size === 0) { alert('Please select at least one column'); return; }
    if (!validateTimeRange()) return;
    tableMode = 'selected';
    currentPage = 0;
    loadTablePage();
}

function validateTimeRange() {
    const ds = allDatasets.find(d => d.id === currentDatasetId);
    if (!ds) return true;

    const minVal = parseTimeInput(document.getElementById('time-min').value);
    const maxVal = parseTimeInput(document.getElementById('time-max').value);

    if (minVal !== null && minVal < ds.time_min_seconds) {
        alert(`From time cannot be earlier than data start (${ds.time_min_str} / ${ds.time_min_seconds.toFixed(2)}s)`);
        return false;
    }
    if (maxVal !== null && maxVal > ds.time_max_seconds) {
        alert(`To time cannot be later than data end (${ds.time_max_str} / ${ds.time_max_seconds.toFixed(2)}s)`);
        return false;
    }
    if (minVal !== null && maxVal !== null && minVal >= maxVal) {
        alert('From time must be earlier than To time');
        return false;
    }
    return true;
}

async function loadTablePage() {
    if (!currentDatasetId) return;

    const timeParams = getTimeParams();
    const offset = currentPage * PAGE_SIZE;
    let colParam = '';
    if (tableMode === 'selected' && selectedColumnIndices.size > 0) {
        colParam = 'columns=' + Array.from(selectedColumnIndices).join(',');
    }

    try {
        const resp = await fetch(
            `/api/datasets/${currentDatasetId}/data?${colParam}${timeParams}&limit=${PAGE_SIZE}&offset=${offset}`
        );
        const data = await resp.json();
        totalRows = data.total_rows;
        renderTable(data);
        updatePagination();
    } catch (e) { console.error('Failed to load table:', e); }
}

// ==================== Table ====================
function renderTable(data) {
    const thead = document.getElementById('table-head');
    const tbody = document.getElementById('table-body');

    let headerHtml = "<tr>";
    headerHtml += "<th class='frozen frozen-0'>T'(HH:MM:SS)</th>";
    headerHtml += "<th class='frozen frozen-1'>T'(s)</th>";
    data.columns.forEach(col => {
        const shortCol = col.display_name.includes('.') ? col.display_name.split('.').pop() : col.display_name;
        headerHtml += `<th title="${col.display_name}">${shortCol}</th>`;
    });
    headerHtml += '</tr>';
    thead.innerHTML = headerHtml;

    // Find the closest row to highlight (if navigating from event)
    let hlIdx = -1;
    if (highlightTimeSeconds !== null) {
        let minDist = Infinity;
        for (let i = 0; i < data.returned_rows; i++) {
            const dist = Math.abs(data.time_seconds[i] - highlightTimeSeconds);
            if (dist < minDist) { minDist = dist; hlIdx = i; }
        }
        highlightTimeSeconds = null; // consume once
    }

    let bodyHtml = '';
    for (let i = 0; i < data.returned_rows; i++) {
        const isHl = (i === hlIdx);
        bodyHtml += `<tr${isHl ? ' class="event-highlight"' : ''}>`;
        bodyHtml += `<td class="frozen frozen-0${isHl ? ' hl' : ''}">${data.time_str[i]}</td>`;
        bodyHtml += `<td class="frozen frozen-1${isHl ? ' hl' : ''}">${data.time_seconds[i].toFixed(2)}</td>`;
        data.columns.forEach(col => {
            const val = data.values[col.display_name][i];
            if (val === null || val === undefined) {
                bodyHtml += '<td class="null-val">-</td>';
            } else if (col.type === 'numeric') {
                bodyHtml += `<td class="num-val">${val}</td>`;
            } else {
                bodyHtml += `<td class="text-val" title="${String(val).replace(/"/g, '&quot;')}">${truncate(String(val), 40)}</td>`;
            }
        });
        bodyHtml += '</tr>';
    }
    tbody.innerHTML = bodyHtml;
    document.getElementById('table-info').textContent = `Total: ${data.total_rows.toLocaleString()} rows`;
    document.getElementById('btn-export').disabled = data.total_rows === 0;
    document.getElementById('table-placeholder').classList.add('hidden');

    // Measure actual width of first frozen column and update second column's left offset
    requestAnimationFrame(() => {
        const firstTh = thead.querySelector('.frozen-0');
        if (firstTh) {
            const w = firstTh.offsetWidth;
            document.querySelectorAll('.frozen-1').forEach(el => { el.style.left = w + 'px'; });
        }
    });
}

function updatePagination() {
    const totalPages = Math.ceil(totalRows / PAGE_SIZE);
    document.getElementById('page-info').textContent = `Page ${currentPage + 1} / ${totalPages || 1}`;
    document.getElementById('btn-prev').disabled = currentPage <= 0;
    document.getElementById('btn-next').disabled = currentPage >= totalPages - 1;
}

function prevPage() { if (currentPage > 0) { currentPage--; loadTablePage(); } }
function nextPage() {
    if (currentPage < Math.ceil(totalRows / PAGE_SIZE) - 1) { currentPage++; loadTablePage(); }
}

// ==================== Export ====================
function exportData() {
    if (!currentDatasetId) { alert('Please select a dataset first'); return; }
    const colStr = selectedColumnIndices.size > 0 ? Array.from(selectedColumnIndices).join(',') : '';
    const timeParams = getTimeParams();
    window.open(`/api/datasets/${currentDatasetId}/export?columns=${colStr}${timeParams}`, '_blank');
}

// ==================== Flight Analysis ====================
async function loadAnalysis(batchName) {
    const panel = document.getElementById('analysis-panel');
    try {
        const resp = await fetch(`/api/analyses/${encodeURIComponent(batchName)}`);
        if (!resp.ok) { panel.classList.add('hidden'); return; }
        const a = await resp.json();
        renderAnalysis(a);
        panel.classList.remove('hidden');
    } catch (e) { panel.classList.add('hidden'); }
}

function renderAnalysis(a) {
    const panel = document.getElementById('analysis-panel');
    const info = a.flight_info || {};
    const profile = a.flight_profile || {};
    const batt = a.battery || {};
    const phases = a.phases || [];
    const anomalies = a.anomalies || [];
    const quality = a.quality || 'Unknown';
    const traj = a.trajectory || null;
    const events = a.events || [];
    const narrative = a.narrative || '';

    const qClass = quality === 'Good' ? 'q-good' : quality === 'Critical' ? 'q-critical' : 'q-warning';

    let html = `
    <div class="analysis-header">
        <h3>Flight Analysis</h3>
        <span class="quality-badge ${qClass}">${quality}</span>
    </div>
    <div class="analysis-summary">
        <div class="stat-card">
            <div class="stat-label">Duration</div>
            <div class="stat-value">${info.duration || 'N/A'}</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Time Range</div>
            <div class="stat-value">${info.start_time || ''} ~ ${info.end_time || ''}</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Max Altitude</div>
            <div class="stat-value">${profile.max_altitude_m != null ? profile.max_altitude_m + ' m' : 'N/A'}</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Max Speed</div>
            <div class="stat-value">${profile.max_ground_speed != null ? profile.max_ground_speed + ' m/s' : 'N/A'}</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Battery SOC</div>
            <div class="stat-value">${batt.initial_soc != null ? batt.initial_soc + '% &rarr; ' + batt.final_soc + '%' : 'N/A'}</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Datasets</div>
            <div class="stat-value">${info.dataset_count || 0}</div>
        </div>
    </div>`;

    // Narrative (collapsible)
    if (narrative) {
        html += `<details class="collapsible-section" open>
            <summary>Flight Narrative</summary>
            <div class="narrative-box"><p>${narrative.replace(/\n/g, '</p><p>')}</p></div>
        </details>`;
    }

    if (info.note) {
        html += `<div class="analysis-note">${info.note}</div>`;
    }

    // Phases (collapsible, before charts)
    if (phases.length > 0) {
        html += `<details class="collapsible-section" open>
            <summary>Flight Phases</summary>
            <table class="phase-table">
            <tr><th>Phase</th><th>Start</th><th>End</th><th>Duration</th></tr>`;
        phases.forEach(p => {
            const cls = 'phase-' + p.phase.toLowerCase();
            html += `<tr><td><span class="phase-tag ${cls}">${p.phase}</span></td>
                <td>${p.start}</td><td>${p.end}</td><td>${p.duration}</td></tr>`;
        });
        html += `</table></details>`;
    }

    // Battery + Anomalies (above charts)
    if (Object.keys(batt).length > 0) {
        html += `<div class="analysis-section collapsible-wrap"><h4>Battery Status</h4><div class="detail-grid">`;
        if (batt.voltage_min != null) html += `<div>Voltage: ${batt.voltage_min}V ~ ${batt.voltage_max}V</div>`;
        if (batt.current_max != null) html += `<div>Max Current: ${batt.current_max}A</div>`;
        if (batt.temp_max != null) html += `<div>Max Temp: ${batt.temp_max}&deg;C</div>`;
        if (batt.soc_consumed != null) html += `<div>SOC Consumed: ${batt.soc_consumed}%</div>`;
        html += `</div></div>`;
    }

    html += `<div class="analysis-section collapsible-wrap"><h4>Anomalies (${anomalies.length})</h4>`;
    if (anomalies.length === 0) {
        html += `<p class="no-anomaly">No anomalies detected</p>`;
    } else {
        html += `<table class="anomaly-table">
            <tr><th>Time</th><th>Type</th><th>Detail</th><th>Severity</th><th>Source</th></tr>`;
        anomalies.forEach(an => {
            const sevClass = an.severity === 'critical' ? 'sev-critical' : 'sev-warning';
            html += `<tr class="${sevClass}"><td>${an.time}</td><td>${an.type}</td>
                <td>${an.detail}</td><td>${an.severity}</td><td>${an.source}</td></tr>`;
        });
        html += `</table>`;
    }
    html += `</div>`;

    // ND / VD charts
    if (traj && traj.lat && traj.lat.length > 0) {
        const trajSrc = traj.source_dataset || '';
        const srcTag = trajSrc ? `<span class="chart-src">Source: ${trajSrc}</span>` : '';
        html += `<div class="chart-row">
            <div class="chart-box">
                <div class="chart-title-bar">
                    <h4>ND - Navigation Display ${srcTag}</h4>
                    <div class="zoom-controls">
                        <button class="btn-zoom" onclick="zoomND(1.3)" title="Zoom In">+</button>
                        <button class="btn-zoom" onclick="zoomND(0.7)" title="Zoom Out">&minus;</button>
                        <button class="btn-zoom" onclick="zoomND(0)" title="Reset">R</button>
                    </div>
                </div>
                <div id="chart-nd" class="analysis-chart"></div>
            </div>
            <div class="chart-box">
                <div class="chart-title-bar">
                    <h4>VD - Vertical Display ${srcTag}</h4>
                    <div class="zoom-controls">
                        <button class="btn-zoom" onclick="zoomVD(1.3)" title="Zoom In X">+</button>
                        <button class="btn-zoom" onclick="zoomVD(0.7)" title="Zoom Out X">&minus;</button>
                        <button class="btn-zoom" onclick="zoomVD(0)" title="Reset X">R</button>
                    </div>
                </div>
                <div id="chart-vd" class="analysis-chart"></div>
            </div>
        </div>`;
    }

    // Hidden event detail popup
    html += `<div id="event-popup" class="event-popup hidden">
        <div class="event-popup-content">
            <div class="event-popup-header"><h4 id="event-popup-title"></h4><button class="btn-close" onclick="closeEventPopup()">&times;</button></div>
            <div id="event-popup-body"></div>
        </div>
    </div>`;

    panel.innerHTML = html;

    // Render charts after DOM is ready
    if (traj && traj.lat && traj.lat.length > 0) {
        requestAnimationFrame(() => {
            renderNDChart(traj);
            renderVDChart(traj, events);
        });
    }
}

// ==================== ND/VD Linked Highlight ====================
function findClosestIndex(arr, target) {
    // Binary search for closest value in sorted array
    let lo = 0, hi = arr.length - 1;
    while (lo < hi) {
        const mid = (lo + hi) >> 1;
        if (arr[mid] < target) lo = mid + 1;
        else hi = mid;
    }
    if (lo > 0 && Math.abs(arr[lo - 1] - target) < Math.abs(arr[lo] - target)) lo--;
    return lo;
}

function highlightNDPoint(timeValue) {
    if (!ndChart || !ndTrajectory) return;
    const idx = findClosestIndex(ndTrajectory.time, timeValue);
    const lon = ndTrajectory.lon[idx];
    const lat = ndTrajectory.lat[idx];
    const t = ndTrajectory.time[idx];
    const h = Math.floor(t / 3600);
    const m = Math.floor((t % 3600) / 60);
    const s = Math.floor(t % 60);
    const timeStr = `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;

    ndChart.setOption({
        series: [{}, {}, {}, {}, {
            data: [[lon, lat, t]],
        }],
        graphic: [{
            type: 'text',
            left: 65,
            top: 5,
            style: {
                text: `${timeStr}  Lat:${lat.toFixed(5)} Lon:${lon.toFixed(5)}`,
                fill: '#e63946',
                fontSize: 12,
                fontWeight: 'bold',
            }
        }]
    });
}

function clearNDHighlight() {
    if (!ndChart) return;
    ndChart.setOption({
        series: [{}, {}, {}, {}, { data: [] }],
        graphic: [{ type: 'text', left: 65, top: 5, style: { text: '' } }]
    });
}

// ==================== ND Chart (Navigation Display) ====================
function renderNDChart(traj) {
    const dom = document.getElementById('chart-nd');
    if (!dom) return;
    if (ndChart) ndChart.dispose();
    ndChart = echarts.init(dom, getEchartsTheme());
    ndTrajectory = traj;

    // data: [lon, lat, time] — color by time progression
    const data = traj.lon.map((lon, i) => [lon, traj.lat[i], traj.time[i]]);
    const timeMin = Math.min(...traj.time);
    const timeMax = Math.max(...traj.time);
    const fmtTime = v => {
        const h = Math.floor(v / 3600), m = Math.floor((v % 3600) / 60), s = Math.floor(v % 60);
        return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
    };

    // Calculate equal-scale axis ranges
    // 1 degree latitude ~ 111km, 1 degree longitude ~ 111km * cos(lat)
    const latMin = Math.min(...traj.lat), latMax = Math.max(...traj.lat);
    const lonMin = Math.min(...traj.lon), lonMax = Math.max(...traj.lon);
    const latMid = (latMin + latMax) / 2;
    const cosLat = Math.cos(latMid * Math.PI / 180);

    const latRange = latMax - latMin;
    const lonRange = lonMax - lonMin;
    // Convert to km for comparison
    const latKm = latRange * 111;
    const lonKm = lonRange * 111 * cosLat;

    // Pad the smaller dimension so both represent equal physical distance
    let xMin = lonMin, xMax = lonMax, yMin = latMin, yMax = latMax;
    const padding = 0.15; // 15% margin
    if (lonKm > latKm && lonKm > 0) {
        const targetLatRange = lonRange / cosLat;
        const latCenter = (latMin + latMax) / 2;
        yMin = latCenter - targetLatRange / 2;
        yMax = latCenter + targetLatRange / 2;
    } else if (latKm > 0) {
        const targetLonRange = latRange * cosLat;
        const lonCenter = (lonMin + lonMax) / 2;
        xMin = lonCenter - targetLonRange / 2;
        xMax = lonCenter + targetLonRange / 2;
    }
    // Add padding
    const xPad = (xMax - xMin) * padding || 0.001;
    const yPad = (yMax - yMin) * padding || 0.001;
    xMin -= xPad; xMax += xPad;
    yMin -= yPad; yMax += yPad;

    // Store original ranges for reset
    ndChart._origRange = { xMin, xMax, yMin, yMax };

    ndChart.setOption({
        tooltip: {
            trigger: 'item',
            formatter: p => {
                if (!p.data || !Array.isArray(p.data)) return p.name;
                const idx = traj.lon.indexOf(p.data[0]);
                let timeStr = '';
                if (idx >= 0 && traj.time[idx]) {
                    const t = traj.time[idx];
                    const hh = Math.floor(t / 3600);
                    const mm = Math.floor((t % 3600) / 60);
                    const ss = Math.floor(t % 60);
                    timeStr = `Time: ${String(hh).padStart(2,'0')}:${String(mm).padStart(2,'0')}:${String(ss).padStart(2,'0')}<br>`;
                }
                const timeLabel = p.data[2] != null ? `Time: ${fmtTime(p.data[2])}<br>` : '';
                return `${timeStr}${timeLabel}Lon: ${p.data[0].toFixed(6)}<br>Lat: ${p.data[1].toFixed(6)}`;
            }
        },
        visualMap: {
            min: timeMin, max: timeMax, dimension: 2, seriesIndex: 0,
            inRange: { color: ['#313695','#4575b4','#74add1','#abd9e9','#fee090','#fdae61','#f46d43','#d73027'] },
            text: [fmtTime(timeMax), fmtTime(timeMin)], textStyle: { fontSize: 10 },
            right: 10, top: 'center', itemWidth: 12, itemHeight: 100,
            calculable: true, formatter: v => fmtTime(v),
        },
        grid: { left: 60, right: 80, top: 24, bottom: 40 },
        dataZoom: [
            { type: 'inside', xAxisIndex: 0, filterMode: 'none' },
            { type: 'inside', yAxisIndex: 0, filterMode: 'none' },
        ],
        xAxis: {
            type: 'value', name: 'Longitude (°E)', nameLocation: 'middle', nameGap: 25,
            min: xMin, max: xMax,
            axisLabel: { formatter: v => v.toFixed(3) },
        },
        yAxis: {
            type: 'value', name: 'Latitude (°N)', nameLocation: 'middle', nameGap: 40,
            min: yMin, max: yMax,
            axisLabel: { formatter: v => v.toFixed(3) },
        },
        series: [
            // 0: trajectory scatter (colored by time via visualMap)
            { type: 'scatter', data: data, symbolSize: 3, encode: { x: 0, y: 1 } },
            // 1: flow animation along trajectory (lines series)
            {
                type: 'lines',
                coordinateSystem: 'cartesian2d',
                polyline: true,
                data: [{
                    coords: traj.lon.map((lon, i) => [lon, traj.lat[i]]),
                }],
                lineStyle: { width: 0, opacity: 0 },
                effect: {
                    show: true,
                    period: 8,
                    trailLength: 0.15,
                    symbol: 'circle',
                    symbolSize: 3,
                    color: '#ff9800',
                },
                z: 5,
                silent: true,
            },
            // 2: start point
            {
                type: 'scatter',
                data: [[traj.lon[0], traj.lat[0], traj.time[0]]],
                symbolSize: 14, symbol: 'triangle',
                itemStyle: { color: '#28a745', borderColor: '#fff', borderWidth: 2 },
                z: 20, tooltip: { formatter: () => 'Start' },
            },
            // 3: end point
            {
                type: 'scatter',
                data: [[traj.lon[traj.lon.length-1], traj.lat[traj.lat.length-1], traj.time[traj.time.length-1]]],
                symbolSize: 14, symbol: 'rect',
                itemStyle: { color: '#dc3545', borderColor: '#fff', borderWidth: 2 },
                z: 20, tooltip: { formatter: () => 'End' },
            },
            // 4: cursor highlight (updated by VD hover)
            {
                type: 'scatter', data: [], symbolSize: 16,
                symbol: 'pin',
                itemStyle: { color: '#e63946', borderColor: '#fff', borderWidth: 2 },
                z: 100,
                tooltip: { formatter: p => {
                    if (!p.data) return '';
                    return `Cursor<br>Lon: ${p.data[0].toFixed(6)}<br>Lat: ${p.data[1].toFixed(6)}`;
                }},
            }
        ],
        graphic: [{ type: 'text', left: 65, top: 5, style: { text: '', fill: '#e63946', fontSize: 12 } }]
    });

    window.addEventListener('resize', () => ndChart && ndChart.resize());
}

function zoomND(factor) {
    if (!ndChart) return;
    if (factor === 0) {
        ndChart.dispatchAction({ type: 'dataZoom', dataZoomIndex: 0, start: 0, end: 100 });
        ndChart.dispatchAction({ type: 'dataZoom', dataZoomIndex: 1, start: 0, end: 100 });
        return;
    }
    // Zoom both axes by factor (>1 = zoom in, <1 = zoom out)
    [0, 1].forEach(idx => {
        const opt = ndChart.getOption().dataZoom[idx];
        const start = opt.start || 0, end = opt.end || 100;
        const center = (start + end) / 2;
        const half = (end - start) / 2 / factor;
        ndChart.dispatchAction({
            type: 'dataZoom', dataZoomIndex: idx,
            start: Math.max(0, center - half),
            end: Math.min(100, center + half)
        });
    });
}

// ==================== VD Chart (Vertical Display) ====================
function renderVDChart(traj, events) {
    const dom = document.getElementById('chart-vd');
    if (!dom) return;
    if (vdChart) vdChart.dispose();
    vdChart = echarts.init(dom, getEchartsTheme());
    events = events || [];

    // Build event scatter data: find altitude at each event time
    const altData = traj.time.map((t, i) => [t, traj.alt[i]]);
    let eventScatterData = [];
    if (events.length > 0) {
        events.slice(0, 80).forEach(ev => {
            let lo = 0, hi = traj.time.length - 1;
            while (lo < hi) {
                const mid = (lo + hi) >> 1;
                if (traj.time[mid] < ev.time_seconds) lo = mid + 1;
                else hi = mid;
            }
            if (lo > 0 && Math.abs(traj.time[lo-1] - ev.time_seconds) < Math.abs(traj.time[lo] - ev.time_seconds)) lo--;
            const alt = traj.alt[lo];
            const isErr = ev.label.includes('Err') || ev.label.includes('CAS');
            eventScatterData.push({
                value: [ev.time_seconds, alt],
                _label: ev.label,
                _dataset: ev.dataset || '',
                _source: ev.source || '',
                _from: ev.from || '',
                _to: ev.to || '',
                _group: ev.group || null,
                _isErr: isErr,
            });
        });
    }

    const seriesList = [
        {
            name: 'Altitude (m)', type: 'line', symbol: 'none', sampling: 'lttb',
            data: altData,
            lineStyle: { width: 2, color: '#4361ee' },
            areaStyle: {
                color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                    { offset: 0, color: 'rgba(67,97,238,0.35)' },
                    { offset: 1, color: 'rgba(67,97,238,0.02)' }
                ])
            },
            yAxisIndex: 0,
        }
    ];

    const yAxes = [
        { type: 'value', name: 'Altitude (m)', nameLocation: 'middle', nameGap: 55,
          position: 'left', scale: true,
          axisLine: { lineStyle: { color: '#4361ee' } } }
    ];

    if (traj.speed) {
        seriesList.push({
            name: 'Ground Speed (m/s)', type: 'line', symbol: 'none', sampling: 'lttb',
            data: traj.time.map((t, i) => [t, traj.speed[i]]),
            lineStyle: { width: 1.5, color: '#e63946' }, yAxisIndex: 1,
        });
        yAxes.push({
            type: 'value', name: 'Speed (m/s)', nameLocation: 'middle', nameGap: 55,
            position: 'right', scale: true,
            axisLine: { lineStyle: { color: '#e63946' } }, splitLine: { show: false },
        });
    }

    // Add event markers as a separate scatter series on the altitude Y axis
    if (eventScatterData.length > 0) {
        seriesList.push({
            name: 'Events',
            type: 'scatter',
            data: eventScatterData,
            symbolSize: d => d._isErr ? 10 : 7,
            itemStyle: { color: p => p.data._isErr ? '#dc3545' : '#ff9800', borderColor: '#fff', borderWidth: 1 },
            yAxisIndex: 0,
            z: 20,
        });
    }

    vdChart.setOption({
        tooltip: {
            trigger: 'axis',
            axisPointer: { type: 'line', snap: true },
            formatter: params => {
                if (!params || !params.length) return '';
                const t = params[0].axisValue;
                const h = Math.floor(t / 3600);
                const m = Math.floor((t % 3600) / 60);
                let html = `<strong>${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(Math.floor(t%60)).padStart(2,'0')} (${t.toFixed(1)}s)</strong><br>`;
                params.forEach(p => {
                    if (p.seriesName === 'Events') {
                        // Show event label + dataset
                        const d = p.data;
                        html += `${p.marker} <strong>${d._label}</strong>${d._dataset ? ' <span style="color:#888">(' + d._dataset + ')</span>' : ''}<br>`;
                    } else {
                        html += `${p.marker} ${p.seriesName}: <strong>${p.value[1] != null ? p.value[1].toFixed(2) : 'N/A'}</strong><br>`;
                    }
                });
                return html;
            }
        },
        legend: { top: 0, left: 'center', data: seriesList.filter(s => s.name !== 'Events').map(s => s.name) },
        grid: { left: 80, right: traj.speed ? 80 : 30, top: 30, bottom: 50 },
        xAxis: {
            type: 'value', name: 'Time', nameLocation: 'middle', nameGap: 25,
            min: Math.max(0, Math.min(...traj.time) - 300),  // 5 min before
            max: Math.max(...traj.time) + 300,                // 5 min after
            axisPointer: { show: true, snap: true },
            axisLabel: {
                formatter: v => {
                    const h = Math.floor(v / 3600);
                    const m = Math.floor((v % 3600) / 60);
                    const s = Math.floor(v % 60);
                    return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
                }
            }
        },
        yAxis: yAxes,
        dataZoom: [
            { type: 'inside', xAxisIndex: 0, filterMode: 'none' },
            { type: 'slider', xAxisIndex: 0, filterMode: 'none', height: 18, bottom: 5 }
        ],
        series: seriesList,
    });

    // Link VD -> ND: on axis pointer move, highlight corresponding point on ND
    vdChart.on('updateAxisPointer', (event) => {
        if (event.axesInfo && event.axesInfo.length > 0) {
            const val = event.axesInfo[0].value;
            if (val != null) highlightNDPoint(val);
        }
    });

    // Clear highlight when mouse leaves VD chart
    dom.addEventListener('mouseleave', () => clearNDHighlight());

    // Click on event marker -> show detail popup
    vdChart.on('click', 'series.scatter', (params) => {
        if (params.seriesName === 'Events' && params.data) {
            showEventPopup(params.data);
        }
    });

    window.addEventListener('resize', () => vdChart && vdChart.resize());
}

function showEventPopup(d) {
    const popup = document.getElementById('event-popup');
    const title = document.getElementById('event-popup-title');
    const body = document.getElementById('event-popup-body');

    const t = d.value[0];
    const hh = Math.floor(t / 3600);
    const mm = Math.floor((t % 3600) / 60);
    const ss = Math.floor(t % 60);
    const timeStr = `${String(hh).padStart(2,'0')}:${String(mm).padStart(2,'0')}:${String(ss).padStart(2,'0')}`;

    title.textContent = `Event: ${d._label} @ ${timeStr}`;

    // Determine the primary dataset for the "Go to Data" button
    let primaryDataset = d._dataset || '';
    let eventTime = d.value[0];

    let html = '<table class="event-detail-table">';

    if (d._group && d._group.length > 0) {
        html += '<tr><th>Change</th><th>Column</th><th>From</th><th>To</th><th>Dataset</th></tr>';
        d._group.forEach(g => {
            if (!primaryDataset && g.dataset) primaryDataset = g.dataset;
            html += `<tr>
                <td><strong>${g.label}</strong></td>
                <td class="ev-col">${(g.source || '').split('.').pop()}</td>
                <td class="ev-val">${g.from || ''}</td>
                <td class="ev-val">${g.to || ''}</td>
                <td class="ev-ds">${g.dataset || ''}</td>
            </tr>`;
        });
    } else {
        html += '<tr><th>Field</th><th>Value</th></tr>';
        html += `<tr><td>Label</td><td><strong>${d._label}</strong></td></tr>`;
        html += `<tr><td>Column</td><td class="ev-col">${(d._source || '').split('.').pop()}</td></tr>`;
        html += `<tr><td>Dataset</td><td>${d._dataset}</td></tr>`;
        html += `<tr><td>From</td><td class="ev-val">${d._from}</td></tr>`;
        html += `<tr><td>To</td><td class="ev-val">${d._to}</td></tr>`;
        html += `<tr><td>Altitude</td><td>${d.value[1].toFixed(1)} m</td></tr>`;
    }

    html += '</table>';
    html += `<div class="event-popup-actions">`;
    if (primaryDataset) {
        html += `<button class="btn btn-primary" onclick="goToEventData('${primaryDataset}', ${eventTime})">Go to Data Table</button>`;
    }
    html += `<button class="btn btn-secondary" onclick="closeEventPopup()">Close</button>`;
    html += `</div>`;

    body.innerHTML = html;
    popup.classList.remove('hidden');
}

function closeEventPopup() {
    document.getElementById('event-popup').classList.add('hidden');
}

// Track which time to highlight in the table
let highlightTimeSeconds = null;

async function goToEventData(datasetShortName, timeSeconds) {
    closeEventPopup();

    // Collapse all collapsible sections in the analysis panel
    document.querySelectorAll('.analysis-panel details[open]').forEach(el => {
        el.removeAttribute('open');
    });

    // Find the dataset by short name match
    const ds = allDatasets.find(d => {
        const short = d.name.replace(/_\d{9,}$/, '');
        return short === datasetShortName;
    });

    if (!ds) {
        alert('Dataset not found: ' + datasetShortName);
        return;
    }

    // Select the dataset first (loads columns + page 0 — don't highlight yet)
    highlightTimeSeconds = null;
    await selectDataset(ds.id);

    // Highlight it in the sidebar
    document.querySelectorAll('.dataset-item').forEach(el => {
        el.classList.toggle('active', parseInt(el.dataset.id) === ds.id);
    });

    // Now calculate which page contains the event time and reload with highlight
    try {
        const resp = await fetch(
            `/api/datasets/${ds.id}/data?time_max=${timeSeconds}&limit=1&offset=0`
        );
        const data = await resp.json();
        const rowsBefore = data.total_rows;

        const targetPage = Math.max(0, Math.floor((rowsBefore - PAGE_SIZE / 2) / PAGE_SIZE));
        currentPage = targetPage;

        // NOW set highlight time, right before the render that should use it
        highlightTimeSeconds = timeSeconds;
        await loadTablePage();

        // Scroll the table container into view
        document.getElementById('table-container').scrollIntoView({ behavior: 'smooth', block: 'start' });

        // Scroll to the highlighted row within the table wrapper
        requestAnimationFrame(() => {
            const hlRow = document.querySelector('tr.event-highlight');
            if (hlRow) {
                hlRow.scrollIntoView({ behavior: 'smooth', block: 'center' });
            }
        });
    } catch (e) {
        console.error('Failed to navigate to event data:', e);
    }
}

function zoomVD(factor) {
    if (!vdChart) return;
    if (factor === 0) {
        // Reset X axis zoom
        vdChart.dispatchAction({ type: 'dataZoom', dataZoomIndex: 0, start: 0, end: 100 });
        vdChart.dispatchAction({ type: 'dataZoom', dataZoomIndex: 1, start: 0, end: 100 });
        return;
    }
    const opt = vdChart.getOption().dataZoom[0];
    const start = opt.start || 0, end = opt.end || 100;
    const center = (start + end) / 2;
    const half = (end - start) / 2 / factor;
    vdChart.dispatchAction({
        type: 'dataZoom', dataZoomIndex: 0,
        start: Math.max(0, center - half),
        end: Math.min(100, center + half)
    });
    vdChart.dispatchAction({
        type: 'dataZoom', dataZoomIndex: 1,
        start: Math.max(0, center - half),
        end: Math.min(100, center + half)
    });
}

// ==================== Upload Summary ====================
function buildUploadSummary(task) {
    const s = task.upload_summary || {};
    const results = s.merge_details || [];
    const skipped = s.skipped_details || [];
    const failed = s.failed_details || [];
    const nonCsv = s.non_csv_skipped || [];

    let html = `<div class="upload-summary">
        <h3>Upload Complete</h3>
        <div class="summary-stats">
            <div class="ss-item"><span class="ss-num">${s.csv_files_count || 0}</span><span class="ss-label">CSV files received</span></div>
            <div class="ss-item"><span class="ss-num">${s.total_groups || 0}</span><span class="ss-label">file groups detected</span></div>
            <div class="ss-item ss-ok"><span class="ss-num">${s.datasets_created || 0}</span><span class="ss-label">datasets created</span></div>`;
    if (s.groups_skipped > 0)
        html += `<div class="ss-item ss-skip"><span class="ss-num">${s.groups_skipped}</span><span class="ss-label">groups skipped</span></div>`;
    if (s.groups_failed > 0)
        html += `<div class="ss-item ss-fail"><span class="ss-num">${s.groups_failed}</span><span class="ss-label">groups failed</span></div>`;
    html += `</div>`;

    // Merge details (collapsible)
    html += `<details class="summary-section"><summary>Merge Details (${results.length} datasets, ${s.total_source_files_merged || 0} files merged)</summary>
        <table class="summary-table"><tr><th>Dataset</th><th>Files Merged</th><th>Source Files</th></tr>`;
    results.forEach(r => {
        html += `<tr><td title="${r.name}">${r.short_name}</td><td>${r.files_merged}</td>
            <td class="src-files">${(r.source_files || []).join(', ')}</td></tr>`;
    });
    html += `</table></details>`;

    // Skipped groups
    if (skipped.length > 0) {
        html += `<details class="summary-section summary-warn"><summary>Skipped Groups (${skipped.length})</summary>
            <table class="summary-table"><tr><th>Group</th><th>Files</th><th>Reason</th></tr>`;
        skipped.forEach(g => {
            html += `<tr><td>${g.short_name}</td><td>${g.files}</td><td>${g.reason}</td></tr>`;
        });
        html += `</table></details>`;
    }

    // Failed groups
    if (failed.length > 0) {
        html += `<details class="summary-section summary-err" open><summary>Failed Groups (${failed.length})</summary>
            <table class="summary-table"><tr><th>Group</th><th>Files</th><th>Error</th></tr>`;
        failed.forEach(g => {
            html += `<tr><td>${g.short_name}</td><td>${g.files}</td><td>${g.reason}</td></tr>`;
        });
        html += `</table></details>`;
    }

    // Non-CSV files
    if (nonCsv.length > 0) {
        html += `<details class="summary-section"><summary>Non-CSV Files Ignored (${nonCsv.length})</summary>
            <div class="non-csv-list">${nonCsv.join(', ')}</div></details>`;
    }

    html += `<button class="btn btn-primary" style="margin-top:12px" onclick="toggleUploadPanel(); loadDatasets();">View Data</button></div>`;
    return html;
}

// ==================== Utils ====================
function truncate(str, maxLen) {
    if (!str) return '';
    return str.length > maxLen ? str.substring(0, maxLen) + '...' : str;
}
