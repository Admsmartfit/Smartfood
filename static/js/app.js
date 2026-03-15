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
// Defined globally in app.js so it persists across hx-boost navigations
// (avoids race condition where Alpine MutationObserver fires before HTMX
//  re-executes inline scripts from swapped content).
function bomBuilder(cfg) {
  cfg = cfg || {};
  return {
    activeTab: 'receita',
    items: Array.isArray(cfg.items) ? cfg.items : [],
    _counter: Array.isArray(cfg.items) ? cfg.items.length : 0,

    // Equipamentos
    equipmentsList: Array.isArray(cfg.equipmentsList) ? cfg.equipmentsList : [],
    bomEquipments: Array.isArray(cfg.bomEquipments)
      ? cfg.bomEquipments.map((eq, i) => ({ _key: i + 1, params: [], ...eq }))
      : [],
    _eqCounter: Array.isArray(cfg.bomEquipments) ? cfg.bomEquipments.length : 0,

    // Rendimento wizard
    pesoBruto: 0,
    pesoLimpo: 0,
    pesoFinal: 0,
    fc:   cfg.fc   !== undefined ? cfg.fc   : 1.0,
    fcoc: cfg.fcoc !== undefined ? cfg.fcoc : 1.0,

    // Porcionamento
    rendimentoKg:     cfg.rendimentoKg     !== undefined ? cfg.rendimentoKg     : 1.0,
    pesoPorcaoGramas: cfg.pesoPorcaoGramas !== undefined ? cfg.pesoPorcaoGramas : 350,
    markup:           cfg.markup           !== undefined ? cfg.markup           : 2.0,
    custoIngredientes: 0,
    custoEmbalagens:   0,
    numPorcoes:   0,
    sobraGramas:  0,
    custoPorPorcao: 0,
    precoSugerido:  0,
    margemPct:      0,

    init() {
      // Pequeno delay para garantir que o DOM dos selects/options esteja pronto
      setTimeout(() => {
        try { this.calcPorcoes(); } catch (e) { console.error(e); }
      }, 50);
    },

    addEquipment() {
      this._eqCounter++;
      this.bomEquipments.push({ _key: this._eqCounter, equipment_id: '', perda_processo_kg: 0, params: [] });
    },

    async loadEqParams(eq) {
      if (!eq.equipment_id) { eq.params = []; return; }
      try {
        const res = await fetch(`/api/cadastro/equipment/${eq.equipment_id}/parameters-json`);
        const data = await res.json();
        eq.params = data.map(p => ({ nome: p.nome + (p.unidade ? ' (' + p.unidade + ')' : ''), valor: p.valor_padrao || '' }));
      } catch (e) {
        console.error('[SmartFood] Erro ao carregar parâmetros do equipamento:', e);
        eq.params = [];
      }
    },

    addEqParam(eq) {
      if (!eq.params) eq.params = [];
      if (eq.params.length < 5) {
        eq.params.push({ nome: '', valor: '' });
      }
    },

    bomEquipmentsJson() {
      return JSON.stringify(this.bomEquipments.map(eq => ({
        equipment_id: eq.equipment_id,
        perda_processo_kg: eq.perda_processo_kg || 0,
        parametros_json: Object.fromEntries((eq.params || []).map(p => [p.nome, p.valor])),
      })));
    },

    addItem(tipo) {
      this._counter++;
      this.items.push({
        _key: this._counter, tipo,
        ingredient_id: '', supply_id: '',
        quantidade: '', unidade: tipo === 'ingrediente' ? 'kg' : 'un',
        perda_esperada_pct: 0,
      });
    },

    removeItem(index) { this.items.splice(index, 1); },

    calcFC() {
      try {
        this.fc   = this.pesoLimpo > 0 ? +(this.pesoBruto / this.pesoLimpo).toFixed(4)  : 0;
        this.fcoc = this.pesoFinal > 0 ? +(this.pesoLimpo / this.pesoFinal).toFixed(4) : 0;
        this.calcPorcoes();
      } catch (e) { console.error(e); }
    },

    _estimarCustos() {
      try {
        let ing = 0, sup = 0;
        this.items.forEach(item => {
          const qty   = parseFloat(item.quantidade) || 0;
          const perda = parseFloat(item.perda_esperada_pct) || 0;
          const fator = 1 + perda / 100;
          if (item.tipo === 'ingrediente' && item.ingredient_id) {
            const opt = document.querySelector(`option[value="${item.ingredient_id}"]`);
            if (opt) {
              ing += (parseFloat(opt.dataset?.custo) || 0) * qty * fator;
            }
          } else if (item.tipo === 'embalagem' && item.supply_id) {
            const opt = document.querySelector(`option[value="${item.supply_id}"]`);
            if (opt) {
              sup += (parseFloat(opt.dataset?.custo) || 0) * qty;
            }
          }
        });
        this.custoIngredientes = ing;
        this.custoEmbalagens   = sup;
      } catch (e) { console.error(e); }
    },

    calcPorcoes() {
      try {
        this._estimarCustos();
        const totalG = this.rendimentoKg * 1000;
        const porcao = this.pesoPorcaoGramas;
        if (!porcao || porcao <= 0 || totalG <= 0) {
          this.numPorcoes = 0; this.sobraGramas = 0;
          this.custoPorPorcao = 0; this.precoSugerido = 0; this.margemPct = 0;
          return;
        }
        this.numPorcoes  = Math.floor(totalG / porcao);
        this.sobraGramas = totalG % porcao;
        const custo = this.custoIngredientes + this.custoEmbalagens;
        this.custoPorPorcao = this.numPorcoes > 0 ? custo / this.numPorcoes : 0;
        this.precoSugerido  = this.custoPorPorcao * this.markup;
        this.margemPct      = this.precoSugerido > 0
          ? (this.precoSugerido - this.custoPorPorcao) / this.precoSugerido * 100 : 0;
      } catch (e) { console.error(e); }
    },
  };
}

// bomBuilder is defined in this file (app.js), which is never swapped by HTMX boost,
// so Alpine can always find it — no need to reinit after settle.

