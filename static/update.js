/* SaveVido native desktop update panel. Website visitors never see this control. */
(() => {
  if (!new URLSearchParams(location.search).has('desktop')) return;
  const nav = document.querySelector('.site-header nav');
  if (!nav || document.getElementById('checkUpdatesBtn')) return;
  const link = document.createElement('a');
  link.id = 'checkUpdatesBtn';
  link.href = 'savevido://check-updates';
  link.textContent = 'Check for updates';
  nav.appendChild(link);

  const panel = document.createElement('div');
  panel.id = 'savevidoUpdatePanel';
  panel.hidden = true;
  panel.setAttribute('role', 'dialog');
  panel.setAttribute('aria-modal', 'true');
  panel.setAttribute('aria-labelledby', 'savevidoUpdateTitle');
  panel.innerHTML = `
    <div class="savevido-update-card">
      <button type="button" class="savevido-update-close" aria-label="Close">×</button>
      <p class="eyebrow">SAVEVIDO UPDATE</p>
      <h2 id="savevidoUpdateTitle">Check for updates</h2>
      <p id="savevidoUpdateMessage">Checking for the latest version…</p>
      <p id="savevidoUpdateDetails" class="savevido-update-details"></p>
      <button type="button" id="savevidoInstallUpdate" hidden>Install update</button>
    </div>`;
  document.body.appendChild(panel);
  const message = panel.querySelector('#savevidoUpdateMessage');
  const details = panel.querySelector('#savevidoUpdateDetails');
  const install = panel.querySelector('#savevidoInstallUpdate');
  const show = () => { panel.hidden = false; };
  const hide = () => { panel.hidden = true; };
  panel.querySelector('.savevido-update-close').addEventListener('click', hide);
  panel.addEventListener('click', e => { if (e.target === panel) hide(); });
  link.addEventListener('click', e => {
    e.preventDefault(); show(); message.textContent = 'Checking for updates…';
    details.textContent = ''; install.hidden = true;
    location.href = 'savevido://check-updates';
  });
  install.addEventListener('click', () => {
    install.disabled = true; install.textContent = 'Preparing update…';
    message.textContent = 'The update is being prepared. SaveVido will close, update changed files, and restart.';
    location.href = 'savevido://install-update';
  });
  window.addEventListener('savevido-update-result', event => {
    const data = event.detail || {};
    show(); install.hidden = true; install.disabled = false; install.textContent = 'Install update';
    if (data.status === 'current') {
      message.textContent = 'Your app is up to date.';
      details.textContent = 'You are using SaveVido ' + (data.current_version || '');
    } else if (data.status === 'available') {
      message.textContent = 'A new update is available.';
      details.textContent = 'Version ' + data.version + ' · Only changed files will be downloaded.';
      install.hidden = false;
    } else if (data.status === 'bootstrap') {
      message.textContent = 'A one-time full installer update is required to activate the incremental updater.';
      details.textContent = 'After this installation, future updates will download only changed files.';
    } else {
      message.textContent = data.message || 'Could not check for updates. Please try again.';
    }
  });
  window.addEventListener('savevido-update-installing', () => {
    show(); message.textContent = 'Installing update…'; details.textContent = 'Please wait. SaveVido will restart when the update is complete.';
    install.hidden = true;
  });
})();
