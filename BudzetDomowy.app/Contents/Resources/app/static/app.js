'use strict';
/* Budżet domowy – interfejs */
const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const zl = (g, opt = {}) => new Intl.NumberFormat('pl-PL', { style: 'currency', currency: 'PLN', maximumFractionDigits: opt.round ? 0 : 2 }).format((g || 0) / 100);
const num = g => ((g || 0) / 100).toFixed(2).replace('.', ',');
const toGr = s => Math.round(parseFloat(String(s).replace(/\s/g, '').replace(',', '.')) * 100) || 0;
const MONTHS = ['styczeń', 'luty', 'marzec', 'kwiecień', 'maj', 'czerwiec', 'lipiec', 'sierpień', 'wrzesień', 'październik', 'listopad', 'grudzień'];
const MSHORT = ['sty', 'lut', 'mar', 'kwi', 'maj', 'cze', 'lip', 'sie', 'wrz', 'paź', 'lis', 'gru'];
const PCOL = ['var(--p1)', 'var(--p2)', 'var(--p3)', 'var(--p4)'];

let S = null;                                   // stan z serwera
const F = { mode: 'month', anchor: null, person: null };   // wybrany okres i osoba
const TX = { q: '', category: '', limit: 200 };
let view = 'przeglad', receiptId = null;

async function api(path, opt = {}) {
  const o = { method: opt.method || (opt.body ? 'POST' : 'GET'), headers: opt.headers || {} };
  if (opt.raw) o.body = opt.raw;
  else if (opt.body) { o.body = JSON.stringify(opt.body); o.headers['Content-Type'] = 'application/json'; }
  const r = await fetch('/api/' + path, o);
  const j = await r.json().catch(() => ({ error: 'Program nie odpowiada.' }));
  if (!r.ok) throw new Error(j.error || 'Coś poszło nie tak.');
  return j;
}
const qs = o => Object.entries(o).filter(([, v]) => v !== null && v !== undefined && v !== '').map(([k, v]) => k + '=' + encodeURIComponent(v)).join('&');
const pcolor = id => PCOL[Math.max(0, S.people.findIndex(p => p.id === id)) % PCOL.length];
const pname = id => (S.people.find(p => p.id === id) || {}).name || '—';
const catOptions = (sel, withNone = true) => (withNone ? `<option value="">bez kategorii</option>` : '') +
  [['expense', 'Wydatki'], ['income', 'Przychody'], ['transfer', 'Poza budżetem']].map(([k, lab]) =>
    `<optgroup label="${lab}">` + S.categories.filter(c => c.kind === k).map(c => `<option value="${c.id}" ${c.id === sel ? 'selected' : ''}>${esc(c.name)}</option>`).join('') + '</optgroup>').join('');

function range() {
  if (F.mode === 'all' || !F.anchor) return { from: S.first, to: S.last };
  const [y, m] = F.anchor.split('-').map(Number);
  if (F.mode === 'year') return { from: `${y}-01-01`, to: `${y}-12-31` };
  const last = new Date(y, m, 0).getDate();
  return { from: `${F.anchor}-01`, to: `${F.anchor}-${String(last).padStart(2, '0')}` };
}
function periodLabel() {
  if (F.mode === 'all') return 'cały okres';
  const [y, m] = F.anchor.split('-').map(Number);
  return F.mode === 'year' ? String(y) : `${MONTHS[m - 1]} ${y}`;
}
function shift(d) {
  let [y, m] = F.anchor.split('-').map(Number);
  if (F.mode === 'year') y += d; else { m += d; if (m < 1) { m = 12; y--; } if (m > 12) { m = 1; y++; } }
  F.anchor = `${y}-${String(m).padStart(2, '0')}`; render();
}

function toast(msg, action, fn, ms = 6000) {
  const t = $('#toast');
  t.innerHTML = `<span>${esc(msg)}</span>` + (action ? `<button>${esc(action)}</button>` : '');
  t.hidden = false;
  if (action) $('button', t).onclick = () => { t.hidden = true; fn(); };
  clearTimeout(toast.t); toast.t = setTimeout(() => t.hidden = true, ms);
}
function modal(html) { const m = $('#modal'); m.innerHTML = `<div class="box">${html}</div>`; m.hidden = false; return m; }
function closeModal() { $('#modal').hidden = true; }
function tip(ev, html) { const t = $('#tip'); if (!html) { t.hidden = true; return; } t.innerHTML = html; t.hidden = false;
  const w = t.offsetWidth; t.style.left = Math.min(window.innerWidth - w - 10, ev.clientX + 14) + 'px'; t.style.top = (ev.clientY + 14) + 'px'; }

// ---------- szkielet ----------
async function load() {
  S = await api('state');
  if (!F.anchor) F.anchor = (S.last || new Date().toISOString()).slice(0, 7);
}
function go(v, extra) { view = v; receiptId = null; if (extra) Object.assign(TX, extra); location.hash = v; render(); }
window.addEventListener('hashchange', () => { const v = location.hash.slice(1); if (v && v !== view) { view = v; receiptId = null; render(); } });

