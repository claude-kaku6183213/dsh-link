/* Service worker: network-first (hamesha fresh code), cache sirf offline fallback ke liye.
   Pehle cache-first tha -> ek baar 404 cache ho gaya to app hamesha purani rehti thi. */
const CACHE = 'dsh-link-shell-v5';
const SHELL = ['./', './index.html', './style.css', './app.js', './config.js', './manifest.webmanifest', './icon.svg'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL).catch(() => {})).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys()
    .then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', (e) => {
  const url = e.request.url;
  // live data aur cross-origin API: kabhi cache nahi
  if (e.request.method !== 'GET' || url.includes('current.json') || url.includes('cb=') ||
      url.includes('supabase.co') || url.includes('api.github.com') || url.includes('raw.githubusercontent.com')) return;

  // network-first: online ho to hamesha fresh, offline ho to cache se
  e.respondWith(
    fetch(e.request).then((r) => {
      if (r && r.ok) { const cp = r.clone(); caches.open(CACHE).then((c) => c.put(e.request, cp)).catch(() => {}); }
      return r;                                   // 404/500 cache NAHI karte
    }).catch(() => caches.match(e.request).then((hit) => hit || caches.match('./index.html')))
  );
});
