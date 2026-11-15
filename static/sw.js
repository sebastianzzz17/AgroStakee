/* AgroStake: uso sin señal.
   - La app (página, Leaflet e iconos) queda guardada y abre aunque no haya conexión.
   - Las teselas del mapa que ya viste se guardan (como máximo 500) para verlas sin conexión.
   - Las respuestas de la API las guarda la propia página (localStorage) y las muestra con un aviso.
   Solo funciona en https o en localhost (regla de los navegadores para los service workers). */
const APP = "agrostake-app-v9", MAPA = "agrostake-mapa-v1";
const ARCHIVOS = ["/", "/manifest.webmanifest", "/static/icono-192.png", "/static/icono-512.png",
  "/static/vendor/leaflet/leaflet.js", "/static/vendor/leaflet/leaflet.css",
  "/static/vendor/leaflet/images/marker-icon.png", "/static/vendor/leaflet/images/marker-icon-2x.png",
  "/static/vendor/leaflet/images/marker-shadow.png", "/static/vendor/leaflet/images/layers.png", "/static/vendor/leaflet/images/layers-2x.png"];

self.addEventListener("install", e => e.waitUntil(caches.open(APP).then(c => c.addAll(ARCHIVOS)).then(() => self.skipWaiting())));
self.addEventListener("activate", e => e.waitUntil(
  caches.keys().then(ks => Promise.all(ks.filter(k => k !== APP && k !== MAPA).map(k => caches.delete(k)))).then(() => self.clients.claim())));

async function recortar(nombre, max){
  const c = await caches.open(nombre), ks = await c.keys();
  for (let i = 0; i < ks.length - max; i++) await c.delete(ks[i]);
}

self.addEventListener("fetch", e => {
  const r = e.request, u = new URL(r.url);
  if (r.method !== "GET") return;
  if (u.origin === location.origin) {
    if (u.pathname.startsWith("/api/") || u.pathname === "/sw.js") return;
    if (r.mode === "navigate" || u.pathname === "/") {         // la página: primero la red (versión nueva), si no, la guardada
      e.respondWith(fetch(r).then(res => {                  // solo se guarda la página de AgroStake (no una de error o de espera)
          if (res.ok && res.headers.get("X-App") === "AgroStake") { const copia = res.clone(); caches.open(APP).then(c => c.put("/", copia)); }
          return res; })
        .catch(() => caches.match("/")));
      return;
    }
    e.respondWith(caches.match(r).then(g => g || fetch(r).then(res => {
      if (res.ok) { const copia = res.clone(); caches.open(APP).then(c => c.put(r, copia)); }
      return res;
    })));
    return;
  }
  if (u.hostname.endsWith("tile.openstreetmap.org")) {           // mapa base: lo guardado al instante y se actualiza por detrás
    e.respondWith(caches.open(MAPA).then(async c => {
      const g = await c.match(r);
      const red = fetch(r).then(res => { if (res.ok) { c.put(r, res.clone()); recortar(MAPA, 500); } return res; }).catch(() => g);
      return g || red;
    }));
  }
});
