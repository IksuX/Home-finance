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
const TX = { q: '', category: '', account: '', limit: 200 };
const accName = x => x.name || (x.bank === 'Ręczne' ? x.label : `${x.bank} ${x.label}`);
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
// sign < 0: tylko kategorie wydatków (i „poza budżetem”), sign > 0: tylko przychodów; bez sign: wszystkie
const catOptions = (sel, withNone = true, sign = 0) => {
  const groups = [['expense', 'Wydatki'], ['income', 'Przychody'], ['transfer', 'Poza budżetem']].filter(([k]) => !sign || k === 'transfer' || (k === 'expense') === (sign < 0));
  const cur = S.categories.find(c => c.id === sel), bad = cur && !groups.some(([k]) => k === cur.kind);
  return (withNone ? `<option value="">bez kategorii</option>` : '') + (bad ? `<option value="${cur.id}" selected>⚠ ${esc(cur.name)} – nie pasuje, zmień</option>` : '') +
    groups.map(([k, lab]) => `<optgroup label="${lab}">` + S.categories.filter(c => c.kind === k).map(c => `<option value="${c.id}" ${c.id === sel ? 'selected' : ''}>${esc(c.name)}</option>`).join('') + '</optgroup>').join('');
};

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
function go(v, extra) { view = v; receiptId = null; PR.open = null; if (extra) Object.assign(TX, extra); location.hash = v; render(); }
window.addEventListener('hashchange', () => { const v = location.hash.slice(1); if (v && v !== view) { view = v; receiptId = null; PR.open = null; render(); } });

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
  const nav = [['przeglad', 'Przegląd'], ['transakcje', 'Transakcje'], ['paragony', 'Paragony'], ['produkty', 'Produkty'], ['konta', 'Konta'], ['rozliczenia', 'Rozliczenia'], ['import', 'Wczytaj wyciąg'], ['ustawienia', 'Ustawienia']];
  app.innerHTML = `<div class="shell"><nav class="side"><div class="brand">Budżet domowy<small>${S.people.map(p => esc(p.name)).join(' i ')}</small></div>
    ${nav.map(([k, l]) => `<a href="#${k}" class="${view === k ? 'on' : ''}" onclick="go('${k}');return false">${l}</a>`).join('')}
    <div class="foot">wersja ${S.version}<br>Dane zostają na tym komputerze.</div></nav><main class="main" id="main"></main></div>`;
  const main = $('#main');
  try { await ({ przeglad: vOverview, transakcje: vTx, paragony: vReceipts, produkty: vProducts, konta: vAccounts, rozliczenia: vSettle, import: vImport, ustawienia: vSettings }[view] || vOverview)(main); }
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
  const [d, an, nw, st] = await Promise.all([api('summary?' + qs({ ...r, person: F.person })), api('items?' + qs({ ...r, person: F.person })), api('networth?' + qs({ person: F.person })), api('settlements?' + qs({ ...r, person: F.person }))]);
  const rate = d.income > 0 ? Math.round(d.balance / d.income * 100) : null;
  let h = topbar('Przegląd');
  if (d.uncategorized) h += `<div class="note warn"><span>${d.uncategorized} ${plural(d.uncategorized, 'transakcja nie ma', 'transakcje nie mają', 'transakcji nie ma')} kategorii, więc podział wydatków jest niepełny.</span><button class="btn small" onclick="go('transakcje',{category:'none',q:''})">Przypisz kategorie</button></div>`;
  h += `<div class="figs">
    <div class="fig"><div class="lab"><i class="sw" style="background:var(--income)"></i>Przychody</div><div class="val num">${zl(d.income)}</div><div class="sub">${F.person ? esc(pname(F.person)) : 'wszystkie konta'}</div></div>
    <div class="fig"><div class="lab"><i class="sw" style="background:var(--expense)"></i>Wydatki</div><div class="val num">${zl(d.expense)}</div><div class="sub">${d.count} ${plural(d.count, 'transakcja', 'transakcje', 'transakcji')}</div></div>
    <div class="fig"><div class="lab">${d.balance >= 0 ? 'Zostaje' : 'Brakuje'}</div><div class="val num" style="color:${d.balance >= 0 ? 'var(--good)' : 'var(--bad)'}">${zl(Math.abs(d.balance))}</div><div class="sub">${rate === null ? 'brak przychodów w tym okresie' : rate >= 0 ? `${rate}% przychodów` : 'wydatki większe niż przychody'}${d.saved > 0 ? `, z tego ${zl(d.saved)} odłożono poza budżet` : d.saved < 0 ? `; z kont poza budżetem wróciło ${zl(-d.saved)}` : ''}</div></div></div>`;

  if (!F.person && S.people.length > 1) {
    const bar = (label, key) => { const tot = d.people.reduce((a, p) => a + Math.max(0, p[key]), 0);
      return `<div class="split"><div class="cap"><span>${label}</span><span class="num">${zl(tot)}</span></div><div class="track">` +
        d.people.map(p => `<div class="seg-p" style="background:${pcolor(p.id)};flex:${Math.max(0, p[key]) || 0.0001}"></div>`).join('') + `</div><div class="who">` +
        d.people.map(p => `<span><i class="dot" style="background:${pcolor(p.id)}"></i>${esc(p.name)} <b class="num">${zl(p[key])}</b> <span class="muted">${tot ? Math.round(Math.max(0, p[key]) / tot * 100) : 0}%</span></span>`).join('') + '</div></div>'; };
    h += `<div class="panel"><h2>Kto ile wnosi i wydaje</h2>${bar('Przychody', 'income')}${bar('Wydatki', 'expense')}
      <div class="who small" style="display:flex;gap:18px;flex-wrap:wrap">${d.people.map(p => `<span>${esc(p.name)}: ${p.balance >= 0 ? 'zostaje' : 'brakuje'} <b class="num">${zl(Math.abs(p.balance))}</b></span>`).join('')}</div></div>`;
  }
  if (an.savings.total) h += `<div class="note"><span>Na promocjach i rabatach zaoszczędzono <b class="num">${zl(an.savings.total)}</b> – tyle wynika z ${an.savings.receipts} ${plural(an.savings.receipts, 'wczytanego dokumentu', 'wczytanych dokumentów', 'wczytanych dokumentów')} w tym okresie.</span><button class="btn small" onclick="go('paragony')">Szczegóły</button></div>`;
  h += flowPanel(d);
  const miss = st.groups.filter(g => g.missing_in_period);
  if (miss.length) h += `<div class="note warn"><span>Rozliczenia, które się nie wyzerowały w tym okresie: ${miss.map(g => `${esc(g.name)} (${g.missing_in_period} bez zwrotu)`).join(', ')}.</span><button class="btn small" onclick="go('rozliczenia')">Pokaż</button></div>`;
  h += worthPanel(nw);
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
function flowPanel(d) {
  const f = d.flow;
  if (f.missing.length) return `<div class="note warn"><span>Żeby policzyć, ile pieniędzy było na początku okresu i ile zostało na koniec, brakuje salda otwarcia: ${f.missing.map(esc).join(', ')}.</span><button class="btn small" onclick="go('konta');setTimeout(openingDialog,400)">Wpisz salda otwarcia</button></div>`;
  if (!f.start && !f.end) return '';
  const net = d.income - d.expense, gap = f.end - f.start - net - f.transfers;
  const cell = (lab, val, sub, op) => `${op ? `<div class="op">${op}</div>` : ''}<div class="fc"><div class="lab">${lab}</div><div class="num v">${val}</div><div class="sub">${sub}</div></div>`;
  return `<div class="panel"><h2>Pieniądze w budżecie<span>konta bieżące i gotówka${F.person ? ', ' + esc(pname(F.person)) : ''}</span></h2><div class="flow">
    ${cell('Na początek okresu', zl(f.start), 'stan na ' + f.before)}
    ${cell('Przychody', zl(d.income), periodLabel(), '+')}
    ${cell('Wydatki', zl(d.expense), periodLabel(), '−')}
    ${f.transfers ? cell(f.transfers < 0 ? 'Przelano poza budżet' : 'Wróciło do budżetu', zl(Math.abs(f.transfers)), F.person ? 'oszczędności, inwestycje, przelewy między Wami' : 'oszczędności, inwestycje i podobne', f.transfers < 0 ? '−' : '+') : ''}
    ${Math.abs(gap) > 100 ? cell('Różnica do wyjaśnienia', `<span style="color:var(--warn)">${zl(Math.abs(gap))}</span>`, 'stan kont różni się od wyliczenia', gap < 0 ? '−' : '+') : ''}
    ${cell('Na koniec okresu', `<b>${zl(f.end)}</b>`, 'stan na ' + d.period.to, '=')}</div>
    ${Math.abs(gap) > 100 ? `<p class="small muted" style="margin-top:12px">Różnica bierze się zwykle z brakującego wyciągu za część okresu, przelewu, którego druga strona nie jest wczytana, albo poprawionego ręcznie stanu konta.</p>` : ''}
    ${net < 0 && f.start > 0 ? `<p class="small" style="margin-top:12px">Wydatki były większe od przychodów o <b class="num">${zl(-net)}</b>. Tę różnicę pokryło saldo z początku okresu.</p>` : ''}</div>`;
}
function worthPanel(nw) {
  if (!nw.known && !nw.unknown.length) return '';
  const max = Math.max(1, ...nw.groups.map(g => Math.abs(g.amount)));
  const pts = nw.monthly.filter(m => m.accounts > 0);
  const missing = nw.unknown.length ? `<div class="note warn" style="margin:14px 0 0"><span>Bez ${plural(nw.unknown.length, 'konta', 'kont', 'kont')} o nieznanym stanie: ${nw.unknown.map(u => esc(u.name)).join(', ')}. Wyciąg nie podaje salda – wpisz stan ręcznie.</span><button class="btn small" onclick="go('konta')">Wpisz stan</button></div>` : '';
  return `<div class="panel"><h2>Stan posiadania<span>${F.person ? esc(pname(F.person)) : 'wszystkie konta'}, według najnowszych danych</span></h2>
    <div class="worth"><div><div class="val num">${zl(nw.total)}</div><div class="muted small">${nw.known} ${plural(nw.known, 'konto', 'konta', 'kont')} ze znanym stanem</div>
      <div class="cats" style="grid-template-columns:minmax(110px,170px) 1fr auto;margin-top:14px">${nw.groups.map(g => `<div class="row" onclick="go('konta')" title="Otwórz Konta"><div class="name">${esc(g.name)}</div><div class="track"><div class="fill" style="width:${Math.abs(g.amount) / max * 100}%"></div></div><div class="num" style="text-align:right">${zl(g.amount)}</div></div>`).join('')}</div></div>
      <div>${pts.length >= 2 ? worthChart(nw.monthly) : '<span class="muted small">Wykres zmian pojawi się, gdy stany kont będą znane z co najmniej dwóch miesięcy.</span>'}</div></div>${missing}</div>`;
}
function worthChart(rows) {
  const W = 420, H = 190, L = 50, B = 24, T = 10, Rm = 10, pts = rows.map((r, i) => ({ ...r, i })).filter(r => r.accounts > 0);
  const vals = pts.map(p => p.total); let lo = Math.min(...vals), hi = Math.max(...vals); const pad = Math.max((hi - lo) * 0.15, hi * 0.03, 100); lo -= pad; hi += pad;
  const x = i => L + (W - L - Rm) * i / (rows.length - 1), y = v => T + (H - T - B) * (1 - (v - lo) / (hi - lo));
  let g = '';
  for (let k = 0; k <= 2; k++) { const v = lo + (hi - lo) * k / 2; g += `<line x1="${L}" x2="${W - Rm}" y1="${y(v)}" y2="${y(v)}" stroke="var(--line2)"/><text x="${L - 6}" y="${y(v) + 4}" text-anchor="end">${Math.round(v / 100000) ? (v / 100000).toFixed(1).replace('.', ',') + ' tys.' : Math.round(v / 100)}</text>`; }
  g += `<polyline fill="none" stroke="var(--seq)" stroke-width="2" stroke-linejoin="round" points="${pts.map(p => `${x(p.i)},${y(p.total)}`).join(' ')}"/>`;
  pts.forEach((p, k) => { const [yy, mm] = p.month.split('-').map(Number);
    const t = `<b>koniec: ${MONTHS[mm - 1]} ${yy}</b><i><span>Razem</span><span>${zl(p.total)}</span></i><i><span>Kont ze znanym stanem</span><span>${p.accounts}</span></i>`;
    g += `<circle cx="${x(p.i)}" cy="${y(p.total)}" r="4" fill="var(--seq)" stroke="var(--surface)" stroke-width="2"/>` + (k === 0 || k === pts.length - 1 ? `<text x="${x(p.i)}" y="${H - 6}" text-anchor="${k === 0 ? 'start' : 'end'}">${MSHORT[mm - 1]} ${yy}</text>` : '') +
      `<rect x="${x(p.i) - 14}" y="0" width="28" height="${H}" fill="transparent" data-tip="${esc(t)}" onmousemove="tip(event,this.dataset.tip)" onmouseleave="tip()"/>`; });
  return `<div class="muted small" style="margin-bottom:4px">Suma na koniec miesiąca, z kont o znanym wtedy stanie</div><svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="Stan posiadania miesiąc po miesiącu">${g}</svg>`;
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
  const d = await api('transactions?' + qs({ ...r, person: F.person, category: TX.category, q: TX.q, account: TX.account, limit: TX.limit }));
  TXROWS = Object.fromEntries(d.rows.map(t => [t.id, t]));
  main.innerHTML = topbar('Transakcje') + `<div class="filters">
    <input type="search" placeholder="Szukaj w opisie albo kwoty" value="${esc(TX.q)}" onchange="TX.q=this.value;render()" style="width:240px">
    <select onchange="TX.category=this.value;render()"><option value="">wszystkie kategorie</option><option value="none" ${TX.category === 'none' ? 'selected' : ''}>tylko bez kategorii</option>${catOptions(+TX.category || null, false)}</select>
    <select style="max-width:240px" onchange="TX.account=this.value;render()"><option value="">wszystkie konta</option>${S.accounts.filter(x => x.n).map(x => `<option value="${x.id}" ${+TX.account === x.id ? 'selected' : ''}>${esc(accName(x))}${x.kind && !['budget', 'cash'].includes(x.kind) ? ' (poza budżetem)' : ''}</option>`).join('')}</select>
    <button class="btn primary small" onclick="manualDialog()">Dodaj ręcznie</button>
    <span class="muted small">${d.total} ${plural(d.total, 'transakcja', 'transakcje', 'transakcji')}, razem <b class="num">${zl(d.sum)}</b></span>
    <a class="btn small" style="margin-left:auto;text-decoration:none" href="/api/export.csv?${qs({ ...r, person: F.person, category: TX.category, q: TX.q })}">Zapisz jako CSV</a></div>
    <div class="panel" style="padding:6px 8px">${d.rows.length ? `<table><tr><th>Data</th><th>Opis</th><th>Kto</th><th>Kategoria</th><th class="r">Kwota</th></tr>` +
      d.rows.map(t => `<tr><td class="num small">${t.date}</td><td class="tx-desc"><b>${esc(t.manual ? t.description : (t.merchant || t.counterparty || '—'))}${t.receipt_id ? ` <a href="#paragony" class="small" onclick="openReceipt(${t.receipt_id});return false" title="Ta transakcja ma paragon">paragon</a>` : ''}</b><span title="${esc(t.description)}">${t.account_kind && !['budget', 'cash'].includes(t.account_kind) ? '<em style="font-style:normal;color:var(--warn)">poza budżetem</em> · ' : ''}${t.manual ? `<em style="font-style:normal;color:var(--accent)">wpisane ręcznie${t.account_kind === 'cash' ? ', gotówka' : ''}</em>` : esc(t.description)}</span>
          ${t.pair_id ? `<span class="small" style="color:var(--accent)">↔ ${t.amount < 0 ? 'na' : 'z'} ${esc(t.pair_bank === 'Ręczne' ? t.pair_account : t.pair_bank + ' ' + t.pair_account)} · ${t.pair_date}${t.pair_amount !== -t.amount ? ` · ${zl(t.pair_amount)}` : ''} <button class="btn small" style="padding:0 6px" onclick="unlinkTx(${t.id})">Rozłącz</button></span>` : `<button class="rowact small" onclick="pairDialog(${t.id})">↔ Powiąż z transakcją na innym koncie</button>`}
          <input class="note-in" type="text" value="${esc(t.note || '')}" placeholder="Dodaj opis" aria-label="Opis transakcji" onchange="saveNote(${t.id},this.value)"></td>
        <td class="small"><i class="dot" style="background:${pcolor(t.person_id)}"></i> ${esc(pname(t.person_id))}</td>
        <td><select class="${catFits(t) ? '' : 'none'}" onchange="setCat(${t.id},this.value)">${catOptions(t.category_id, true, t.amount)}</select>${t.processor ? `<div class="muted small" title="Odbiorcą jest pośrednik płatności – sprzedawca pochodzi z tytułu przelewu">przez ${esc((t.counterparty || '').split(/\s+/).slice(0, 2).join(' '))}</div>` : ''}</td>
        <td class="r num ${t.amount > 0 ? 'pos' : ''}">${t.amount > 0 ? '+' : ''}${zl(t.amount)}${t.manual ? `<div><button class="btn small danger" onclick="delTx(${t.id})">Usuń</button></div>` : ''}</td></tr>`).join('') + '</table>' +
      (d.total > d.rows.length ? `<div class="actions" style="justify-content:center;margin:10px"><button class="btn" onclick="TX.limit+=300;render()">Pokaż więcej</button></div>` : '')
      : `<div class="empty"><b>Nic tu nie ma</b>Zmień okres, osobę albo filtr.</div>`}</div>`;
}
async function pairDialog(id) {
  const t = TXROWS[id], c = await api(`transactions/${id}/pairs`);
  modal(`<h2>Powiąż transakcje</h2><p>${t.amount < 0 ? 'Wypływ' : 'Wpływ'} ${zl(t.amount)} z ${t.date} (${esc(t.bank === 'Ręczne' ? t.account : t.bank + ' ' + t.account)}). Wskaż ${t.amount < 0 ? 'wpływ' : 'wypływ'} na innym koncie, który jest drugą stroną tego przelewu – np. doładowanie Revolut. Obie transakcje przestaną się liczyć jako wydatek i przychód.</p>
    ${c.length ? `<table class="tight">${c.map(x => `<tr><td class="num small">${x.date}</td><td class="small">${esc(x.bank === 'Ręczne' ? x.account : x.bank + ' ' + x.account)}<div class="muted">${esc((x.counterparty || x.description || '')).slice(0, 50)}</div></td>
      <td class="r num">${zl(x.amount)}<div class="small" style="color:var(--${Math.abs(x.amount) === Math.abs(t.amount) ? 'good' : 'warn'})">${Math.abs(x.amount) === Math.abs(t.amount) ? 'kwota zgodna' : 'różnica ' + zl(Math.abs(Math.abs(x.amount) - Math.abs(t.amount)))}</div></td>
      <td class="r"><button class="btn small" onclick="linkTx2(${id},${x.id})">Powiąż</button></td></tr>`).join('')}</table>`
      : '<p class="muted">Na innych kontach nie ma pasującej transakcji w ciągu 7 dni. Wczytaj wyciąg drugiego konta, np. Revolut.</p>'}
    <div class="actions"><button class="btn" onclick="closeModal()">Zamknij</button></div>`);
}
async function linkTx2(a, b) { try { await api(`transactions/${a}/link`, { body: { other: b } }); closeModal(); await render(); toast('Powiązano. Ten przelew nie liczy się już jako wydatek ani przychód.'); } catch (e) { toast(e.message); } }
async function unlinkTx(id) { await api(`transactions/${id}/unlink`, { method: 'POST' }); await render(); toast('Rozłączono.'); }
async function saveNote(id, note) { try { await api('transactions/' + id, { body: { note } }); toast(note.trim() ? 'Zapisano opis.' : 'Usunięto opis.', null, null, 1800); } catch (e) { toast(e.message); } }
async function delTx(id) { if (confirm('Usunąć ten ręczny wpis?')) { try { await api('transactions/' + id, { method: 'DELETE' }); render(); } catch (e) { toast(e.message); } } }
function manualDialog(kind = 'expense') {
  const today = new Date().toISOString().slice(0, 10), r = range(), day = today >= r.from && today <= r.to ? today : r.to;
  const manualAcc = S.accounts.filter(x => x.bank === 'Ręczne' && x.kind !== 'cash');
  modal(`<h2>Wpis ręczny</h2><p>Dla wydatków i przychodów, których nie ma w wyciągach: gotówka, bony, rozliczenia ze znajomymi. Wpis liczy się w budżecie tak jak transakcja z banku.</p>
    <form class="form" onsubmit="saveManual(event)">
      <div class="seg" role="group" style="justify-self:start"><button type="button" class="${kind === 'expense' ? 'on' : ''}" onclick="manualDialog('expense')">Wydatek</button><button type="button" class="${kind === 'income' ? 'on' : ''}" onclick="manualDialog('income')">Przychód</button></div>
      <input type="hidden" name="kind" value="${kind}">
      <span style="display:flex;gap:10px"><label style="flex:1">Kwota, zł<input type="text" name="a" inputmode="decimal" required autofocus style="text-align:right"></label><label style="flex:1">Dzień<input type="date" name="d" value="${day}" required></label></span>
      <label>Co to było<input type="text" name="t" placeholder="${kind === 'expense' ? 'np. Targ, warzywa' : 'np. Zwrot od Kasi'}" required></label>
      <span style="display:flex;gap:10px"><label style="flex:1">Kategoria<select name="c"><option value="">bez kategorii</option>${S.categories.filter(c => c.kind === kind).map(c => `<option value="${c.id}">${esc(c.name)}</option>`).join('')}</select></label>
        <label style="flex:1">Kto<select name="p">${personOptions(F.person)}</select></label></span>
      <label>Skąd / dokąd<select name="acc"><option value="">gotówka (portfel tej osoby)</option>${manualAcc.map(x => `<option value="${x.id}">${esc(accName(x))}</option>`).join('')}</select></label>
      <label>Opis (opcjonalnie)<input type="text" name="n"></label>
      <div class="actions"><button class="btn primary">Dodaj ${kind === 'expense' ? 'wydatek' : 'przychód'}</button><button type="button" class="btn" onclick="closeModal()">Anuluj</button></div></form>`);
}
async function saveManual(ev) {
  ev.preventDefault(); const f = ev.target, amt = Math.abs(toGr(f.a.value));
  try { await api('transactions', { body: { date: f.d.value, amount: f.kind.value === 'expense' ? -amt : amt, description: f.t.value, category_id: +f.c.value || null, person_id: +f.p.value, account_id: +f.acc.value || null, note: f.n.value } });
    closeModal(); F.mode === 'month' && (F.anchor = f.d.value.slice(0, 7)); await render(); toast('Dodano wpis.'); } catch (e) { toast(e.message); }
}
let TXROWS = {};
const catFits = t => { const c = S.categories.find(x => x.id === t.category_id); return !!c && (c.kind === 'transfer' || (c.kind === 'expense') === (t.amount < 0)); };
async function setCat(id, cat) {
  try { await api('transactions/' + id, { body: { category_id: +cat || null } }); } catch (e) { toast(e.message); return render(); }
  const t = TXROWS[id], phrase = t && t.phrases && t.phrases[0];
  if (cat && phrase) toast(`Zmieniono. Zawsze tak dla „${phrase}”?`, 'Utwórz regułę', () => ruleDialog(id, +cat));
  else toast('Zmieniono kategorię.');
}
function ruleDialog(txid, cat) {
  const t = TXROWS[txid] || { phrases: [], amount: -1 };
  modal(`<h2>Nowa reguła</h2><p>Każda transakcja, której opis albo odbiorca zawiera tę frazę, dostanie wybraną kategorię – także w przyszłych wyciągach. Reguła z kategorią wydatku działa tylko na wydatki, z kategorią przychodu tylko na wpływy. Ręcznie ustawione kategorie zostają.</p>
    ${t.processor ? `<div class="note warn" style="margin-bottom:12px"><span>Odbiorcą jest pośrednik płatności (${esc((t.counterparty || '').split(/\s+/).slice(0, 2).join(' '))}). Przez niego płaci się w wielu różnych sklepach, więc wybierz frazę z tytułu przelewu, np. nazwę sklepu.</span></div>` : ''}
    <form class="form" onsubmit="saveRule(event)"><label>Fraza<input type="text" name="p" value="${esc(t.phrases[0] || '')}" required minlength="3" oninput="rulePreview(this.form)"></label>
      ${t.phrases.length ? `<div class="small" style="display:flex;gap:6px;flex-wrap:wrap;align-items:center"><span class="muted">Podpowiedzi:</span>${t.phrases.map(p => `<button type="button" class="btn small" onclick="this.form.p.value=this.textContent;rulePreview(this.form)">${esc(p)}</button>`).join('')}</div>` : ''}
      <div class="muted small" title="${esc(t.description || '')}">Pełny opis: ${esc(((t.counterparty || '') + ' · ' + (t.description || '')).slice(0, 160))}</div>
      <label>Kategoria<select name="c" onchange="rulePreview(this.form)">${catOptions(cat, false, t.amount)}</select></label>
      <div id="rpv" class="small muted"></div>
      <div class="actions"><button class="btn primary">Zapisz regułę</button><button type="button" class="btn" onclick="closeModal()">Anuluj</button></div></form>`);
  rulePreview($('#modal form'));
}
let rpvTimer;
function rulePreview(f) {
  clearTimeout(rpvTimer);
  rpvTimer = setTimeout(async () => {
    const r = await api('rules/preview', { body: { pattern: f.p.value, category_id: +f.c.value } }), el = $('#rpv'); if (!el) return;
    el.innerHTML = (r.processor ? '<div style="color:var(--bad);margin-bottom:4px">To nazwa pośrednika płatności – reguła obejmie zakupy w różnych sklepach.</div>' : '') +
      (r.count ? `<b style="color:var(--ink)">Pasuje ${r.count} ${plural(r.count, 'transakcja', 'transakcje', 'transakcji')}</b>${r.manual ? `, z tego ${r.manual} z ręcznie ustawioną kategorią (zostaną bez zmian)` : ''}. Ostatnie:
        <table class="tight">${r.rows.map(x => `<tr><td class="num">${x.date}</td><td>${esc((x.counterparty || x.description || '')).slice(0, 46)}</td><td class="muted">${esc(x.category || 'bez kategorii')}</td><td class="r num">${zl(x.amount)}</td></tr>`).join('')}</table>`
      : (f.p.value.trim().length >= 3 ? '<span style="color:var(--warn)">Ta fraza nie pasuje do żadnej transakcji.</span>' : ''));
  }, 200);
}
async function saveRule(ev) {
  ev.preventDefault();
  try { const r = await api('rules', { body: { pattern: ev.target.p.value, category_id: +ev.target.c.value } }); closeModal(); await render(); toast(`Zapisano regułę. Zmieniono ${r.changed} ${plural(r.changed, 'transakcję', 'transakcje', 'transakcji')}.`); }
  catch (e) { toast(e.message); }
}

