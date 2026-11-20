/* DSH Link — GitHub Pages launcher for a handoff-driven DSH harness.
 * State file = AES-GCM encrypted JSON, written by the Kaggle notebook.
 * Nothing secret is stored in this repo. */
(() => {
  'use strict';

  const LS_PASS = 'dsh_link_pass';
  const LS_AUTO = 'dsh_link_autoopen';
  const POLL_MS = 20000;
  const STALE_MS = 25 * 60 * 1000;

  // ---------------------------------------------------------------- config
  const auto = (() => {
    const c = { owner: '', repo: '', branch: 'main', path: 'state/current.json', salt: 'dsh-link-v1', stateUrl: '' };
    if (location.hostname.endsWith('.github.io')) {
      c.owner = location.hostname.split('.')[0];
      const seg = location.pathname.split('/').filter(Boolean);
      c.repo = seg[0] || '';
    }
    return c;
  })();
  const CFG = Object.assign(auto, window.DSH_LINK_CONFIG || {});

  const $ = (id) => document.getElementById(id);
  const b64ToBytes = (s) => Uint8Array.from(atob(s.replace(/-/g, '+').replace(/_/g, '/')), (c) => c.charCodeAt(0));
  const ageText = (s) => (s < 60 ? s + 's ago' : s < 3600 ? Math.round(s / 60) + 'm ago' : Math.round(s / 3600) + 'h ago');

  let pass = '';
  let timer = null;
  let lastOpened = null;
  let countdownTimer = null;

  // ------------------------------------------------------------ state fetch
  function candidates() {
    if (CFG.stateUrl) return [CFG.stateUrl];
    const cb = Date.now();
    const out = [];
    if (CFG.owner && CFG.repo) {
      out.push(`https://raw.githubusercontent.com/${CFG.owner}/${CFG.repo}/${CFG.branch}/${CFG.path}?cb=${cb}`);
      out.push(`https://api.github.com/repos/${CFG.owner}/${CFG.repo}/contents/${CFG.path}?ref=${CFG.branch}&cb=${cb}`);
    }
    out.push(`./${CFG.path}?cb=${cb}`);            // same-origin (Pages) fallback
    return out;
  }

  async function fetchState() {
    let lastErr = null;
    for (const url of candidates()) {
      try {
        const r = await fetch(url, { cache: 'no-store', headers: { Accept: 'application/vnd.github.raw, application/json' } });
        if (!r.ok) throw new Error('HTTP ' + r.status);
        const text = (await r.text()).trim();
        if (!text) throw new Error('empty payload');
        return { json: JSON.parse(text), from: url.split('?')[0] };
      } catch (e) { lastErr = e; }
    }
    throw lastErr || new Error('state file not reachable');
  }

  // -------------------------------------------------------------- decrypt
  async function decrypt(env, p) {
    if (!env || env.v !== 1 || !env.iv || !env.ct) throw new Error('bad payload format');
    const enc = new TextEncoder();
    const base = await crypto.subtle.importKey('raw', enc.encode(p), 'PBKDF2', false, ['deriveKey']);
    const key = await crypto.subtle.deriveKey(
      { name: 'PBKDF2', salt: enc.encode(env.salt || CFG.salt || 'dsh-link-v1'), iterations: env.it || 200000, hash: 'SHA-256' },
      base, { name: 'AES-GCM', length: 256 }, false, ['decrypt']);
    const plain = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: b64ToBytes(env.iv) }, key, b64ToBytes(env.ct));
    return JSON.parse(new TextDecoder().decode(plain));
  }

  // --------------------------------------------------------------- render
  function setPill(status) {
    const map = {
      online: ['ok', 'Online'], handoff: ['warn', 'Handoff'],
      starting: ['warn', 'Starting'], offline: ['bad', 'Offline'],
    };
    const [cls, label] = map[status] || ['bad', status ? status : 'No data'];
    const pill = $('status-pill');
    pill.textContent = label;
    pill.className = 'pill ' + cls;
    $('dot').className = 'dot ' + (cls === 'ok' ? 'ok' : cls === 'warn' ? 'warn' : 'bad');
    $('status2').textContent = label;
  }

  function render(data, src) {
    const now = Date.now();
    const ts = (data.ts || 0) * 1000;
    const ageMs = ts ? now - ts : Infinity;
    const stale = ageMs > STALE_MS;
    const status = data.status || 'unknown';
    const url = data.url || '';
    const live = !!url && !stale && (status === 'online' || status === 'handoff' || status === 'starting');

    setPill(stale && status !== 'offline' ? 'stale' : status);
    if (stale && status !== 'offline') {
      $('status-pill').textContent = 'Stale';
      $('status-pill').className = 'pill warn';
      $('dot').className = 'dot warn';
    }

    let host = '—';
    try { host = url ? new URL(url).host : (status === 'offline' ? 'Harness band hai' : '—'); } catch { host = url; }
    $('node').textContent = data.node ? 'node ' + data.node : '';
    $('node2').textContent = data.node || '—';
    $('host').textContent = host;
    $('updated').textContent = ts ? 'updated ' + ageText(Math.round(ageMs / 1000)) : 'never updated';
    $('age').textContent = ts ? new Date(ts).toLocaleString() : '—';
    $('payload-state').textContent = src || '—';
    $('src').textContent = src || '';

    $('open').disabled = !live;
    $('copy').disabled = !live;
    $('open').dataset.url = live ? url : '';
    $('rawlink').href = src || '#';

    $('hint').textContent = live
      ? 'Link har restart pe badalta hai — ye page khud latest link laata hai, isliye bookmark/PWA hamesha kaam karega.'
      : stale && status !== 'offline'
        ? 'State purana hai (>25 min). Harness shayad restart ho raha hai — thodi der me refresh karo.'
        : 'Harness abhi offline hai ya notebook start ho raha hai. Link aate hi ye page khud update ho jayega.';

    if (live && $('autoopen').checked && lastOpened !== url) {
      startCountdown(url);
    }
  }

  function startCountdown(url) {
    clearInterval(countdownTimer);
    let n = 3;
    const btn = $('open');
    const tick = () => {
      btn.textContent = `Open Harness → (${n})`;
      if (n-- <= 0) {
        clearInterval(countdownTimer);
        btn.textContent = 'Open Harness →';
        lastOpened = url;
        location.href = url;
      }
    };
    tick();
    countdownTimer = setInterval(tick, 1000);
  }

  function fail(msg) {
    setPill('offline');
    $('host').textContent = 'Data nahi mila';
    $('hint').textContent = msg;
    $('payload-state').textContent = 'error';
    $('open').disabled = true;
    $('copy').disabled = true;
    $('open').dataset.url = '';
  }

  function waiting(msg) {
    setPill('waiting');
    $('status-pill').textContent = 'Waiting';
    $('status-pill').className = 'pill warn';
    $('dot').className = 'dot warn';
    $('host').textContent = 'Link ka intezaar…';
    $('node').textContent = '';
    $('node2').textContent = '—';
    $('hint').textContent = msg;
    $('open').disabled = true;
    $('copy').disabled = true;
    $('open').dataset.url = '';
  }

  // ----------------------------------------------------------------- flow
  async function refresh() {
    try {
      const { json, from } = await fetchState();
      if (!json || !json.ct) { waiting('Abhi tak koi link publish nahi hua. Notebook start hone pe ye page khud update ho jayega.'); return; }
      const data = await decrypt(json, pass);
      render(data, from.replace('https://', ''));
    } catch (e) {
      const msg = String((e && e.message) || e);
      if (e && (e.name === 'OperationError' || msg.includes('OperationError'))) {
        lock('Passphrase galat lag rahi hai. Dobara try karo.');
        return;
      }
      if (msg.includes('404') || msg.includes('empty payload') || msg.includes('not reachable') || msg.includes('Failed to fetch')) {
        waiting('State file abhi nahi mili — notebook ke first publish ka intezaar hai (har 20s pe retry hota hai).');
        return;
      }
      fail('State file nahi mili / decrypt nahi hui: ' + msg);
    }
  }

  function start() {
    $('gate').classList.add('hidden');
    $('app').classList.remove('hidden');
    lastOpened = null;
    refresh();
    clearInterval(timer);
    timer = setInterval(refresh, POLL_MS);
  }

  function lock(msg) {
    clearInterval(timer);
    clearInterval(countdownTimer);
    $('app').classList.add('hidden');
    $('gate').classList.remove('hidden');
    if (msg) { $('gate-error').textContent = msg; $('gate-error').classList.remove('hidden'); }
    $('pass').value = '';
    $('pass').focus();
  }

  // --------------------------------------------------------------- events
  $('gate-form').addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const p = $('pass').value;
    if (!p) return;
    $('gate-error').classList.add('hidden');
    pass = p;
    try {
      // State file abhi na ho ya khaali ho to bhi unlock karne do: app "waiting" dikhayega.
      let json = null;
      try { json = (await fetchState()).json; } catch { json = null; }
      if (json && json.ct) await decrypt(json, pass);   // validate before storing
      if ($('remember').checked) localStorage.setItem(LS_PASS, pass);
      else localStorage.removeItem(LS_PASS);
      start();
    } catch (e) {
      $('gate-error').textContent = 'Unlock nahi hua: ' + (e && e.message ? e.message : e);
      $('gate-error').classList.remove('hidden');
    }
  });

  $('open').addEventListener('click', () => {
    const u = $('open').dataset.url;
    if (u) { lastOpened = u; location.href = u; }
  });
  $('copy').addEventListener('click', async () => {
    const u = $('open').dataset.url;
    if (!u) return;
    try { await navigator.clipboard.writeText(u); $('copy').textContent = 'Copied ✓'; }
    catch { prompt('Link copy karo:', u); }
    setTimeout(() => ($('copy').textContent = 'Copy link'), 1500);
  });
  $('refresh').addEventListener('click', refresh);
  $('lock').addEventListener('click', () => { localStorage.removeItem(LS_PASS); lock(''); });
  $('autoopen').addEventListener('change', () => localStorage.setItem(LS_AUTO, $('autoopen').checked ? '1' : '0'));

  // ------------------------------------------------------------------ boot
  $('autoopen').checked = localStorage.getItem(LS_AUTO) === '1';
  const saved = localStorage.getItem(LS_PASS);
  if (saved) { pass = saved; start(); } else { lock(''); }

  if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js').catch(() => {});
})();
