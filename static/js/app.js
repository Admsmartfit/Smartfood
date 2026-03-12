/**
 * SmartFood Ops 360 — app.js
 * Alpine.js global state + HTMX hooks + offline sync
 */

// ─── Estado global Alpine ─────────────────────────────────────────────────────
function appState() {
  return {
    sidebarOpen: window.innerWidth >= 768,
    toasts: [],
    isOffline: !navigator.onLine,
    activeNav: window.location.pathname,

    // ── Init ──
    init() {
      // NProgress + HTMX hooks
      document.addEventListener('htmx:beforeRequest', (e) => {
        if (typeof NProgress !== 'undefined') NProgress.start();
        // Suspende apenas polling automático quando offline (every X)
        // Deixa 'load' passar: service worker pode servir do cache
        if (this.isOffline) {
          const trigger = e.detail.triggerSpec?.trigger || '';
          if (trigger.includes('every')) {
            e.preventDefault();
            if (typeof NProgress !== 'undefined') NProgress.done();
          }
        }
      });
      document.addEventListener('htmx:afterRequest', (e) => {
        if (typeof NProgress !== 'undefined') NProgress.done();
        this._handleHtmxTrigger(e);
      });
      document.addEventListener('htmx:responseError', (e) => {
        if (typeof NProgress !== 'undefined') NProgress.done();
        this.addToast('Erro na requisição. Tente novamente.', 'error');
      });

      // Highlight de nav ativo
      document.addEventListener('htmx:pushedIntoHistory', (e) => {
        this.activeNav = e.detail.path;
      });

      // Offline / Online
      window.addEventListener('offline', () => {
        this.isOffline = true;
        this.addToast('Modo offline ativado. Dados salvos localmente.', 'warning');
      });
      window.addEventListener('online', () => {
        this.isOffline = false;
        this.addToast('Conexão restaurada. Sincronizando...', 'success');
        this.syncOfflineData();
      });
    },

    // ── Toast ──
    addToast(message, type = 'success') {
      const id = Date.now() + Math.random();
      this.toasts.push({ id, message, type });
      setTimeout(() => {
        this.toasts = this.toasts.filter(t => t.id !== id);
      }, 3500);
    },

    removeToast(id) {
      this.toasts = this.toasts.filter(t => t.id !== id);
    },

    toastIcon(type) {
      return { success: '✅', error: '❌', warning: '⚠️', info: 'ℹ️' }[type] || 'ℹ️';
    },

    toastColor(type) {
      return {
        success: 'border-l-green-500 bg-green-50 text-green-900',
        error:   'border-l-red-500 bg-red-50 text-red-900',
        warning: 'border-l-yellow-500 bg-yellow-50 text-yellow-900',
        info:    'border-l-blue-500 bg-blue-50 text-blue-900',
      }[type] || 'border-l-blue-500 bg-blue-50 text-blue-900';
    },

    // Lê HX-Trigger e exibe toast se presente
    _handleHtmxTrigger(event) {
      let header = null;
      try {
        header = event.detail?.xhr?.getResponseHeader('HX-Trigger');
      } catch (e) { return; }
      if (!header) return;
      try {
        const data = JSON.parse(header);
        if (data.showToast) {
          this.addToast(data.showToast.message, data.showToast.type || 'success');
        }
      } catch (e) {
        // HX-Trigger não é JSON — ignora
      }
    },

    // ── Sidebar ──
    toggleSidebar() {
      this.sidebarOpen = !this.sidebarOpen;
    },

    // ── Offline Sync ──
    async syncOfflineData() {
      const raw = localStorage.getItem('sf-sync-queue');
      if (!raw) return;
      let events = [];
      try { events = JSON.parse(raw); } catch { return; }
      if (!events.length) return;

      const deviceId = localStorage.getItem('sf-device-id') || ('web-' + Math.random().toString(36).slice(2));
      localStorage.setItem('sf-device-id', deviceId);

      try {
        const res = await fetch('/sync', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ device_id: deviceId, events }),
        });
        if (res.ok) {
          localStorage.removeItem('sf-sync-queue');
          this.addToast(`${events.length} eventos offline sincronizados!`, 'success');
        }
      } catch (e) {
        console.error('[SmartFood] Sync falhou:', e);
      }
    },

    // Enfileira evento offline (usado por outras partes do app)
    queueOfflineEvent(type, payload) {
      const raw = localStorage.getItem('sf-sync-queue') || '[]';
      let queue = [];
      try { queue = JSON.parse(raw); } catch {}
      queue.push({
        event_id: crypto.randomUUID?.() || (Date.now() + '-' + Math.random()),
        event_type: type,
        payload,
        synced_at: new Date().toISOString(),
      });
      localStorage.setItem('sf-sync-queue', JSON.stringify(queue));
    },
  };
}
