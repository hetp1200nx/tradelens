// Minimal service worker so TradeLens can be installed on a phone home screen.
// Live data always comes from the network; only the app shell is cached for a faster start.
const SHELL = "tradelens-v2";
self.addEventListener("install", (e) => { e.waitUntil(caches.open(SHELL).then(c => c.addAll(["/", "/style.css", "/app.js", "/icon.svg"]).catch(() => {}))); self.skipWaiting(); });
self.addEventListener("activate", (e) => { e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== SHELL).map(k => caches.delete(k))))); self.clients.claim(); });
self.addEventListener("fetch", (e) => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.pathname.startsWith("/api/")) return;
  e.respondWith(fetch(e.request).then(r => { const copy = r.clone(); caches.open(SHELL).then(c => c.put(e.request, copy)).catch(() => {}); return r; })
    .catch(() => caches.match(e.request)));
});
