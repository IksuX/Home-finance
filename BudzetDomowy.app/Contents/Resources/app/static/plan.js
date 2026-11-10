// ---------- plan wydatków i przychodów ----------
const PL = { months: 6, data: null, all: false };
const PLFREQ = { once: 'jednorazowo', weekly: 'co tydzień', biweekly: 'co 2 tygodnie', monthly: 'co miesiąc', bimonthly: 'co 2 miesiące', quarterly: 'co kwartał', halfyear: 'co pół roku', yearly: 'co rok' };
const MGEN = ['stycznia', 'lutego', 'marca', 'kwietnia', 'maja', 'czerwca', 'lipca', 'sierpnia', 'września', 'października', 'listopada', 'grudnia'];
const fmtDay = s => { const [y, m, d] = s.split('-').map(Number); return `${d} ${MSHORT[m - 1]}${y !== new Date().getFullYear() ? ' ' + y : ''}`; };
const daysTo = s => Math.round((new Date(s + 'T12:00:00') - new Date(new Date().toISOString().slice(0, 10) + 'T12:00:00')) / 864e5);

async function vPlan(main) {
  const d = PL.data = await api('plan?' + qs({ months: PL.months, person: F.person }));
  const people = S.people.length > 1 ? `<div class="seg" role="group" aria-label="Osoba"><button class="${F.person ? '' : 'on'}" onclick="F.person=null;render()">Razem</button>` +
    S.people.map(p => `<button class="${F.person === p.id ? 'on' : ''}" onclick="F.person=${p.id};render()"><i class="dot" style="background:${pcolor(p.id)}"></i>${esc(p.name)}</button>`).join('') + '</div>' : '';
  const hz = `<div class="seg" role="group" aria-label="Na ile miesięcy">${[[1, 'Ten miesiąc'], [3, '3 mies.'], [6, '6 mies.'], [12, '12 mies.']].map(([k, l]) => `<button class="${PL.months === k ? 'on' : ''}" onclick="PL.months=${k};render()">${l}</button>`).join('')}</div>`;
  const ahead = d.occurrences.filter(o => o.status === 'due' || o.status === 'overdue');
  const out = -ahead.filter(o => o.amount < 0).reduce((a, o) => a + o.amount, 0), inc = ahead.filter(o => o.amount > 0).reduce((a, o) => a + o.amount, 0);
  const overdue = d.occurrences.filter(o => o.status === 'overdue');
  const last = d.forecast[d.forecast.length - 1], hzLabel = PL.months === 1 ? 'do końca miesiąca' : `do końca ${MGEN[+d.horizon.slice(5, 7) - 1]}${d.horizon.slice(0, 4) !== d.today.slice(0, 4) ? ' ' + d.horizon.slice(0, 4) : ''}`;

  let h = `<div class="bar"><h1>Plan</h1>${hz}${people}</div>`;
  h += `<div class="figs">
    <div class="fig"><div class="lab"><i class="sw" style="background:var(--expense)"></i>Zaplanowane wydatki</div><div class="val num">${zl(out)}</div><div class="sub">${ahead.filter(o => o.amount < 0).length} ${plural(ahead.filter(o => o.amount < 0).length, 'termin', 'terminy', 'terminów')} ${hzLabel}${overdue.length ? `, <span style="color:var(--bad)">${overdue.length} ${plural(overdue.length, 'zaległy', 'zaległe', 'zaległych')}</span>` : ''}</div></div>
    <div class="fig"><div class="lab"><i class="sw" style="background:var(--income)"></i>Zaplanowane wpływy</div><div class="val num">${zl(inc)}</div><div class="sub">${hzLabel}</div></div>
    <div class="fig"><div class="lab">Prognoza: pieniądze w budżecie</div>${last && last.end !== null ? `<div class="val num" style="color:${last.end >= 0 ? 'var(--ink)' : 'var(--bad)'}">${zl(last.end)}</div><div class="sub">na koniec ${MGEN[+last.month.slice(5) - 1]} ${last.month.slice(0, 4)}, dziś ${zl(d.money)} (stan z ${d.data_to})</div>`
      : `<div class="val num muted">—</div><div class="sub">Brakuje salda otwarcia: ${d.money_missing.map(esc).join(', ')}. <a href="#konta" onclick="go('konta');return false">Wpisz</a></div>`}</div></div>`;

  if (d.suggestions.length) {
    const exp = d.suggestions.filter(s => s.amount < 0);
    h += `<div class="panel"><h2 style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">Wykryte powtarzające się płatności<span>${d.suggestions.length} – na podstawie wyciągów</span>${d.suggestions.length > 1 ? `<button class="btn small" style="margin-left:auto" onclick="acceptAll()">Dodaj wszystkie</button>` : ''}</h2>
      <p class="muted small" style="margin:-6px 0 10px">Program znalazł odbiorców, którym płacicie regularnie. Dodaj je do planu, żeby widzieć je w prognozie i wiedzieć, czy zostały zapłacone. Kwota w planie to mediana z ostatnich płatności. Czegoś brakuje? W <a href="#transakcje" onclick="go('transakcje');return false">Transakcjach</a> najedź na transakcję i wybierz „Powtarza się – dodaj do planu” albo zaznacz kilka i użyj „Dodaj do planu jako cykliczne”.</p>
      <table class="plan">${d.suggestions.map((s, i) => `<tr><td><b style="font-weight:600">${esc(s.name)}</b><div class="muted small">${s.freq_label} · ${s.count}× · ostatnio ${fmtDay(s.last)}</div></td>
        <td class="small">następna ok. <b class="num" style="font-weight:600">${fmtDay(s.next)}</b></td>
        <td class="r num ${s.amount > 0 ? 'pos' : ''}">${s.variable ? '<span class="muted small">ok.</span> ' : ''}${s.amount > 0 ? '+' : ''}${zl(s.amount)}${s.variable ? `<div class="muted small">od ${zl(Math.abs(s.min) < Math.abs(s.max) ? s.min : s.max)} do ${zl(Math.abs(s.min) < Math.abs(s.max) ? s.max : s.min)}</div>` : ''}</td>
        <td><select id="sgc${i}" aria-label="Kategoria">${catOptions(s.category_id, true, s.amount)}</select></td>
        <td class="r" style="white-space:nowrap"><button class="btn small primary" onclick="acceptSug(${i})">Dodaj do planu</button> <button class="btn small" onclick="ignoreSug(${i})">Pomiń</button></td></tr>`).join('')}</table></div>`;
  }

  const soon = addDays(d.today, 45);
  const show = PL.all ? d.occurrences : d.occurrences.filter(o => o.due <= soon || o.status === 'overdue'), hiddenN = d.occurrences.length - show.length;
  let mon = '';
  h += `<div class="panel"><h2>Terminy<span>${PL.all ? `najbliższe ${PL.months} mies.` : 'najbliższe 45 dni'} · zapłacone rozpoznaje po wyciągach</span></h2>${show.length ? `<table class="plan">` + show.map(o => {
    const p = d.plans.find(x => x.id === o.plan_id) || {};
    let st;
    if (o.status === 'paid') st = o.tx ? `<span class="chip good">✓ zapłacone ${fmtDay(o.tx.date)}${o.tx.amount !== o.planned ? ` · ${zl(o.tx.amount)}` : ''}</span>` : `<span class="chip good">✓ oznaczone jako zapłacone</span>`;
    else if (o.status === 'skipped') st = `<span class="chip">pominięte</span>`;
    else if (o.status === 'overdue') st = `<span class="chip bad">nie widać płatności</span>`;
    else { const n = daysTo(o.due); st = `<span class="chip ${n <= 3 ? 'warn' : ''}">${n < 0 ? 'czeka na wyciąg' : n === 0 ? 'dziś' : n === 1 ? 'jutro' : `za ${n} dni`}</span>`; }
    const acts = o.status === 'due' || o.status === 'overdue' ? `<button class="btn small" onclick="markOcc(${o.plan_id},'${o.due}','paid')">Zapłacone</button> <button class="btn small" onclick="markOcc(${o.plan_id},'${o.due}','skipped')">Pomiń</button>`
      : !o.tx ? `<button class="btn small" onclick="markOcc(${o.plan_id},'${o.due}',null)">Cofnij</button>` : '';
    const m = o.due.slice(0, 7), head = m !== mon ? (mon = m, `<tr class="mhead"><td colspan="5">${MONTHS[+m.slice(5) - 1]} ${m.slice(0, 4)}</td></tr>`) : '';
    return head + `<tr class="${o.status === 'paid' || o.status === 'skipped' ? 'done' : ''}"><td class="num small" style="white-space:nowrap">${fmtDay(o.due)}</td>
      <td><b style="font-weight:600">${esc(o.name)}</b><div class="muted small">${esc(o.category || 'bez kategorii')}${o.person_id && S.people.length > 1 ? ` · <i class="dot" style="background:${pcolor(o.person_id)}"></i> ${esc(pname(o.person_id))}` : ''}${p.variable ? ' · kwota zmienna' : ''}</div></td>
      <td>${st}</td><td class="r num ${o.amount > 0 ? 'pos' : ''}">${o.amount > 0 ? '+' : ''}${zl(o.amount)}</td><td class="r" style="white-space:nowrap">${acts}</td></tr>`; }).join('') + '</table>'
    + (hiddenN ? `<div class="actions" style="justify-content:center;margin-top:10px"><button class="btn small" onclick="PL.all=true;render()">Pokaż dalsze terminy (${hiddenN})</button></div>` : PL.all && d.occurrences.length > 12 ? `<div class="actions" style="justify-content:center;margin-top:10px"><button class="btn small" onclick="PL.all=false;render()">Tylko najbliższe 45 dni</button></div>` : '')
    : `<div class="empty"><b>Plan jest pusty</b>Dodaj wykryte płatności albo własny planowany wydatek, np. ubezpieczenie samochodu czy wakacje.</div>`}</div>`;

  h += `<div class="panel"><h2>Prognoza miesiąc po miesiącu</h2>
    <p class="muted small" style="margin:-6px 0 10px">„Poza planem” to typowy miesiąc z ostatnich ${d.history_months} ${plural(d.history_months, 'miesiąca', 'miesięcy', 'miesięcy')} bez pozycji z planu: wpływy ok. ${zl(d.avg_unplanned_in, { round: 1 })}, wydatki ok. ${zl(d.avg_unplanned, { round: 1 })} (zakupy, paliwo, restauracje – mediana, więc jeden duży zakup jej nie zawyża). W bieżącym miesiącu liczone tylko za dni, które zostały. Im więcej stałych wpływów i wydatków dodasz do planu, tym dokładniejsza prognoza.</p>
    <table class="plan fc"><tr><th>Miesiąc</th><th class="r">Wpływy z planu</th><th class="r">Wydatki z planu</th><th class="r">Poza planem</th><th class="r">Bilans miesiąca</th><th class="r">Na koniec</th></tr>
    ${d.forecast.map((f, i) => `<tr><td>${MONTHS[+f.month.slice(5) - 1]} ${f.month.slice(0, 4)}</td><td class="r num">${zl(f.plan_in)}</td><td class="r num">${zl(f.plan_out)}</td><td class="r num muted">${f.rest >= 0 ? '+' : '−'}${zl(Math.abs(f.rest))}</td>
      <td class="r num" style="color:var(--${f.net >= 0 ? 'good' : 'bad'})">${f.net >= 0 ? '+' : '−'}${zl(Math.abs(f.net))}</td><td class="r num"><b style="font-weight:600;color:${f.end !== null && f.end < 0 ? 'var(--bad)' : 'inherit'}">${f.end === null ? '—' : zl(f.end)}</b></td></tr>`).join('')}</table></div>`;

  h += `<div class="panel"><h2 style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">Twój plan<span>${d.plans.length} ${plural(d.plans.length, 'pozycja', 'pozycje', 'pozycji')}</span>
      <span style="margin-left:auto;display:flex;gap:6px"><button class="btn small primary" onclick="planDialog()">Dodaj planowany wydatek</button><button class="btn small" onclick="planDialog({amount:1})">Dodaj planowany wpływ</button></span></h2>
    ${d.plans.length ? `<table class="plan">${d.plans.map(p => `<tr><td><b style="font-weight:600">${esc(p.name)}</b><div class="muted small">${p.freq_label}${p.freq === 'once' ? ' · ' + fmtDay(p.start) : p.until ? ` · do ${fmtDay(p.until)}` : ''}${p.phrase ? ` · rozpoznaje „${esc(p.phrase)}”` : ''}${p.note ? ' · ' + esc(p.note) : ''}</div></td>
      <td class="small">${esc(p.category || 'bez kategorii')}${p.person_id && S.people.length > 1 ? `<div class="muted"><i class="dot" style="background:${pcolor(p.person_id)}"></i> ${esc(pname(p.person_id))}</div>` : ''}</td>
      <td class="small">${p.next ? `następny ${fmtDay(p.next)}` : '<span class="muted">brak terminów w tym okresie</span>'}</td>
      <td class="r num ${p.amount > 0 ? 'pos' : ''}">${p.variable ? '<span class="muted small">ok.</span> ' : ''}${p.amount > 0 ? '+' : ''}${zl(p.amount)}${p.freq !== 'once' && p.freq !== 'monthly' ? `<div class="muted small">ok. ${zl(Math.abs(p.monthly), { round: 1 })}/mies.</div>` : ''}</td>
      <td class="r" style="white-space:nowrap"><button class="btn small" onclick="planDialog(${p.id})">Zmień</button> <button class="btn small danger" onclick="delPlan(${p.id})">Usuń</button></td></tr>`).join('')}</table>`
    : '<span class="muted">Nic jeszcze nie zaplanowano.</span>'}</div>`;
  main.innerHTML = h;
}

