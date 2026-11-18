/* SaveVido native desktop updater UI. Hidden from ordinary website visitors. */
(() => {
  if (!new URLSearchParams(location.search).has('desktop')) return;
  if (document.getElementById('savevidoUpdateWidget')) return;

  const widget = document.createElement('div');
  widget.id = 'savevidoUpdateWidget';
  widget.innerHTML = `
    <button type="button" id="savevidoUpdateIcon" aria-label="Update progress" title="Update progress" hidden>
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12m-5-5 5 5 5-5M4 19h16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
      <span id="savevidoUpdatePercent"></span>
    </button>
    <section id="savevidoUpdatePanel" role="dialog" aria-modal="true" aria-labelledby="savevidoUpdateTitle" hidden>
      <div class="savevido-update-card">
        <button type="button" class="savevido-update-close" aria-label="Close">×</button>
        <p class="eyebrow">SAVEVIDO UPDATE</p>
        <h2 id="savevidoUpdateTitle">Update SaveVido</h2>
        <p id="savevidoUpdateMessage">Checking for updates…</p>
        <p id="savevidoUpdateDetails" class="savevido-update-details"></p>
        <div id="savevidoUpdateProgressWrap" hidden>
          <div class="savevido-update-track"><span id="savevidoUpdateFill"></span></div>
          <p id="savevidoUpdateProgressText">0% downloaded</p>
        </div>
        <button type="button" id="savevidoInstallUpdate" hidden>Install update</button>
        <button type="button" id="savevidoRestartUpdate" hidden>Restart SaveVido</button>
      </div>
    </section>`;
  document.body.appendChild(widget);

  const panel = widget.querySelector('#savevidoUpdatePanel');
  const icon = widget.querySelector('#savevidoUpdateIcon');
  const percentLabel = widget.querySelector('#savevidoUpdatePercent');
  const message = widget.querySelector('#savevidoUpdateMessage');
  const details = widget.querySelector('#savevidoUpdateDetails');
  const progressWrap = widget.querySelector('#savevidoUpdateProgressWrap');
  const progressFill = widget.querySelector('#savevidoUpdateFill');
  const progressText = widget.querySelector('#savevidoUpdateProgressText');
  const install = widget.querySelector('#savevidoInstallUpdate');
  const restart = widget.querySelector('#savevidoRestartUpdate');
  const close = widget.querySelector('.savevido-update-close');
  let mandatory = false;
  let installAction = 'savevido://install-update';

  const show = () => { panel.hidden = false; };
  const hide = () => { if (!mandatory) panel.hidden = true; };
  const setProgress = (value, label) => {
    const pct = Math.max(0, Math.min(100, Number(value) || 0));
    icon.hidden = false;
    percentLabel.textContent = pct + '%';
    progressWrap.hidden = false;
    progressFill.style.width = pct + '%';
    progressText.textContent = label || (pct + '% downloaded');
  };

  close.addEventListener('click', hide);
  panel.addEventListener('click', event => {
    if (event.target === panel && !mandatory) hide();
  });
  icon.addEventListener('click', show);
  install.addEventListener('click', () => {
    install.disabled = true;
    install.textContent = 'Starting update…';
    message.textContent = 'Downloading only the changed update files. SaveVido will close only after the download is verified.';
    show();
    location.href = installAction;
  });
  restart.addEventListener('click', () => {
    restart.disabled = true;
    restart.textContent = 'Restarting…';
    location.href = 'savevido://restart-app';
  });

  document.addEventListener('click', event => {
    if (!mandatory || panel.contains(event.target)) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    show();
    message.textContent = 'This update is required before you can use SaveVido.';
  }, true);
  document.addEventListener('submit', event => {
    if (!mandatory) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    show();
  }, true);
  document.addEventListener('keydown', event => {
    if (!mandatory || panel.contains(event.target)) return;
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      event.stopImmediatePropagation();
      show();
    }
  }, true);

  window.addEventListener('savevido-update-result', event => {
    const data = event.detail || {};
    mandatory = Boolean(data.mandatory);
    close.hidden = mandatory;
    show();
    install.hidden = true;
    restart.hidden = true;
    install.disabled = false;
    install.textContent = 'Install update';
    if (data.status === 'checking') {
      message.textContent = 'Checking for updates…';
      details.textContent = 'Connecting securely to SaveVido release information.';
    } else if (data.status === 'current') {
      mandatory = false;
      icon.hidden = true;
      message.textContent = 'Your app is up to date.';
      details.textContent = 'You are using SaveVido ' + (data.current_version || '');
      if (!progressWrap.hidden) progressWrap.hidden = true;
    } else if (data.status === 'available') {
      message.textContent = mandatory ? 'This update is now required.' : 'A new update is available.';
      details.textContent = 'Version ' + data.version + '. Only changed files will be downloaded.';
      install.hidden = false;
      installAction = 'savevido://install-update';
    } else if (data.status === 'bootstrap') {
      message.textContent = mandatory ? 'A required update must be installed.' : 'A one-time full installer update is required.';
      details.textContent = 'This installation is too far behind for a safe incremental patch. After this one-time update, compatible releases use changed files only.';
      install.hidden = false;
      install.textContent = 'Download full installer';
      installAction = data.installer_url || '';
      install.onclick = () => { if (installAction) location.href = installAction; };
    } else {
      message.textContent = data.message || 'Could not check for updates. Please try again.';
    }
  });

  window.addEventListener('savevido-update-installing', event => {
    const data = event.detail || {};
    show();
    icon.hidden = false;
    setProgress(0, 'Preparing update download…');
    message.textContent = 'Downloading update files…';
    details.textContent = 'SaveVido stays open while the update is downloaded and verified.';
    install.hidden = true;
    restart.hidden = true;
  });

  window.addEventListener('savevido-update-progress', event => {
    const data = event.detail || {};
    show();
    setProgress(data.percent || 0, data.message || 'Downloading update…');
    message.textContent = data.status === 'verifying' ? 'Verifying update…' : 'Downloading update…';
    details.textContent = 'Version ' + (data.version || '') + ' · ' + (data.percent || 0) + '% complete.';
  });

  window.addEventListener('savevido-update-ready', event => {
    const data = event.detail || {};
    setProgress(100, 'Download complete · Applying files…');
    message.textContent = 'Update downloaded and verified.';
    details.textContent = 'SaveVido is closing briefly to replace the changed files.';
  });

  window.addEventListener('savevido-update-installed', event => {
    const data = event.detail || {};
    mandatory = false;
    close.hidden = false;
    show();
    setProgress(100, 'Update completed');
    message.textContent = 'Update completed successfully!';
    details.textContent = 'SaveVido ' + (data.version || '') + ' is ready. Restart SaveVido to apply the update.';
    restart.hidden = false;
    restart.disabled = false;
    restart.textContent = 'Restart SaveVido';
  });

  window.addEventListener('savevido-update-failed', event => {
    const data = event.detail || {};
    show();
    install.hidden = true;
    restart.hidden = true;
    message.textContent = 'The update could not be installed.';
    details.textContent = data.message || 'Your previous files were restored. Please try again.';
  });
})();
