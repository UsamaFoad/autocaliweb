const CACHE_NAME = "acw-cache-v1";
const PRECACHE_URLS = [
    "/", // Start‑URL, laut manifest.json
    "/index.html",
    "/static/icon-dark.svg",
    "/static/icon-light.svg",
    "/static/css/main.css", // ergänze eure CSS‑Dateien
    "/static/js/main.js", // ergänze eure JS‑Dateien
    "/static/…", // weitere Assets
];

self.addEventListener("install", (event) => {
    event.waitUntil(
        caches
            .open(CACHE_NAME)
            .then((cache) => cache.addAll(PRECACHE_URLS))
            .then(() => self.skipWaiting())
    );
});

self.addEventListener("activate", (event) => {
    event.waitUntil(
        caches
            .keys()
            .then((names) =>
                Promise.all(
                    names.map((name) => {
                        if (name !== CACHE_NAME) return caches.delete(name);
                    })
                )
            )
            .then(() => self.clients.claim())
    );
});

self.addEventListener("fetch", (event) => {
    if (!event.request.url.startsWith(self.location.origin)) return;
    event.respondWith(
        caches.match(event.request).then(
            (cached) =>
                cached ||
                fetch(event.request).then((response) => {
                    return caches.open(CACHE_NAME).then((cache) => {
                        cache.put(event.request, response.clone());
                        return response;
                    });
                })
        )
    );
});
