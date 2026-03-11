/**
 * SmartFood Ops 360 — Service Worker
 * E-19: PWA Mobile para Operadores
 *
 * Estratégia de cache:
 *  - Shell PWA (estático): Cache First
 *  - API de leitura (/mobile/*): Network First com fallback para cache
 *  - API de escrita (POST/PUT): Background Sync (IndexedDB offline queue)
 *  - /sync: sempre online (crítico para idempotência)
 */

const CACHE_NAME = "smartfood-v1";
const OFFLINE_BUNDLE_URL = "/mobile/offline-bundle";

// Recursos do shell PWA que ficam sempre em cache
const SHELL_ASSETS = [
  "/mobile",
  "/static/manifest.json",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
];

// Rotas de leitura que podem ser servidas do cache quando offline
const CACHEABLE_API_PATTERNS = [
  /^\/mobile\/dashboard/,
  /^\/mobile\/production-orders/,
  /^\/mobile\/products/,
  /^\/mobile\/ingredients/,
  /^\/mobile\/offline-bundle/,
];

// ─── Install: pré-caching do shell ───────────────────────────────────────────

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) => cache.addAll(SHELL_ASSETS))
      .then(() => self.skipWaiting())
  );
});

// ─── Activate: limpa caches antigos ──────────────────────────────────────────

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((k) => k !== CACHE_NAME)
            .map((k) => caches.delete(k))
        )
      )
      .then(() => self.clients.claim())
  );
});

// ─── Fetch: Network First para API, Cache First para assets ──────────────────

self.addEventListener("fetch", (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Ignorar requisições não-GET para fora da API mobile
  if (request.method !== "GET") return;

  // Verificar se é rota cacheável
  const isCacheable = CACHEABLE_API_PATTERNS.some((p) =>
    p.test(url.pathname)
  );

  if (isCacheable) {
    // Network First: tenta rede, cai para cache se offline
    event.respondWith(networkFirst(request));
  } else if (SHELL_ASSETS.some((a) => url.pathname === a || url.pathname.startsWith("/static/"))) {
    // Cache First para assets estáticos
    event.respondWith(cacheFirst(request));
  }
  // Demais requisições: comportamento padrão do browser
});

async function networkFirst(request) {
  const cache = await caches.open(CACHE_NAME);
  try {
    const response = await fetch(request);
    if (response.ok) {
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    const cached = await cache.match(request);
    if (cached) return cached;
    return offlineFallback(request);
  }
}

async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(CACHE_NAME);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    return offlineFallback(request);
  }
}

function offlineFallback(request) {
  const url = new URL(request.url);
  // Retorna JSON de fallback para rotas API
  if (url.pathname.startsWith("/mobile/")) {
    return new Response(
      JSON.stringify({
        offline: true,
        message: "Sem conexão. Dados podem estar desatualizados.",
        cached_at: null,
      }),
      {
        status: 503,
        headers: { "Content-Type": "application/json" },
      }
    );
  }
  return new Response("Offline", { status: 503 });
}

// ─── Background Sync: fila de eventos offline ────────────────────────────────

self.addEventListener("sync", (event) => {
  if (event.tag === "sync-offline-events") {
    event.waitUntil(flushOfflineQueue());
  }
});

async function flushOfflineQueue() {
  // Lê fila do IndexedDB e envia para POST /sync
  // A implementação do IndexedDB fica no app frontend (mobile.html)
  const clients = await self.clients.matchAll();
  clients.forEach((client) =>
    client.postMessage({ type: "SYNC_REQUESTED" })
  );
}

// ─── Push Notifications: alertas do servidor ─────────────────────────────────

self.addEventListener("push", (event) => {
  if (!event.data) return;

  let data;
  try {
    data = event.data.json();
  } catch {
    data = { title: "SmartFood Ops", body: event.data.text() };
  }

  event.waitUntil(
    self.registration.showNotification(data.title || "SmartFood Ops 360", {
      body: data.body || "",
      icon: "/static/icons/icon-192.png",
      badge: "/static/icons/icon-192.png",
      tag: data.tag || "smartfood-alert",
      data: { url: data.url || "/mobile" },
      actions: data.actions || [],
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const targetUrl = event.notification.data?.url || "/mobile";
  event.waitUntil(
    self.clients
      .matchAll({ type: "window", includeUncontrolled: true })
      .then((clients) => {
        const existing = clients.find((c) => c.url.includes("/mobile"));
        if (existing) {
          existing.focus();
          existing.navigate(targetUrl);
        } else {
          self.clients.openWindow(targetUrl);
        }
      })
  );
});
