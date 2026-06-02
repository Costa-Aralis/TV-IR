// Service worker for the iPad kiosk.
//
// IMPORTANT: navigation requests (the HTML shell) are ALWAYS network-first.
// Vite emits content-hashed asset filenames on every build, so a cached
// index.html would point at /assets/index-OLDHASH.js that no longer exists →
// blank app after a deploy. Network-first on the shell avoids that entirely;
// hashed assets are immutable so they're safe to cache-first.

const CACHE = "tv-ir-v2";

self.addEventListener("install", (e) => {
  // Activate the new SW immediately instead of waiting for old tabs to close.
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)));
      await self.clients.claim();
    })()
  );
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  const url = new URL(req.url);

  // Never touch API calls — they must be live.
  if (url.pathname.startsWith("/api/")) return;

  // HTML navigation: network-first, fall back to cache only when offline.
  if (req.mode === "navigate" || url.pathname === "/") {
    e.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put("/", copy));
          return res;
        })
        .catch(() => caches.match("/"))
    );
    return;
  }

  // Hashed static assets: cache-first (immutable for a given URL).
  e.respondWith(
    caches.match(req).then(
      (hit) =>
        hit ||
        fetch(req).then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy));
          return res;
        })
    )
  );
});
