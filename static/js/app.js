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
        const status = e.detail?.xhr?.status;
        if (status === 403) {
          this.addToast('Sem permissão para aceder a esta área.', 'error');
          return;
        }
        if (status === 401) {
          window.location.href = '/login';
          return;
        }
        // Suprime toast para fragments automáticos (load/every) — eles exibem erro inline
        const verb = e.detail?.requestConfig?.verb || 'get';
        const trigger = e.detail?.triggerSpec?.trigger || '';
        const isAutoFragment = verb === 'get' && (trigger.includes('load') || trigger.includes('every'));
        if (!isAutoFragment) {
          this.addToast('Erro na requisição. Tente novamente.', 'error');
        }
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

// ─── BOM Builder Alpine Component ─────────────────────────────────────────────
document.addEventListener('alpine:init', () => {
    Alpine.data('bomBuilder', () => ({
      activeTab: 'receita',
      fc: 1.0,
      fcoc: 1.0,
      rendimentoKg: 1.0,
      pesoPorcaoGramas: 350,
      markup: 2.0,
      margemMinima: 30,

      sections: [],
      embalagens: [],
      bomEquipments: [],
      ingredientsMap: {},

      numPorcoes: 0,
      sobraGramas: 0,
      custoPorPorcao: 0,
      precoSugerido: 0,
      margemPct: 0,

      init() {
        const _r = (id) => document.getElementById(id)?.textContent || '';
        
        this.fc = parseFloat(_r('d-fc')) || 1.0;
        this.fcoc = parseFloat(_r('d-fcoc')) || 1.0;
        this.rendimentoKg = parseFloat(_r('d-rendimento')) || 1.0;
        this.pesoPorcaoGramas = parseInt(_r('d-peso-porcao')) || 350;
        this.markup = parseFloat(_r('d-markup')) || 2.0;

        try { this.ingredientsMap = JSON.parse(_r('d-ingmap') || '{}'); } catch (e) { }
        try { this.bomEquipments = JSON.parse(_r('d-bomeq') || '[]'); } catch (e) { }

        try {
          let loadedSections = JSON.parse(_r('d-sections') || '[]');
          if (Array.isArray(loadedSections) && loadedSections.length > 0) {
            this.sections = loadedSections.map(s => {
              if (!s.items) s.items = [];
              if (!s._key) s._key = Date.now().toString() + Math.random();
              return s;
            });
          }
        } catch (e) { }

        try {
          let loadedEmbs = JSON.parse(_r('d-embalagens') || '[]');
          if (Array.isArray(loadedEmbs) && loadedEmbs.length > 0) {
            this.embalagens = loadedEmbs;
          }
        } catch (e) { }

        if (this.sections.length === 0) {
          this.sections.push({
            _key: Date.now().toString(),
            nome: 'Massa / Base',
            peso_final_esperado_kg: 0,
            items: []
          });
        }
        this.calcPorcoes();
      },

      addSection() {
        this.sections.push({
          _key: Date.now().toString(),
          nome: `Nova Seção ${this.sections.length + 1}`,
          peso_final_esperado_kg: 0,
          items: []
        });
      },
      removeSection(idx) {
        if (confirm("Remover esta seção?")) {
          this.sections.splice(idx, 1);
          this.calcPorcoes();
        }
      },
      addIngredient(sIdx) {
        this.sections[sIdx].items.push({
          _key: Date.now().toString(),
          tipo: 'ingrediente',
          ingredient_id: '',
          quantidade: '',
          unidade: 'kg'
        });
      },
      removeIngredient(sIdx, iIdx) {
        this.sections[sIdx].items.splice(iIdx, 1);
        this.calcPorcoes();
      },
      addEmbalagem() {
        this.embalagens.push({
          _key: Date.now().toString(),
          supply_id: '',
          quantidade: 1,
          unidade: 'un'
        });
      },
      removeEmbalagem(idx) {
        this.embalagens.splice(idx, 1);
      },

      sectionsJson() { return JSON.stringify(this.sections); },
      embalagensJson() { return JSON.stringify(this.embalagens); },
      bomEquipmentsJson() { return JSON.stringify(this.bomEquipments); },

      pesoTotalIngredientes() {
        let t = 0;
        this.sections.forEach(s => {
          s.items.forEach(it => {
            if (it.tipo === 'ingrediente') t += (parseFloat(it.quantidade) || 0);
          });
        });
        return t;
      },
      calcFC() {
        // Logica simplificada para manter compatibilidade
      },
      calcPorcoes() {
        if (this.rendimentoKg > 0 && this.pesoPorcaoGramas > 0) {
          let totalG = this.rendimentoKg * 1000;
          this.numPorcoes = Math.floor(totalG / this.pesoPorcaoGramas);
          this.sobraGramas = totalG % this.pesoPorcaoGramas;
        } else {
          this.numPorcoes = 0;
          this.sobraGramas = 0;
        }
      },
      submitForm() {
        try {
          const form = document.getElementById('bom-form');
          form.querySelector('[name=sections_json]').value      = this.sectionsJson();
          form.querySelector('[name=embalagens_json]').value    = this.embalagensJson();
          form.querySelector('[name=bom_equipments_json]').value = this.bomEquipmentsJson();
          form.querySelector('[name=fc]').value   = this.fc;
          form.querySelector('[name=fcoc]').value = this.fcoc;

          htmx.ajax('POST', '/api/bom/save', {
            source: form,
            target: '#form-feedback',
            swap: 'innerHTML'
          });
        } catch (err) {
          console.error('[BOM submitForm]', err);
          document.getElementById('form-feedback').innerHTML =
            '<span class="text-red-600"><i class="ph ph-warning-circle"></i> Erro interno: ' + err.message + '</span>';
        }
      }
    }));
});