function topbar(title, withPeriod = true) {
  const people = S.people.length > 1 ? `<div class="seg" role="group" aria-label="Osoba">
    <button class="${F.person ? '' : 'on'}" onclick="F.person=null;render()">Razem</button>` +
    S.people.map(p => `<button class="${F.person === p.id ? 'on' : ''}" onclick="F.person=${p.id};render()"><i class="dot" style="background:${pcolor(p.id)}"></i>${esc(p.name)}</button>`).join('') + '</div>' : '';
  const period = withPeriod ? `<div class="period">${F.mode !== 'all' ? `<button class="icon" aria-label="Wcześniej" onclick="shift(-1)">‹</button>` : ''}<b>${periodLabel()}</b>${F.mode !== 'all' ? `<button class="icon" aria-label="Później" onclick="shift(1)">›</button>` : ''}</div>
    <div class="seg" role="group" aria-label="Okres">${[['month', 'Miesiąc'], ['year', 'Rok'], ['all', 'Wszystko']].map(([k, l]) => `<button class="${F.mode === k ? 'on' : ''}" onclick="F.mode='${k}';render()">${l}</button>`).join('')}</div>` : '';
  return `<div class="bar"><h1>${title}</h1>${period}${withPeriod ? people : ''}</div>`;
}

async function render() {
  await load();
  const app = $('#app');
  if (!S.people.length) return welcome(app);
  const nav = [['przeglad', 'Przegląd'], ['transakcje', 'Transakcje'], ['paragony', 'Paragony'], ['import', 'Wczytaj wyciąg'], ['ustawienia', 'Ustawienia']];
  app.innerHTML = `<div class="shell"><nav class="side"><div class="brand">Budżet domowy<small>${S.people.map(p => esc(p.name)).join(' i ')}</small></div>
    ${nav.map(([k, l]) => `<a href="#${k}" class="${view === k ? 'on' : ''}" onclick="go('${k}');return false">${l}</a>`).join('')}
    <div class="foot">wersja ${S.version}<br>Dane zostają na tym komputerze.</div></nav><main class="main" id="main"></main></div>`;
  const main = $('#main');
  try { await ({ przeglad: vOverview, transakcje: vTx, paragony: vReceipts, import: vImport, ustawienia: vSettings }[view] || vOverview)(main); }
  catch (e) { main.innerHTML = `<div class="panel">${esc(e.message)}</div>`; }
}

function welcome(app) {
  app.innerHTML = `<div class="welcome"><h1>Budżet domowy</h1><p>Zacznijmy od imion. Każde z Was będzie miało swoje konta i swój widok, a razem zobaczycie wspólny budżet.</p>
    <form class="form panel" onsubmit="saveNames(event)"><label>Pierwsza osoba<input type="text" name="a" required autofocus></label>
    <label>Druga osoba<input type="text" name="b"></label><div><button class="btn primary">Zapisz i wczytaj pierwszy wyciąg</button></div></form></div>`;
}
async function saveNames(ev) {
  ev.preventDefault();
  for (const n of [ev.target.a.value, ev.target.b.value]) if (n.trim()) await api('people', { body: { name: n.trim() } });
  go('import');
}

