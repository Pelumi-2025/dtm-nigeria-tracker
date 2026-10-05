// Offline cache: the dashboard and the last harvested data keep working with no connection.
// Written to be safe in every browser (Firefox shows "Corrupted Content Error" when a service
// worker returns a redirected page or nothing at all):
//  - only requests to this site are handled; fonts and other sites go straight to the network
//  - redirected pages are copied into a fresh response before they are returned
//  - when the network and the cache both fail, a proper error response is returned
const CACHE = "dtm-ng-v4";
const SHELL = ["./", "index.html", "manifest.webmanifest", "data/reports.js", "data/status.json"];

self.addEventListener("install", e => e.waitUntil(
  caches.open(CACHE).then(c => Promise.all(SHELL.map(u => c.add(u).catch(() => {})))).then(() => self.skipWaiting())));

self.addEventListener("activate", e => e.waitUntil(
  caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim())));

function clean(r) {
  // a redirected response cannot be handed back for a page load in Firefox: copy it
  if (!r.redirected) return Promise.resolve(r);
  return r.blob().then(b => new Response(b, { status: r.status, statusText: r.statusText, headers: r.headers }));
}

self.addEventListener("fetch", e => {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== self.location.origin || url.pathname.includes("/api/")) return;
  const isPage = req.mode === "navigate";
  e.respondWith(
    fetch(req).then(clean).then(r => {
      if (r.ok && !isPage) { const copy = r.clone(); caches.open(CACHE).then(c => c.put(req, copy)).catch(() => {}); }
      return r;
    }).catch(() =>
      caches.match(req, { ignoreSearch: true })
        .then(m => m || (isPage ? caches.match("index.html") : undefined))
        .then(m => m || Response.error()))
  );
});