function sugBody(s, cat) {
  return { name: s.name, amount: s.amount, category_id: cat ?? s.category_id, person_id: s.person_id, freq: s.freq, start: s.next, phrase: s.phrase, variable: s.variable, source: 'auto' };
}
async function acceptSug(i) {
  const s = PL.data.suggestions[i], c = +document.getElementById('sgc' + i).value || null;
  try { await api('plans', { body: sugBody(s, c) }); await render(); toast(`Dodano do planu: ${s.name}.`); } catch (e) { toast(e.message); }
}
async function acceptAll(kind) {
  const list = PL.data.suggestions.map((s, i) => [s, i]);
  if (!confirm(`Dodać do planu ${list.length} ${plural(list.length, 'płatność', 'płatności', 'płatności')}?`)) return;
  for (const [s, i] of list) await api('plans', { body: sugBody(s, +document.getElementById('sgc' + i).value || null) });
  await render(); toast(`Dodano ${list.length} ${plural(list.length, 'pozycję', 'pozycje', 'pozycji')} do planu.`);
}
async function ignoreSug(i) {
  const s = PL.data.suggestions[i];
  await api('plan_ignore', { body: { key: s.key } }); await render();
  toast(`Pominięto: ${s.name}. Nie będzie już proponowane.`, 'Cofnij', async () => { await api('plan_ignore', { body: { key: s.key, undo: 1 } }); render(); });
}
async function markOcc(id, due, status) {
  try { await api(`plans/${id}/mark`, { body: { due, status } }); await render(); } catch (e) { toast(e.message); }
}
async function delPlan(id) {
  const p = PL.data.plans.find(x => x.id === id);
  if (confirm(`Usunąć z planu „${p.name}”?`)) { await api('plans/' + id, { method: 'DELETE' }); render(); }
}
function planDialog(arg) {
  const p = typeof arg === 'number' ? PL.data.plans.find(x => x.id === arg) : null;
  const kind = p ? (p.amount > 0 ? 'income' : 'expense') : arg && arg.kind ? arg.kind : arg && arg.amount > 0 ? 'income' : 'expense';
  const pre = arg && typeof arg === 'object' && arg.name ? arg : null;      // propozycja z zaznaczonych transakcji
  const today = new Date().toISOString().slice(0, 10), v = p || pre || {};
  const freqs = Object.entries(PLFREQ).map(([k, l]) => `<option value="${k}" ${k === (v.freq || 'once') ? 'selected' : ''}>${l}</option>`).join('');
  modal(`<h2>${p ? 'Zmień pozycję planu' : kind === 'income' ? 'Planowany wpływ' : 'Planowany wydatek'}</h2>
    <p>${pre ? `Na podstawie ${pre.count} ${plural(pre.count, 'wystąpienia', 'wystąpień', 'wystąpień')} na wyciągach${pre.guessed ? ' – sprawdź, jak często się powtarza' : ''}. Kwota to mediana z ostatnich, pierwszy termin to następne spodziewane wystąpienie.`
      : kind === 'income' ? 'Np. premia, zwrot podatku, stałe wynagrodzenie.' : 'Np. ubezpieczenie samochodu, przegląd, wakacje, prezenty na święta, rata.'} Pozycja pojawi się w terminach i w prognozie.</p>
    <form class="form" onsubmit="savePlan(event,${p ? p.id : 'null'})">
      ${p || pre ? '' : `<div class="seg" role="group" style="justify-self:start"><button type="button" class="${kind === 'expense' ? 'on' : ''}" onclick="planDialog({kind:'expense'})">Wydatek</button><button type="button" class="${kind === 'income' ? 'on' : ''}" onclick="planDialog({kind:'income'})">Wpływ</button></div>`}
      <input type="hidden" name="kind" value="${kind}">
      <label>Nazwa<input type="text" name="n" value="${esc(v.name || '')}" required autofocus placeholder="${kind === 'income' ? 'np. Zwrot podatku' : 'np. OC i AC samochodu'}"></label>
      <span style="display:flex;gap:10px"><label style="flex:1">Kwota, zł<input type="text" name="a" inputmode="decimal" required style="text-align:right" value="${v.amount ? (Math.abs(v.amount) / 100).toFixed(2).replace('.', ',') : ''}"></label>
        <label style="flex:1">${v.freq && v.freq !== 'once' ? 'Pierwszy termin' : 'Termin'}<input type="date" name="d" value="${v.start || today}" required></label></span>
      <span style="display:flex;gap:10px"><label style="flex:1">Powtarzanie<select name="f">${freqs}</select></label><label style="flex:1">Do kiedy (opcjonalnie)<input type="date" name="u" value="${v.until || ''}"></label></span>
      <span style="display:flex;gap:10px"><label style="flex:1">Kategoria<select name="c"><option value="">bez kategorii</option>${S.categories.filter(c => c.kind === kind).map(c => `<option value="${c.id}" ${c.id === v.category_id ? 'selected' : ''}>${esc(c.name)}</option>`).join('')}</select></label>
        <label style="flex:1">Kto<select name="p"><option value="">wspólne</option>${personOptions(v.person_id ?? F.person)}</select></label></span>
      <label>Fraza do rozpoznania płatności (opcjonalnie)<input type="text" name="ph" value="${esc(v.phrase || '')}" placeholder="np. PZU – fragment opisu z wyciągu"></label>
      <div class="muted small" style="margin-top:-6px">Gdy na wyciągu pojawi się transakcja z tą frazą blisko terminu, pozycja zostanie oznaczona jako zapłacona.</div>
      <label class="check"><input type="checkbox" name="vr" ${v.variable ? 'checked' : ''}> <span>Kwota bywa różna (np. rachunek za prąd)</span></label>
      <label>Notatka (opcjonalnie)<input type="text" name="no" value="${esc(v.note || '')}"></label>
      <div class="actions"><button class="btn primary">${p ? 'Zapisz' : 'Dodaj do planu'}</button><button type="button" class="btn" onclick="closeModal()">Anuluj</button></div></form>`);
}
async function savePlan(ev, id) {
  ev.preventDefault(); const f = ev.target, amt = Math.abs(toGr(f.a.value));
  const p = id && PL.data ? PL.data.plans.find(x => x.id === id) : null;
  try {
    await api('plans' + (id ? '/' + id : ''), { body: { name: f.n.value, amount: f.kind.value === 'income' ? amt : -amt, start: f.d.value, freq: f.f.value, until: f.u.value || null,
      category_id: +f.c.value || null, person_id: +f.p.value || null, phrase: f.ph.value, variable: f.vr.checked, note: f.no.value, source: p ? p.source : 'manual' } });
    closeModal(); if (view === 'transakcje') { TX.sel.clear(); await render(); toast('Dodano do planu.', 'Otwórz Plan', () => go('plan')); } else { await render(); toast(id ? 'Zapisano.' : 'Dodano do planu.'); }
  } catch (e) { toast(e.message); }
}

async function planFromTx(ids) {
  try { const s = await api('plans/from', { body: { ids } }); planDialog(s); } catch (e) { toast(e.message); }
}