// ---------- przegląd ----------
async function vOverview(main) {
  if (!S.tx_count) { main.innerHTML = topbar('Przegląd', false) + `<div class="panel empty"><b>Nie ma jeszcze żadnych transakcji</b>Wczytaj wyciąg z banku, a zobaczysz tu przychody, wydatki i podział na kategorie.<div class="actions" style="justify-content:center"><button class="btn primary" onclick="go('import')">Wczytaj wyciąg</button></div></div>`; return; }
  const r = range();
  const d = await api('summary?' + qs({ ...r, person: F.person }));
  const rate = d.income > 0 ? Math.round(d.balance / d.income * 100) : null;
  let h = topbar('Przegląd');
  if (d.uncategorized) h += `<div class="note warn"><span>${d.uncategorized} ${plural(d.uncategorized, 'transakcja nie ma', 'transakcje nie mają', 'transakcji nie ma')} kategorii, więc podział wydatków jest niepełny.</span><button class="btn small" onclick="go('transakcje',{category:'none',q:''})">Przypisz kategorie</button></div>`;
  h += `<div class="figs">
    <div class="fig"><div class="lab"><i class="sw" style="background:var(--income)"></i>Przychody</div><div class="val num">${zl(d.income)}</div><div class="sub">${F.person ? esc(pname(F.person)) : 'wszystkie konta'}</div></div>
    <div class="fig"><div class="lab"><i class="sw" style="background:var(--expense)"></i>Wydatki</div><div class="val num">${zl(d.expense)}</div><div class="sub">${d.count} ${plural(d.count, 'transakcja', 'transakcje', 'transakcji')}</div></div>
    <div class="fig"><div class="lab">${d.balance >= 0 ? 'Zostaje' : 'Brakuje'}</div><div class="val num" style="color:${d.balance >= 0 ? 'var(--good)' : 'var(--bad)'}">${zl(Math.abs(d.balance))}</div><div class="sub">${rate === null ? 'brak przychodów w tym okresie' : rate >= 0 ? `${rate}% przychodów` : 'wydatki większe niż przychody'}</div></div></div>`;

  if (!F.person && S.people.length > 1) {
    const bar = (label, key) => { const tot = d.people.reduce((a, p) => a + Math.max(0, p[key]), 0);
      return `<div class="split"><div class="cap"><span>${label}</span><span class="num">${zl(tot)}</span></div><div class="track">` +
        d.people.map(p => `<div class="seg-p" style="background:${pcolor(p.id)};flex:${Math.max(0, p[key]) || 0.0001}"></div>`).join('') + `</div><div class="who">` +
        d.people.map(p => `<span><i class="dot" style="background:${pcolor(p.id)}"></i>${esc(p.name)} <b class="num">${zl(p[key])}</b> <span class="muted">${tot ? Math.round(Math.max(0, p[key]) / tot * 100) : 0}%</span></span>`).join('') + '</div></div>'; };
    h += `<div class="panel"><h2>Kto ile wnosi i wydaje</h2>${bar('Przychody', 'income')}${bar('Wydatki', 'expense')}
      <div class="who small" style="display:flex;gap:18px;flex-wrap:wrap">${d.people.map(p => `<span>${esc(p.name)}: ${p.balance >= 0 ? 'zostaje' : 'brakuje'} <b class="num">${zl(Math.abs(p.balance))}</b></span>`).join('')}</div></div>`;
  }
  h += `<div class="panel"><h2>Przychody i wydatki w ostatnich 12 miesiącach</h2>${monthlyChart(d.monthly)}</div>`;

  const max = Math.max(1, ...d.expense_by_category.map(c => Math.max(c.amount, c.budget || 0)));
  h += `<div class="panel"><h2>Na co poszły pieniądze<span>${periodLabel()}${d.period.months === 1 ? ' · porównanie ze średnią z 3 poprzednich miesięcy' : ''}</span></h2><div class="cats">` +
    (d.expense_by_category.length ? d.expense_by_category.map(c => {
      const over = c.budget && c.amount > c.budget;
      let delta = '';
      if (c.budget) delta = over ? `<span style="color:var(--bad)">${zl(c.amount - c.budget, { round: 1 })} ponad limit</span>` : `limit ${zl(c.budget, { round: 1 })}`;
      else if (c.avg) { const p = Math.round((c.amount - c.avg) / c.avg * 100); delta = Math.abs(p) < 5 ? 'jak zwykle' : `${p > 0 ? '+' : '−'}${Math.abs(p)}% niż zwykle`; }
      return `<div class="row" onclick="go('transakcje',{category:'${c.id ?? 'none'}',q:''})" title="Pokaż transakcje">
        <div class="name">${esc(c.name)}</div><div class="track"><div class="fill ${over ? 'over' : ''}" style="width:${Math.max(0, c.amount) / max * 100}%"></div>${c.budget ? `<div class="limit" style="left:${c.budget / max * 100}%"></div>` : ''}</div>
        <div class="num" style="text-align:right">${zl(c.amount)}</div><div class="delta">${delta}</div></div>`; }).join('') : '<div class="muted">Brak wydatków w tym okresie.</div>') + '</div></div>';

  h += `<div class="grid2"><div class="panel"><h2>Gdzie wydajecie najwięcej</h2><table>${d.merchants.map(m => `<tr><td>${esc(m.name)}</td><td class="muted small">${m.count}×</td><td class="r num">${zl(m.amount)}</td></tr>`).join('') || '<tr><td class="muted">Brak danych.</td></tr>'}</table></div>
    <div class="panel"><h2>Skąd przychody</h2><table>${d.income_by_category.map(c => `<tr><td>${esc(c.name)}</td><td class="r num">${zl(c.amount)}</td></tr>`).join('') || '<tr><td class="muted">Brak przychodów w tym okresie.</td></tr>'}</table></div></div>`;
  main.innerHTML = h;
}
function plural(n, a, b, c) { const m10 = n % 10, m100 = n % 100; return n === 1 ? a : (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) ? b : c; }

function monthlyChart(rows) {
  const W = 760, H = 230, L = 46, B = 26, T = 8, pw = (W - L) / rows.length, bw = Math.min(18, pw / 2 - 5);
  const max = niceMax(Math.max(1, ...rows.map(r => Math.max(r.income, r.expense))));
  const y = v => T + (H - T - B) * (1 - Math.max(0, v) / max);
  const bar = (x, v, col) => { const top = y(v), h = H - B - top; if (h < 0.5) return ''; const r = Math.min(4, h);
    return `<path d="M${x},${H - B}V${top + r}q0,${-r} ${r},${-r}h${bw - 2 * r}q${r},0 ${r},${r}V${H - B}z" fill="${col}"/>`; };
  let g = '';
  for (let i = 0; i <= 3; i++) { const v = max * i / 3; g += `<line x1="${L}" x2="${W}" y1="${y(v)}" y2="${y(v)}" stroke="var(--line2)"/><text x="${L - 8}" y="${y(v) + 4}" text-anchor="end">${i ? Math.round(v / 100).toLocaleString('pl-PL') : '0'}</text>`; }
  rows.forEach((r, i) => {
    const cx = L + pw * i + pw / 2, [yy, mm] = r.month.split('-').map(Number), sel = F.mode === 'month' && r.month === F.anchor;
    const t = `<b>${MONTHS[mm - 1]} ${yy}</b><i><span>Przychody</span><span>${zl(r.income)}</span></i><i><span>Wydatki</span><span>${zl(r.expense)}</span></i><i><span>${r.income - r.expense >= 0 ? 'Zostaje' : 'Brakuje'}</span><span>${zl(Math.abs(r.income - r.expense))}</span></i>`;
    g += (sel ? `<rect x="${cx - pw / 2 + 2}" y="${T}" width="${pw - 4}" height="${H - T - B}" fill="var(--line2)" rx="6"/>` : '') +
      bar(cx - bw - 1, r.income, 'var(--income)') + bar(cx + 1, r.expense, 'var(--expense)') +
      `<text x="${cx}" y="${H - 8}" text-anchor="middle" ${sel ? 'style="fill:var(--ink);font-weight:600"' : ''}>${MSHORT[mm - 1]}${mm === 1 || i === 0 ? " '" + String(yy).slice(2) : ''}</text>` +
      `<rect x="${cx - pw / 2}" y="0" width="${pw}" height="${H}" fill="transparent" style="cursor:pointer" data-tip="${esc(t)}" onmousemove="tip(event,this.dataset.tip)" onmouseleave="tip()" onclick="F.mode='month';F.anchor='${r.month}';tip();render()"/>`;
  });
  return `<div class="legend"><span><i class="sw" style="background:var(--income)"></i>Przychody</span><span><i class="sw" style="background:var(--expense)"></i>Wydatki</span><span class="muted">w złotych · kliknij miesiąc, aby go otworzyć</span></div>
    <svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="Przychody i wydatki miesiąc po miesiącu">${g}<line x1="${L}" x2="${W}" y1="${H - B}" y2="${H - B}" stroke="var(--line)"/></svg>
    <details class="tbl"><summary>Pokaż liczby w tabeli</summary><table><tr><th>Miesiąc</th><th class="r">Przychody</th><th class="r">Wydatki</th><th class="r">Różnica</th></tr>${rows.map(r => `<tr><td>${r.month}</td><td class="r num">${zl(r.income)}</td><td class="r num">${zl(r.expense)}</td><td class="r num">${zl(r.income - r.expense)}</td></tr>`).join('')}</table></details>`;
}
function niceMax(v) { const z = v / 100, p = Math.pow(10, Math.floor(Math.log10(z))), n = z / p; return (n <= 1.5 ? 1.5 : n <= 3 ? 3 : n <= 6 ? 6 : n <= 9 ? 9 : 15) * p * 100; }

