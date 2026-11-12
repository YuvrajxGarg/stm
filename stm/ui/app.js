// Stm UI. Talks to Python through window.pywebview.api; Python pushes
// updates back by calling App.on(event, payload).
(function () {
  const ICONS = {
    upload: '<path d="M12 15V4"/><path d="m7 9 5-5 5 5"/><path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/>',
    file: '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>',
    folder: '<path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9L9.6 3.6A2 2 0 0 0 8.2 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2z"/>',
    shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/>',
    layers: '<path d="m12 2 10 5-10 5L2 7z"/><path d="m2 17 10 5 10-5"/><path d="m2 12 10 5 10-5"/>',
    mic: '<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10a7 7 0 0 0 14 0M12 17v5"/>',
    split: '<path d="M4 6h6M4 12h10M4 18h4"/><path d="M14 6h6M18 12h2M12 18h8"/>',
    stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
    play: '<path d="m7 4 13 8-13 8z"/>',
    check: '<path d="M20 6 9 17l-5-5"/>',
    x: '<path d="M18 6 6 18M6 6l12 12"/>',
    trash: '<path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/>',
    reveal: '<path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
    alert: '<path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/>',
    gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
    download: '<path d="M12 4v11"/><path d="m7 10 5 5 5-5"/><path d="M4 20h16"/>',
    refresh: '<path d="M21 12a9 9 0 1 1-2.6-6.4L21 8"/><path d="M21 3v5h-5"/>',
    lock: '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    bolt: '<path d="M13 2 3 14h9l-1 8 10-12h-9z"/>',
    chip: '<rect x="5" y="5" width="14" height="14" rx="2"/><path d="M9 9h6v6H9zM9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/>',
  };
  const icon = (n) => `<svg class="i" viewBox="0 0 24 24">${ICONS[n] || ''}</svg>`;
  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  document.querySelectorAll('[data-icon]').forEach((el) => {
    const svg = icon(el.dataset.icon);
    if (el.tagName === 'I') el.outerHTML = svg; else el.insertAdjacentHTML('afterbegin', svg);
  });

  const STEMS = { '4': ['vocals', 'drums', 'bass', 'other'], '2': ['vocals', 'instrumental'] };
  const items = new Map(); // id -> item
  let mode = 'beside', customDir = null, busy = false, lastDir = null, stems = '4', fmt = 'wav';
  let api = null, engineState = { ready: false, loading: true };
  let settings = {}, upd = null, modal = null, home = '';
  const tilde = (p) => (home && p && p.startsWith(home) ? '~' + p.slice(home.length) : p);
  const stemChip = (name, path) => path
    ? `<button class="stem" style="--c:var(--${name})" data-stem="${esc(path)}" title="Play ${esc(name)}">${esc(name)}${icon('play')}</button>`
    : `<span class="stem" style="--c:var(--${name})">${esc(name)}</span>`;

  // ---------- rendering ----------
  const STATUS = {
    reading: ['', 'Reading', true], ready: ['', 'Ready'], queued: ['queued', 'Waiting'], splitting: ['', 'Splitting', true],
    done: ['done', 'Split', false, 'check'], failed: ['failed', 'Failed', false, 'alert'],
    stopped: ['', 'Stopped'], unsupported: ['', 'Not supported'],
  };
  const PHASE = { reading: 'Reading the song', splitting: 'Separating', saving: 'Saving stems', done: 'Done' };

  function statusPill(it) {
    const [cls, text, spin, ic] = STATUS[it.status] || ['', it.status];
    const label = it.status === 'splitting' ? `${Math.round((it.progress || 0) * 100)}%` : text;
    return `<span class="status ${cls} ${spin ? 'busy' : ''}">${ic ? icon(ic) : ''}${label}</span>`;
  }

  function waveHTML(it) {
    const p = it.peaks || [];
    const lit = it.status === 'done' ? p.length : it.status === 'splitting' ? Math.floor((it.progress || 0) * p.length) : 0;
    const bars = p.length ? p.map((v, i) => `<i class="${i < lit ? 'on' : ''}" style="height:${Math.max(6, Math.round(v * 100))}%"></i>`).join('') : '';
    return `<div class="wave">${bars}<span class="ext">${esc(it.ext)}</span></div>`;
  }

  function lineHTML(it) {
    if (it.status === 'unsupported' || it.status === 'failed') return `<span class="err">${esc(it.error || 'Something went wrong')}</span>`;
    if (it.status === 'splitting') return `<div class="sub">${esc(PHASE[it.phase] || 'Starting')}</div><div class="bar"><div style="width:${Math.round((it.progress || 0) * 100)}%"></div></div>`;
    if (it.status === 'done') return `<div class="tags">${it.stems.map((s) => stemChip(s.name, s.path)).join('')}<span class="sub">in ${esc(it.took)}s</span></div>`;
    return `<div class="sub"><span>${esc(it.duration)}</span><span>·</span><span>${esc(it.size)}</span><span>·</span><span class="path">${esc(tilde(it.folder))}</span></div>`;
  }

  function rowHTML(it) {
    return `${waveHTML(it)}
      <div class="meta">
        <div class="title">${esc(it.name)}</div>
        ${lineHTML(it)}
      </div>
      ${statusPill(it)}
      <div class="acts">
        <button class="btn-icon" data-act="reveal" title="${it.out ? 'Show stems' : 'Show in folder'}">${icon('reveal')}</button>
        <button class="btn-icon" data-act="remove" title="Remove from list">${icon('x')}</button>
      </div>`;
  }

  function upsert(it) {
    items.set(it.id, it);
    let el = document.getElementById('row-' + it.id);
    if (!el) {
      el = document.createElement('div');
      el.className = 'row';
      el.id = 'row-' + it.id;
      el.dataset.id = it.id;
      $('#list').appendChild(el);
    }
    el.innerHTML = rowHTML(it);
    refresh();
  }

  function todoCount() {
    return [...items.values()].filter((i) => ['ready', 'failed', 'stopped'].includes(i.status) ||
      (i.status === 'done' && (i.mode || '') !== stems + fmt)).length;
  }

  function refresh() {
    const all = [...items.values()];
    const done = all.filter((i) => i.status === 'done').length;
    const todo = todoCount();
    $('#empty').classList.toggle('hidden', all.length > 0);
    $('#clear').classList.toggle('hidden', !all.length || busy);
    $('#open-out').classList.toggle('hidden', !lastDir);
    $('#stop-btn').classList.toggle('hidden', !busy);
    $('#stats').innerHTML = all.length ? `
      <span class="stat"><b>${all.length}</b>song${all.length === 1 ? '' : 's'}</span>
      ${done ? `<span class="stat lime"><b>${done}</b>split</span>` : ''}` : '';
    const btn = $('#split-btn');
    btn.disabled = busy || !todo || !engineState.ready || (mode === 'custom' && !customDir);
    btn.querySelector('span').textContent = busy ? 'Splitting…' : todo ? `Split ${todo} song${todo === 1 ? '' : 's'}` : (done ? 'All split' : 'Split');
  }

  function renderEngine() {
    const e = engineState;
    $('#engine-note').innerHTML = e.ready ? `<i class="dot"></i><span>Runs on</span><span class="path">${esc(e.device)}</span>` :
      e.loading || (!e.error) ? '<i class="dot wait"></i><span>Loading the model…</span>' :
      `<i class="dot bad"></i><span class="path" title="${esc(e.error)}">The model didn't load</span>`;
    refresh();
  }

  function renderLegend() {
    $('#stem-legend').innerHTML = STEMS[stems].map((n) => stemChip(n)).join('');
  }

  function toast(text, err, action) {
    const t = document.createElement('div');
    t.className = 'toast' + (err ? ' err' : '');
    t.innerHTML = icon(err ? 'alert' : 'check') + `<span>${esc(text)}</span>`;
    if (action) {
      const b = document.createElement('button');
      b.textContent = action.label;
      b.onclick = action.run;
      t.appendChild(b);
    }
    $('#toasts').appendChild(t);
    setTimeout(() => { t.style.transition = 'opacity .3s'; t.style.opacity = 0; setTimeout(() => t.remove(), 300); }, 4200);
  }

  // ---------- modals ----------
  function closeModal() { $('#modal-root').innerHTML = ''; modal = null; }
  function showModal(name, html, onClick, cls) {
    modal = name;
    $('#modal-root').innerHTML = `<div class="modal-back"><div class="modal ${cls || ''}">${html}</div></div>`;
    $('#modal-root .modal-back').onclick = (e) => {
      if (e.target.classList.contains('modal-back')) return closeModal();
      const el = e.target.closest('[data-m]');
      if (el) onClick(el.dataset.m, el);
    };
  }
  const sw = (on) => `<span class="switch ${on ? 'on' : ''}"></span>`;
  const opt = (key, title, detail) => `<button class="opt" data-m="toggle" data-key="${key}"><div class="t"><b>${title}</b><span>${detail}</span></div>${sw(settings[key])}</button>`;
  const ago = (iso) => {
    if (!iso) return 'Never checked';
    const s = (Date.now() - new Date(iso).getTime()) / 1000;
    if (s < 60) return 'Checked just now';
    if (s < 3600) return `Checked ${Math.round(s / 60)} min ago`;
    if (s < 86400) return `Checked ${Math.round(s / 3600)} h ago`;
    return 'Checked ' + new Date(iso).toLocaleDateString();
  };
  function updateLine() {
    if (!upd) return ['', ''];
    switch (upd.phase) {
      case 'checking': return ['Checking for updates…', ''];
      case 'uptodate': return ["You're up to date", 'ok'];
      case 'available': return [`Version ${upd.latest} is available`, 'ok'];
      case 'downloading': return [`Downloading ${upd.latest}… ${Math.round(upd.progress * 100)}%`, ''];
      case 'ready': return [`Version ${upd.latest} is ready to install`, 'ok'];
      case 'installing': return ['Installing…', ''];
      case 'failed': return [upd.error || 'Update failed', 'bad'];
      default: return [ago(upd.last_checked), ''];
    }
  }
  function renderUpdateRow() {
    const el = $('#upd-row');
    if (!el) return;
    const [line, cls] = updateLine();
    const has = upd && ['available', 'downloading', 'ready'].includes(upd.phase);
    el.innerHTML = `<div class="t"><b>Stm ${esc(upd ? upd.current : '')}</b><span class="${cls}">${esc(line)}</span></div>
      ${has ? `<button class="btn-quiet" data-m="see-update">${icon('download')}See update</button>` : `<button class="btn-quiet" data-m="check" ${upd && upd.phase === 'checking' ? 'disabled' : ''}>${icon('refresh')}Check now</button>`}`;
  }
  function openSettings() {
    const dev = settings.device || 'auto';
    showModal('settings', `
      <div class="modal-title"><h2>Settings</h2><button class="btn-icon" data-m="close">${icon('x')}</button></div>
      <div class="label">Splitting</div>
      <div class="group">
        <div class="opt"><div class="t"><b>Run the model on</b><span>${esc(engineState.ready ? 'Now: ' + engineState.device : 'Loading…')}</span></div>
          <div class="seg"><button data-m="device" data-v="auto" class="${dev === 'auto' ? 'on' : ''}">GPU when possible</button><button data-m="device" data-v="cpu" class="${dev === 'cpu' ? 'on' : ''}">CPU only</button></div></div>
        ${opt('open_after', 'Open the folder when splitting finishes', 'Shows the stems in Finder or Explorer')}
      </div>
      <div class="label">Updates</div>
      <div class="group">
        <div class="ver-row" id="upd-row"></div>
        ${opt('auto_check', 'Check for updates automatically', 'Looks for a new version at launch and every few hours')}
        ${opt('auto_install', 'Download and install updates automatically', 'Downloads in the background and installs when you quit')}
      </div>
      <div class="label">About</div>
      <div class="about">Stm uses Hybrid Transformer Demucs (htdemucs) by Meta AI Research, running in ONNX Runtime on this computer. Songs are never uploaded.</div>
      <div class="foot"><button class="link" data-m="page">Release notes on GitHub</button><button class="link" data-m="welcome" style="margin-right:0">Show welcome screen</button></div>`,
      async (m, el) => {
        if (m === 'close') closeModal();
        else if (m === 'toggle') {
          const k = el.dataset.key;
          settings = await api.set_setting(k, !settings[k]);
          el.querySelector('.switch').classList.toggle('on', !!settings[k]);
        } else if (m === 'device') {
          if (busy || settings.device === el.dataset.v) return;
          settings = await api.set_setting('device', el.dataset.v);
          engineState = { ready: false, loading: true };
          renderEngine();
          openSettings();
        } else if (m === 'check') { upd = await api.check_updates(); renderUpdateRow(); renderPill(); }
        else if (m === 'see-update') openUpdate();
        else if (m === 'page') api.open_url(upd ? upd.page : '');
        else if (m === 'welcome') { closeModal(); showWelcome(); }
      }, 'settings');
    renderUpdateRow();
  }

  function renderPill() {
    const p = $('#update-pill');
    if (!upd || !['available', 'downloading', 'ready', 'installing'].includes(upd.phase)) { p.classList.add('hidden'); return; }
    p.classList.remove('hidden');
    p.innerHTML = upd.phase === 'ready' ? `${icon('refresh')}Restart to update` :
      upd.phase === 'downloading' ? `${icon('download')}Updating ${Math.round(upd.progress * 100)}%` :
      upd.phase === 'installing' ? `${icon('refresh')}Installing…` : `${icon('download')}Update to ${esc(upd.latest)}`;
  }

  const logo = (size) => `<span class="mark" style="--size:${size}px">stm<i class="bars"><b></b><b></b><b></b><b></b></i></span>`;

  function openUpdate() {
    if (!upd) return;
    const ph = upd.phase;
    const pct = Math.round((upd.progress || 0) * 100);
    const sub = ph === 'ready' ? 'Downloaded and ready. Restart now, or it installs the next time you quit.' :
      ph === 'downloading' ? `Downloading… ${pct}%` : ph === 'installing' ? 'Installing and restarting…' :
      ph === 'failed' ? (upd.error || 'Something went wrong.') : ph === 'uptodate' ? "You're on the newest version." :
      `You have ${esc(upd.current)}.` + (upd.can_install ? '' : ' This copy runs from source, so the download page opens instead.');
    const primary = ph === 'ready' ? `<button class="btn-primary inline" data-m="install">${icon('refresh')}Restart to update</button>` :
      ph === 'available' || ph === 'failed' ? `<button class="btn-primary inline" data-m="${upd.can_install ? 'download' : 'page'}">${icon('download')}${upd.can_install ? 'Download update' : 'Open download page'}</button>` : '';
    showModal('update', `
      <div class="update-hero">
        <div class="logomark lg">${logo(30)}</div>
        <div><h2>${upd.latest ? 'Stm ' + esc(upd.latest) : 'Updates'}</h2><p class="${ph === 'failed' ? 'err' : ''}">${sub}</p></div>
      </div>
      ${ph === 'downloading' ? `<div class="progress"><div style="width:${pct}%"></div></div>` : ''}
      ${upd.notes ? `<div class="label">What's new</div><div class="notes">${esc(upd.notes)}</div>` : ''}
      <div class="foot"><button class="link" data-m="page">View on GitHub</button><button class="btn-quiet" data-m="close">Later</button>${primary}</div>`,
      (m) => {
        if (m === 'close') closeModal();
        else if (m === 'install') api.install_update();
        else if (m === 'download') api.download_update();
        else if (m === 'page') api.open_url(upd.page);
      });
  }

  // ---------- welcome (first launch) ----------
  function showWelcome() {
    const w = $('#welcome');
    let page = 0;
    const pages = [
      () => `<div class="logomark lg" style="width:96px;height:96px;border-radius:26px">${logo(38)}</div>
        <h1>Welcome to Stm</h1>
        <p class="lead">Splits any song into vocals, drums, bass and everything else,<br>so you can make acapellas, karaoke tracks and remix stems.</p>
        <div class="facts">
          <div class="card fact">${icon('chip')}<b>On your GPU</b><span>Runs on Apple silicon's GPU and Neural Engine, or your PC's graphics card.</span></div>
          <div class="card fact">${icon('bolt')}<b>Studio quality</b><span>The same Demucs model producers use, with 24-bit WAV or FLAC out.</span></div>
          <div class="card fact">${icon('shield')}<b>Private</b><span>Nothing is uploaded. Your songs never leave this computer.</span></div>
        </div>`,
      () => `<h1>Stay up to date</h1>
        <p class="lead">New versions arrive from GitHub with better models and more options.</p>
        <div class="group">
          ${opt('auto_check', 'Check for updates automatically', 'Looks for a new version at launch and every few hours')}
          ${opt('auto_install', 'Download and install updates automatically', 'Downloads in the background and installs when you quit')}
        </div>`,
    ];
    const render = () => {
      w.innerHTML = `<div class="glow"></div><div class="dots">${pages.map((_, i) => `<i class="${i <= page ? 'on' : ''} ${i === page ? 'cur' : ''}"></i>`).join('')}</div>
        <div class="page">${pages[page]()}</div>
        <div class="foot">${page ? '<button class="btn-quiet" data-w="back">Back</button>' : ''}
          <button class="btn-primary" data-w="next">${page === pages.length - 1 ? 'Get started' : 'Continue'}</button></div>`;
    };
    w.onclick = async (e) => {
      const t = e.target.closest('[data-w],[data-m]');
      if (!t) return;
      if (t.dataset.m === 'toggle') {
        const k = t.dataset.key;
        settings = await api.set_setting(k, !settings[k]);
        t.querySelector('.switch').classList.toggle('on', !!settings[k]);
      } else if (t.dataset.w === 'back') { page--; render(); }
      else if (t.dataset.w === 'next') {
        if (page < pages.length - 1) { page++; render(); }
        else { w.classList.add('hidden'); settings = await api.set_setting('welcomed', true); }
      }
    };
    render();
    w.classList.remove('hidden');
  }

  // ---------- events from Python ----------
  window.App = {
    on(event, p) {
      if (event === 'upsert') {
        const prev = items.get(p.id);
        if (p.status === 'done') p.mode = stems + fmt;
        else if (prev && prev.mode) p.mode = prev.mode;
        upsert(p);
      } else if (event === 'row_progress') {
        const it = items.get(p.id);
        if (it) { it.progress = p.progress; it.phase = p.phase; upsert(it); }
      } else if (event === 'busy') {
        busy = p.busy;
        $('#progress').classList.toggle('hidden', !busy);
        if (busy) $('#progress > div').style.width = '0%';
        refresh();
      } else if (event === 'progress') $('#progress > div').style.width = (100 * p.done / p.total) + '%';
      else if (event === 'finished') {
        if (p.dir) { lastDir = p.dir; if (mode !== 'custom') $('#save-path').textContent = tilde(p.dir); }
        refresh();
        const failed = p.total - p.ok;
        toast(p.stopped ? `Stopped after ${p.ok} song${p.ok === 1 ? '' : 's'}` :
          failed ? `Split ${p.ok} of ${p.total} songs` : `Split ${p.ok} song${p.ok === 1 ? '' : 's'}`, !!failed && !p.stopped,
          p.dir ? { label: 'Show', run: () => api.reveal(p.dir) } : null);
      } else if (event === 'engine') { engineState = p; renderEngine(); }
      else if (event === 'toast') toast(p.text, p.err);
      else if (event === 'update') {
        const prev = upd && upd.phase;
        upd = p;
        renderPill();
        if (modal === 'update') openUpdate();
        else if (modal === 'settings') renderUpdateRow();
        if (prev !== 'ready' && p.phase === 'ready' && modal !== 'update')
          toast(`Version ${p.latest} is ready`, false, { label: 'Restart', run: () => api.install_update() });
      }
    },
  };

  // ---------- user actions ----------
  $('#add-files').onclick = () => api.pick_files();
  $('#dropzone').onclick = () => api.pick_files();
  $('#add-folder').onclick = () => api.pick_folder();
  $('#split-btn').onclick = () => api.split(stems, fmt, mode, customDir);
  $('#stop-btn').onclick = () => { api.cancel(); $('#stop-btn').disabled = true; setTimeout(() => { $('#stop-btn').disabled = false; }, 1500); };
  $('#open-out').onclick = () => lastDir && api.reveal(lastDir);
  $('#clear').onclick = () => { api.clear(); items.clear(); $('#list').innerHTML = ''; lastDir = null; refresh(); };
  const pickTab = (sel, v) => document.querySelectorAll(sel + ' button').forEach((x) => x.classList.toggle('on', x.dataset.v === v));
  function setStems(v) { stems = STEMS[v] ? v : '4'; pickTab('#stems', stems); renderLegend(); refresh(); }
  function setFormat(v) { fmt = ['wav', 'flac', 'mp3'].includes(v) ? v : 'wav'; pickTab('#format', fmt); refresh(); }
  $('#stems').onclick = (e) => { const b = e.target.closest('button'); if (b && !busy) { setStems(b.dataset.v); api.set_setting('stems', stems); } };
  $('#format').onclick = (e) => { const b = e.target.closest('button'); if (b && !busy) { setFormat(b.dataset.v); api.set_setting('format', fmt); } };
  async function pickCustom() {
    const d = await api.choose_output();
    if (d) { customDir = d; api.set_setting('custom_dir', d); }
    return !!customDir;
  }
  function setMode(m) {
    mode = m;
    document.querySelectorAll('#out-mode button').forEach((x) => x.classList.toggle('on', x.dataset.mode === m));
    $('#custom-row').classList.toggle('hidden', m !== 'custom');
    $('#custom-path').textContent = tilde(customDir) || '';
    $('#save-path').textContent = m === 'custom' && customDir ? tilde(customDir) : 'a “(stems)” folder beside each song';
    refresh();
  }
  $('#out-mode').onclick = async (e) => {
    const b = e.target.closest('button');
    if (!b || busy) return;
    if (b.dataset.mode === 'custom' && !customDir && !(await pickCustom())) return;
    setMode(b.dataset.mode);
    api.set_setting('out_mode', mode);
  };
  $('#custom-row').onclick = async () => { if (await pickCustom()) setMode('custom'); };
  $('#save-row').onclick = () => {
    const target = mode === 'custom' && customDir ? customDir : lastDir;
    if (target) api.reveal(target);
  };
  $('#list').onclick = (e) => {
    const stem = e.target.closest('[data-stem]');
    if (stem) { api.play(stem.dataset.stem); return; }
    const row = e.target.closest('.row');
    if (!row) return;
    const it = items.get(+row.dataset.id);
    const act = e.target.closest('[data-act]');
    if (!act) return;
    if (act.dataset.act === 'reveal') api.reveal(it.out || it.path);
    else if (act.dataset.act === 'remove' && !['splitting', 'queued'].includes(it.status)) {
      api.remove(it.id); items.delete(it.id); row.remove(); refresh();
    }
  };
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeModal(); });
  $('#open-settings').onclick = () => openSettings();
  $('#update-pill').onclick = () => openUpdate();

  // Drag overlay (Python receives the actual drop with full file paths).
  let depth = 0;
  const showDrop = (on) => { $('#drop').classList.toggle('hidden', !on); document.body.classList.toggle('dragging', on); };
  document.addEventListener('dragenter', (e) => { e.preventDefault(); depth++; showDrop(true); });
  document.addEventListener('dragover', (e) => e.preventDefault());
  document.addEventListener('dragleave', () => { if (--depth <= 0) { depth = 0; showDrop(false); } });
  document.addEventListener('drop', (e) => { e.preventDefault(); depth = 0; showDrop(false); });

  // ---------- start ----------
  async function start(a) {
    api = a;
    const info = await api.info();
    document.body.classList.add(info.platform === 'darwin' ? 'mac' : info.platform.startsWith('win') ? 'win' : 'other');
    $('#version').textContent = 'v' + info.version;
    settings = info.settings || {};
    home = info.home || '';
    upd = info.update;
    if (settings.custom_dir) customDir = settings.custom_dir;
    setStems(settings.stems || '4');
    setFormat(settings.format || 'wav');
    setMode(settings.out_mode === 'custom' && customDir ? 'custom' : 'beside');
    if (info.engine && (info.engine.ready || info.engine.error)) engineState = info.engine;
    renderEngine();
    renderPill();
    if (!info.ffmpeg) toast("ffmpeg wasn't found, so songs can't be read", true);
    if (!settings.welcomed) setTimeout(showWelcome, 3300);
    refresh();
    setTimeout(() => { $('#splash').classList.add('out'); $('#app').classList.add('in'); }, 3300);
    setTimeout(() => $('#splash').remove(), 4000);
  }

  // Demo data for previewing the UI in a plain browser (open index.html?demo).
  function demoApi() {
    const sample = [
      { name: 'Midnight Drive (Master).wav', ext: 'WAV', size: '41.2 MB', duration: '3:54' },
      { name: 'demo_vocal_idea_v4.mp3', ext: 'MP3', size: '6.1 MB', duration: '2:31' },
      { name: 'Live at the Roundhouse.flac', ext: 'FLAC', size: '88.0 MB', duration: '7:12' },
      { name: 'reel_cut_01.mov', ext: 'MOV', size: '212.4 MB', duration: '0:48' },
    ];
    let n = 0;
    const wave = (seed) => Array.from({ length: 72 }, (_, i) => +(0.35 + 0.65 * Math.abs(Math.sin(i * 0.37 + seed) * Math.cos(i * 0.11 + seed * 2))).toFixed(3));
    const add = () => sample.forEach((s, i) => {
      const it = Object.assign({ id: ++n, path: '/Users/demo/Music/' + s.name, folder: '/Users/demo/Music', status: 'reading', stems: [] }, s);
      upsert(it);
      setTimeout(() => upsert(Object.assign({}, it, { status: 'ready', peaks: wave(i + 1) })), 300 + i * 120);
    });
    const demo = {
      info: async () => ({ version: '1.0.0', ffmpeg: true, platform: 'darwin',
        settings: { out_mode: 'beside', open_after: false, auto_check: true, auto_install: true, stems: '4', format: 'wav', device: 'auto',
          welcomed: !location.search.includes('welcome') },
        engine: { ready: true, device: 'Apple GPU / Neural Engine (CoreML)', model: 'htdemucs' },
        update: { phase: 'uptodate', current: '1.0.0', latest: '1.0.0', progress: 0, can_install: true, notes: '', page: 'https://github.com', last_checked: new Date().toISOString() } }),
      set_setting: async (k, v) => { settings[k] = v; return Object.assign({}, settings); },
      check_updates: async () => upd, download_update() {}, install_update() {}, open_url() {}, play() {}, cancel() {},
      pick_files: add, pick_folder: add, choose_output: async () => '/Users/demo/Music/Stems',
      split: (st) => {
        App.on('busy', { busy: true });
        const todo = [...items.values()].filter((i) => i.status === 'ready');
        const step = location.search.includes('mid') ? 1e9 : 900;
        todo.forEach((it, k) => {
          setTimeout(() => App.on('upsert', Object.assign({}, it, { status: 'splitting', progress: 0.42, phase: 'splitting' })), k * step);
          setTimeout(() => {
            const out = '/Users/demo/Music/' + it.name.replace(/\.[^.]+$/, '') + ' (stems)';
            App.on('upsert', Object.assign({}, it, { status: 'done', out, took: (8 + k * 3.7).toFixed(1), stems: STEMS[st].map((s) => ({ name: s, path: out + '/' + s + '.wav' })) }));
            App.on('progress', { done: k + 1, total: todo.length });
          }, k * step + step - 50);
        });
        if (step < 1e8) setTimeout(() => { App.on('busy', { busy: false }); App.on('finished', { ok: todo.length, total: todo.length, dir: '/Users/demo/Music' }); }, todo.length * step + 100);
      },
      remove() {}, clear() {}, reveal() {},
      _add: add,
    };
    return demo;
  }

  if (window.pywebview && window.pywebview.api) start(window.pywebview.api);
  else window.addEventListener('pywebviewready', () => start(window.pywebview.api));
  if (location.search.includes('demo')) {
    const d = demoApi();
    start(d).then(() => {
      if (location.search.includes('filled')) d._add();
      if (location.search.includes('split')) setTimeout(() => d.split(stems), 1200);
    });
  }
})();
