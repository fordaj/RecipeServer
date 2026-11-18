// Service worker: resilient asset delivery on flaky networks (for example an
// iPad reaching the server through a Tailscale relay). Browsers do not
// retry a failed subresource, so one dropped stream could lose a stylesheet
// or script and the page arrived unstyled — the dictation button, which
// speech-button.js reveals over HTTPS, disappeared with it.
//
// The generated pages themselves are never cached (the server sends
// Cache-Control: no-store), but the assets under /assets/ are content-hashed
// (?v=<hash>), which makes them immutable: cache-first is always correct and
// an old cache entry can never shadow a newer file. Recipe images are served
// stale-while-revalidate instead. Bump ASSET_CACHE/IMAGE_CACHE to roll out a
// clean cache.
const ASSET_CACHE = "recipe-assets-v1";
const IMAGE_CACHE = "recipe-images-v1";
const ASSET_PREFIX = "/assets/";
const IMAGE_EXTENSIONS = [".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif", ".svg"];

self.addEventListener("install", () => {
  // Take over as soon as possible; the page stays in control either way.
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(
        keys
          .filter(
            (key) =>
              (key.startsWith("recipe-assets-v") || key.startsWith("recipe-images-v")) &&
              key !== ASSET_CACHE &&
              key !== IMAGE_CACHE,
          )
          .map((key) => caches.delete(key)),
      );
      await self.clients.claim();
    })(),
  );
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return;

  if (url.pathname.startsWith(ASSET_PREFIX)) {
    // Content-hashed assets: serve from the cache, fetch once, immutable.
    event.respondWith(
      (async () => {
        const cached = await caches.match(event.request);
        if (cached) return cached;
        const response = await fetch(event.request);
        if (response.ok) {
          const cache = await caches.open(ASSET_CACHE);
          cache.put(event.request, response.clone());
        }
        return response;
      })(),
    );
    return;
  }

  const path = url.pathname.toLowerCase();
  if (IMAGE_EXTENSIONS.some((extension) => path.endsWith(extension))) {
    // Recipe images: serve a cached copy instantly and refresh it in the
    // background (stale-while-revalidate).
    event.respondWith(
      (async () => {
        const cached = await caches.match(event.request);
        const network = fetch(event.request)
          .then((response) => {
            if (response.ok) {
              const copy = response.clone();
              caches.open(IMAGE_CACHE).then((cache) => cache.put(event.request, copy));
            }
            return response;
          })
          .catch(() => cached);
        return cached || network;
      })(),
    );
  }
});