// ---------- transakcje ----------
async function vTx(main) {
  const r = range();
  const d = await api('transactions?' + qs({ ...r, person: F.person, category: TX.category, q: TX.q, limit: TX.limit }));
  main.innerHTML = topbar('Transakcje') + `<div class="filters">
    <input type="search" placeholder="Szukaj w opisie" value="${esc(TX.q)}" onchange="TX.q=this.value;render()" style="width:240px">
    <select onchange="TX.category=this.value;render()"><option value="">wszystkie kategorie</option><option value="none" ${TX.category === 'none' ? 'selected' : ''}>tylko bez kategorii</option>${catOptions(+TX.category || null, false)}</select>
    <span class="muted small">${d.total} ${plural(d.total, 'transakcja', 'transakcje', 'transakcji')}, razem <b class="num">${zl(d.sum)}</b></span>
    <a class="btn small" style="margin-left:auto;text-decoration:none" href="/api/export.csv?${qs({ ...r, person: F.person, category: TX.category, q: TX.q })}">Zapisz jako CSV</a></div>
    <div class="panel" style="padding:6px 8px">${d.rows.length ? `<table><tr><th>Data</th><th>Opis</th><th>Kto</th><th>Kategoria</th><th class="r">Kwota</th></tr>` +
      d.rows.map(t => `<tr><td class="num small">${t.date}</td><td class="tx-desc"><b>${esc(t.merchant || t.counterparty || '—')}${t.receipt_id ? ` <a href="#paragony" class="small" onclick="openReceipt(${t.receipt_id});return false" title="Ta transakcja ma paragon">paragon</a>` : ''}</b><span title="${esc(t.description)}">${esc(t.description)}</span></td>
        <td class="small"><i class="dot" style="background:${pcolor(t.person_id)}"></i> ${esc(pname(t.person_id))}</td>
        <td><select class="${t.category_id ? '' : 'none'}" onchange="setCat(${t.id},this.value,'${esc(t.merchant).replace(/'/g, '')}')">${catOptions(t.category_id)}</select></td>
        <td class="r num ${t.amount > 0 ? 'pos' : ''}">${t.amount > 0 ? '+' : ''}${zl(t.amount)}</td></tr>`).join('') + '</table>' +
      (d.total > d.rows.length ? `<div class="actions" style="justify-content:center;margin:10px"><button class="btn" onclick="TX.limit+=300;render()">Pokaż więcej</button></div>` : '')
      : `<div class="empty"><b>Nic tu nie ma</b>Zmień okres, osobę albo filtr.</div>`}</div>`;
}
async function setCat(id, cat, merch) {
  await api('transactions/' + id, { body: { category_id: +cat || null } });
  if (cat && merch && merch.length >= 3) toast(`Zmieniono. Zawsze tak dla „${merch}”?`, 'Utwórz regułę', () => ruleDialog(merch, +cat));
  else toast('Zmieniono kategorię.');
}
function ruleDialog(pattern, cat) {
  modal(`<h2>Nowa reguła</h2><p>Każda transakcja, której opis zawiera tę frazę, dostanie wybraną kategorię. Dotyczy też przyszłych wyciągów. Ręcznie ustawione kategorie zostają.</p>
    <form class="form" onsubmit="saveRule(event)"><label>Fraza w opisie<input type="text" name="p" value="${esc(pattern)}" required minlength="3"></label>
    <label>Kategoria<select name="c">${catOptions(cat, false)}</select></label>
    <div class="actions"><button class="btn primary">Zapisz regułę</button><button type="button" class="btn" onclick="closeModal()">Anuluj</button></div></form>`);
}
async function saveRule(ev) {
  ev.preventDefault();
  try { const r = await api('rules', { body: { pattern: ev.target.p.value, category_id: +ev.target.c.value } }); closeModal(); await render(); toast(`Zapisano regułę. Zmieniono ${r.changed} ${plural(r.changed, 'transakcję', 'transakcje', 'transakcji')}.`); }
  catch (e) { toast(e.message); }
}