// ---------- import ----------
let importLog = [];
async function vImport(main) {
  main.innerHTML = topbar('Wczytaj wyciąg', false) + `<label class="drop" id="drop"><input type="file" accept=".csv,.txt,.sta,.mt940,.940,.xlsx,.pdf" multiple hidden onchange="importFiles(this.files)">
    <b>Przeciągnij tu wyciągi z banku: CSV, MT940 (.sta) albo Excel z Revolut</b>albo kliknij, żeby je wybrać. Możesz wczytać kilka naraz, także te same okresy ponownie albo w innym formacie – już wczytane transakcje są rozpoznawane i tylko uzupełniane.</label>
    <div class="results" id="results">${importLog.join('')}</div>
    <div class="grid2" style="margin-top:18px"><div class="panel"><h2>Jak pobrać plik z mBanku</h2><ol class="steps"><li>Zaloguj się w serwisie transakcyjnym i otwórz Historię.</li><li>Wybierz rachunek i okres.</li><li>Pobierz historię w formacie CSV.</li></ol></div>
    <div class="panel"><h2>Jak pobrać plik z ING</h2><ol class="steps"><li>Zaloguj się do Mojego ING i otwórz Historię.</li><li>Ustaw rachunek i zakres dat.</li><li>Pobierz listę transakcji jako CSV albo wyciąg w formacie MT940 (plik .sta). MT940 zawiera saldo po każdej operacji.</li></ol></div>
    <div class="panel"><h2>Jak pobrać plik z Revolut</h2><ol class="steps"><li>W aplikacji Revolut otwórz konto w złotych i wybierz Wyciąg.</li><li>Ustaw format Excel (albo CSV) i okres.</li><li>Wczytaj plik tutaj. Doładowania kartą z mBanku czy ING zostaną powiązane z wpływami na Revolut.</li></ol></div></div>
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
    (r.duplicates ? `, ${r.duplicates} już było` : '') + (r.updated ? ` (w ${r.updated} uzupełniono saldo)` : '') + (r.skipped ? `, ${r.skipped} nierozliczonych blokad pominięto` : '') +
    (r.transfers ? `, ${r.transfers} ${plural(r.transfers, 'przelew', 'przelewy', 'przelewów')} między Waszymi kontami` : '') + (r.receipts_matched ? `, dopasowano ${r.receipts_matched} paragonów` : '') + '.</div>');
  if (r.added) { F.anchor = r.to.slice(0, 7); }
}
function askOwners(name, r) {
  return new Promise(res => {
    const m = modal(`<h2>Czyje to konto?</h2><p>Plik ${esc(name)} (${esc(r.bank)}) zawiera konto, którego jeszcze nie znam. Zapamiętam wybór na przyszłość. Konta poza budżetem (oszczędnościowe, 800+, inwestycyjne) nie wchodzą do przychodów i wydatków.</p>
      <form class="form">${r.need_person.map((l, i) => `<label>${esc(l)}<span style="display:flex;gap:8px"><select name="a${i}">${S.people.map(p => `<option value="${p.id}">${esc(p.name)}</option>`).join('')}</select>
        <select name="k${i}">${Object.entries(S.kinds).filter(([k]) => k !== 'cash').map(([k, v]) => `<option value="${k}">${k === 'budget' ? 'konto w budżecie' : 'poza budżetem: ' + esc(v)}</option>`).join('')}</select></span></label>`).join('')}
      <div class="actions"><button class="btn primary">Wczytaj</button><button type="button" class="btn" id="cancel">Pomiń ten plik</button></div></form>`);
    $('form', m).onsubmit = e => { e.preventDefault(); const o = {}; r.need_person.forEach((l, i) => o[l] = { person: +e.target['a' + i].value, kind: e.target['k' + i].value }); closeModal(); res(o); };
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
    <b>Przeciągnij tu skany albo zdjęcia paragonów i faktur</b>JPG, PNG, HEIC lub PDF. Program odczyta pozycje i rabaty, a dokument połączy z płatnością z wyciągu.</label>
    <div class="results" id="rresults">${receiptLog.join('')}</div>
    ${savingsPanel(an.savings)}
    <div class="panel" style="margin-top:18px"><h2>Wczytane dokumenty<span>${list.length}</span>${list.some(r => !r.checked) ? `<button class="btn small" style="float:right" onclick="rereadAll()">Odczytaj ponownie niesprawdzone</button>` : ''}</h2>${list.length ? `<div class="rlist">` + list.map(r => {
      const diff = r.items_sum !== r.total;
      return `<button class="rcard" onclick="openReceipt(${r.id})"><b>${esc(r.store || 'Sklep nieodczytany')}</b>${r.kind === 'faktura' ? 'FAKTURA · ' : ''}${r.date || 'brak daty'} · ${r.n} poz.
        ${r.saved ? `<div style="display:flex;justify-content:space-between;margin-top:8px"><span>RABATY</span><span>-${num(r.saved)}</span></div>` : ''}
        <div class="sum" ${r.saved ? 'style="margin-top:2px"' : ''}><span>SUMA</span><span>${num(r.total)}</span></div>
        <div class="st">${r.transaction_id ? 'połączony z płatnością' : r.payment === 'cash' ? 'gotówka' : 'bez pary w wyciągu'}${diff && !r.checked ? ' · <span style="color:#b45309">do sprawdzenia</span>' : ''}</div></button>`; }).join('') + '</div>'
      : '<span class="muted">Nie ma jeszcze paragonów ani faktur.</span>'}</div>
    <div class="grid2"><div class="panel"><h2>Co kupujecie<span>${periodLabel()}, z paragonów</span></h2><div class="cats" style="grid-template-columns:minmax(120px,180px) 1fr auto">${an.categories.map(c => `<div class="name">${esc(c.name)}</div><div class="track"><div class="fill" style="width:${c.amount / maxC * 100}%"></div></div><div class="num" style="text-align:right">${zl(c.amount)}</div>`).join('') || '<span class="muted">Brak paragonów w tym okresie.</span>'}</div></div>
    <div class="panel"><h2>Produkty, na które idzie najwięcej</h2><table>${an.products.slice(0, 12).map(p => `<tr><td>${esc(p.name)}<div class="muted small">${esc(p.category || '')}</div></td><td class="muted small num">${p.n}×</td><td class="r num">${zl(p.amount)}</td></tr>`).join('') || '<tr><td class="muted">Brak danych.</td></tr>'}</table></div></div>`;
  dropzone($('#drop'), uploadReceipts);
}
function savingsPanel(sv) {
  if (!sv.receipts) return '';
  const reg = sv.paid + sv.total, pct = reg ? (sv.total / reg * 100) : 0;
  if (!sv.total) return `<div class="panel" style="margin-top:18px"><h2>Zaoszczędzone na promocjach<span>${periodLabel()}</span></h2><span class="muted">Na ${sv.receipts} ${plural(sv.receipts, 'dokumencie', 'dokumentach', 'dokumentach')} z tego okresu nie znalazłem żadnych rabatów. Jeśli na paragonie były, otwórz go i sprawdź odczytany tekst.</span></div>`;
  const max = Math.max(1, ...sv.stores.map(s => s.saved_sum));
  return `<div class="panel" style="margin-top:18px"><h2>Zaoszczędzone na promocjach<span>${periodLabel()}</span></h2>
    <div class="figs" style="margin-bottom:16px"><div class="fig"><div class="lab">Zaoszczędzono</div><div class="val num" style="color:var(--good)">${zl(sv.total)}</div><div class="sub">${pct.toFixed(1).replace('.', ',')}% cen bez rabatów</div></div>
      <div class="fig"><div class="lab">Zapłacono</div><div class="val num">${zl(sv.paid)}</div><div class="sub">bez rabatów byłoby ${zl(reg)}</div></div>
      <div class="fig"><div class="lab">Dokumenty z rabatem</div><div class="val num">${sv.with_discount} z ${sv.receipts}</div><div class="sub">paragony i faktury w tym okresie</div></div></div>
    <div class="grid2"><div><h2 style="font-size:14px">Gdzie</h2><div class="cats" style="grid-template-columns:minmax(100px,160px) 1fr auto">${sv.stores.map(s => `<div class="name">${esc(s.name || 'nieznany sklep')}</div><div class="track"><div class="fill" style="width:${s.saved_sum / max * 100}%"></div></div><div class="num" style="text-align:right">${zl(s.saved_sum)}</div>`).join('')}</div></div>
      <div><h2 style="font-size:14px">Na czym najwięcej</h2><table>${sv.products.map(p => `<tr><td>${esc(p.name)}</td><td class="muted small num">${p.n}×</td><td class="r num">${zl(p.saved)}</td></tr>`).join('') || '<tr><td class="muted">Rabaty nie były przypisane do konkretnych pozycji.</td></tr>'}</table></div></div></div>`;
}
async function rereadAll() {
  toast('Odczytuję dokumenty ponownie…', null, null, 60000);
  try { const r = await api('receipts/rereadall', { method: 'POST' }); await render(); toast(`Odczytano ponownie ${r.count}, połączono z wyciągiem ${r.matched}.`); } catch (e) { toast(e.message); }
}
async function reread() {
  if (!confirm('Odczytać ten dokument od nowa? Ręczne poprawki pozycji zostaną zastąpione.')) return;
  toast('Odczytuję…', null, null, 60000);
  try { await api(`receipts/${R.id}/reread`, { method: 'POST' }); await render(); toast('Odczytano ponownie.'); } catch (e) { toast(e.message); }
}
async function uploadReceipts(files) {
  for (const f of files) {
    $('#rresults').insertAdjacentHTML('afterbegin', `<div id="busy">Odczytuję ${esc(f.name)}…</div>`);
    try {
      const r = await api('receipts?' + qs({ person: F.person || S.people[0].id }), { method: 'POST', raw: f, headers: { 'X-Filename': encodeURIComponent(f.name) } });
      if (r.duplicate) { receiptLog.unshift(`<div><b>${esc(f.name)}</b> – ten plik był już wczytany (${esc(r.store || 'dokument')} z ${r.date || '?'}), pominięto.</div>`); continue; }
      receiptLog.unshift(`<div><b>${esc(f.name)}</b>: ${esc(r.store || 'sklep nieodczytany')}, ${r.items.length} pozycji, suma ${zl(r.total)}${(r.saved + r.items.reduce((a, i) => a + (i.discount || 0), 0)) ? ', rabaty ' + zl(r.saved + r.items.reduce((a, i) => a + (i.discount || 0), 0)) : ''}${r.transaction ? ', połączono z płatnością z ' + r.transaction.date : ''}. <a href="#" onclick="openReceipt(${r.id});return false">Sprawdź</a></div>`);
    } catch (e) { receiptLog.unshift(`<div class="err"><b>${esc(f.name)}</b> – ${esc(e.message)}</div>`); }
  }
  render();
}
function openReceipt(id) { view = 'paragony'; receiptId = id; location.hash = 'paragony'; render(); }
let R = null;
async function vReceipt(main) {
  R = await api('receipts/' + receiptId);
  main.innerHTML = `<div class="bar"><button class="btn" onclick="receiptId=null;render()">‹ Wszystkie paragony</button><h1 style="margin-left:6px">${R.kind === 'faktura' ? 'Faktura' : 'Paragon'}</h1><button class="btn" onclick="reread()">Odczytaj ponownie</button></div>
    <div class="rdetail"><div>${/\.pdf$/i.test(R.preview || '') ? `<a href="/paragon/${esc(R.preview)}" target="_blank">Otwórz plik PDF</a>` : `<a href="/paragon/${esc(R.preview)}" target="_blank"><img src="/paragon/${esc(R.preview)}" alt="Skan dokumentu"></a>`}
      ${R.ocr_text ? `<details class="tbl"><summary>Odczytany tekst</summary><pre style="white-space:pre-wrap;font:12px var(--mono)">${esc(R.ocr_text)}</pre></details>` : '<p class="muted small" style="margin-top:8px">Nie udało się odczytać tekstu – wpisz pozycje ręcznie.</p>'}</div>
    <div><div class="paper" id="paper"></div>
      <div class="panel" style="margin-top:18px"><h2>Płatność w wyciągu</h2><div id="link"></div></div></div></div>`;
  drawPaper(); drawLink();
}
function drawPaper() {
  const sum = R.items.reduce((a, i) => a + i.amount, 0), diff = sum - R.total;
  const disc = R.items.reduce((a, i) => a + (i.discount || 0), 0), saved = disc + (R.saved || 0);
  $('#paper').innerHTML = `<div class="hd"><div><label>Sklep</label><input value="${esc(R.store || '')}" onchange="R.store=this.value"></div>
    <div><label>Data</label><input type="date" value="${R.date || ''}" onchange="R.date=this.value"></div>
    <div><label>Suma</label><input value="${num(R.total)}" inputmode="decimal" onchange="R.total=toGr(this.value);drawPaper()"></div>
    <div><label>Kto płacił</label><select onchange="R.person_id=+this.value">${S.people.map(p => `<option value="${p.id}" ${p.id === R.person_id ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}</select></div></div>
    <table><tr><th>Pozycja</th><th style="width:54px">Ilość</th><th style="width:76px" class="r">Przed rabatem</th><th style="width:62px" class="r">Rabat</th><th style="width:76px" class="r">Zapłacono</th><th style="width:150px">Kategoria</th><th style="width:26px"></th></tr>` +
    R.items.map((it, i) => `<tr><td><input value="${esc(it.name)}" onchange="R.items[${i}].name=this.value"></td>
      <td><input value="${String(it.qty).replace('.', ',')}" inputmode="decimal" onchange="R.items[${i}].qty=parseFloat(this.value.replace(',','.'))||1"></td>
      <td><input style="text-align:right" value="${num(it.amount + (it.discount || 0))}" inputmode="decimal" aria-label="Kwota przed rabatem" onchange="R.items[${i}].amount=toGr(this.value)-(R.items[${i}].discount||0);drawPaper()"></td>
      <td><input style="text-align:right${diff && it.discount > 0.4 * (it.amount + it.discount) ? ';color:#b45309;font-weight:700' : ''}" title="${diff && it.discount > 0.4 * (it.amount + it.discount) ? 'Nietypowo duży rabat – sprawdź na paragonie' : ''}" value="${it.discount ? num(it.discount) : ''}" placeholder="–" inputmode="decimal" aria-label="Rabat" onchange="{const it=R.items[${i}], before=it.amount+(it.discount||0); it.discount=Math.abs(toGr(this.value)); it.amount=before-it.discount;}drawPaper()"></td>
      <td><input style="text-align:right" value="${num(it.amount)}" inputmode="decimal" aria-label="Zapłacono" onchange="R.items[${i}].amount=toGr(this.value);drawPaper()"></td>
      <td><select onchange="R.items[${i}].category_id=+this.value||null">${catOptions(it.category_id, true, -1)}</select></td>
      <td><button class="x" aria-label="Usuń pozycję" onclick="R.items.splice(${i},1);drawPaper()">×</button></td></tr>`).join('') + `</table>
    <div class="actions" style="margin-top:8px"><button class="btn small" onclick="R.items.push({name:'',qty:1,amount:0,discount:0,unit_price:0,category_id:null});drawPaper()">Dodaj pozycję</button></div>
    <div style="display:grid;grid-template-columns:1fr 110px;gap:10px;align-items:end;margin-top:12px"><label>Rabaty na cały dokument (kupony, rabat od sumy), nieprzypisane do pozycji</label><input style="text-align:right" value="${R.saved ? num(R.saved) : ''}" placeholder="0,00" inputmode="decimal" onchange="R.saved=Math.abs(toGr(this.value));drawPaper()"></div>
    ${disc ? `<div style="display:flex;justify-content:space-between;margin-top:12px;padding-top:8px;border-top:1px dashed #b9b5a6"><span>PRZED RABATAMI</span><span>${num(sum + disc)}</span></div>
    <div style="display:flex;justify-content:space-between;margin-top:2px"><span>RABATY NA POZYCJACH</span><span>−${num(disc)}</span></div>` : ''}
    <div class="tot"><span>SUMA POZYCJI</span><span>${num(sum)}</span></div>
    ${saved ? `<div style="display:flex;justify-content:space-between;margin-top:4px"><span>ZAOSZCZĘDZONO RAZEM</span><span>${num(saved)}</span></div>` : ''}
    <div class="chk">${diff === 0 ? '✓ Pozycje zgadzają się z sumą dokumentu.' : `<span style="color:#b45309">Pozycje ${diff > 0 ? 'przekraczają sumę' : 'są mniejsze od sumy'} o ${num(Math.abs(diff))} zł – sprawdź kwoty, ilości i rabaty${R.items.some(it => it.discount > 0.4 * (it.amount + it.discount)) ? ' (podejrzanie duże rabaty są wyróżnione)' : ''}.</span>`}</div>
    <div class="actions"><button class="btn primary" onclick="saveReceipt()">Zapisz</button>
      <select style="width:auto" onchange="R.kind=this.value"><option value="paragon" ${R.kind !== 'faktura' ? 'selected' : ''}>paragon</option><option value="faktura" ${R.kind === 'faktura' ? 'selected' : ''}>faktura</option></select>
      <select style="width:auto" onchange="R.payment=this.value||null"><option value="card" ${R.payment !== 'cash' ? 'selected' : ''}>płatność kartą</option><option value="cash" ${R.payment === 'cash' ? 'selected' : ''}>gotówka</option></select>
      <button class="btn danger" style="margin-left:auto" onclick="delReceipt()">Usuń</button></div>`;
}
async function drawLink() {
  const el = $('#link');
  if (R.transaction) { const t = R.transaction;
    el.innerHTML = `<p>${t.date} · ${esc(t.counterparty || t.description)} · <b class="num">${zl(t.amount)}</b> · ${esc(pname(t.person_id))}</p><p class="muted small" style="margin:6px 0 10px">W zestawieniach ta płatność jest rozbita na pozycje paragonu.</p><button class="btn small" onclick="linkTx(null)">Rozłącz</button>`;
    return; }
  if (R.payment === 'cash') { el.innerHTML = `<p class="muted">Dokument oznaczony jako płatność gotówką. Jego pozycje widać w zestawieniu zakupów, a w budżecie gotówka liczy się w chwili wypłaty z bankomatu.</p>`; return; }
  const c = await api(`receipts/${R.id}/candidates`);
  if (!R.date || !R.total) { el.innerHTML = `<p style="color:var(--warn)">Brakuje ${!R.date ? 'daty' : 'sumy'} dokumentu, więc nie mam czego szukać w wyciągu. Uzupełnij ${!R.date ? 'datę' : 'sumę'} u góry i zapisz.</p>`; return; }
  const day = t => Math.round((new Date(t.date) - new Date(R.date)) / 864e5);
  el.innerHTML = `<p class="small" style="margin-bottom:8px">Szukam płatności na dokładnie <b class="num">${zl(R.total)}</b> w dniach od 2 przed do ${R.kind === 'faktura' ? 35 : 7} po ${R.date}. Takiej nie ma wśród wczytanych transakcji${S.last && S.last < R.date ? ` – wyciągi kończą się na ${S.last}, wczytaj nowszy` : ''}. Najbliższe:</p>` +
    (c.length ? `<table>${c.map(t => { const dz = -t.amount - R.total, dd = day(t);
      return `<tr><td class="num small">${t.date}<div class="muted">${dd === 0 ? 'ten sam dzień' : `${Math.abs(dd)} ${plural(Math.abs(dd), 'dzień', 'dni', 'dni')} ${dd > 0 ? 'po' : 'przed'}`}</div></td><td class="small">${esc(t.counterparty || t.description).slice(0, 48)}<div class="muted">${esc(pname(t.person_id))}</div></td>
        <td class="r num">${zl(t.amount)}<div class="small" style="color:${dz ? 'var(--warn)' : 'var(--good)'}">${dz ? 'różnica ' + zl(Math.abs(dz)) : 'kwota zgodna'}</div></td><td class="r"><button class="btn small" onclick="linkTx(${t.id})">To ta</button></td></tr>`; }).join('')}</table>` : '<span class="muted small">Brak wolnych płatności w pobliżu tej daty.</span>');
}
async function linkTx(id) { await api('receipts/' + R.id, { body: { transaction_id: id } }); render(); }
async function saveReceipt() {
  try { await api('receipts/' + R.id, { body: { store: R.store, date: R.date, total: R.total, saved: R.saved || 0, kind: R.kind || 'paragon', payment: R.payment || 'card', person_id: R.person_id, items: R.items, checked: 1, rematch: !R.transaction } });
    await render(); toast(R.transaction ? 'Zapisano.' : 'Zapisano. Sprawdziłem ponownie wyciąg.'); } catch (e) { toast(e.message); }
}
async function delReceipt() { if (confirm('Usunąć ten paragon razem ze skanem?')) { await api('receipts/' + R.id, { method: 'DELETE' }); receiptId = null; render(); } }

// ---------- ustawienia ----------
async function vSettings(main) {
  const kinds = { expense: 'wydatek', income: 'przychód', transfer: 'poza budżetem' };
  main.innerHTML = topbar('Ustawienia', false) + `<div class="grid2"><div class="panel"><h2>Osoby</h2><p class="muted small" style="margin:-6px 0 10px">Imię i nazwisko tak, jak widnieje na przelewach. Dzięki temu przelewy do siebie i między Wami nie liczą się jako przychód ani wydatek. Kilka wersji oddziel średnikiem.</p><table>${S.people.map(p => `<tr><td><i class="dot" style="background:${pcolor(p.id)}"></i></td><td><input type="text" value="${esc(p.name)}" onchange="savePerson(${p.id},this.value)"></td><td><input type="text" value="${esc(p.fullname || '')}" placeholder="np. Jan Kowalski" aria-label="Imię i nazwisko w banku" onchange="saveFullname(${p.id},'${esc(p.name).replace(/'/g, '')}',this.value)"></td></tr>`).join('')}</table>
      <form class="actions" onsubmit="event.preventDefault();savePerson(null,this.n.value)"><input type="text" name="n" placeholder="np. Wspólne" required><button class="btn">Dodaj osobę</button></form></div>
    <div class="panel"><h2>Konta</h2><p class="muted" style="margin-bottom:12px">Właściciela i rodzaj konta (w budżecie albo poza nim) ustawisz w zakładce Konta. Tam też dodasz konta bez wyciągów, np. inwestycyjne.</p><button class="btn" onclick="go('konta')">Otwórz Konta</button></div></div>
    <div class="panel" style="margin-top:18px"><h2>Kategorie<span>kolejność tutaj to kolejność na listach wyboru · limit 0 oznacza brak limitu</span></h2>
      ${[['expense', 'Wydatki'], ['income', 'Przychody'], ['transfer', 'Poza budżetem']].map(([k, lab]) => { const list = S.categories.filter(c => c.kind === k);
        return `<h2 style="font-size:14px;margin:16px 0 6px">${lab}<span>${list.length}</span><button class="btn small" style="float:right" onclick="sortCats('${k}')">Sortuj A–Z</button></h2>
        <table class="tight"><tr><th style="width:74px">Kolejność</th><th>Nazwa</th><th>Rodzaj</th><th class="r">${k === 'expense' ? 'Limit na miesiąc (zł)' : ''}</th><th></th></tr>${list.map((c, i) => `<tr>
          <td style="white-space:nowrap"><button class="icon" aria-label="W górę" ${i ? '' : 'disabled style="opacity:.3"'} onclick="moveCat(${c.id},-1)">▲</button><button class="icon" aria-label="W dół" ${i < list.length - 1 ? '' : 'disabled style="opacity:.3"'} onclick="moveCat(${c.id},1)">▼</button></td>
          <td><input type="text" value="${esc(c.name)}" onchange="saveCat(${c.id},{name:this.value})"></td>
          <td><select onchange="saveCat(${c.id},{kind:this.value}).then(render)">${Object.entries(kinds).map(([kk, l]) => `<option value="${kk}" ${c.kind === kk ? 'selected' : ''}>${l}</option>`).join('')}</select></td>
          <td class="r">${c.kind === 'expense' ? `<input type="number" min="0" step="50" style="width:110px;text-align:right" value="${c.budget / 100}" onchange="saveCat(${c.id},{budget:Math.round(this.value*100)})">` : ''}</td>
          <td class="r"><button class="btn small danger" onclick="delCat(${c.id},'${esc(c.name).replace(/'/g, '')}')">Usuń</button></td></tr>`).join('')}</table>`; }).join('')}
      <form class="actions" onsubmit="event.preventDefault();addCat(this)"><input type="text" name="n" placeholder="Nowa kategoria" required><select name="k">${Object.entries(kinds).map(([k, l]) => `<option value="${k}">${l}</option>`).join('')}</select><button class="btn">Dodaj kategorię</button></form></div>
    <div class="panel"><h2>Twoje reguły<span>fraza w opisie transakcji → kategoria</span></h2>${S.rules.length ? `<table>${S.rules.map(r => `<tr><td><code>${esc(r.pattern)}</code>${r.sign ? `<div class="muted small">tylko ${r.sign < 0 ? 'wydatki' : 'wpływy'}</div>` : ''}</td><td>${esc(r.category)}</td><td class="r"><button class="btn small danger" onclick="delRule(${r.id})">Usuń</button></td></tr>`).join('')}</table>` : '<span class="muted">Reguły powstają, gdy zmienisz kategorię transakcji i wybierzesz „Utwórz regułę”. Program ma też wbudowane reguły dla popularnych sklepów i usług.</span>'}</div>
    <div class="panel"><h2>Dane i program</h2><p class="small">Wszystko jest zapisane w folderze <code>${esc(S.data_dir)}</code>. Skopiuj ten folder, żeby zrobić kopię zapasową.</p>
      <div class="actions"><button class="btn" onclick="quit()">Zamknij program</button></div></div>`;
}
async function saveFullname(id, name, fullname) { try { await api('people/' + id, { body: { name, fullname } }); await render(); toast('Zapisano. Przelewy do siebie i między Wami rozpoznałem od nowa.'); } catch (e) { toast(e.message); } }
async function savePerson(id, name) { try { await api('people' + (id ? '/' + id : ''), { body: { name } }); render(); } catch (e) { toast(e.message); } }
async function saveCat(id, b) { try { await api('categories/' + id, { body: b }); await load(); toast('Zapisano.'); } catch (e) { toast(e.message); } }
async function saveOrder(ids) { await api('categories/order', { body: { ids } }); await render(); }
function moveCat(id, dir) {
  const c = S.categories.find(x => x.id === id), list = S.categories.filter(x => x.kind === c.kind).map(x => x.id), i = list.indexOf(id), j = i + dir;
  if (j < 0 || j >= list.length) return;
  [list[i], list[j]] = [list[j], list[i]];
  const order = { expense: 0, income: 1, transfer: 2 };
  saveOrder([...[0, 1, 2].flatMap(o => o === order[c.kind] ? list : S.categories.filter(x => order[x.kind] === o).map(x => x.id))]);
}
function sortCats(kind) {
  const order = { expense: 0, income: 1, transfer: 2 };
  saveOrder([0, 1, 2].flatMap(o => { const l = S.categories.filter(x => order[x.kind] === o); return o === order[kind] ? [...l].sort((x, y) => x.name.localeCompare(y.name, 'pl')).map(x => x.id) : l.map(x => x.id); }));
}
async function addCat(f) { try { await api('categories', { body: { name: f.n.value, kind: f.k.value } }); render(); } catch (e) { toast(e.message); } }
async function delCat(id, name) { if (confirm(`Usunąć kategorię „${name}”? Jej transakcje zostaną bez kategorii.`)) { await api('categories/' + id, { method: 'DELETE' }); render(); } }
async function delRule(id) { await api('rules/' + id, { method: 'DELETE' }); render(); }
async function quit() { await api('quit', { method: 'POST' }); $('#app').innerHTML = '<div class="welcome"><h1>Program zamknięty</h1><p>Możesz zamknąć tę kartę. Żeby wrócić, otwórz Budżet domowy z folderu Programy.</p></div>'; }

// ---------- produkty i ceny ----------
const PR = { q: '', sort: 'paid', open: null };
const unitPrice = g => num(g) + ' zł';
function changeCell(p) {
  if (p.change === null) return '<span class="muted small">jeden zakup</span>';
  if (p.change === 0) return '<span class="muted">bez zmian</span>';
  const up = p.change > 0;
  return `<span style="color:var(--${up ? 'bad' : 'good'})">${up ? '▲' : '▼'} ${num(Math.abs(p.change))} zł</span> <span class="muted small">${up ? '+' : '−'}${String(Math.abs(p.pct)).replace('.', ',')}%</span>`;
}
async function vProducts(main) {
  if (PR.open) return vProduct(main);
  const d = await api('products?' + qs({ ...range(), person: F.person }));
  const sorts = { paid: (x, y) => y.paid - x.paid, up: (x, y) => (y.pct ?? -1e9) - (x.pct ?? -1e9), down: (x, y) => (x.pct ?? 1e9) - (y.pct ?? 1e9), n: (x, y) => y.n - x.n, name: (x, y) => x.name.localeCompare(y.name, 'pl') };
  const words = PR.q.toLowerCase().split(/\s+/).filter(Boolean);
  const list = d.products.filter(p => words.every(w => p.name.toLowerCase().includes(w))).sort(sorts[PR.sort]);
  let h = topbar('Produkty');
  if (!d.products.length) { main.innerHTML = h + `<div class="panel empty"><b>Brak produktów w tym okresie</b>Zestawienie powstaje z pozycji paragonów i faktur. Wczytaj dokumenty albo wybierz inny okres.<div class="actions" style="justify-content:center"><button class="btn primary" onclick="go('paragony')">Wczytaj paragony</button></div></div>`; return; }
  h += d.compared ? `<div class="figs"><div class="fig"><div class="lab">Te same produkty kosztują</div><div class="val num" style="color:var(--${d.basket > 0 ? 'bad' : d.basket < 0 ? 'good' : 'ink'})">${d.basket > 0 ? '+' : d.basket < 0 ? '−' : ''}${String(Math.abs(d.basket)).replace('.', ',')}%</div><div class="sub">ostatni zakup w okresie wobec pierwszego, ceny bez rabatów</div></div>
    <div class="fig"><div class="lab">Zmiany cen</div><div class="val num">${d.up} ▲ ${d.down} ▼</div><div class="sub">podrożało ${d.up}, potaniało ${d.down}, bez zmian ${d.same}</div></div>
    <div class="fig"><div class="lab">Produkty w okresie</div><div class="val num">${d.products.length}</div><div class="sub">${d.compared} kupionych co najmniej dwa razy</div></div></div>`
    : `<div class="note"><span>W tym okresie każdy produkt był kupiony tylko raz, więc nie ma jeszcze czego porównywać. Zmiany cen pojawią się, gdy ten sam produkt trafi na paragony z różnych dni – wybierz dłuższy okres albo wczytaj więcej paragonów.</span></div>`;
  if (d.skipped) h += `<div class="note warn"><span>${d.skipped} ${plural(d.skipped, 'dokument czeka', 'dokumenty czekają', 'dokumentów czeka')} na sprawdzenie (pozycje nie zgadzają się z sumą), więc nie ${plural(d.skipped, 'jest liczony', 'są liczone', 'jest liczonych')} w cenach. Popraw i zapisz, a ${plural(d.skipped, 'trafi', 'trafią', 'trafi')} do zestawienia.</span><button class="btn small" onclick="go('paragony')">Pokaż paragony</button></div>`;
  h += `<div class="filters"><input type="search" placeholder="Szukaj produktu" value="${esc(PR.q)}" onchange="PR.q=this.value;render()" style="width:240px">
    <select onchange="PR.sort=this.value;render()">${[['paid', 'najwięcej wydane'], ['up', 'najbardziej podrożały'], ['down', 'najbardziej potaniały'], ['n', 'najczęściej kupowane'], ['name', 'alfabetycznie']].map(([k, l]) => `<option value="${k}" ${PR.sort === k ? 'selected' : ''}>${l}</option>`).join('')}</select>
    <span class="muted small">${list.length} ${plural(list.length, 'produkt', 'produkty', 'produktów')} · ceny za sztukę lub kilogram, przed rabatem</span></div>
    <div class="panel" style="padding:6px 8px"><table><tr><th>Produkt</th><th class="r">Kupiono</th><th class="r">Wydano</th><th class="r">Pierwsza cena</th><th class="r">Ostatnia cena</th><th class="r">Zmiana</th><th class="r">Śr. zapłacono</th></tr>` +
    list.map(p => `<tr style="cursor:pointer" onclick="PR.open=decodeURIComponent('${encodeURIComponent(p.key)}');render()"><td><b style="font-weight:600">${esc(p.name)}</b><div class="muted small">${esc(p.category || 'bez kategorii')}${p.stores.filter(Boolean).length ? ' · ' + esc(p.stores.filter(Boolean).join(', ')) : ''}</div></td>
      <td class="r num">${p.n}×<div class="muted small">${String(p.qty).replace('.', ',')} szt./kg</div></td><td class="r num">${zl(p.paid)}${p.saved ? `<div class="small" style="color:var(--good)">rabaty ${zl(p.saved)}</div>` : ''}</td>
      <td class="r num">${unitPrice(p.first)}<div class="muted small">${p.first_date}</div></td><td class="r num">${unitPrice(p.last)}<div class="muted small">${p.last_date}</div></td>
      <td class="r num">${changeCell(p)}</td><td class="r num">${unitPrice(p.avg_paid)}</td></tr>`).join('') + `</table></div>
    <p class="muted small">Produkty są łączone po nazwie z paragonu (drobne różnice w odczycie nie przeszkadzają). Jeśli ten sam produkt ma w różnych sklepach inne nazwy, ujednolić je można w widoku paragonu.</p>`;
  main.innerHTML = h;
}
async function vProduct(main) {
  const all = await api('product?' + qs({ name: PR.open, person: F.person }));
  const r = range(), inP = all.filter(d => d.date >= r.from && d.date <= r.to);
  if (!all.length) { PR.open = null; return vProducts(main); }
  const use = F.mode === 'all' || inP.length < 2 ? all : inP;
  const first = use[0], last = use[use.length - 1], ch = last.price - first.price;
  const prices = use.map(d => d.price), qty = use.reduce((a, d) => a + d.qty, 0), paid = use.reduce((a, d) => a + d.amount, 0);
  main.innerHTML = `<div class="bar"><button class="btn" onclick="PR.open=null;render()">‹ Wszystkie produkty</button><h1 style="margin-left:6px">${esc(last.name)}</h1></div>
    <div class="figs"><div class="fig"><div class="lab">Cena ostatnio</div><div class="val num">${unitPrice(last.price)}</div><div class="sub">${last.date}${last.store ? ', ' + esc(last.store) : ''}</div></div>
      <div class="fig"><div class="lab">Zmiana od ${first.date}</div><div class="val num" style="color:var(--${ch > 0 ? 'bad' : ch < 0 ? 'good' : 'ink'})">${use.length < 2 ? '–' : ch === 0 ? 'bez zmian' : (ch > 0 ? '▲ ' : '▼ ') + unitPrice(Math.abs(ch))}</div><div class="sub">${use.length < 2 ? 'potrzeba co najmniej dwóch zakupów' : `z ${unitPrice(first.price)}${first.price ? `, ${ch >= 0 ? '+' : '−'}${(Math.abs(ch) / first.price * 100).toFixed(1).replace('.', ',')}%` : ''}`}</div></div>
      <div class="fig"><div class="lab">Najtaniej i najdrożej</div><div class="val num">${num(Math.min(...prices))} – ${num(Math.max(...prices))}</div><div class="sub">kupiono ${use.length}×, razem ${zl(paid)}</div></div></div>
    <div class="panel"><h2>Cena za sztukę lub kilogram<span>${use === all ? 'wszystkie zakupy' : periodLabel()}</span></h2>${priceChart(use)}</div>
    <div class="panel" style="padding:6px 8px"><table><tr><th>Data</th><th>Sklep</th><th class="r">Ilość</th><th class="r">Cena</th><th class="r">Rabat</th><th class="r">Zapłacono za szt./kg</th><th></th></tr>` +
    all.slice().reverse().map(d => `<tr ${use.includes(d) ? '' : 'style="opacity:.55"'}><td class="num small">${d.date}</td><td>${esc(d.store || '—')}</td><td class="r num">${String(d.qty).replace('.', ',')}</td><td class="r num">${unitPrice(d.price)}</td>
      <td class="r num">${d.discount ? `<span style="color:var(--good)">−${num(d.discount)} zł</span>` : '<span class="muted">–</span>'}</td><td class="r num">${unitPrice(d.paid)}</td><td class="r"><button class="btn small" onclick="openReceipt(${d.receipt_id})">Paragon</button></td></tr>`).join('') + '</table></div>';
}
function priceChart(rows) {
  if (rows.length < 2) return '<span class="muted">Wykres pojawi się po drugim zakupie tego produktu.</span>';
  const W = 760, H = 240, L = 54, Rm = 16, B = 28, T = 12;
  const t = d => new Date(d.date).getTime(), t0 = t(rows[0]), t1 = Math.max(t(rows[rows.length - 1]), t0 + 864e5);
  const vals = rows.flatMap(d => [d.price, d.paid]); let lo = Math.min(...vals), hi = Math.max(...vals);
  const pad = Math.max((hi - lo) * 0.2, hi * 0.05, 10); lo = Math.max(0, lo - pad); hi += pad;
  const x = d => L + (W - L - Rm) * (t(d) - t0) / (t1 - t0), y = v => T + (H - T - B) * (1 - (v - lo) / (hi - lo));
  let g = '';
  for (let i = 0; i <= 3; i++) { const v = lo + (hi - lo) * i / 3; g += `<line x1="${L}" x2="${W - Rm}" y1="${y(v)}" y2="${y(v)}" stroke="var(--line2)"/><text x="${L - 8}" y="${y(v) + 4}" text-anchor="end">${num(Math.round(v))}</text>`; }
  g += `<text x="${L}" y="${H - 8}">${rows[0].date}</text><text x="${W - Rm}" y="${H - 8}" text-anchor="end">${rows[rows.length - 1].date}</text>`;
  g += `<polyline fill="none" stroke="var(--seq)" stroke-width="2" stroke-linejoin="round" points="${rows.map(d => `${x(d)},${y(d.price)}`).join(' ')}"/>`;
  rows.forEach(d => {
    const tipHtml = `<b>${d.date}${d.store ? ' · ' + esc(d.store) : ''}</b><i><span>Cena</span><span>${unitPrice(d.price)}</span></i>` + (d.discount ? `<i><span>Po rabacie</span><span>${unitPrice(d.paid)}</span></i>` : '') + `<i><span>Ilość</span><span>${String(d.qty).replace('.', ',')}</span></i>`;
    if (d.paid < d.price) g += `<line x1="${x(d)}" x2="${x(d)}" y1="${y(d.price)}" y2="${y(d.paid)}" stroke="var(--seq)" stroke-dasharray="2 3"/><circle cx="${x(d)}" cy="${y(d.paid)}" r="4" fill="var(--surface)" stroke="var(--seq)" stroke-width="2"/>`;
    g += `<circle cx="${x(d)}" cy="${y(d.price)}" r="5" fill="var(--seq)" stroke="var(--surface)" stroke-width="2"/>
      <rect x="${x(d) - 14}" y="${T}" width="28" height="${H - T - B}" fill="transparent" data-tip="${esc(tipHtml)}" onmousemove="tip(event,this.dataset.tip)" onmouseleave="tip()"/>`;
  });
  return `<div class="legend"><span><svg width="14" height="12"><circle cx="7" cy="6" r="5" fill="var(--seq)"/></svg>cena na paragonie</span><span><svg width="14" height="12"><circle cx="7" cy="6" r="4" fill="none" stroke="var(--seq)" stroke-width="2"/></svg>cena po rabacie</span><span class="muted">w złotych</span></div>
    <svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="Historia ceny produktu">${g}</svg>`;
}

// ---------- konta ----------
const kindOptions = sel => Object.entries(S.kinds).filter(([k]) => k !== 'cash' || sel === 'cash').map(([k, v]) => `<option value="${k}" ${k === sel ? 'selected' : ''}>${esc(v)}</option>`).join('');
const personOptions = sel => S.people.map(p => `<option value="${p.id}" ${p.id === sel ? 'selected' : ''}>${esc(p.name)}</option>`).join('');
let ACC = [];
async function vAccounts(main) {
  const r = range();
  ACC = (await api('accounts?' + qs(r))).filter(x => !F.person || x.person_id === F.person);
  const side = ACC.filter(x => !['budget', 'cash'].includes(x.kind)), inb = ACC.filter(x => x.kind === 'budget'), cash = ACC.filter(x => x.kind === 'cash');
  const gcat = S.categories.find(c => c.name === 'Gotówka');
  const known = side.filter(x => x.balance !== null && x.balance_source !== 'flows');
  const total = known.reduce((s, x) => s + x.balance, 0), inflow = side.reduce((s, x) => s + x.inflow, 0), outflow = side.reduce((s, x) => s + x.outflow, 0);
  const stan = x => x.balance === null ? '<span class="muted">brak danych</span>'
    : x.balance_source === 'flows' ? `<span class="muted">${zl(x.balance)}</span><div class="small" style="color:var(--warn)">suma operacji, wpisz stan</div>`
    : `<b>${zl(x.balance)}</b><div class="muted small">${x.balance_source === 'statement' ? 'saldo z wyciągu' : 'stan wpisany'} ${x.balance_date}</div>`;
  let h = topbar('Konta');
  h += `<div class="figs"><div class="fig"><div class="lab">Poza budżetem razem</div><div class="val num">${zl(total)}</div><div class="sub">${known.length} z ${side.length} ${plural(side.length, 'konta', 'kont', 'kont')} ze znanym stanem, według najnowszych danych</div></div>
    <div class="fig"><div class="lab">Wpłynęło na te konta</div><div class="val num" style="color:var(--good)">${zl(inflow)}</div><div class="sub">${periodLabel()}, według wyciągów</div></div>
    <div class="fig"><div class="lab">Wypłynęło z tych kont</div><div class="val num">${zl(outflow)}</div><div class="sub">${periodLabel()}, według wyciągów</div></div></div>`;
  h += `<div class="panel"><h2>Poza budżetem<span>nie liczą się do przychodów i wydatków</span></h2>${side.length ? `<table class="tight"><tr><th>Konto</th><th>Rodzaj</th><th>Czyje</th><th class="r">Wpłaty</th><th class="r">Wypłaty</th><th class="r">Stan</th><th></th></tr>` +
    side.map(x => `<tr><td><b style="font-weight:600">${esc(x.name)}</b><div class="muted small">${x.manual ? 'dodane ręcznie' : `${x.n} ${plural(x.n, 'transakcja', 'transakcje', 'transakcji')} z wyciągów`}</div></td>
      <td><select onchange="saveAcc(${x.id},{kind:this.value})">${kindOptions(x.kind)}</select></td><td><select onchange="saveAcc(${x.id},{person_id:+this.value})">${personOptions(x.person_id)}</select></td>
      <td class="r num">${x.n ? zl(x.inflow) : '<span class="muted">–</span>'}</td><td class="r num">${x.n ? zl(x.outflow) : '<span class="muted">–</span>'}</td><td class="r num">${stan(x)}</td>
      <td class="r" style="white-space:nowrap"><button class="btn small" onclick="balanceDialog(${x.id})">Wpisz stan</button> ${x.n ? `<button class="btn small" onclick="go('transakcje',{account:'${x.id}',category:'',q:''})">Transakcje</button>` : `<button class="btn small danger" onclick="delAcc(${x.id})">Usuń</button>`}</td></tr>`).join('') + '</table>'
    : '<span class="muted">Nie ma jeszcze kont poza budżetem. Dodaj konto ręcznie poniżej albo wczytaj jego wyciąg i przy pytaniu o konto wybierz „poza budżetem”. Istniejące konto przeniesiesz tu, zmieniając jego rodzaj w tabeli niżej.</span>'}</div>`;
  h += `<div class="note"><span>Wczytujesz wyciągi tylko od pewnego dnia? Wpisz, ile było na kontach dzień wcześniej, np. 31 grudnia. Program policzy z tego stan każdego konta i pokaże w Przeglądzie, z czym zaczynaliście okres.</span><button class="btn primary small" onclick="openingDialog()">Salda otwarcia</button></div>`;
  h += `<div class="panel"><h2>Dodaj konto bez wyciągu<span>np. rachunek inwestycyjny, lokata, konto w innym banku</span></h2>
    <form class="filters" style="margin:0" onsubmit="event.preventDefault();addAcc(this)"><input type="text" name="n" placeholder="Nazwa, np. XTB" required style="width:200px">
      <select name="k">${kindOptions('invest').replace(/<option value="(budget|cash)"[^>]*>[^<]*<\/option>/g, '')}</select><select name="p">${personOptions(F.person)}</select>
      <input type="text" name="a" placeholder="Stan dziś, zł" inputmode="decimal" style="width:130px;text-align:right"><button class="btn primary">Dodaj konto</button></form>
    <p class="muted small" style="margin-top:10px">Stan takiego konta wpisujesz sam, kiedy chcesz go odnotować. Przelewy na nie z kont budżetu trafiają do kategorii „Oszczędności i inwestycje” i nie są wydatkiem.</p></div>`;
  const noWallet = S.people.filter(p => (!F.person || p.id === F.person) && !cash.some(x => x.person_id === p.id));
  h += `<div class="panel"><h2>Gotówka<span>portfele liczą się w budżecie</span></h2>${cash.length ? `<table class="tight"><tr><th>Portfel</th><th class="r">Wpłynęło</th><th class="r">Wydano</th><th class="r">Stan</th><th></th></tr>` +
    cash.map(x => `<tr><td><b style="font-weight:600">${esc(x.name)}</b><div class="muted small">${x.n} ${plural(x.n, 'wpis ręczny', 'wpisy ręczne', 'wpisów ręcznych')}</div></td><td class="r num">${zl(x.inflow)}</td><td class="r num">${zl(x.outflow)}</td>
      <td class="r num">${x.balance_source === 'snapshot' ? stan(x) : '<span class="small" style="color:var(--warn)">wpisz, ile jest w portfelu</span>'}</td>
      <td class="r" style="white-space:nowrap"><button class="btn small" onclick="balanceDialog(${x.id})">Wpisz stan</button> <button class="btn small" onclick="F.person=${x.person_id};manualDialog()">Dodaj wydatek</button></td></tr>`).join('') + '</table>' : ''}
    ${noWallet.length ? `<div class="actions" style="margin-top:${cash.length ? 12 : 0}px">${noWallet.map(p => `<button class="btn" onclick="addWallet(${p.id})">Dodaj portfel: ${esc(p.name)}</button>`).join('')}</div>` : ''}
    ${gcat ? `<label class="small" style="display:flex;gap:10px;align-items:center;margin-top:14px;flex-wrap:wrap">Wypłaty z bankomatu:<select onchange="setAtm(${gcat.id},this.value)"><option value="expense" ${gcat.kind !== 'transfer' ? 'selected' : ''}>licz jako wydatek (nie wpisuję wydatków gotówkowych)</option><option value="transfer" ${gcat.kind === 'transfer' ? 'selected' : ''}>zasilają portfel (wydatki gotówkowe wpisuję ręcznie)</option></select></label>` : ''}</div>`;
  h += `<div class="panel"><h2>W budżecie</h2>${inb.length ? `<table><tr><th>Konto</th><th>Rodzaj</th><th>Czyje</th><th class="r">Stan</th><th></th></tr>` +
    inb.map(x => `<tr><td><b style="font-weight:600">${esc(x.name)}</b><div class="muted small">${x.n} ${plural(x.n, 'transakcja', 'transakcje', 'transakcji')}</div></td>
      <td><select onchange="saveAcc(${x.id},{kind:this.value})">${kindOptions(x.kind)}</select></td><td><select onchange="saveAcc(${x.id},{person_id:+this.value})">${personOptions(x.person_id)}</select></td>
      <td class="r num">${x.balance_source === 'flows' ? '<span class="small" style="color:var(--warn)">wyciąg bez salda, wpisz stan</span>' : stan(x)}</td>
      <td class="r" style="white-space:nowrap"><button class="btn small" onclick="balanceDialog(${x.id})">Wpisz stan</button> <button class="btn small" onclick="go('transakcje',{account:'${x.id}',category:'',q:''})">Transakcje</button></td></tr>`).join('') + '</table>' : '<span class="muted">Konta pojawią się po wczytaniu wyciągu.</span>'}</div>`;
  main.innerHTML = h;
}
async function saveAcc(id, b) { try { await api('accounts/' + id, { body: b }); await render(); toast('Zapisano. Przelewy między kontami rozpoznałem od nowa.'); } catch (e) { toast(e.message); } }
async function addAcc(f) {
  try { await api('accounts', { body: { name: f.n.value, kind: f.k.value, person_id: +f.p.value, amount: f.a.value.trim() ? toGr(f.a.value) : null } }); await render(); toast('Dodano konto.'); } catch (e) { toast(e.message); }
}
function openingDialog(day) {
  const first = S.first || new Date().toISOString().slice(0, 10);
  day = day || `${+first.slice(0, 4) - 1}-12-31`;
  const list = ACC.length ? ACC : [];
  modal(`<h2>Salda otwarcia</h2><p>Wpisz stan każdego konta na koniec wybranego dnia, zwykle ostatniego dnia poprzedniego roku. Puste pola są pomijane. Wczytane wyciągi powinny zaczynać się następnego dnia.</p>
    <form class="form" onsubmit="saveOpening(event)"><label style="max-width:200px">Stan na koniec dnia<input type="date" name="day" value="${day}" required onchange="openingDialog(this.value)"></label>
      <table class="tight"><tr><th>Konto</th><th class="r" style="width:150px">Stan, zł</th></tr>${list.map(x => { const s = x.snapshots.find(q => q.date === day);
        return `<tr><td>${esc(x.name)}<div class="muted small">${esc(S.kinds[x.kind] || '')} · ${esc(pname(x.person_id))}${x.balance_source === 'statement' ? ' · wyciąg podaje saldo, wpis nie jest potrzebny' : ''}</div></td>
          <td><input type="text" name="b${x.id}" inputmode="decimal" style="text-align:right;width:140px" value="${s ? num(s.amount) : ''}" placeholder="${x.balance_source === 'statement' ? 'z wyciągu' : '0,00'}"></td></tr>`; }).join('') || '<tr><td class="muted">Najpierw wczytaj wyciąg albo dodaj konto.</td></tr>'}</table>
      <div class="actions"><button class="btn primary">Zapisz salda</button><button type="button" class="btn" onclick="closeModal()">Anuluj</button></div></form>`);
}
async function saveOpening(ev) {
  ev.preventDefault(); const f = ev.target; let n = 0;
  try { for (const x of ACC) { const v = f['b' + x.id] && f['b' + x.id].value.trim(); if (v) { await api(`accounts/${x.id}/balance`, { body: { date: f.day.value, amount: toGr(v) } }); n++; } }
    closeModal(); await render(); toast(`Zapisano ${n} ${plural(n, 'saldo', 'salda', 'sald')} na ${f.day.value}.`); } catch (e) { toast(e.message); }
}
async function addWallet(pid) { try { await api('accounts', { body: { name: 'Gotówka', kind: 'cash', person_id: pid } }); await render(); toast('Dodano portfel. Wpisz, ile w nim teraz jest.'); } catch (e) { toast(e.message); } }
async function setAtm(cid, kind) { try { await api('categories/' + cid, { body: { kind } }); await render(); toast(kind === 'transfer' ? 'Wypłaty z bankomatu zasilają teraz portfel i nie są wydatkiem.' : 'Wypłaty z bankomatu liczą się jako wydatek.'); } catch (e) { toast(e.message); } }
async function delAcc(id) { if (confirm('Usunąć to konto razem z wpisanymi stanami?')) { try { await api('accounts/' + id, { method: 'DELETE' }); render(); } catch (e) { toast(e.message); } } }
function balanceDialog(id) {
  const x = ACC.find(q => q.id === id), today = new Date().toISOString().slice(0, 10);
  modal(`<h2>Stan konta ${esc(x.name)}</h2><p>Wpisz, ile było na koncie danego dnia. Późniejsze operacje z wyciągów program doliczy sam.</p>
    <form class="form" onsubmit="saveBalance(event,${id})"><span style="display:flex;gap:10px"><label style="flex:1">Dzień<input type="date" name="d" value="${today}" required></label><label style="flex:1">Stan, zł<input type="text" name="a" inputmode="decimal" required autofocus style="text-align:right"></label></span>
    <div class="actions"><button class="btn primary">Zapisz stan</button><button type="button" class="btn" onclick="closeModal()">Zamknij</button></div></form>
    ${x.snapshots.length ? `<table style="margin-top:14px"><tr><th>Dzień</th><th class="r">Stan</th><th></th></tr>${x.snapshots.map(s => `<tr><td class="num">${s.date}</td><td class="r num">${zl(s.amount)}</td><td class="r"><button class="btn small danger" onclick="delBalance(${s.id})">Usuń</button></td></tr>`).join('')}</table>` : ''}`);
}
async function saveBalance(ev, id) { ev.preventDefault(); try { await api(`accounts/${id}/balance`, { body: { date: ev.target.d.value, amount: toGr(ev.target.a.value) } }); closeModal(); await render(); toast('Zapisano stan.'); } catch (e) { toast(e.message); } }
async function delBalance(id) { await api('balances/' + id, { method: 'DELETE' }); closeModal(); render(); }

// ---------- rozliczenia (pozycje, które mają się zerować) ----------
let SETTLE = [];
const ST = { settled: ['✓', 'wyzerowane', 'good'], waiting: ['…', 'czeka na zwrot', 'warn'], missing: ['✕', 'brak zwrotu', 'bad'], extra: ['+', 'zwrot bez obciążenia', 'warn'], refund: ['✓', 'zwrot', 'good'] };
const stTag = s => `<span style="color:var(--${ST[s][2]});white-space:nowrap">${ST[s][0]} ${ST[s][1]}</span>`;
async function vSettle(main) {
  const d = await api('settlements?' + qs({ ...range(), person: F.person }));
  SETTLE = d.groups;
  let h = topbar('Rozliczenia');
  h += `<div class="note"><span>Rozliczenie to zestaw, który ma dawać zero: koszt i jego zwrot. Według frazy – program sam zbiera transakcje o wspólnym fragmencie opisu (np. opłata za kartę). Ręcznie – sam wskazujesz koszty i wpływy, które do siebie należą (np. wydatek służbowy i zwrot z firmy).</span>
    <span style="display:flex;gap:8px;flex:none"><button class="btn primary small" onclick="manualSettle()">Nowe ręcznie</button><button class="btn small" onclick="settleDialog()">Nowe według frazy</button></span></div>`;
  if (d.suggestions.length) h += `<div class="panel"><h2>Podpowiedzi<span>zwroty w wyciągach, które nie należą do żadnego rozliczenia</span></h2><table>${d.suggestions.map((s, i) => `<tr><td><code>${esc(s.phrase)}</code><div class="muted small">${esc(s.example)}</div></td><td class="r"><button class="btn small" onclick="settleDialog(null,${i})">Utwórz rozliczenie</button></td></tr>`).join('')}</table></div>`;
  window._sugg = d.suggestions;
  if (!d.groups.length) h += `<div class="panel empty"><b>Nie ma jeszcze rozliczeń</b>Dodaj pierwsze, np. „Opłata za kartę” z frazą „ZA KARTĘ”.</div>`;
  for (const g of d.groups) {
    if (g.mode === 'manual') { if (g.in_period || g.status !== 'settled' || F.mode === 'all') h += manualPanel(g); continue; }
    const head = g.balance === 0 && !g.missing && !g.waiting ? `<span style="color:var(--good)">✓ wszystko się zeruje</span>`
      : `<b class="num" style="color:var(--${g.missing ? 'bad' : 'warn'})">${g.balance > 0 ? '+' : ''}${zl(g.balance)}</b> ` + [g.missing ? `${g.missing} bez zwrotu` : '', g.waiting ? `${g.waiting} czeka` : '', g.extra ? `${g.extra} ${plural(g.extra, 'zwrot', 'zwroty', 'zwrotów')} bez obciążenia` : ''].filter(Boolean).join(', ');
    h += `<div class="panel"><h2>${esc(g.name)}<span>${g.count} ${plural(g.count, 'transakcja', 'transakcje', 'transakcji')} od początku danych · saldo: ${head}</span>
      <span style="float:right;margin:0"><button class="btn small" onclick="settleDialog(${g.id})">Zmień</button> <button class="btn small danger" onclick="delSettle(${g.id})">Usuń</button></span></h2>
      <p class="muted small" style="margin:-6px 0 12px">Frazy: ${g.patterns.split('\n').map(p => `<code>${esc(p)}</code>`).join(', ')} · zwrot do ${g.window} dni${g.category ? ' · kategoria: ' + esc(g.category) : ''}</p>` +
      (g.months.length ? `<table class="tight"><tr><th>Miesiąc obciążenia</th><th class="r">Obciążenia</th><th class="r">Zwrócono</th><th class="r">Do wyjaśnienia</th><th>Wynik</th></tr>` + g.months.map(m => {
        const [yy, mm] = m.month.split('-').map(Number), open = m.open - m.extra;
        return `<tr><td>${MONTHS[mm - 1]} ${yy}</td><td class="r num">${zl(m.charged)}</td><td class="r num">${zl(m.refunded)}</td><td class="r num">${open ? `<b>${zl(-open)}</b>` : '<span class="muted">0,00 zł</span>'}</td><td>${stTag(m.status)}</td></tr>
          <tr><td colspan="5" style="padding:0 6px 10px;border-bottom:1px solid var(--line2)"><details class="tbl" ${m.status === 'settled' ? '' : 'open'} style="margin:0"><summary>${m.items.length} ${plural(m.items.length, 'pozycja', 'pozycje', 'pozycji')}</summary><table>${m.items.map(t => `<tr><td class="num small" style="width:96px">${t.date}</td><td class="small">${esc(t.description).slice(0, 70)}${t.note ? `<div class="muted">${esc(t.note)}</div>` : ''}</td><td class="small">${esc(pname(t.person_id))}</td>
            <td class="r num small">${zl(t.amount)}</td><td class="small" style="width:230px">${t.pair ? `<span style="color:var(--good)">✓ zwrot ${t.pair.date}</span> <span class="muted">${t.pair.days === 0 ? 'tego samego dnia' : t.pair.days > 0 ? `po ${t.pair.days} ${plural(t.pair.days, 'dniu', 'dniach', 'dniach')}` : 'przed obciążeniem'}</span>` : stTag(t.status)}</td></tr>`).join('')}</table></details></td></tr>`; }).join('') + '</table>'
        : `<span class="muted">${g.count ? 'Brak pozycji w wybranym okresie.' : 'Żadna transakcja nie pasuje do tych fraz. Sprawdź je przyciskiem Zmień.'}</span>`) + '</div>';
  }
  main.innerHTML = h;
}
function settleCatOptions(sel) {      // wspólna kategoria dla kosztów i zwrotów musi być „poza budżetem”, inaczej jedna ze stron byłaby niezgodna
  const cur = S.categories.find(c => c.id === sel);
  return `<option value="">zostaw kategorie bez zmian</option>` + (cur && cur.kind !== 'transfer' ? `<option value="${cur.id}" selected>${esc(cur.name)} – tylko dla ${cur.kind === 'expense' ? 'kosztów' : 'wpływów'}</option>` : '') +
    S.categories.filter(c => c.kind === 'transfer').map(c => `<option value="${c.id}" ${c.id === sel ? 'selected' : ''}>${esc(c.name)}</option>`).join('');
}
function manualPanel(g) {
  const col = (title, rows, sum, empty) => `<div><h2 style="font-size:14px;margin-bottom:6px">${title}<span class="num" style="float:right;color:var(--ink);font-size:14px;font-weight:600;margin:0">${zl(sum)}</span></h2>
    ${rows.length ? `<table class="tight">${rows.map(t => `<tr><td class="num small" style="width:92px">${t.date}</td><td class="small">${esc(t.counterparty || t.description).slice(0, 44)}${t.note ? `<div class="muted">${esc(t.note)}</div>` : ''}<div class="muted">${esc(pname(t.person_id))}</div></td><td class="r num small">${zl(Math.abs(t.amount))}</td></tr>`).join('')}</table>` : `<span class="muted small">${empty}</span>`}</div>`;
  const res = g.balance === 0 ? `<span style="color:var(--good)">✓ wyzerowane</span>` : g.balance < 0 ? `<b class="num" style="color:var(--${g.status === 'missing' ? 'bad' : 'warn'})">brakuje ${zl(-g.balance)}</b> ${g.status === 'waiting' ? '· czeka na zwrot' : '· zwrot nie przyszedł'}` : `<b class="num" style="color:var(--warn)">nadwyżka ${zl(g.balance)}</b> · zwrotów jest więcej niż kosztów`;
  return `<div class="panel"><h2>${esc(g.name)}<span>zestaw ręczny · ${g.count} ${plural(g.count, 'transakcja', 'transakcje', 'transakcji')} · wynik: ${res}</span>
    <span style="float:right;margin:0"><button class="btn small" onclick="manualSettle(${g.id})">Zmień</button> <button class="btn small danger" onclick="delSettle(${g.id})">Usuń</button></span></h2>
    <p class="muted small" style="margin:-6px 0 12px">Zwrot oczekiwany w ciągu ${g.window} dni od ostatniego kosztu${g.category ? ' · kategoria: ' + esc(g.category) : ''}</p>
    <div class="grid2" style="gap:26px">${col('Koszty', g.costs, g.cost_sum, 'Brak kosztów.')}${col('Zwroty i wpływy', g.refunds, g.refund_sum, 'Zwrot jeszcze nie przyszedł.')}</div></div>`;
}
let MS = null;
function manualSettle(id) {
  const g = id ? SETTLE.find(x => x.id === id) : null, def = S.categories.find(c => c.name === 'Wydatki do zwrotu');
  MS = g ? { id, name: g.name, window: g.window, category_id: g.category_id, items: [...g.costs, ...g.refunds] } : { id: 0, name: '', window: 40, category_id: def ? def.id : null, items: [] };
  modal(`<h2>${id ? 'Zmień zestaw' : 'Nowe rozliczenie ręczne'}</h2><p>Wyszukaj i dodaj koszty po lewej oraz zwroty po prawej. Szukać można po opisie, kontrahencie, własnym opisie albo kwocie (np. 850 lub 849,99). Kwoty nie muszą być identyczne – liczy się suma.</p>
    <form class="form" onsubmit="saveManualSettle(event)">
      <span style="display:flex;gap:10px;flex-wrap:wrap"><label style="flex:2;min-width:200px">Nazwa<input type="text" name="n" value="${esc(MS.name)}" placeholder="np. Mechanik – wydatek służbowy" required></label>
        <label style="flex:1.4;min-width:180px">Kategoria (koszty i zwroty razem)<select name="c">${settleCatOptions(MS.category_id)}</select></label>
        <label style="flex:.8;min-width:120px">Zwrot w ciągu (dni)<input type="number" name="w" min="1" max="400" value="${MS.window}"></label></span>
      <div class="grid2" style="gap:18px;align-items:start">${['neg', 'pos'].map(sg => `<div><b>${sg === 'neg' ? 'Koszty' : 'Zwroty i wpływy'}</b>
        <div id="ms-sel-${sg}" style="margin:6px 0 10px"></div>
        <input type="search" placeholder="${sg === 'neg' ? 'Szukaj wydatku' : 'Szukaj wpływu'}" style="width:100%" oninput="msSearch('${sg}',this.value)" onkeydown="if(event.key==='Enter')event.preventDefault()">
        <div id="ms-res-${sg}" class="small" style="margin-top:6px;max-height:230px;overflow:auto"></div></div>`).join('')}</div>
      <div id="ms-sum" style="padding:10px 14px;background:var(--line2);border-radius:10px"></div>
      <div class="actions"><button class="btn primary">Zapisz</button><button type="button" class="btn" onclick="closeModal()">Anuluj</button></div></form>`);
  $('#modal .box').style.width = 'min(1000px, 100%)';
  msDraw(); msSearch('neg', ''); msSearch('pos', '');
}
function msDraw() {
  for (const sg of ['neg', 'pos']) {
    const rows = MS.items.filter(t => sg === 'neg' ? t.amount < 0 : t.amount > 0);
    $('#ms-sel-' + sg).innerHTML = rows.length ? `<table class="tight">${rows.map(t => `<tr><td class="num small">${t.date}</td><td class="small">${esc(t.counterparty || t.description).slice(0, 34)}</td><td class="r num small">${zl(Math.abs(t.amount))}</td><td class="r"><button type="button" class="btn small" aria-label="Usuń z zestawu" onclick="msRemove(${t.id})">×</button></td></tr>`).join('')}</table>` : `<span class="muted small">${sg === 'neg' ? 'Nie wybrano jeszcze kosztu.' : 'Nie wybrano jeszcze zwrotu (można dodać później).'}</span>`;
  }
  const cost = -MS.items.filter(t => t.amount < 0).reduce((s, t) => s + t.amount, 0), inc = MS.items.filter(t => t.amount > 0).reduce((s, t) => s + t.amount, 0), bal = inc - cost;
  $('#ms-sum').innerHTML = `Koszty <b class="num">${zl(cost)}</b> · zwroty <b class="num">${zl(inc)}</b> · wynik: ${bal === 0 && MS.items.length ? '<b style="color:var(--good)">✓ zeruje się</b>' : bal < 0 ? `<b class="num" style="color:var(--warn)">brakuje ${zl(-bal)}</b>` : bal > 0 ? `<b class="num" style="color:var(--warn)">nadwyżka ${zl(bal)}</b>` : '<span class="muted">dodaj transakcje</span>'}`;
}
let msTimer = {}, msFound = {};
function msSearch(sg, q) {
  clearTimeout(msTimer[sg]);
  msTimer[sg] = setTimeout(async () => {
    const d = await api('transactions?' + qs({ q, sign: sg, limit: 14 }));
    d.rows.forEach(t => msFound[t.id] = t);
    const rows = d.rows.filter(t => !MS.items.some(i => i.id === t.id));
    const el = $('#ms-res-' + sg); if (!el) return;
    el.innerHTML = rows.length ? `<table class="tight">${rows.map(t => `<tr><td class="num">${t.date}</td><td>${esc(t.manual ? t.description : (t.counterparty || t.merchant || t.description)).slice(0, 30)}<div class="muted" title="${esc(t.description)}">${esc(t.note || t.description).slice(0, 44)} · ${esc(pname(t.person_id))}</div></td><td class="r num">${zl(Math.abs(t.amount))}</td><td class="r"><button type="button" class="btn small" onclick="msAdd(${t.id},'${sg}')">Dodaj</button></td></tr>`).join('')}</table>${d.total > d.rows.length ? `<div class="muted" style="padding:4px 6px">Pokazuję ${d.rows.length} z ${d.total} – zawęź wyszukiwanie.</div>` : ''}` : '<span class="muted">Nic nie pasuje.</span>';
  }, 180);
}
function msAdd(id, sg) { MS.items.push(msFound[id]); MS.items.sort((x, y) => x.date < y.date ? -1 : 1); msDraw(); const inp = $(`#ms-res-${sg}`).previousElementSibling; msSearch(sg, inp.value); }
function msRemove(id) { MS.items = MS.items.filter(t => t.id !== id); msDraw(); for (const sg of ['neg', 'pos']) msSearch(sg, $(`#ms-res-${sg}`).previousElementSibling.value); }
async function saveManualSettle(ev) {
  ev.preventDefault(); const f = ev.target;
  try { await api('settlements' + (MS.id ? '/' + MS.id : ''), { body: { mode: 'manual', name: f.n.value, window: +f.w.value, category_id: +f.c.value || null, items: MS.items.map(t => t.id) } });
    closeModal(); if (MS.items.length && F.mode === 'month') F.anchor = MS.items[MS.items.length - 1].date.slice(0, 7); await render(); toast('Zapisano rozliczenie.'); } catch (e) { toast(e.message); }
}
function settleDialog(id, sugg) {
  const g = id ? SETTLE.find(x => x.id === id) : { name: '', patterns: sugg !== undefined ? window._sugg[sugg].phrase : '', window: 40, category_id: null };
  modal(`<h2>${id ? 'Zmień rozliczenie' : 'Nowe rozliczenie'}</h2><p>Wpisz fragment opisu wspólny dla obciążenia i zwrotu. Wielkość liter i polskie znaki nie mają znaczenia. Kilka fraz – każda w osobnej linii.</p>
    <form class="form" onsubmit="saveSettle(event,${id || 0})"><label>Nazwa<input type="text" name="n" value="${esc(g.name)}" placeholder="np. Opłata za kartę" required></label>
      <label>Frazy w opisie<textarea name="p" rows="3" required style="border:1px solid var(--line);background:var(--raised);border-radius:8px;padding:6px 9px;font:inherit;color:inherit" placeholder="ZA KARTĘ">${esc(g.patterns)}</textarea></label>
      <span style="display:flex;gap:10px"><label style="flex:1">Zwrot powinien przyjść w ciągu (dni)<input type="number" name="w" min="1" max="400" value="${g.window}"></label>
        <label style="flex:1">Kategoria (obciążenia i zwroty razem)<select name="c">${settleCatOptions(g.category_id)}</select></label></span>
      <div id="spv" class="small muted">Kliknij „Sprawdź”, żeby zobaczyć, które transakcje pasują.</div>
      <div class="actions"><button class="btn primary">Zapisz</button><button type="button" class="btn" onclick="previewSettle(this.form)">Sprawdź</button><button type="button" class="btn" onclick="closeModal()">Anuluj</button></div></form>`);
  if (g.patterns) previewSettle($('#modal form'));
}
async function previewSettle(f) {
  const r = await api('settlements/preview', { body: { patterns: f.p.value } });
  $('#spv').innerHTML = r.count ? `<b style="color:var(--ink)">${r.count} ${plural(r.count, 'transakcja pasuje', 'transakcje pasują', 'transakcji pasuje')}</b>, razem ${zl(r.balance)}. Ostatnie:<table>${r.rows.map(t => `<tr><td class="num">${t.date}</td><td>${esc(t.description).slice(0, 52)}</td><td class="r num">${zl(t.amount)}</td></tr>`).join('')}</table>` : '<span style="color:var(--warn)">Żadna transakcja nie pasuje. Spróbuj krótszej frazy.</span>';
}
async function saveSettle(ev, id) {
  ev.preventDefault(); const f = ev.target;
  try { await api('settlements' + (id ? '/' + id : ''), { body: { name: f.n.value, patterns: f.p.value, window: +f.w.value, category_id: +f.c.value || null } }); closeModal(); await render(); toast('Zapisano rozliczenie.'); } catch (e) { toast(e.message); }
}
async function delSettle(id) { if (confirm('Usunąć to rozliczenie? Transakcje zostają.')) { await api('settlements/' + id, { method: 'DELETE' }); render(); } }

view = location.hash.slice(1) || 'przeglad';
render();
