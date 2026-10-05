// VanPere Digital service worker. Scope: /event/ only.
// It caches static files and the upload page shell so the page opens on a poor connection.
// It never touches /api/, /media/, galleries or any other page, and never uploads in the background:
// queued uploads resume from IndexedDB when the upload page is open and online.
const CACHE = "vanpere-{{ version }}";
const PRECACHE = [{% for u in urls %}"{{ u }}"{% if not forloop.last %}, {% endif %}{% endfor %}];
const UPLOAD_PAGE = /^\/event\/[^/]+\/upload\/$/;

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith("vanpere-") && k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

const remember = (request, response) => {
  if (response.ok) {
    const copy = response.clone();
    caches.open(CACHE).then((c) => c.put(request, copy));
  }
  return response;
};

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/static/")) {
    event.respondWith(caches.match(request).then((hit) => hit || fetch(request).then((res) => remember(request, res))));
  } else if (request.mode === "navigate" && UPLOAD_PAGE.test(url.pathname)) {
    event.respondWith(fetch(request).then((res) => remember(request, res)).catch(() => caches.match(request)));
  }
});
