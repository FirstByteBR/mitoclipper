/* ═══════════════════════════════════════════════════════════════════════════
   MitoClipper — Frontend Application Logic
   ═══════════════════════════════════════════════════════════════════════════ */

// ─── Utilities ───────────────────────────────────────────────────────────────

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

async function api(path, options = {}) {
  const { method = 'GET', body } = options;
  const opts = { method, headers: {} };
  if (body) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(`/api${path}`, opts);
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

function toast(message, type = 'success') {
  const container = $('#toast-container');
  const el = document.createElement('div');
  el.className = `toast toast--${type}`;
  el.textContent = message;
  container.appendChild(el);
  setTimeout(() => {
    el.style.opacity = '0';
    el.style.transform = 'translateY(10px)';
    el.style.transition = '300ms ease';
    setTimeout(() => el.remove(), 300);
  }, 3500);
}

function formatDuration(sec) {
  if (sec == null) return '—';
  if (sec < 60) return `${sec.toFixed(1)}s`;
  const m = Math.floor(sec / 60);
  const s = (sec % 60).toFixed(0);
  return `${m}m ${s}s`;
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1048576).toFixed(1)} MB`;
}

function closeModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.remove('active');
  // Pause any playing video
  const video = el?.querySelector('video');
  if (video) { video.pause(); video.src = ''; }
}

function openModal(id) {
  document.getElementById(id)?.classList.add('active');
}

// ─── Navigation ──────────────────────────────────────────────────────────────

const navLinks = $$('.navbar__link');
const pages = $$('.page');

function navigateTo(pageName) {
  navLinks.forEach(l => l.classList.toggle('active', l.dataset.page === pageName));
  pages.forEach(p => p.classList.toggle('active', p.id === `page-${pageName}`));

  // Trigger page-specific loads
  if (pageName === 'clips') loadClips();
  if (pageName === 'status') { loadMetrics(); loadLogs(); }
}

navLinks.forEach(link => {
  link.addEventListener('click', () => navigateTo(link.dataset.page));
});

// ─── Create Page ─────────────────────────────────────────────────────────────

// Advanced toggle
$('#btn-toggle-advanced').addEventListener('click', () => {
  const panel = $('#advanced-settings');
  panel.classList.toggle('show');
  const chevron = $('#btn-toggle-advanced svg');
  chevron.style.transform = panel.classList.contains('show') ? 'rotate(180deg)' : '';
});

// Style picker
const stylePicker = $('#style-picker');
let selectedStyle = 'hormozi';

stylePicker.addEventListener('click', (e) => {
  const option = e.target.closest('.style-picker__option');
  if (!option) return;
  stylePicker.querySelectorAll('.style-picker__option').forEach(o => o.classList.remove('selected'));
  option.classList.add('selected');
  selectedStyle = option.dataset.style;
});

// Auto-upload toggle reveals privacy selector
$('#check-upload').addEventListener('change', (e) => {
  $('#yt-privacy-row').style.display = e.target.checked ? 'grid' : 'none';
});

// Run pipeline
$('#btn-run-pipeline').addEventListener('click', async () => {
  const url = $('#input-url').value.trim();
  if (!url) {
    toast('Please enter a video URL or path', 'error');
    return;
  }

  const body = {
    url,
    top_k: parseInt($('#input-topk').value) || 3,
    max_duration: parseInt($('#input-max-duration').value) || 60,
    min_clip_duration: parseFloat($('#input-min-clip').value) || 15,
    target_clip_duration: parseFloat($('#input-target-clip').value) || 35,
    subtitle_style: selectedStyle,
    subtitle_font: $('#input-font').value.trim() || null,
    no_vertical: !$('#check-vertical').checked,
    no_face: !$('#check-face').checked,
    no_heatmap: !$('#check-heatmap').checked,
    auto_upload: $('#check-upload').checked,
    youtube_privacy: $('#input-privacy').value,
  };

  try {
    $('#btn-run-pipeline').disabled = true;
    await api('/pipeline/run', { method: 'POST', body });
    toast('Pipeline started!');
    startProgressPolling();
  } catch (err) {
    toast(err.message, 'error');
    $('#btn-run-pipeline').disabled = false;
  }
});

// ─── Pipeline Progress Polling ───────────────────────────────────────────────

let progressInterval = null;
const STEP_ORDER = ['download', 'video_duration', 'audio_extraction', 'transcription', 'analysis', 'metadata', 'clip_generation', 'youtube_upload'];

function startProgressPolling() {
  const panel = $('#progress-panel');
  panel.classList.add('active');
  updatePipelineBadge('running');

  if (progressInterval) clearInterval(progressInterval);
  progressInterval = setInterval(pollProgress, 1500);
  pollProgress();
}

async function pollProgress() {
  try {
    const data = await api('/pipeline/status');
    renderProgress(data);

    if (data.status === 'done' || data.status === 'failed') {
      clearInterval(progressInterval);
      progressInterval = null;
      $('#btn-run-pipeline').disabled = false;
      updatePipelineBadge(data.status);

      if (data.status === 'done') {
        toast('Pipeline completed! Your clips are ready.', 'success');
      } else {
        toast(`Pipeline failed: ${data.error || 'Unknown error'}`, 'error');
      }
    }
  } catch (err) {
    // Silently retry
  }
}

function renderProgress(data) {
  const steps = data.steps || {};
  const currentStage = data.stage;
  const stepEls = $$('#progress-steps .progress-step');
  let doneCount = 0;

  stepEls.forEach(el => {
    const stepName = el.dataset.step;
    el.classList.remove('done', 'active', 'failed');

    if (steps[stepName] === true) {
      el.classList.add('done');
      doneCount++;
    } else if (stepName === currentStage && data.status === 'running') {
      el.classList.add('active');
      doneCount += 0.5; // half-credit for in-progress
    } else if (data.status === 'failed' && stepName === currentStage) {
      el.classList.add('failed');
    }
  });

  // Progress bar
  const pct = Math.min(100, (doneCount / STEP_ORDER.length) * 100);
  $('#progress-bar-fill').style.width = `${pct}%`;

  // Elapsed
  $('#progress-elapsed').textContent = data.elapsed_sec != null ? formatDuration(data.elapsed_sec) : '--';

  // Status badge
  const badge = $('#progress-status-badge');
  badge.textContent = capitalize(data.status);
  badge.className = `badge badge--${data.status === 'done' ? 'done' : data.status === 'failed' ? 'failed' : 'running'}`;
}

function updatePipelineBadge(status) {
  const badge = $('#pipeline-badge');
  const map = { idle: 'badge--idle', running: 'badge--running', done: 'badge--done', failed: 'badge--failed' };
  badge.className = `badge ${map[status] || 'badge--idle'}`;
  badge.textContent = capitalize(status);
}

function capitalize(str) {
  return str ? str.charAt(0).toUpperCase() + str.slice(1) : '';
}

// ─── Clips Page ──────────────────────────────────────────────────────────────

let clipsData = [];

async function loadClips() {
  try {
    clipsData = await api('/clips');
    renderClips(clipsData);
  } catch (err) {
    toast('Failed to load clips', 'error');
  }
}

function renderClips(clips) {
  const grid = $('#clip-grid');
  const empty = $('#clips-empty');
  const count = $('#clips-count');

  if (!clips.length) {
    grid.innerHTML = '';
    empty.style.display = 'block';
    count.textContent = 'No clips found';
    return;
  }

  empty.style.display = 'none';
  count.textContent = `${clips.length} clip${clips.length !== 1 ? 's' : ''} found`;

  grid.innerHTML = clips.map((clip, i) => `
    <div class="card clip-card" data-filename="${esc(clip.filename)}" data-idx="${i}">
      <div class="clip-card__preview" onclick="previewClip('${esc(clip.filename)}', '${esc(clip.title || clip.basename)}')">
        <video src="/api/clips/${encodeURIComponent(clip.filename)}/stream" preload="metadata" muted></video>
        <div class="clip-card__preview-overlay">
          <svg viewBox="0 0 24 24"><polygon points="5 3 19 12 5 21 5 3"/></svg>
        </div>
      </div>
      <div class="clip-card__body">
        <div class="clip-card__title">
          <input type="text" value="${esc(clip.title || clip.basename)}" 
                 data-filename="${esc(clip.filename)}" 
                 data-field="title"
                 onchange="saveClipField(this)">
        </div>
        <div class="clip-card__meta">${clip.size_mb} MB • ${new Date(clip.created).toLocaleDateString()}</div>
        <div class="clip-card__description">
          <textarea placeholder="Add a description..." 
                    data-filename="${esc(clip.filename)}"
                    data-field="description"
                    onchange="saveClipField(this)">${esc(clip.description || '')}</textarea>
        </div>
        <div class="clip-card__actions">
          <button class="btn btn--secondary btn--sm" onclick="downloadClip('${esc(clip.filename)}')">
            <svg viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
            Download
          </button>
          <button class="btn btn--success btn--sm" onclick="uploadClip('${esc(clip.filename)}')">
            <svg viewBox="0 0 24 24"><path d="M22.54 6.42a2.78 2.78 0 0 0-1.94-2C18.88 4 12 4 12 4s-6.88 0-8.6.46a2.78 2.78 0 0 0-1.94 2A29 29 0 0 0 1 11.75a29 29 0 0 0 .46 5.33A2.78 2.78 0 0 0 3.4 19.13C5.12 19.56 12 19.56 12 19.56s6.88 0 8.6-.46a2.78 2.78 0 0 0 1.94-2 29 29 0 0 0 .46-5.37 29 29 0 0 0-.46-5.31z"/><polygon points="9.75 15.02 15.5 11.75 9.75 8.48 9.75 15.02" fill="currentColor" stroke="none"/></svg>
            YouTube
          </button>
          <button class="btn btn--danger btn--sm" onclick="confirmDeleteClip('${esc(clip.filename)}')">
            <svg viewBox="0 0 24 24"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
            Delete
          </button>
        </div>
      </div>
    </div>
  `).join('');
}

function esc(str) {
  if (!str) return '';
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// Clip Actions

function previewClip(filename, title) {
  const player = $('#video-modal-player');
  player.src = `/api/clips/${encodeURIComponent(filename)}/stream`;
  $('#video-modal-title').textContent = title || filename;
  openModal('video-modal');
  player.play();
}

$('#video-modal-close').addEventListener('click', () => closeModal('video-modal'));
$('#video-modal').addEventListener('click', (e) => {
  if (e.target === $('#video-modal')) closeModal('video-modal');
});

function downloadClip(filename) {
  const a = document.createElement('a');
  a.href = `/api/clips/${encodeURIComponent(filename)}/download`;
  a.download = filename;
  a.click();
}

async function saveClipField(el) {
  const filename = el.dataset.filename;
  const field = el.dataset.field;
  const value = el.value.trim();
  try {
    await api(`/clips/${encodeURIComponent(filename)}/metadata`, {
      method: 'PUT',
      body: { [field]: value },
    });
    toast(`${capitalize(field)} saved`, 'success');
  } catch (err) {
    toast(`Failed to save ${field}`, 'error');
  }
}

let pendingDeleteFilename = null;

function confirmDeleteClip(filename) {
  pendingDeleteFilename = filename;
  $('#delete-clip-name').textContent = filename;
  openModal('delete-modal');
}

$('#btn-confirm-delete').addEventListener('click', async () => {
  if (!pendingDeleteFilename) return;
  try {
    await api(`/clips/${encodeURIComponent(pendingDeleteFilename)}`, { method: 'DELETE' });
    toast('Clip deleted');
    closeModal('delete-modal');
    loadClips();
  } catch (err) {
    toast(err.message, 'error');
  }
  pendingDeleteFilename = null;
});

async function uploadClip(filename) {
  try {
    toast('Uploading to YouTube...', 'success');
    const result = await api(`/clips/${encodeURIComponent(filename)}/upload`, {
      method: 'POST',
      body: { privacy: 'unlisted' },
    });
    toast('Uploaded to YouTube!', 'success');
  } catch (err) {
    toast(`Upload failed: ${err.message}`, 'error');
  }
}

$('#btn-refresh-clips').addEventListener('click', loadClips);

// ─── Status Page ─────────────────────────────────────────────────────────────

async function loadMetrics() {
  try {
    const data = await api('/metrics');

    $('#metric-runs').textContent = data.runs ?? '—';
    $('#metric-failures').textContent = data.failures ?? '—';

    const lr = data.last_run;
    if (lr) {
      $('#metric-duration').textContent = formatDuration(lr.duration_sec);
      const statusEl = $('#metric-last-status');
      statusEl.textContent = capitalize(lr.status || '—');
      statusEl.className = `metric-card__value ${lr.status === 'done' ? 'success' : lr.status === 'failed' ? 'danger' : 'accent'}`;

      // Steps timeline
      renderStepsTimeline(lr.steps);
    }
  } catch (err) {
    // silent
  }
}

function renderStepsTimeline(steps) {
  const container = $('#steps-timeline');
  if (!steps || !Object.keys(steps).length) {
    container.innerHTML = '<div class="text-muted" style="font-size: 0.85rem; padding: 12px;">No run data available yet.</div>';
    return;
  }

  const durations = Object.values(steps).map(s => s.duration_sec || 0);
  const maxDur = Math.max(...durations, 0.01);

  container.innerHTML = Object.entries(steps).map(([name, info]) => {
    const dur = info.duration_sec || 0;
    const pct = (dur / maxDur) * 100;
    return `
      <div class="step-row">
        <div class="step-row__name">${capitalize(name.replace(/_/g, ' '))}</div>
        <div class="step-row__bar">
          <div class="step-row__bar-fill" style="width: ${pct}%"></div>
        </div>
        <div class="step-row__duration">${dur.toFixed(1)}s</div>
      </div>
    `;
  }).join('');
}

async function loadLogs() {
  try {
    const data = await api('/logs?lines=100');
    const viewer = $('#log-viewer');

    if (!data.lines || !data.lines.length) {
      viewer.innerHTML = '<div class="text-muted">No logs available.</div>';
      return;
    }

    viewer.innerHTML = data.lines.map(line => {
      let cls = 'log-line';
      if (/ERROR/i.test(line)) cls += ' log-line--error';
      else if (/WARNING/i.test(line)) cls += ' log-line--warning';
      else cls += ' log-line--info';
      return `<div class="${cls}">${escHtml(line)}</div>`;
    }).join('');

    // Scroll to bottom
    viewer.scrollTop = viewer.scrollHeight;
  } catch (err) {
    // silent
  }
}

function escHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

$('#btn-refresh-status').addEventListener('click', () => { loadMetrics(); loadLogs(); });
$('#btn-refresh-logs').addEventListener('click', loadLogs);

// ─── Init ────────────────────────────────────────────────────────────────────

// Check if pipeline is currently running on page load
(async function init() {
  try {
    const status = await api('/pipeline/status');
    if (status.status === 'running') {
      startProgressPolling();
    }
    updatePipelineBadge(status.status);
  } catch (err) {
    // Server might not be fully ready
  }
})();
