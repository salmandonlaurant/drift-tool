'use strict';

/* ============================================================ state */

const S = {
  P: null,
  boot: null,
  tab: 'data',
  chart: null,
  curveResult: null,
  scale: 1,
  writeHeights: true,
  modelView: null,
  showParse: false,
  busy: false,
};

const LS_KEY = 'driftTool.project.v1';
const LS_LANG = 'driftTool.lang';

const $ = (sel, root) => (root || document).querySelector(sel);
const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

/* ============================================================ utils */

function api(path, body) {
  const opts = body === undefined
    ? { method: 'GET' }
    : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
  return fetch(path, opts).then(async (r) => {
    const text = await r.text();
    let data;
    try { data = JSON.parse(text); } catch (e) { data = { error: text.slice(0, 300) }; }
    if (!r.ok) throw new Error(data.error || r.statusText);
    return data;
  });
}

function esc(s) {
  return String(s === null || s === undefined ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function parseNum(v) {
  if (v === null || v === undefined) return null;
  const s = String(v).trim().replace(/\s/g, '').replace(',', '.');
  if (s === '') return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

function fnum(v, dec) {
  if (v === null || v === undefined || !Number.isFinite(Number(v))) return '—';
  const d = dec === undefined ? 4 : dec;
  const s = Number(v).toFixed(d);
  return LANG === 'el' ? s.replace('.', ',') : s;
}

function fnumTrim(v, dec) {
  if (v === null || v === undefined || !Number.isFinite(Number(v))) return '—';
  let s = Number(v).toFixed(dec === undefined ? 5 : dec);
  if (s.indexOf('.') >= 0) s = s.replace(/0+$/, '').replace(/\.$/, '');
  return LANG === 'el' ? s.replace('.', ',') : s;
}

function debounce(fn, ms) {
  let t = null;
  return function () {
    const args = arguments;
    clearTimeout(t);
    t = setTimeout(() => fn.apply(null, args), ms);
  };
}

let toastTimer = null;
function toast(msg, isErr) {
  const el = $('#toast');
  el.textContent = msg;
  el.className = 'toast' + (isErr ? ' err' : '');
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, isErr ? 5200 : 2200);
}

function download(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}

function slug(s) {
  return String(s || 'drift').replace(/[^\p{L}\p{N}\-_]+/gu, '_').slice(0, 60) || 'drift';
}

/* ============================================================ model access */

const activeCurve = () => S.P.curves.find((c) => c.id === S.P.active_curve) || S.P.curves[0];
const activeDiagram = () => S.P.diagrams.find((d) => d.id === S.P.active_diagram) || S.P.diagrams[0];
const modelById = (id) => S.P.models.find((m) => m.id === id) || S.P.models[0];
const curveModel = () => modelById(activeCurve().model_id);
const viewModel = () => modelById(S.modelView || activeCurve().model_id);

function persist() {
  try { localStorage.setItem(LS_KEY, JSON.stringify(S.P)); } catch (e) { /* quota */ }
}
const persistDebounced = debounce(persist, 500);

function softRefresh() {
  renderSidebar();
  analyzeCurve();
  renderChart();
  persistDebounced();
}

/* ============================================================ boot */

async function boot() {
  try {
    const savedLang = localStorage.getItem(LS_LANG);
    if (savedLang === 'el' || savedLang === 'en') LANG = savedLang;
  } catch (e) { /* private mode */ }
  applyStaticI18n();
  S.boot = await api('/api/bootstrap?lang=' + encodeURIComponent(LANG));
  let restored = null;
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (raw) restored = JSON.parse(raw);
  } catch (e) { restored = null; }
  S.P = restored || S.boot.project;
  try {
    const norm = await api('/api/normalize', { project: S.P });
    if (norm && norm.project) S.P = norm.project;
  } catch (e) { /* keep as is */ }
  if (restored) toast(t('restore_work'));
  bindEvents();
  renderAll();
}

async function setLang(lang, silent) {
  LANG = lang === 'en' ? 'en' : 'el';
  try { localStorage.setItem(LS_LANG, LANG); } catch (e) { /* ignore */ }
  applyStaticI18n();
  try {
    const boot = await api('/api/bootstrap?lang=' + encodeURIComponent(LANG));
    const keep = S.boot ? S.boot.docs_example : null;
    S.boot = boot;
    if (keep) S.boot.docs_example = keep;
  } catch (e) { /* keep old bootstrap */ }
  renderAll();
  if (!silent) toast(t('lang_changed'));
}

/* ============================================================ render: chrome */

function renderAll() {
  if (!S.P.curves.length) S.P.curves.push(newCurveLocal());
  if (!S.P.diagrams.length) S.P.diagrams.push(newDiagramLocal());
  if (!activeCurve()) S.P.active_curve = S.P.curves[0].id;
  if (!activeDiagram()) S.P.active_diagram = S.P.diagrams[0].id;
  $('#projectName').value = S.P.name || '';
  renderSidebar();
  renderTab();
  analyzeCurve();
  renderChart();
  persist();
}

function renderSidebar() {
  const dl = $('#diagramList');
  dl.innerHTML = S.P.diagrams.map((d) => {
    const n = (d.curve_ids || []).length;
    return `<li class="${d.id === S.P.active_diagram ? 'active' : ''}" data-act="sel-diagram" data-id="${d.id}"
                title="${esc(t('rename_diagram'))}">
        <span class="name">${esc(d.name)}</span>
        <span class="badge">${n}</span>
        <button class="mini" data-act="del-diagram" data-id="${d.id}" title="${esc(t('delete_diagram'))}">×</button>
      </li>`;
  }).join('');

  const cl = $('#curveList');
  cl.innerHTML = S.P.curves.map((c) => {
    const inDia = (activeDiagram().curve_ids || []).includes(c.id);
    return `<li class="${c.id === S.P.active_curve ? 'active' : ''}" data-act="sel-curve" data-id="${c.id}"
                title="${esc(t('rename_curve'))}">
        <span class="swatch" style="background:${esc(c.color)}"></span>
        <span class="name">${esc(c.name)}</span>
        ${inDia ? '' : `<span class="badge" title="${esc(t('not_in_diagram'))}">–</span>`}
        <span class="eye ${c.visible === false ? '' : 'on'}" data-act="toggle-curve" data-id="${c.id}"
              title="${esc(t('toggle_curve'))}">${c.visible === false ? '◌' : '◉'}</span>
        <button class="mini" data-act="del-curve" data-id="${c.id}" title="${esc(t('delete_curve'))}">×</button>
      </li>`;
  }).join('');
}

function renderTab() {
  $$('.tab-btn').forEach((b) => b.classList.toggle('active', b.dataset.tab === S.tab));
  $$('.tab').forEach((t) => t.classList.toggle('active', t.id === 'tab-' + S.tab));
  if (S.tab === 'data') renderData();
  if (S.tab === 'diagram') renderDiagram();
  if (S.tab === 'model') renderModel();
  if (S.tab === 'outrigger') renderOuTrigger();
}

/* ============================================================ render: data tab */

function renderData() {
  const c = activeCurve();
  const units = S.boot.units;
  const unitOpts = (sel) => units.map((u) => `<option value="${u}" ${u === sel ? 'selected' : ''}>${u}</option>`).join('');
  const modelOpts = S.P.models.map((m) => `<option value="${m.id}" ${m.id === c.model_id ? 'selected' : ''}>${esc(m.name)}</option>`).join('');
  const provOpts = Object.keys(S.boot.provenance).map((k) => `<option value="${k}" ${k === c.provenance ? 'selected' : ''}>${esc(t('prov_' + k))}</option>`).join('');
  const dashOpts = ['solid', 'dash', 'longdash', 'dashdot', 'dot']
    .map((k) => `<option value="${k}" ${k === c.dash ? 'selected' : ''}>${esc(t('dash_' + k))}</option>`).join('');

  $('#tab-data').innerHTML = `
  <div class="card">
    <h4>${esc(t('curve_props'))}</h4>
    <div class="row">
      <div class="field grow"><label>${esc(t('name'))}</label>
        <input type="text" data-bind="name" value="${esc(c.name)}"></div>
      <div class="field"><label>${esc(t('model'))}</label>
        <select data-bindfull="model_id">${modelOpts}</select></div>
      <div class="field"><label>${esc(t('direction'))}</label>
        <input type="text" data-bind="direction" value="${esc(c.direction || '')}" placeholder="X" style="width:64px"></div>
      <div class="field grow"><label>${esc(t('analysis_case'))}</label>
        <input type="text" data-bind="case" value="${esc(c.case || '')}" placeholder="${esc(t('analysis_case_ph'))}"></div>
    </div>
    <div class="row">
      <div class="field"><label>${esc(t('provenance'))}</label>
        <select data-bindfull="provenance">${provOpts}</select></div>
      <div class="field"><label>${esc(t('unit_u'))}</label>
        <select data-bindfull="units_u">${unitOpts(c.units_u)}</select></div>
      <div class="field"><label>${esc(t('unit_h'))}</label>
        <select data-bindfull="units_h">${unitOpts(c.units_h)}</select></div>
      <div class="field"><label>${esc(t('colour'))}</label>
        <input type="color" data-bindfull="color" value="${esc(c.color || '#1f4e79')}"></div>
      <div class="field"><label>${esc(t('width'))}</label>
        <input type="number" step="0.2" min="0.5" max="6" data-bind="width" value="${esc(c.width)}" style="width:66px"></div>
      <div class="field"><label>${esc(t('line'))}</label>
        <select data-bindfull="dash">${dashOpts}</select></div>
    </div>
    ${c.provenance === 'spectrum' ? `<div class="warn err">${esc(t('spectral_warning'))}</div>` : ''}
  </div>

  <details class="card" ${S.showParse ? 'open' : ''} id="pasteCard">
    <summary><b>${esc(t('paste_title'))}</b>
      <span class="muted small">${esc(t('paste_cols'))}</span></summary>
    <div class="row" style="margin-top:10px">
      <div class="field"><label>${esc(t('header'))}</label>
        <select id="optHeader">
          <option value="auto">${esc(t('auto'))}</option>
          <option value="yes">${esc(t('yes_present'))}</option>
          <option value="no">${esc(t('no'))}</option>
        </select></div>
      <div class="field"><label>${esc(t('decimal'))}</label>
        <select id="optDecimal">
          <option value="auto">${esc(t('auto'))}</option>
          <option value="comma">${esc(t('comma'))}</option>
          <option value="dot">${esc(t('dot'))}</option>
        </select></div>
      <div class="field grow"></div>
      <button class="btn primary" data-act="apply-paste">${esc(t('analyse_apply'))}</button>
      <button class="btn" data-act="append-paste">${esc(t('append'))}</button>
    </div>
    <textarea id="pasteBox" spellcheck="false" placeholder="0&#9;0,0000&#9;—&#10;1&#9;0,0042&#9;4,2&#10;2&#9;0,0118&#9;3,8&#10;3&#9;0,0139&#9;4,2"></textarea>
    <div class="small muted" style="margin-top:6px">
      ${t('paste_help_html')}
      <a href="#" data-act="load-example">${esc(t('load_doc_example'))}</a>
    </div>
  </details>

  <div class="card">
    <h4>${esc(t('floor_table'))}
      <span class="pill ${curveIssueClass()}" id="rowPill">${curveIssueText()}</span>
    </h4>
    <div class="gridwrap">
      <table class="grid" id="dataGrid">
        <thead><tr>
          <th>#</th><th>${esc(t('th_floor'))}</th><th>u [${esc(c.units_u)}]</th><th>h [${esc(c.units_h)}]</th>
          <th>Δu [m]</th><th>d [–]</th><th>d [%]</th><th>${esc(t('th_check'))}</th>
        </tr></thead>
        <tbody>${gridRowsHTML()}</tbody>
      </table>
    </div>
    <div class="tbl-actions">
      <button class="btn" data-act="add-row">${esc(t('add_row'))}</button>
      <button class="btn" data-act="del-row">${esc(t('del_last'))}</button>
      <button class="btn" data-act="sort-rows">${esc(t('sort_rows'))}</button>
      <label class="check" style="margin-left:8px">
        <input type="checkbox" id="writeHeights" ${S.writeHeights ? 'checked' : ''}>
        ${esc(t('write_heights'))}
      </label>
    </div>
    <div class="small muted" style="margin-top:8px">
      ${activeDiagram().limit !== null && activeDiagram().limit !== undefined
        ? t('limit_check_html', { v: fnum(activeDiagram().limit, 5) })
        : esc(t('no_limit'))}
    </div>
  </div>`;
  updateComputed(S.curveResult);
}

function gridRowsHTML() {
  const c = activeCurve();
  const rows = c.rows || [];
  if (!rows.length) {
    return `<tr><td colspan="8" class="muted" style="text-align:center;padding:16px">
      ${esc(t('no_rows'))}</td></tr>`;
  }
  return rows.map((r, i) => {
    const isBase = Number(r.floor) === 0;
    return `<tr data-i="${i}" class="${isBase ? 'base' : ''}">
      <td>${i + 1}</td>
      <td><input class="floor" type="text" data-i="${i}" data-f="floor" value="${r.floor === null ? '' : esc(fnumTrim(r.floor, 2))}"></td>
      <td><input class="num" type="text" data-i="${i}" data-f="u" value="${r.u === null || r.u === undefined ? '' : esc(fnumTrim(r.u, 6))}"></td>
      <td>${isBase
        ? '<span class="muted">—</span>'
        : `<input class="num" type="text" data-i="${i}" data-f="h" value="${r.h === null || r.h === undefined ? '' : esc(fnumTrim(r.h, 3))}">`}</td>
      <td class="mono du"></td>
      <td class="mono d"></td>
      <td class="mono pct"></td>
      <td class="flag"></td>
    </tr>`;
  }).join('');
}

function updateComputed(res) {
  S.curveResult = res;
  const grid = $('#dataGrid');
  if (!grid || !res) return;
  const byFloor = new Map();
  (res.rows || []).forEach((r) => { if (!byFloor.has(r.floor)) byFloor.set(r.floor, r); });
  $$('tr[data-i]', grid).forEach((tr) => {
    const input = $('input.floor', tr);
    if (!input) return;
    const floor = parseNum(input.value);
    const r = byFloor.get(floor);
    const cell = (cls, txt) => { const td = $('td.' + cls, tr); if (td) td.textContent = txt; };
    if (!r) {
      cell('du', '—'); cell('d', '—'); cell('pct', '—');
      const f = $('td.flag', tr); if (f) { f.textContent = ''; f.title = ''; }
      tr.classList.remove('exceed', 'bad');
      return;
    }
    cell('du', r.du === null ? '—' : fnum(r.du, 5));
    cell('d', r.d === null ? '—' : fnum(r.d, 5));
    cell('pct', r.d_pct === null ? '—' : fnum(r.d_pct, 3) + '%');
    const flag = $('td.flag', tr);
    const bad = (r.codes || []).length > 0;
    if (flag) {
      flag.textContent = r.exceeds ? t('exceeds') : (bad ? '⚠' : (r.ok ? '✓' : ''));
      flag.title = bad ? (r.codes || []).map((c) => S.boot.messages[c] || c).join('\n') : '';
      flag.className = 'flag ' + (r.exceeds ? 'err' : (bad ? 'warn' : ''));
      flag.style.color = r.exceeds ? 'var(--err)' : (bad ? 'var(--warn)' : 'var(--ok)');
      flag.style.fontWeight = r.exceeds ? '700' : '400';
    }
    tr.classList.toggle('exceed', !!r.exceeds);
    tr.classList.toggle('bad', bad && !r.exceeds);
  });
  const pill = $('#rowPill');
  if (pill) { pill.className = 'pill ' + curveIssueClass(); pill.textContent = curveIssueText(); }
}

function curveIssues() {
  const res = S.curveResult;
  if (!res) return [];
  const seen = new Set();
  return (res.issues || []).filter((i) => {
    const k = i.code + '|' + i.floor;
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
}

function curveIssueClass() {
  const list = curveIssues();
  if (list.some((i) => i.level === 'error')) return 'err';
  if (list.length) return 'warn';
  const n = S.curveResult ? S.curveResult.summary.n_valid : 0;
  return n ? 'ok' : '';
}

function curveIssueText() {
  const list = curveIssues();
  if (list.some((i) => i.level === 'error')) {
    return t('errors_count', { n: list.filter((i) => i.level === 'error').length });
  }
  if (list.length) return t('warnings_count', { n: list.length });
  const n = S.curveResult ? S.curveResult.summary.n_valid : 0;
  return n ? t('valid_floors', { n }) : t('no_data');
}

/* ============================================================ render: diagram tab */

function renderDiagram() {
  const d = activeDiagram();
  const parsed = limitPreview(d.limit_input, d.limit);
  const rows = S.P.curves.map((c) => {
    const inDia = (d.curve_ids || []).includes(c.id);
    const isMean = (d.mean_ids || []).includes(c.id);
    return `<tr>
      <td class="c"><input type="checkbox" data-act="member" data-id="${c.id}" ${inDia ? 'checked' : ''}></td>
      <td class="l"><span class="swatch" style="display:inline-block;background:${esc(c.color)}"></span>
        ${esc(c.name)} <span class="muted small">${esc(c.direction || '')} ${c.case ? '· ' + esc(c.case) : ''}</span></td>
      <td class="l muted small">${esc(modelById(c.model_id).name)}</td>
      <td class="c"><input type="checkbox" data-act="mean" data-id="${c.id}" ${isMean ? 'checked' : ''} ${inDia ? '' : 'disabled'}></td>
    </tr>`;
  }).join('');

  $('#tab-diagram').innerHTML = `
  <div class="card">
    <h4>${esc(t('diagram_settings'))}</h4>
    <div class="row">
      <div class="field grow"><label>${esc(t('name'))}</label>
        <input type="text" data-bind="name" value="${esc(d.name)}"></div>
      <div class="field"><label>${esc(t('limit'))}</label>
        <input type="text" id="limitInput" data-bind="limit_input" value="${esc(d.limit_input)}"
               placeholder="${esc(t('limit_ph'))}" style="width:150px"></div>
      <div class="field" style="justify-content:flex-end">
        <span class="pill ${parsed.err ? 'err' : 'ok'}" id="limitPill">${parsed.text}</span></div>
    </div>
    <div class="row">
      <div class="field"><label>${esc(t('x_axis'))}</label>
        <select data-bindfull="x_mode">
          <option value="ratio" ${d.x_mode === 'ratio' ? 'selected' : ''}>${esc(t('x_ratio'))}</option>
          <option value="percent" ${d.x_mode === 'percent' ? 'selected' : ''}>${esc(t('x_percent'))}</option>
        </select></div>
      <div class="field"><label>${esc(t('y_axis'))}</label>
        <select data-bindfull="y_mode">
          <option value="floor" ${d.y_mode === 'floor' ? 'selected' : ''}>${esc(t('y_floor'))}</option>
          <option value="elevation" ${d.y_mode === 'elevation' ? 'selected' : ''}>${esc(t('y_elevation'))}</option>
        </select></div>
      <div class="field"><label>${esc(t('x_min'))}</label>
        <input type="text" data-bind="x_min" value="${d.x_min === null || d.x_min === undefined ? '' : esc(d.x_min)}" style="width:80px" placeholder="${esc(t('automatic'))}"></div>
      <div class="field"><label>${esc(t('x_max'))}</label>
        <input type="text" data-bind="x_max" value="${d.x_max === null || d.x_max === undefined ? '' : esc(d.x_max)}" style="width:80px" placeholder="${esc(t('automatic'))}"></div>
      <label class="check"><input type="checkbox" data-bindfull="show_grid" ${d.show_grid ? 'checked' : ''}> ${esc(t('grid'))}</label>
      <label class="check"><input type="checkbox" data-bindfull="legend_outside" ${d.legend_outside ? 'checked' : ''}> ${esc(t('legend_outside'))}</label>
    </div>
    <div class="row">
      <div class="field grow"><label>${esc(t('note_label'))}</label>
        <input type="text" data-bind="note" value="${esc(d.note || '')}" placeholder="${esc(t('note_ph'))}"></div>
    </div>
  </div>

  <div class="card">
    <h4>${esc(t('curves_of_diagram'))}</h4>
    <table class="plain">
      <thead><tr><th style="width:34px">${t('in_diagram')}</th><th>${esc(t('curve'))}</th><th>${esc(t('model'))}</th><th style="width:56px">${esc(t('mean'))}</th></tr></thead>
      <tbody>${rows || `<tr><td colspan="4" class="muted">${esc(t('no_curves'))}</td></tr>`}</tbody>
    </table>
    <div class="small muted" style="margin-top:8px">
      ${esc(t('mean_help'))}
    </div>
  </div>`;
}

function limitPreview(text, fallback) {
  if (!text || !String(text).trim()) {
    if (fallback === null || fallback === undefined) return { text: t('limit_none'), err: true };
    return { text: fnum(fallback, 5), err: false };
  }
  const s = String(text).trim().replace(/\s/g, '');
  let v = null, form = 'decimal';
  if (s.endsWith('%')) { v = parseNum(s.slice(0, -1)); if (v !== null) v = v / 100; form = 'percent'; }
  else if (s.includes('/')) {
    const parts = s.split('/');
    const a = parseNum(parts[0]), b = parseNum(parts[1]);
    if (a !== null && b) { v = a / b; form = 'fraction'; }
  } else v = parseNum(s);
  if (v === null) return { text: t('limit_invalid'), err: true };
  const inv = v ? '1/' + fnum(1 / v, 0) : '—';
  return { text: `= ${fnum(v, 5)}  (${inv}, ${fnum(v * 100, 3)}%)`, err: false, value: v, form };
}

/* ============================================================ render: model tab */

function renderModel() {
  const m = viewModel();
  const modelOpts = S.P.models.map((x) => `<option value="${x.id}" ${x.id === m.id ? 'selected' : ''}>${esc(x.name)}</option>`).join('');
  const heights = m.heights || {};
  const floors = new Set();
  Object.keys(heights).forEach((k) => { const n = Number(k); if (Number.isFinite(n) && n > 0) floors.add(n); });
  S.P.curves.filter((c) => c.model_id === m.id).forEach((c) => (c.rows || []).forEach((r) => {
    if (Number(r.floor) > 0) floors.add(Number(r.floor));
  }));
  const list = Array.from(floors).sort((a, b) => a - b);
  const body = list.map((f) => {
    const v = heights[String(f)];
    return `<tr data-floor="${f}">
      <td>${fnumTrim(f, 0)}</td>
      <td><input type="text" class="num" data-hfloor="${f}" value="${v === undefined || v === null ? '' : esc(fnumTrim(v, 3))}" placeholder="${esc(m.default_h)}" style="width:90px"></td>
      <td class="l muted small">${v === undefined || v === null ? esc(t('inherits')) : esc(t('defined'))}</td>
    </tr>`;
  }).join('') || `<tr><td colspan="3" class="muted">${esc(t('no_floors'))}</td></tr>`;

  $('#tab-model').innerHTML = `
  <div class="card">
    <h4>${esc(t('model_section'))}</h4>
    <div class="row">
      <div class="field grow"><label>${esc(t('model'))}</label>
        <select data-bindfull="_model_select">${modelOpts}</select></div>
      <div class="field grow"><label>${esc(t('name'))}</label>
        <input type="text" data-bind="_model_name" value="${esc(m.name)}"></div>
    </div>
    <div class="row">
      <div class="field"><label>${esc(t('default_height'))}</label>
        <input type="text" data-bind="_model_h" value="${esc(fnumTrim(m.default_h, 3))}" style="width:110px"></div>
      <div class="field"><label>${esc(t('base_u', { unit: activeCurve().units_u }))}</label>
        <input type="text" data-bind="_model_base" value="${esc(fnumTrim(m.base_u, 6))}" style="width:120px"></div>
      <label class="check"><input type="checkbox" data-bindfull="_model_base_ok" ${m.base_confirmed ? 'checked' : ''}>
        ${esc(t('base_confirmed'))}</label>
    </div>
    <div class="small muted">${esc(t('base_help'))}</div>
  </div>

  <div class="card">
    <h4>${esc(t('height_table'))}</h4>
    <div class="row">
      <button class="btn" data-act="heights-from-curve">${esc(t('from_curve'))}</button>
      <button class="btn" data-act="heights-default-all">${esc(t('default_all'))}</button>
    </div>
    <div class="gridwrap" style="max-height:360px">
      <table class="plain">
        <thead><tr><th style="width:70px">${esc(t('th_floor'))}</th><th style="width:110px">h [m]</th><th class="l">${esc(t('status'))}</th></tr></thead>
        <tbody>${body}</tbody>
      </table>
    </div>
    <div class="small muted" style="margin-top:8px">
      ${esc(t('height_help'))}
    </div>
  </div>`;
}

/* ============================================================ analysis requests */

let curveTimer = null;
function analyzeCurve() {
  clearTimeout(curveTimer);
  curveTimer = setTimeout(async () => {
    const c = activeCurve();
    if (!c) return;
    try {
      const r = await api('/api/curve', {
        project: S.P,
        curve_id: c.id,
        limit: activeDiagram().limit,
        y_mode: activeDiagram().y_mode,
        lang: LANG,
      });
      updateComputed(r.result);
    } catch (e) { toast(t('err_calc', { msg: e.message }), true); }
  }, 90);
}

let chartTimer = null;
function renderChart() {
  clearTimeout(chartTimer);
  chartTimer = setTimeout(doRenderChart, 130);
}

async function doRenderChart() {
  const d = activeDiagram();
  const host = $('#chartHost');
  if (!d || !host) return;
  const width = Math.max(430, Math.round(host.clientWidth || 720));
  const height = Math.round(Math.min(780, Math.max(430, width * 0.62 * S.scale)));
  try {
    const r = await api('/api/chart', {
      project: S.P,
      diagram_id: d.id,
      width: width,
      height: height,
      lang: LANG,
    });
    S.chart = r;
    host.innerHTML = r.svg;
    $('#chartTitle').textContent = d.name;
    renderStats(r);
    renderWarnings(r);
  } catch (e) {
    host.innerHTML = `<div class="warn err" style="margin:12px">${esc(t('err_chart', { msg: e.message }))}</div>`;
  }
}

function renderStats(r) {
  const el = $('#chartStats');
  if (!r) { el.innerHTML = ''; return; }
  const series = r.series || [];
  const maxS = series.filter((s) => s.summary && s.summary.max !== null);
  const best = maxS.sort((a, b) => b.summary.max - a.summary.max)[0];
  const exceed = series.reduce((acc, s) => acc + ((s.summary && s.summary.n_exceed) || 0), 0);
  el.innerHTML = `
    <span>${esc(t('stats_curves'))} <b>${series.length}</b></span>
    <span>${esc(t('stats_max'))} <b>${best ? fnum(best.summary.max, 5) : '—'}</b>
      ${best ? `&nbsp;<span class="muted">(${esc(best.name)}, ${esc(t('stats_floor'))} ${fnumTrim(best.summary.max_floor, 0)})</span>` : ''}</span>
    <span>${esc(t('stats_exceed'))} <b style="color:${exceed ? 'var(--err)' : 'inherit'}">${exceed}</b></span>`;
}

function renderWarnings(r) {
  const el = $('#warnings');
  if (!r) { el.innerHTML = ''; return; }
  const items = [];
  if (r.spectral_warning) {
    items.push(`<div class="warn err"><b>${esc(t('spectral_title'))}</b> ${esc(S.boot.provenance_warning)}</div>`);
  }
  const errs = new Set();
  (r.warnings || []).forEach((w) => {
    if (r.spectral_warning && w === S.boot.provenance_warning) return;
    if (errs.has(w)) return;
    errs.add(w);
    items.push(`<div class="warn">${esc(w)}</div>`);
  });
  el.innerHTML = items.slice(0, 12).join('');
}

/* ============================================================ chart interaction */

function bindChartEvents() {
  const host = $('#chartHost');
  const tip = $('#tooltip');

  host.addEventListener('click', (e) => {
    const g = e.target.closest('g.legend');
    if (!g) return;
    const id = g.getAttribute('data-curve-id');
    if (!id || id === '__mean__') return;
    const c = S.P.curves.find((x) => x.id === id);
    if (!c) return;
    c.visible = c.visible === false;
    renderSidebar();
    renderChart();
  });

  host.addEventListener('mousemove', (e) => {
    const c = e.target.closest('circle[data-curve]');
    if (!c) { tip.hidden = true; undim(host); return; }
    const x = Number(c.getAttribute('data-x'));
    const floor = c.getAttribute('data-floor');
    const name = c.getAttribute('data-curve');
    const mode = (S.chart && S.chart.diagram && S.chart.diagram.x_mode) || 'ratio';
    const dTxt = mode === 'percent' ? fnum(x * 100, 3) + '%' : fnum(x, 5);
    tip.textContent = `${name}\n${t('tooltip_floor')} ${fnumTrim(floor, 0)}\nd = ${dTxt}  (${fnum(x * 100, 3)}%)`;
    tip.hidden = false;
    tip.style.left = Math.min(window.innerWidth - 220, e.clientX + 14) + 'px';
    tip.style.top = Math.max(8, e.clientY - 56) + 'px';
    dim(host, name);
  });

  host.addEventListener('mouseleave', () => { tip.hidden = true; undim(host); });
}

function dim(host, name) {
  $$('g.curve', host).forEach((g) => {
    g.style.opacity = (g.getAttribute('data-name') === name) ? '1' : '0.18';
  });
}
function undim(host) {
  $$('g.curve', host).forEach((g) => { g.style.opacity = '1'; });
}

/* ============================================================ events */

function bindEvents() {
  document.addEventListener('click', onClick);
  $$('.tab-btn').forEach((b) => b.addEventListener('click', () => {
    S.tab = b.dataset.tab;
    renderTab();
  }));
  document.addEventListener('change', onChange);
  document.addEventListener('input', onInput);
  document.addEventListener('dblclick', onDblClick);
  $('#projectName').addEventListener('input', (e) => { S.P.name = e.target.value; persistDebounced(); });
  $('#fileInput').addEventListener('change', onFileOpen);
  bindChartEvents();
  window.addEventListener('resize', debounce(() => renderChart(), 250));
}

async function onClick(e) {
  const t = e.target.closest('[data-act]');
  if (!t) return;
  const act = t.dataset.act;
  const id = t.dataset.id;

  if (act === 'sel-diagram') { S.P.active_diagram = id; renderAll(); return; }
  if (act === 'sel-curve') {
    S.P.active_curve = id;
    const c = S.P.curves.find((x) => x.id === id);
    if (c) S.modelView = c.model_id;
    renderAll();
    return;
  }

  if (act === 'toggle-curve') {
    e.stopPropagation();
    const c = S.P.curves.find((x) => x.id === id);
    c.visible = c.visible === false;
    renderAll();
    return;
  }
  if (act === 'add-diagram') {
    const d = newDiagramLocal();
    S.P.diagrams.push(d);
    S.P.active_diagram = d.id;
    d.curve_ids = [];
    renderAll();
    return;
  }
  if (act === 'add-curve') {
    const c = newCurveLocal();
    S.P.curves.push(c);
    S.P.active_curve = c.id;
    if (!(activeDiagram().curve_ids || []).includes(c.id)) activeDiagram().curve_ids.push(c.id);
    renderAll();
    return;
  }
  if (act === 'del-curve') {
    e.stopPropagation();
    const target = S.P.curves.find((x) => x.id === id) || activeCurve();
    if (!confirm(t('del_curve_confirm', { name: target.name }))) return;
    S.P.curves = S.P.curves.filter((c) => c.id !== id);
    S.P.diagrams.forEach((d) => {
      d.curve_ids = (d.curve_ids || []).filter((x) => x !== id);
      d.mean_ids = (d.mean_ids || []).filter((x) => x !== id);
    });
    if (!S.P.curves.length) S.P.curves.push(newCurveLocal());
    S.P.active_curve = S.P.curves[0].id;
    renderAll();
    return;
  }
  if (act === 'del-diagram') {
    e.stopPropagation();
    if (S.P.diagrams.length < 2) { toast(t('last_diagram'), true); return; }
    const target = S.P.diagrams.find((x) => x.id === id) || activeDiagram();
    if (!confirm(t('del_diagram_confirm', { name: target.name }))) return;
    S.P.diagrams = S.P.diagrams.filter((d) => d.id !== id);
    S.P.active_diagram = S.P.diagrams[0].id;
    renderAll();
    return;
  }
  if (act === 'apply-paste' || act === 'append-paste') {
    await applyPaste(act === 'append-paste');
    return;
  }
  if (act === 'load-example') {
    e.preventDefault();
    const ex = S.boot.docs_example;
    activeCurve().rows = ex.rows.map((r) => ({ floor: r.floor, u: r.u, h: r.h }));
    activeCurve().units_u = 'm';
    activeCurve().units_h = 'm';
    activeDiagram().limit_input = ex.limit;
    activeDiagram().limit = 0.002;
    renderAll();
    toast(t('loaded_example'));
    return;
  }
  if (act === 'load-demo') {
    e.preventDefault();
    if (!confirm(t('demo_confirm'))) return;
    try {
      const r = await api('/api/demo?lang=' + encodeURIComponent(LANG));
      S.P = r.project;
      S.modelView = null;
      renderAll();
      setLang(LANG, true);
      toast(t('loaded_demo'));
    } catch (err) {
      toast(t('demo_missing', { msg: err.message }), true);
    }
    return;
  }
  if (act === 'add-row') {
    const c = activeCurve();
    const last = c.rows.length ? Number(c.rows[c.rows.length - 1].floor) : 0;
    c.rows.push({ floor: last + 1, u: null, h: curveModel().default_h });
    renderData();
    analyzeCurve();
    return;
  }
  if (act === 'del-row') {
    const c = activeCurve();
    if (c.rows.length) c.rows.pop();
    renderData();
    analyzeCurve();
    return;
  }
  if (act === 'sort-rows') {
    const c = activeCurve();
    c.rows.sort((a, b) => (Number(a.floor) || 0) - (Number(b.floor) || 0));
    renderData();
    analyzeCurve();
    return;
  }
  if (act === 'heights-from-curve') {
    const m = viewModel();
    (activeCurve().rows || []).forEach((r) => {
      if (r.h !== null && r.h !== undefined && r.h > 0 && Number(r.floor) !== 0) {
        m.heights[String(Math.round(Number(r.floor)))] = r.h;
      }
    });
    renderModel(); analyzeCurve(); renderChart(); persist();
    toast(t('heights_updated'));
    return;
  }
  if (act === 'heights-default-all') {
    const m = viewModel();
    Object.keys(m.heights || {}).forEach((k) => { m.heights[k] = m.default_h; });
    renderModel(); analyzeCurve(); renderChart(); persist();
    return;
  }
  if (act === 'save') {
    const blob = new Blob([JSON.stringify(S.P, null, 1)], { type: 'application/json;charset=utf-8' });
    download(blob, slug(S.P.name) + '.drift.json');
    return;
  }
  if (act === 'open') { $('#fileInput').click(); return; }
  if (act === 'lang') { setLang(LANG === 'el' ? 'en' : 'el'); return; }
  if (act === 'xlsx') { await exportXlsx(); return; }
  if (act === 'svg') { exportSvg(); return; }
  if (act === 'png') { await exportPng(); return; }
  if (act === 'print') { window.print(); return; }
  if (act === 'zoom-in') { S.scale = Math.min(2, S.scale * 1.12); renderChart(); return; }
  if (act === 'o-compute') { await computeOuTrigger(); return; }
  if (act === 'zoom-out') { S.scale = Math.max(0.6, S.scale / 1.12); renderChart(); return; }
}

async function onChange(e) {
  const t = e.target;

  if (t.id === 'optHeader' || t.id === 'optDecimal') return; // read at paste time
  if (t.id === 'writeHeights') { S.writeHeights = t.checked; return; }

  if (t.dataset.act === 'member') {
    const d = activeDiagram();
    const id = t.dataset.id;
    if (t.checked) { if (!d.curve_ids.includes(id)) d.curve_ids.push(id); }
    else {
      d.curve_ids = d.curve_ids.filter((x) => x !== id);
      d.mean_ids = (d.mean_ids || []).filter((x) => x !== id);
    }
    renderSidebar(); renderDiagram(); renderChart(); persist();
    return;
  }
  if (t.dataset.act === 'mean') {
    const d = activeDiagram();
    const id = t.dataset.id;
    d.mean_ids = d.mean_ids || [];
    if (t.checked) { if (!d.mean_ids.includes(id)) d.mean_ids.push(id); }
    else d.mean_ids = d.mean_ids.filter((x) => x !== id);
    renderChart(); persist();
    return;
  }
  if (t.dataset.hfloor !== undefined) {
    const m = viewModel();
    const f = t.dataset.hfloor;
    const v = parseNum(t.value);
    if (v === null) delete m.heights[f]; else m.heights[f] = v;
    renderModel();
    analyzeCurve(); renderChart(); persist();
    return;
  }
  if (t.dataset.bindfull) {
    applyBind(t, t.dataset.bindfull, true);
    return;
  }
}

function onInput(e) {
  const t = e.target;
  if (t.dataset.f && t.dataset.i !== undefined) {
    rowEdit(t);
    return;
  }
  if (t.id === 'limitInput') {
    const p = limitPreview(t.value, null);
    const pill = $('#limitPill');
    if (pill) { pill.textContent = p.text; pill.className = 'pill ' + (p.err ? 'err' : 'ok'); }
    return;
  }
  if (t.dataset.bind) {
    applyBind(t, t.dataset.bind, false);
  }
}

function applyBind(t, path, full) {
  const v = t.type === 'checkbox' ? t.checked : t.value;
  switch (path) {
    case 'name': activeCurve().name = v; break;
    case 'direction': activeCurve().direction = v; break;
    case 'case': activeCurve().case = v; break;
    case 'width': activeCurve().width = parseNum(v) === null ? 2 : parseNum(v); break;
    case 'model_id': activeCurve().model_id = v; break;
    case 'provenance': activeCurve().provenance = v; break;
    case 'units_u': activeCurve().units_u = v; break;
    case 'units_h': activeCurve().units_h = v; break;
    case 'color': activeCurve().color = v; break;
    case 'dash': activeCurve().dash = v; break;

    case 'limit_input': {
      const d = activeDiagram();
      d.limit_input = v;
      const p = limitPreview(v, d.limit);
      d.limit = p.value === undefined ? d.limit : p.value;
      if (p.value === undefined && p.err) d.limit = null;
      break;
    }
    case 'x_min': activeDiagram().x_min = parseNum(v); break;
    case 'x_max': activeDiagram().x_max = parseNum(v); break;
    case 'note': activeDiagram().note = v; break;
    case 'show_grid': activeDiagram().show_grid = v; break;
    case 'legend_outside': activeDiagram().legend_outside = v; break;
    case 'x_mode': activeDiagram().x_mode = v; break;
    case 'y_mode': activeDiagram().y_mode = v; break;

    case '_model_name': viewModel().name = v; break;
    case '_model_h': viewModel().default_h = parseNum(v); break;
    case '_model_base': viewModel().base_u = parseNum(v); break;
    case '_model_base_ok': viewModel().base_confirmed = v; break;
    case '_model_select': S.modelView = v; break;
    default: break;
  }
  if (full) renderAll();
  else softRefresh();
}

function onDblClick(e) {
  const li = e.target.closest('li[data-act]');
  if (!li) return;
  const act = li.dataset.act;
  const id = li.dataset.id;
  if (act === 'sel-curve') {
    const c = S.P.curves.find((x) => x.id === id);
    const name = prompt(t('rename_curve'), c.name);
    if (name) { c.name = name; renderAll(); }
  } else if (act === 'sel-diagram') {
    const d = S.P.diagrams.find((x) => x.id === id);
    const name = prompt(t('rename_diagram'), d.name);
    if (name) { d.name = name; renderAll(); }
  }
}

/* row editing ------------------------------------------------------ */

let rowTimer = null;
function rowEdit(t) {
  const i = Number(t.dataset.i);
  const f = t.dataset.f;
  const c = activeCurve();
  if (!c.rows[i]) return;
  const v = (t.value || '').trim() === '' ? null : parseNum(t.value);
  c.rows[i][f] = v;

  if (f === 'h' && S.writeHeights && v !== null && v > 0) {
    const floor = c.rows[i].floor;
    if (floor !== null && floor !== undefined) {
      curveModel().heights[String(Math.round(Number(floor)))] = v;
    }
  }
  persistDebounced();
  clearTimeout(rowTimer);
  rowTimer = setTimeout(() => { analyzeCurve(); renderChart(); }, 260);
}

/* paste ------------------------------------------------------------ */

async function applyPaste(append) {
  const box = $('#pasteBox');
  const text = box ? box.value : '';
  if (!text.trim()) { toast(t('err_paste_empty'), true); return; }
  const c = activeCurve();
  const m = curveModel();
  try {
    const parsed = await api('/api/parse', {
      text,
      has_header: $('#optHeader').value,
      decimal: $('#optDecimal').value,
      units_u: c.units_u,
      units_h: c.units_h,
      default_h: null,
    });
    const rows = parsed.rows.map((r) => ({ floor: r.floor, u: r.u, h: r.h }));
    // fill missing heights from the model height table
    rows.forEach((r) => {
      if (r.h === null && r.floor !== null && Number(r.floor) !== 0) {
        const key = String(Math.round(Number(r.floor)));
        r.h = m.heights[key] !== undefined ? m.heights[key] : m.default_h;
      }
    });
    if (append) c.rows = (c.rows || []).concat(rows);
    else c.rows = rows;
    S.showParse = true;

    // keep the model height table in sync with pasted heights
    if (S.writeHeights) {
      rows.forEach((r) => {
        if (r.h !== null && r.h > 0 && r.floor !== null && Number(r.floor) !== 0) {
          m.heights[String(Math.round(Number(r.floor)))] = r.h;
        }
      });
    }
    renderData();
    analyzeCurve();
    renderChart();
    persist();
    const missingU = rows.filter((r) => r.u === null).length;
    const missingH = rows.filter((r) => r.u !== null && r.h === null && Number(r.floor) !== 0).length;
    toast(t('paste_result', { n: rows.length }) +
      (missingU ? t('paste_missing_u', { n: missingU }) : '') +
      (missingH ? t('paste_missing_h', { n: missingH }) : ''));
  } catch (e) {
    toast(t('err_parse', { msg: e.message }), true);
  }
}

/* exports ---------------------------------------------------------- */

function exportSvg() {
  if (!S.chart || !S.chart.svg) { toast(t('err_no_chart'), true); return; }
  const blob = new Blob([S.chart.svg], { type: 'image/svg+xml;charset=utf-8' });
  download(blob, slug(S.P.name) + '_' + slug(activeDiagram().name) + '.svg');
}

async function exportPng() {
  const svgEl = $('#chartHost svg');
  if (!svgEl) { toast(t('err_no_chart'), true); return; }
  const w = Number(svgEl.getAttribute('width'));
  const h = Number(svgEl.getAttribute('height'));
  const scale = 3;
  const data = new XMLSerializer().serializeToString(svgEl);
  const blob = new Blob([data], { type: 'image/svg+xml;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const img = new Image();
  await new Promise((res, rej) => {
    img.onload = res;
    img.onerror = () => rej(new Error(t('err_image')));
    img.src = url;
  });
  const canvas = document.createElement('canvas');
  canvas.width = Math.round(w * scale);
  canvas.height = Math.round(h * scale);
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
  URL.revokeObjectURL(url);
  canvas.toBlob((b) => {
    download(b, slug(S.P.name) + '_' + slug(activeDiagram().name) + '.png');
  }, 'image/png');
}

async function exportXlsx() {
  try {
    const res = await fetch('/api/export/xlsx', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project: S.P, diagram_id: S.P.active_diagram, lang: LANG }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: res.statusText }));
      throw new Error(err.error || res.statusText);
    }
    const blob = await res.blob();
    download(blob, slug(S.P.name) + '_' + slug(activeDiagram().name) + '.xlsx');
  } catch (e) {
    toast(t('err_excel', { msg: e.message }), true);
  }
}

/* open file -------------------------------------------------------- */

function onFileOpen(e) {
  const file = e.target.files && e.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = async () => {
    try {
      const data = JSON.parse(reader.result);
      const norm = await api('/api/normalize', { project: data });
      S.P = norm.project || data;
      renderAll();
      toast(t('opened_project', { name: S.P.name || '' }));
    } catch (err) {
      toast(t('err_open'), true);
    }
  };
  reader.readAsText(file, 'utf-8');
  e.target.value = '';
}

/* local constructors ---------------------------------------------- */

function uid(prefix) {
  return prefix + '_' + Math.random().toString(16).slice(2, 10);
}

function newCurveLocal() {
  const n = S.P ? S.P.curves.length + 1 : 1;
  return {
    id: uid('crv'),
    name: t('new_curve_name', { n }),
    model_id: S.P && S.P.models.length ? S.P.models[0].id : 'mdl_1',
    direction: 'X',
    case: '',
    provenance: 'static',
    units_u: 'mm',
    units_h: 'm',
    rows: [],
    color: ['#1f4e79', '#c00000', '#2e7d32', '#ed7d31', '#7030a0', '#00838f'][n % 6],
    width: 2,
    dash: 'solid',
    visible: true,
  };
}

function newDiagramLocal() {
  const n = S.P ? S.P.diagrams.length + 1 : 1;
  return {
    id: uid('dia'),
    name: t('new_diagram_name', { n }),
    limit_input: '1/500',
    limit: 0.002,
    x_mode: 'ratio',
    y_mode: 'floor',
    show_grid: true,
    legend_outside: true,
    curve_ids: [],
    mean_ids: [],
    x_min: null,
    x_max: null,
    note: '',
  };
}

/* ============================================================ outrigger tab */
const O_DEFAULTS = {
  system: 'CSB',
  H: 250,
  EI_w: 1e10,
  EI_o: 1e9,
  EI_c: 1e9,
  GA_o: '',
  auto_ga: true,
  E: 3e10,
  d: 8,
  a: 10,
  h: 4,
  A_d: 0.5,
  A_b: 0.3,
  b: 20,
  alpha: 1,
  e_over_r: 0,
  w: 1,
  floor_heights: '',
  eccs: '0, 1.52, 2.13, 2.85, 3.80, 4.75',
};

function O() {
  if (!S.outrigger) S.outrigger = Object.assign({}, O_DEFAULTS);
  return S.outrigger;
}

function renderOuTrigger() {
  const o = O();
  const num = (id, val, step) => `<input type="text" id="${id}" value="${esc(val === null || val === undefined ? '' : val)}" style="width:120px" ${step ? 'data-step="' + step + '"' : ''}>`;
  $('#tab-outrigger').innerHTML = `
  <div class="card">
    <h4>Βελτιστοποίηση θέσης ζυγοστάτη</h4>
    <div class="row">
      <div class="field"><label>Σύστημα</label>
        <select id="o_system">
          <option value="CSB" ${o.system === 'CSB' ? 'selected' : ''}>CSB</option>
          <option value="BIE" ${o.system === 'BIE' ? 'selected' : ''}>BIE</option>
        </select></div>
      <label class="check"><input type="checkbox" id="o_auto_ga" ${o.auto_ga ? 'checked' : ''}> Αυτόματος υπολογισμός GA_o</label>
    </div>
  </div>

  <div class="card">
    <h4>Χαρακτηριστικά κτιρίου</h4>
    <div class="row">
      <div class="field"><label>H [m]</label>${num('o_H', o.H)}</div>
      <div class="field"><label>EI_w</label>${num('o_EI_w', o.EI_w)}</div>
      <div class="field"><label>EI_o</label>${num('o_EI_o', o.EI_o)}</div>
      <div class="field"><label>EI_c</label>${num('o_EI_c', o.EI_c)}</div>
      <div class="field"><label>GA_o</label>${num('o_GA_o', o.GA_o)}</div>
    </div>
    <div class="row">
      <div class="field"><label>E [Pa]</label>${num('o_E', o.E)}</div>
      <div class="field"><label>d [m]</label>${num('o_d', o.d)}</div>
      <div class="field"><label>a [m]</label>${num('o_a', o.a)}</div>
      <div class="field"><label>h [m]</label>${num('o_h', o.h)}</div>
    </div>
    <div class="row">
      <div class="field"><label>A_d [m²]</label>${num('o_A_d', o.A_d)}</div>
      <div class="field"><label>A_b [m²]</label>${num('o_A_b', o.A_b)}</div>
      <div class="field"><label>b [m]</label>${num('o_b', o.b)}</div>
      <div class="field"><label>α</label>${num('o_alpha', o.alpha)}</div>
      <div class="field"><label>e/r</label>${num('o_e_over_r', o.e_over_r)}</div>
    </div>
    <div class="row">
      <div class="field"><label>w [kN/m]</label>${num('o_w', o.w)}</div>
    </div>
  </div>

  <div class="card">
    <h4>Ύψη ορόφων (ένα ανά γραμμή, m)</h4>
    <textarea id="o_floors" style="width:100%;min-height:120px" placeholder="4.2&#10;3.8&#10;...">${esc(o.floor_heights)}</textarea>
    <div class="small muted">Χρησιμοποιούνται για μετατροπή της θεωρητικής θέσης σε πραγματικό όροφο.</div>
  </div>

  <div class="card">
    <h4>Τιμές e/r για το δεύτερο διάγραμμα</h4>
    <input type="text" id="o_eccs" value="${esc(o.eccs || '0, 1.52, 2.13, 2.85, 3.80, 4.75')}" style="width:100%">
  </div>

  <div class="row">
    <button class="btn primary" data-act="o-compute">Υπολογισμός Βέλτιστης Θέσης</button>
  </div>

  <div id="o_results"></div>
  <div id="o_chart1_host" class="chart-host"></div>
  <div id="o_chart2_host" class="chart-host"></div>
  `;
  // bind compute
}

async function computeOuTrigger() {
  const o = O();
  // collect
  o.system = $('#o_system').value;
  o.auto_ga = $('#o_auto_ga').checked;
  const g = (id) => { const el = $('#' + id); return el ? el.value : ''; };
  o.H = g('o_H'); o.EI_w = g('o_EI_w'); o.EI_o = g('o_EI_o'); o.EI_c = g('o_EI_c'); o.GA_o = g('o_GA_o');
  o.E = g('o_E'); o.d = g('o_d'); o.a = g('o_a'); o.h = g('o_h');
  o.A_d = g('o_A_d'); o.A_b = g('o_A_b'); o.b = g('o_b'); o.alpha = g('o_alpha'); o.e_over_r = g('o_e_over_r');
  o.w = g('o_w');
  o.floor_heights = $('#o_floors').value;
  o.eccs = $('#o_eccs').value;
  const params = {
    system: o.system,
    auto_ga: o.auto_ga,
    H: parseNum(o.H),
    EI_w: parseNum(o.EI_w),
    EI_o: parseNum(o.EI_o),
    EI_c: parseNum(o.EI_c),
    GA_o: o.GA_o === '' ? null : parseNum(o.GA_o),
    E: parseNum(o.E),
    d: parseNum(o.d),
    a: parseNum(o.a),
    h: parseNum(o.h),
    A_d: parseNum(o.A_d),
    A_b: parseNum(o.A_b),
    b: parseNum(o.b),
    alpha: parseNum(o.alpha),
    e_over_r: parseNum(o.e_over_r),
    w: parseNum(o.w),
    floor_heights: o.floor_heights,
    eccentricities: o.eccs.split(/[,\s]+/).filter(Boolean).map(parseNum).filter((v) => v !== null),
  };
  try {
    const r = await api('/api/outrigger', { params: params, lang: LANG });
    const res = r.result;
    const host1 = $('#o_chart1_host'); if (host1) host1.innerHTML = r.svg1;
    const host2 = $('#o_chart2_host'); if (host2) host2.innerHTML = r.svg2;
    const el = $('#o_results');
    if (el) {
      el.innerHTML = `
      <div class="card">
        <h4>Αποτελέσματα</h4>
        <div class="row"><b>δ_s:</b> ${fnum(res.delta_s, 6)} &nbsp; <b>GA_o:</b> ${fnum(res.GA_o, 6)}</div>
        <div class="row"><b>S_h:</b> ${fnum(res.S_h, 6)} &nbsp; <b>S_v:</b> ${fnum(res.S_v, 6)} &nbsp; <b>ω:</b> ${fnum(res.omega, 6)}</div>
        <div class="row"><b>x/H (βέλτιστο):</b> ${fnum(res.xbar_opt, 6)} &nbsp; <b>x:</b> ${fnum(res.x, 3)} m &nbsp; <b>z:</b> ${fnum(res.z, 3)} m</div>
        <div class="row"><b>y_top (βέλτιστο):</b> ${fnum(res.y_top_opt, 6)} m</div>
        <div class="row"><b>Πλησιέστερος όροφος:</b> ${res.floor_info.storey !== null ? res.floor_info.storey : '—'} (στάθμη ${fnum(res.floor_info.level, 3)} m, απόκλιση ${fnum(res.floor_info.deviation, 3)} m)</div>
        ${res.floor_info.neighbors && res.floor_info.neighbors.length ? '<div class="row"><b>Γειτονικοί:</b> ' + res.floor_info.neighbors.map(n => n.storey + ' (' + fnum(n.level,3) + ' m)').join(', ') + '</div>' : ''}
      </div>`;
    }
  } catch (e) {
    toast(t('err_calc', { msg: e.message }), true);
  }
}

/* go --------------------------------------------------------------- */

boot().catch((e) => {
  document.body.innerHTML = `<div style="padding:30px;font:14px sans-serif">
    <b>${esc(t('err_start'))}</b><br><br>${esc(e.message)}</div>`;
});
