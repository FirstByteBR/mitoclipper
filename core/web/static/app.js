document.addEventListener("DOMContentLoaded", () => {
  const clipCards = Array.from(document.querySelectorAll('.clip-card'));
  const mainPlayer = document.querySelector('#main-clip-player');
  const mainSource = document.querySelector('#main-clip-source');
  const playerTitle = document.querySelector('#player-title');
  const downloadCurrent = document.querySelector('#download-current');
  const warningBox = document.querySelector('#player-warning');

  if (!mainPlayer || clipCards.length === 0) return;

  function setActiveCard(card) {
    clipCards.forEach(c => c.classList.toggle('active', c === card));
    const src = card.dataset.src;
    const name = card.dataset.name;
    mainSource.setAttribute('src', src);
    mainSource.setAttribute('type', src.endsWith('.mp4') ? 'video/mp4' : 'video/webm');
    playerTitle.textContent = name;
    downloadCurrent.setAttribute('href', src);
    downloadCurrent.setAttribute('download', name);
    warningBox.classList.add('d-none');
    mainPlayer.load();
    mainPlayer.play().catch(() => {
      // not all browsers auto-play; ignore
    });
  }

  clipCards.forEach(card => {
    card.addEventListener('click', () => setActiveCard(card));
  });

  const deleteButtons = Array.from(document.querySelectorAll('.btn-delete'));
  const renameButtons = Array.from(document.querySelectorAll('.btn-rename'));

  deleteButtons.forEach(btn => {
    btn.addEventListener('click', async (event) => {
      event.stopPropagation();
      const clipName = btn.dataset.name;
      if (!confirm(`Delete clip ${clipName}?`)) return;
      const resp = await fetch('/api/clips/delete', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({clip_name: clipName}),
      });
      const data = await resp.json();
      if (resp.ok) {
        window.location.reload();
      } else {
        alert(data.error || 'Delete failed');
      }
    });
  });

  renameButtons.forEach(btn => {
    btn.addEventListener('click', async (event) => {
      event.stopPropagation();
      const clipName = btn.dataset.name;
      const newName = prompt('New file name', clipName);
      if (!newName || newName === clipName) return;
      const resp = await fetch('/api/clips/rename', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({clip_name: clipName, new_name: newName}),
      });
      const data = await resp.json();
      if (resp.ok) {
        window.location.reload();
      } else {
        alert(data.error || 'Rename failed');
      }
    });
  });

  const generateBtn = document.querySelector('#generate-metadata-btn');
  const metadataResults = document.querySelector('#metadata-results');
  if (generateBtn) {
    generateBtn.addEventListener('click', async () => {
      generateBtn.disabled = true;
      generateBtn.textContent = 'Generating...';
      try {
        const resp = await fetch('/api/clips/generate', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({}),
        });
        const data = await resp.json();
        if (resp.ok) {
          metadataResults.classList.remove('d-none');
          metadataResults.innerHTML = '<strong>✓ Metadata generated!</strong><pre style="max-height:300px; overflow-y:auto">' + JSON.stringify(data.metadata, null, 2) + '</pre>';
        } else {
          metadataResults.classList.remove('d-none');
          metadataResults.innerHTML = '<strong>Error:</strong> ' + (data.error || 'Could not generate metadata');
        }
      } catch (err) {
        metadataResults.classList.remove('d-none');
        metadataResults.innerHTML = '<strong>Error:</strong> ' + String(err);
      } finally {
        generateBtn.disabled = false;
        generateBtn.textContent = 'Generate Catchy Titles & Descriptions';
      }
    });
  }

  const publishBtn = document.querySelector('#publish-youtube-btn');
  const publishResults = document.querySelector('#youtube-publish-results');
  if (publishBtn) {
    publishBtn.addEventListener('click', async () => {
      publishBtn.disabled = true;
      publishBtn.textContent = 'Publishing...';
      publishResults.classList.remove('d-none');
      publishResults.innerHTML = 'Uploading clips to YouTube (uses youtube-upload CLI).';
      try {
        const resp = await fetch('/api/clips/youtube_publish', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({}),
        });
        const data = await resp.json();
        if (resp.ok) {
          publishResults.classList.remove('alert-info');
          publishResults.classList.add('alert-success');
          publishResults.innerHTML = '<strong>✓ Upload completed!</strong><pre style="max-height:250px; overflow-y:auto">' + JSON.stringify(data.upload, null, 2) + '</pre>';
        } else {
          publishResults.classList.remove('alert-info');
          publishResults.classList.add('alert-danger');
          publishResults.innerHTML = '<strong>Error:</strong> ' + (data.error || 'Upload failed');
        }
      } catch (err) {
        publishResults.classList.remove('alert-info');
        publishResults.classList.add('alert-danger');
        publishResults.innerHTML = '<strong>Error:</strong> ' + String(err);
      } finally {
        publishBtn.disabled = false;
        publishBtn.textContent = 'Publish Clips to YouTube';
      }
    });
  }

  // YouTube pack modal
  const youtubeModal = document.querySelector('#youtubeModal');
  if (youtubeModal) {
    youtubeModal.addEventListener('show.bs.modal', async () => {
      const body = document.querySelector('#youtube-pack-body');
      body.innerHTML = '<p class="text-muted">Loading...</p>';
      try {
        const resp = await fetch('/api/clips/youtube_data');
        const data = await resp.json();
        if (resp.ok && data.youtube_ready) {
          const html = data.youtube_ready.map((item, idx) => `
            <div class="card bg-dark border-secondary mb-2">
              <div class="card-body">
                <p class="mb-1"><strong>#${idx + 1} - ${item.clip_name}</strong></p>
                <p class="mb-2"><small><strong>Title:</strong> ${item.title || 'N/A'}</small></p>
                <p class="mb-2"><small><strong>Desc:</strong> ${(item.description || 'N/A').substring(0, 140)}...</small></p>
                <a href="${item.download_url}" class="btn btn-sm btn-outline-light" download>Download</a>
              </div>
            </div>
          `).join('');
          body.innerHTML = html;
        } else {
          body.innerHTML = '<p class="text-danger">Failed to load YouTube pack</p>';
        }
      } catch (err) {
        body.innerHTML = '<p class="text-danger">Error: ' + String(err) + '</p>';
      }
    });
  }

  let videoLoadStarted = false;
  let videoSuccessfullyLoaded = false;

  mainPlayer.addEventListener('loadstart', () => {
    videoLoadStarted = true;
    videoSuccessfullyLoaded = false;
    warningBox.classList.add('d-none');
  });

  mainPlayer.addEventListener('canplay', () => {
    videoSuccessfullyLoaded = true;
    warningBox.classList.add('d-none');
  });

  mainPlayer.addEventListener('error', (e) => {
    if (videoSuccessfullyLoaded) return; // ignore errors after successful plays
    if (mainPlayer.networkState === 3) { // NETWORK_NO_SOURCE
      warningBox.classList.remove('d-none');
    }
  });

  // Initialize first card active
  setActiveCard(clipCards[0]);
});