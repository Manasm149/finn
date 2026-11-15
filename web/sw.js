// App shell offline; data always from the network (stale prices are worse than no prices).
const SHELL = "finn-shell-v1";
self.addEventListener("install", e => e.waitUntil(
  caches.open(SHELL).then(c => c.addAll(["./", "app.css", "app.js", "icon.svg"])).then(() => self.skipWaiting())));
self.addEventListener("activate", e => e.waitUntil(
  caches.keys().then(keys => Promise.all(keys.filter(k => k !== SHELL).map(k => caches.delete(k)))).then(() => self.clients.claim())));
self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.pathname.includes("/api/") || url.origin !== location.origin) return;
  e.respondWith(fetch(e.request).then(r => {
    const copy = r.clone();
    caches.open(SHELL).then(c => c.put(e.request, copy));
    return r;
  }).catch(() => caches.match(e.request)));
});
