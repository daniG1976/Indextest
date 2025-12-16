const CACHE_NAME = 'todo-cache-v2';
// Stellen Sie sicher, dass alle kritischen Dateien hier gelistet sind:
const urlsToCache = [
    './', // Die Startseite
    './index.html',
    './manifest.json',
    './icon.png' // Ihr Icon
    // Wenn Sie externe CSS-Dateien oder andere Scripte haben, hier hinzufügen
];

// Installation: Caching der statischen Dateien
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => {
        console.log('Service Worker: Caching App Shell');
        return cache.addAll(urlsToCache);
      })
  );
  self.skipWaiting();
});

// Abrufen (Fetch): Cache-Strategie (Cache first)
self.addEventListener('fetch', event => {
  event.respondWith(
    caches.match(event.request)
      .then(response => {
        // Wenn im Cache, gib Cache-Version zurück
        if (response) {
          return response;
        }
        // Ansonsten, mache Netzwerk-Request
        return fetch(event.request);
      })
  );
});

// Aktivierung: Alte Cache-Versionen aufräumen
self.addEventListener('activate', event => {
  const cacheWhitelist = [CACHE_NAME];
  event.waitUntil(
    caches.keys().then(cacheNames => {
      return Promise.all(
        cacheNames.map(cacheName => {
          if (cacheWhitelist.indexOf(cacheName) === -1) {
            console.log('Service Worker: Löschen von altem Cache:', cacheName);
            return caches.delete(cacheName);
          }
        })
      );
    })
  );
});