// ---------- import ----------
let importLog = [];
async function vImport(main) {
  main.innerHTML = topbar('Wczytaj wyciąg', false) + `<label class="drop" id="drop"><input type="file" accept=".csv,.txt" multiple hidden onchange="importFiles(this.files)">
    <b>Przeciągnij tu pliki CSV z banku</b>albo kliknij, żeby je wybrać. Możesz wczytać kilka naraz, także te same okresy ponownie – powtórki są pomijane.</label>
    <div class="results" id="results">${importLog.join('')}</div>
    <div class="grid2" style="margin-top:18px"><div class="panel"><h2>Jak pobrać plik z mBanku</h2><ol class="steps"><li>Zaloguj się w serwisie transakcyjnym i otwórz Historię.</li><li>Wybierz rachunek i okres.</li><li>Pobierz historię w formacie CSV.</li></ol></div>
    <div class="panel"><h2>Jak pobrać plik z ING</h2><ol class="steps"><li>Zaloguj się do Mojego ING i otwórz Historię.</li><li>Ustaw rachunek i zakres dat.</li><li>Pobierz listę transakcji jako CSV.</li></ol></div></div>
    <div class="panel" style="margin-top:18px"><h2>Wczytane pliki</h2>${S.imports.length ? `<table><tr><th>Kiedy</th><th>Plik</th><th>Bank</th><th class="r">Nowe</th><th class="r">Powtórki</th><th></th></tr>` +
      S.imports.map(i => `<tr><td class="small num">${i.created.replace('T', ' ')}</td><td>${esc(i.filename)}</td><td>${esc(i.bank)}</td><td class="r num">${i.added}</td><td class="r num">${i.duplicates}</td><td class="r"><button class="btn small danger" onclick="delImport(${i.id})">Cofnij</button></td></tr>`).join('') + '</table>' : '<span class="muted">Jeszcze nic nie wczytano.</span>'}</div>`;
  dropzone($('#drop'), importFiles);
}
function dropzone(el, fn) {
  el.ondragover = e => { e.preventDefault(); el.classList.add('over'); };
  el.ondragleave = () => el.classList.remove('over');
  el.ondrop = e => { e.preventDefault(); el.classList.remove('over'); fn(e.dataTransfer.files); };
}
async function importFiles(files) { for (const f of files) await importOne(f, {}, null); await render(); }
async function importOne(file, assign, mapping) {
  const headers = { 'X-Filename': encodeURIComponent(file.name), 'X-Assign': encodeURIComponent(JSON.stringify(assign)) };
  if (mapping) headers['X-Mapping'] = encodeURIComponent(JSON.stringify(mapping));
  let r;
  try { r = await api('import', { method: 'POST', raw: file, headers }); }
  catch (e) { importLog.unshift(`<div class="err"><b>${esc(file.name)}</b> – ${esc(e.message)}</div>`); return; }
  if (r.need_person) {
    const a = await askOwners(file.name, r);
    if (a) return importOne(file, { ...assign, ...a }, mapping);
    importLog.unshift(`<div><b>${esc(file.name)}</b> – pominięto.</div>`); return;
  }
  if (r.need_mapping) {
    const m = await askMapping(file.name, r.need_mapping);
    if (m) return importOne(file, assign, m);
    importLog.unshift(`<div><b>${esc(file.name)}</b> – pominięto.</div>`); return;
  }
  importLog.unshift(`<div><b>${esc(file.name)}</b> (${esc(r.bank)}, ${r.from} – ${r.to}): ${r.added} ${plural(r.added, 'nowa transakcja', 'nowe transakcje', 'nowych transakcji')}` +
    (r.duplicates ? `, ${r.duplicates} już było` : '') + (r.skipped ? `, ${r.skipped} nierozliczonych blokad pominięto` : '') +
    (r.transfers ? `, ${r.transfers} ${plural(r.transfers, 'przelew', 'przelewy', 'przelewów')} między Waszymi kontami` : '') + (r.receipts_matched ? `, dopasowano ${r.receipts_matched} paragonów` : '') + '.</div>');
  if (r.added) { F.anchor = r.to.slice(0, 7); }
}
function askOwners(name, r) {
  return new Promise(res => {
    const m = modal(`<h2>Czyje to konto?</h2><p>Plik ${esc(name)} (${esc(r.bank)}) zawiera konto, którego jeszcze nie znam. Zapamiętam wybór na przyszłość.</p>
      <form class="form">${r.need_person.map((l, i) => `<label>${esc(l)}<select name="a${i}">${S.people.map(p => `<option value="${p.id}">${esc(p.name)}</option>`).join('')}</select></label>`).join('')}
      <div class="actions"><button class="btn primary">Wczytaj</button><button type="button" class="btn" id="cancel">Pomiń ten plik</button></div></form>`);
    $('form', m).onsubmit = e => { e.preventDefault(); const a = {}; r.need_person.forEach((l, i) => a[l] = +e.target['a' + i].value); closeModal(); res(a); };
    $('#cancel', m).onclick = () => { closeModal(); res(null); };
  });
}
function askMapping(name, d) {
  return new Promise(res => {
    const opts = d.headers.map((h, i) => `<option value="${i}">${esc(h || 'kolumna ' + (i + 1))}</option>`).join('');
    const m = modal(`<h2>Nie znam tego układu pliku</h2><p>Wskaż, w których kolumnach pliku ${esc(name)} są data, kwota i opis.</p>
      <form class="form"><label>Data<select name="d">${opts}</select></label><label>Kwota<select name="a">${opts}</select></label><label>Opis<select name="o">${opts}</select></label>
      <div class="small muted" style="overflow:auto"><table>${d.sample.map(r => '<tr>' + r.map(c => `<td>${esc(c)}</td>`).join('') + '</tr>').join('')}</table></div>
      <div class="actions"><button class="btn primary">Wczytaj</button><button type="button" class="btn" id="cancel">Pomiń ten plik</button></div></form>`);
    $('form', m).onsubmit = e => { e.preventDefault(); closeModal(); res({ date: +e.target.d.value, amount: +e.target.a.value, desc: [+e.target.o.value] }); };
    $('#cancel', m).onclick = () => { closeModal(); res(null); };
  });
}
async function delImport(id) { if (confirm('Usunąć transakcje wczytane z tego pliku?')) { await api('imports/' + id, { method: 'DELETE' }); render(); } }

