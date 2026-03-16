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
// Reads data directly from <script type="text/plain"> DOM elements so it works
// regardless of HTMX navigation order (no dependency on window._bomCfg timing).
function bomBuilder() {
  function _r(id) {
    var el = document.getElementById(id);
    return el ? el.textContent.trim() : '';
  }

  // Build sections with items embedded (merges sections_json + bom_items_config_json)
  var rawSecs  = JSON.parse(_r('d-sections') || '[]');
  var rawItems = JSON.parse(_r('d-items')    || '[]');
  var initSections;
  if (rawSecs.length === 0) {
    initSections = [{ _key: 1, nome: 'Base Principal', peso_final_esperado_kg: null, items: rawItems }];
  } else {
    initSections = rawSecs.map(function(sec) {
      var its = rawItems.filter(function(it) { return String(it.section_key) === String(sec._key); });
      return { _key: sec._key, nome: sec.nome, peso_final_esperado_kg: sec.peso_final_esperado_kg, items: its };
    });
  }

  var rawEqs = JSON.parse(_r('d-bomeq') || '[]');
  var initEqs = rawEqs.map(function(eq, i) { return Object.assign({ _key: i + 1, params: [] }, eq); });

  return {
    /* ── Reactive state ─────────────────────────────────────── */
    activeTab:    'receita',
    sections:     initSections,
    _secKey:      initSections.length + 1,
    bomEquipments: initEqs,
    _eqKey:        initEqs.length + 1,
    equipmentsList: JSON.parse(_r('d-equipments') || '[]'),
    ingredientsMap: JSON.parse(_r('d-ingmap')     || '{}'),

    fc:              parseFloat(_r('d-fc'))         || 1.0,
    fcoc:            parseFloat(_r('d-fcoc'))       || 1.0,
    rendimentoKg:    parseFloat(_r('d-rendimento')) || 1.0,
    pesoPorcaoGramas:parseInt(_r('d-peso-porcao'),10)|| 350,
    markup:          parseFloat(_r('d-markup'))     || 2.0,
    pesoFinal:       parseFloat(_r('d-rendimento')) || 1.0,

    numPorcoes: 0, sobraGramas: 0, custoPorPorcao: 0,
    precoSugerido: 0, margemPct: 0,
    custoIngredientes: 0, custoEmbalagens: 0, perdaEquipamentosKg: 0,

    /* ── Init ───────────────────────────────────────────────── */
    init() {
      try { this.calcPorcoes(); } catch(e) { console.error(e); }
    },

    /* ── Seções ─────────────────────────────────────────────── */
    addSection() {
      var key = this._secKey++;
      this.sections = this.sections.concat([{
        _key: key, nome: 'Nova Seção ' + (this.sections.length + 1),
        peso_final_esperado_kg: null, items: []
      }]);
    },

    removeSection(idx) {
      if (confirm('Remover esta seção e todos os seus itens?')) {
        this.sections = this.sections.filter(function(_, i) { return i !== idx; });
      }
    },

    /* ── Itens ──────────────────────────────────────────────── */
    addItem(sIdx, tipo) {
      var newItem = { _key: Date.now(), tipo: tipo,
                      ingredient_id: '', supply_id: '',
                      quantidade: '', unidade: tipo === 'ingrediente' ? 'kg' : 'un' };
      this.sections = this.sections.map(function(sec, i) {
        if (i !== sIdx) return sec;
        return Object.assign({}, sec, { items: (sec.items || []).concat([newItem]) });
      });
    },

    removeItem(sIdx, iIdx) {
      this.sections = this.sections.map(function(sec, i) {
        if (i !== sIdx) return sec;
        return Object.assign({}, sec, { items: sec.items.filter(function(_, j) { return j !== iIdx; }) });
      });
    },

    /* ── Equipamentos ───────────────────────────────────────── */
    addEquipment() {
      var key = this._eqKey++;
      this.bomEquipments = this.bomEquipments.concat([{
        _key: key, equipment_id: '', perda_processo_kg: 0, params: []
      }]);
    },

    removeEquipment(idx) {
      this.bomEquipments = this.bomEquipments.filter(function(_, i) { return i !== idx; });
    },

    addEqParam(eq) {
      if (!eq.params) eq.params = [];
      if (eq.params.length < 5) eq.params.push({ nome: '', valor: '' });
    },

    async loadEqParams(eq) {
      if (!eq.equipment_id) { eq.params = []; return; }
      try {
        var res  = await fetch('/api/cadastro/equipment/' + eq.equipment_id + '/parameters-json');
        var data = await res.json();
        eq.params = data.map(function(p) {
          return { nome: p.nome + (p.unidade ? ' (' + p.unidade + ')' : ''), valor: p.valor_padrao || '' };
        });
      } catch(e) { console.error(e); eq.params = []; }
    },

    /* ── Serialização (formato esperado pelo backend) ────────── */
    sectionsJson() {
      return JSON.stringify(this.sections.map(function(sec, i) {
        return { _key: sec._key, nome: sec.nome, ordem: i + 1,
                 peso_final_esperado_kg: sec.peso_final_esperado_kg || null };
      }));
    },

    itemsJson() {
      var out = [];
      this.sections.forEach(function(sec) {
        (sec.items || []).forEach(function(item) {
          out.push({ _key: item._key, tipo: item.tipo,
                     ingredient_id: item.ingredient_id || '',
                     supply_id: item.supply_id || '',
                     quantidade: parseFloat(item.quantidade) || 0,
                     unidade: item.unidade || 'kg',
                     section_key: sec._key,
                     perda_esperada_pct: item.perda_esperada_pct || 0 });
        });
      });
      return JSON.stringify(out);
    },

    bomEquipmentsJson() {
      return JSON.stringify(this.bomEquipments.map(function(eq) {
        return { equipment_id: eq.equipment_id, perda_processo_kg: eq.perda_processo_kg || 0,
                 parametros_json: Object.fromEntries((eq.params||[]).map(function(p){return [p.nome,p.valor];})) };
      }));
    },

    /* ── Cálculos ────────────────────────────────────────────── */
    pesoTotalIngredientes() {
      var t = 0;
      this.sections.forEach(function(sec) {
        (sec.items||[]).forEach(function(item) {
          if (item.tipo === 'ingrediente') t += parseFloat(item.quantidade) || 0;
        });
      });
      return t;
    },

    ingredientName(id) {
      return (this.ingredientsMap && id) ? (this.ingredientsMap[id] || id) : '—';
    },

    calcPorcoes() {
      try {
        var perdaEq = this.bomEquipments.reduce(function(s,eq){return s+(parseFloat(eq.perda_processo_kg)||0);},0);
        this.perdaEquipamentosKg = perdaEq;
        var liq = Math.max(0, this.rendimentoKg - perdaEq);
        var totalG = liq * 1000;
        var porcao = this.pesoPorcaoGramas;
        if (!porcao || porcao <= 0 || totalG <= 0) {
          this.numPorcoes=0;this.sobraGramas=0;this.custoPorPorcao=0;this.precoSugerido=0;this.margemPct=0;
          return;
        }
        this.numPorcoes  = Math.floor(totalG / porcao);
        this.sobraGramas = totalG % porcao;
        var custo = this.custoIngredientes + this.custoEmbalagens;
        this.custoPorPorcao = this.numPorcoes > 0 ? custo / this.numPorcoes : 0;
        this.precoSugerido  = this.custoPorPorcao * this.markup;
        this.margemPct = this.precoSugerido > 0
          ? (this.precoSugerido - this.custoPorPorcao) / this.precoSugerido * 100 : 0;
      } catch(e) { console.error(e); }
    },
  };
}

