// Offline cache: the dashboard shell and the last harvested data keep working with no connection.
const CACHE = "dtm-ng-v2";
const SHELL = ["./", "index.html", "manifest.webmanifest", "data/reports.js", "data/reports.json", "data/status.json", "DTM_Nigeria_Dashboard_OFFLINE.html"];
self.addEventListener("install", e => e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL).catch(() => {})).then(() => self.skipWaiting())));
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.pathname.includes("/api/")) return;
  // network first so new harvests appear; fall back to cache when offline
  e.respondWith(fetch(e.request).then(r => {
    if (r.ok && url.origin === location.origin) { const copy = r.clone(); caches.open(CACHE).then(c => c.put(e.request, copy)); }
    return r;
  }).catch(() => caches.match(e.request, { ignoreSearch: true })));
});