// ---------- paragony ----------
let receiptLog = [];
async function vReceipts(main) {
  if (receiptId) return vReceipt(main);
  const [list, an] = await Promise.all([api('receipts'), api('items?' + qs({ ...range(), person: F.person }))]);
  const ocrNote = S.ocr.ok ? '' : `<div class="note warn"><span>Na tym Macu brakuje narzędzi Apple do odczytu tekstu ze zdjęć. Otwórz Terminal, wpisz <code>xcode-select --install</code> i potwierdź instalację. Do tego czasu pozycje paragonu trzeba wpisywać ręcznie.</span></div>`;
  const maxC = Math.max(1, ...an.categories.map(c => c.amount));
  main.innerHTML = topbar('Paragony') + ocrNote + `<label class="drop" id="drop"><input type="file" accept="image/*,.pdf,.heic" multiple hidden onchange="uploadReceipts(this.files)">
    <b>Przeciągnij tu skany albo zdjęcia paragonów</b>JPG, PNG, HEIC lub PDF. Program odczyta pozycje i połączy paragon z płatnością kartą z wyciągu.</label>
    <div class="results" id="rresults">${receiptLog.join('')}</div>
    <div class="panel" style="margin-top:18px"><h2>Wczytane paragony<span>${list.length}</span></h2>${list.length ? `<div class="rlist">` + list.map(r => {
      const diff = r.items_sum !== r.total;
      return `<button class="rcard" onclick="openReceipt(${r.id})"><b>${esc(r.store || 'Sklep nieodczytany')}</b>${r.date || 'brak daty'} · ${r.n} poz.
        <div class="sum"><span>SUMA</span><span>${num(r.total)}</span></div>
        <div class="st">${r.transaction_id ? 'połączony z płatnością' : r.payment === 'cash' ? 'gotówka' : 'bez pary w wyciągu'}${diff && !r.checked ? ' · <span style="color:#b45309">do sprawdzenia</span>' : ''}</div></button>`; }).join('') + '</div>'
      : '<span class="muted">Nie ma jeszcze paragonów.</span>'}</div>
    <div class="grid2"><div class="panel"><h2>Co kupujecie<span>${periodLabel()}, z paragonów</span></h2><div class="cats" style="grid-template-columns:minmax(120px,180px) 1fr auto">${an.categories.map(c => `<div class="name">${esc(c.name)}</div><div class="track"><div class="fill" style="width:${c.amount / maxC * 100}%"></div></div><div class="num" style="text-align:right">${zl(c.amount)}</div>`).join('') || '<span class="muted">Brak paragonów w tym okresie.</span>'}</div></div>
    <div class="panel"><h2>Produkty, na które idzie najwięcej</h2><table>${an.products.slice(0, 12).map(p => `<tr><td>${esc(p.name)}<div class="muted small">${esc(p.category || '')}</div></td><td class="muted small num">${p.n}×</td><td class="r num">${zl(p.amount)}</td></tr>`).join('') || '<tr><td class="muted">Brak danych.</td></tr>'}</table></div></div>`;
  dropzone($('#drop'), uploadReceipts);
}
async function uploadReceipts(files) {
  for (const f of files) {
    $('#rresults').insertAdjacentHTML('afterbegin', `<div id="busy">Odczytuję ${esc(f.name)}…</div>`);
    try {
      const r = await api('receipts?' + qs({ person: F.person || S.people[0].id }), { method: 'POST', raw: f, headers: { 'X-Filename': encodeURIComponent(f.name) } });
      receiptLog.unshift(`<div><b>${esc(f.name)}</b>: ${esc(r.store || 'sklep nieodczytany')}, ${r.items.length} pozycji, suma ${zl(r.total)}${r.transaction ? ', połączono z płatnością z ' + r.transaction.date : ''}. <a href="#" onclick="openReceipt(${r.id});return false">Sprawdź</a></div>`);
    } catch (e) { receiptLog.unshift(`<div class="err"><b>${esc(f.name)}</b> – ${esc(e.message)}</div>`); }
  }
  render();
}
function openReceipt(id) { view = 'paragony'; receiptId = id; location.hash = 'paragony'; render(); }
let R = null;
async function vReceipt(main) {
  R = await api('receipts/' + receiptId);
  main.innerHTML = `<div class="bar"><button class="btn" onclick="receiptId=null;render()">‹ Wszystkie paragony</button><h1 style="margin-left:6px">Paragon</h1></div>
    <div class="rdetail"><div>${/\.pdf$/i.test(R.preview || '') ? `<a href="/paragon/${esc(R.preview)}" target="_blank">Otwórz plik PDF</a>` : `<a href="/paragon/${esc(R.preview)}" target="_blank"><img src="/paragon/${esc(R.preview)}" alt="Skan paragonu"></a>`}
      ${R.ocr_text ? `<details class="tbl"><summary>Odczytany tekst</summary><pre style="white-space:pre-wrap;font:12px var(--mono)">${esc(R.ocr_text)}</pre></details>` : '<p class="muted small" style="margin-top:8px">Nie udało się odczytać tekstu – wpisz pozycje ręcznie.</p>'}</div>
    <div><div class="paper" id="paper"></div>
      <div class="panel" style="margin-top:18px"><h2>Płatność w wyciągu</h2><div id="link"></div></div></div></div>`;
  drawPaper(); drawLink();
}
function drawPaper() {
  const sum = R.items.reduce((a, i) => a + i.amount, 0), diff = sum - R.total;
  $('#paper').innerHTML = `<div class="hd"><div><label>Sklep</label><input value="${esc(R.store || '')}" onchange="R.store=this.value"></div>
    <div><label>Data</label><input type="date" value="${R.date || ''}" onchange="R.date=this.value"></div>
    <div><label>Suma</label><input value="${num(R.total)}" inputmode="decimal" onchange="R.total=toGr(this.value);drawPaper()"></div>
    <div><label>Kto płacił</label><select onchange="R.person_id=+this.value">${S.people.map(p => `<option value="${p.id}" ${p.id === R.person_id ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}</select></div></div>
    <table><tr><th>Pozycja</th><th style="width:58px">Ilość</th><th style="width:80px" class="r">Kwota</th><th style="width:170px">Kategoria</th><th style="width:26px"></th></tr>` +
    R.items.map((it, i) => `<tr><td><input value="${esc(it.name)}" onchange="R.items[${i}].name=this.value"></td>
      <td><input value="${String(it.qty).replace('.', ',')}" inputmode="decimal" onchange="R.items[${i}].qty=parseFloat(this.value.replace(',','.'))||1"></td>
      <td><input style="text-align:right" value="${num(it.amount)}" inputmode="decimal" onchange="R.items[${i}].amount=toGr(this.value);drawPaper()"></td>
      <td><select onchange="R.items[${i}].category_id=+this.value||null">${catOptions(it.category_id)}</select></td>
      <td><button class="x" aria-label="Usuń pozycję" onclick="R.items.splice(${i},1);drawPaper()">×</button></td></tr>`).join('') + `</table>
    <div class="actions" style="margin-top:8px"><button class="btn small" onclick="R.items.push({name:'',qty:1,amount:0,unit_price:0,category_id:null});drawPaper()">Dodaj pozycję</button></div>
    <div class="tot"><span>SUMA POZYCJI</span><span>${num(sum)}</span></div>
    <div class="chk">${diff === 0 ? '✓ Pozycje zgadzają się z sumą paragonu.' : `<span style="color:#b45309">Pozycje ${diff > 0 ? 'przekraczają sumę' : 'są mniejsze od sumy'} o ${num(Math.abs(diff))} zł – sprawdź kwoty, ilości i rabaty.</span>`}</div>
    <div class="actions"><button class="btn primary" onclick="saveReceipt()">Zapisz paragon</button>
      <select style="width:auto" onchange="R.payment=this.value||null"><option value="card" ${R.payment !== 'cash' ? 'selected' : ''}>płatność kartą</option><option value="cash" ${R.payment === 'cash' ? 'selected' : ''}>gotówka</option></select>
      <button class="btn danger" style="margin-left:auto" onclick="delReceipt()">Usuń</button></div>`;
}
async function drawLink() {
  const el = $('#link');
  if (R.transaction) { const t = R.transaction;
    el.innerHTML = `<p>${t.date} · ${esc(t.counterparty || t.description)} · <b class="num">${zl(t.amount)}</b> · ${esc(pname(t.person_id))}</p><p class="muted small" style="margin:6px 0 10px">W zestawieniach ta płatność jest rozbita na pozycje paragonu.</p><button class="btn small" onclick="linkTx(null)">Rozłącz</button>`;
    return; }
  if (R.payment === 'cash') { el.innerHTML = `<p class="muted">Paragon gotówkowy. Jego pozycje widać w zestawieniu zakupów, a w budżecie gotówka liczy się w chwili wypłaty z bankomatu.</p>`; return; }
  const c = await api(`receipts/${R.id}/candidates`);
  el.innerHTML = `<p class="muted small" style="margin-bottom:8px">Nie znalazłem płatności na tę samą kwotę. Wczytaj wyciąg z tego okresu albo wskaż ją sam:</p>` +
    (c.length ? `<table>${c.map(t => `<tr><td class="num small">${t.date}</td><td class="small">${esc(t.counterparty || t.description).slice(0, 60)}</td><td class="r num">${zl(t.amount)}</td><td class="r"><button class="btn small" onclick="linkTx(${t.id})">To ta</button></td></tr>`).join('')}</table>` : '<span class="muted small">Brak płatności w pobliżu tej daty.</span>');
}
async function linkTx(id) { await api('receipts/' + R.id, { body: { transaction_id: id } }); render(); }
async function saveReceipt() {
  try { await api('receipts/' + R.id, { body: { store: R.store, date: R.date, total: R.total, payment: R.payment || 'card', person_id: R.person_id, items: R.items, checked: 1, rematch: !R.transaction } });
    await render(); toast('Zapisano paragon.'); } catch (e) { toast(e.message); }
}
async function delReceipt() { if (confirm('Usunąć ten paragon razem ze skanem?')) { await api('receipts/' + R.id, { method: 'DELETE' }); receiptId = null; render(); } }

// ---------- ustawienia ----------
async function vSettings(main) {
  const kinds = { expense: 'wydatek', income: 'przychód', transfer: 'poza budżetem' };
  main.innerHTML = topbar('Ustawienia', false) + `<div class="grid2"><div class="panel"><h2>Osoby</h2><table>${S.people.map(p => `<tr><td><i class="dot" style="background:${pcolor(p.id)}"></i></td><td><input type="text" value="${esc(p.name)}" onchange="savePerson(${p.id},this.value)"></td></tr>`).join('')}</table>
      <form class="actions" onsubmit="event.preventDefault();savePerson(null,this.n.value)"><input type="text" name="n" placeholder="np. Wspólne" required><button class="btn">Dodaj osobę</button></form></div>
    <div class="panel"><h2>Konta</h2>${S.accounts.length ? `<table>${S.accounts.map(a => `<tr><td>${esc(a.bank)}<div class="muted small">${esc(a.label)} · ${a.n} transakcji</div></td><td><select onchange="saveAccount(${a.id},this.value)">${S.people.map(p => `<option value="${p.id}" ${p.id === a.person_id ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}</select></td></tr>`).join('')}</table>` : '<span class="muted">Konta pojawią się po wczytaniu wyciągu.</span>'}</div></div>
    <div class="panel" style="margin-top:18px"><h2>Kategorie i miesięczne limity<span>limit 0 oznacza brak limitu</span></h2><table><tr><th>Nazwa</th><th>Rodzaj</th><th class="r">Limit na miesiąc (zł)</th><th></th></tr>
      ${S.categories.map(c => `<tr><td><input type="text" value="${esc(c.name)}" onchange="saveCat(${c.id},{name:this.value})"></td>
        <td><select onchange="saveCat(${c.id},{kind:this.value})">${Object.entries(kinds).map(([k, l]) => `<option value="${k}" ${c.kind === k ? 'selected' : ''}>${l}</option>`).join('')}</select></td>
        <td class="r">${c.kind === 'expense' ? `<input type="number" min="0" step="50" style="width:110px;text-align:right" value="${c.budget / 100}" onchange="saveCat(${c.id},{budget:Math.round(this.value*100)})">` : ''}</td>
        <td class="r"><button class="btn small danger" onclick="delCat(${c.id},'${esc(c.name).replace(/'/g, '')}')">Usuń</button></td></tr>`).join('')}</table>
      <form class="actions" onsubmit="event.preventDefault();addCat(this)"><input type="text" name="n" placeholder="Nowa kategoria" required><select name="k">${Object.entries(kinds).map(([k, l]) => `<option value="${k}">${l}</option>`).join('')}</select><button class="btn">Dodaj kategorię</button></form></div>
    <div class="panel"><h2>Twoje reguły<span>fraza w opisie transakcji → kategoria</span></h2>${S.rules.length ? `<table>${S.rules.map(r => `<tr><td><code>${esc(r.pattern)}</code></td><td>${esc(r.category)}</td><td class="r"><button class="btn small danger" onclick="delRule(${r.id})">Usuń</button></td></tr>`).join('')}</table>` : '<span class="muted">Reguły powstają, gdy zmienisz kategorię transakcji i wybierzesz „Utwórz regułę”. Program ma też wbudowane reguły dla popularnych sklepów i usług.</span>'}</div>
    <div class="panel"><h2>Dane i program</h2><p class="small">Wszystko jest zapisane w folderze <code>${esc(S.data_dir)}</code>. Skopiuj ten folder, żeby zrobić kopię zapasową.</p>
      <div class="actions"><button class="btn" onclick="quit()">Zamknij program</button></div></div>`;
}
async function savePerson(id, name) { try { await api('people' + (id ? '/' + id : ''), { body: { name } }); render(); } catch (e) { toast(e.message); } }
async function saveAccount(id, pid) { await api('accounts/' + id, { body: { person_id: +pid } }); toast('Zapisano.'); }
async function saveCat(id, b) { try { await api('categories/' + id, { body: b }); await load(); toast('Zapisano.'); } catch (e) { toast(e.message); } }
async function addCat(f) { try { await api('categories', { body: { name: f.n.value, kind: f.k.value } }); render(); } catch (e) { toast(e.message); } }
async function delCat(id, name) { if (confirm(`Usunąć kategorię „${name}”? Jej transakcje zostaną bez kategorii.`)) { await api('categories/' + id, { method: 'DELETE' }); render(); } }
async function delRule(id) { await api('rules/' + id, { method: 'DELETE' }); render(); }
async function quit() { await api('quit', { method: 'POST' }); $('#app').innerHTML = '<div class="welcome"><h1>Program zamknięty</h1><p>Możesz zamknąć tę kartę. Żeby wrócić, otwórz Budżet domowy z folderu Programy.</p></div>'; }

view = location.hash.slice(1) || 'przeglad';
render();
