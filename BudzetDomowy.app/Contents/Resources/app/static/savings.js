// ---------- gdzie można zaoszczędzić ----------
const SV = (() => { try { return Object.assign({ cancel: [], cuts: {}, extra: {}, target: 10 }, JSON.parse(localStorage.getItem('sv') || '{}')); } catch (e) { return { cancel: [], cuts: {}, extra: {}, target: 10 }; } })();
let SVD = null;
const svSave = () => { try { localStorage.setItem('sv', JSON.stringify(SV)); } catch (e) { } };
const r50 = v => Math.max(0, Math.floor(v / 5000) * 5000);
const zlr = v => zl(v, { round: 1 });

function spark(vals, w = 120, h = 26) {
  const mx = Math.max(1, ...vals), bw = w / vals.length;
  return `<svg width="${w}" height="${h}" class="spark" aria-hidden="true">${vals.map((v, i) => `<rect x="${i * bw + 1}" y="${h - Math.max(1, v / mx * h)}" width="${Math.max(1, bw - 2)}" height="${Math.max(1, v / mx * h)}" rx="1"/>`).join('')}</svg>`;
}

function svTotals() {
  if (!SVD || SVD.empty) return { total: 0 };
  let total = 0;
  for (const s of SVD.sections) {
    if (s.id === 'recurring') total += s.items.filter(r => SV.cancel.includes(r.phrase)).reduce((a, r) => a + r.monthly, 0);
    if (s.id === 'flex') total += s.items.reduce((a, f) => { const p = SV.cuts[f.category_id] || 0; return a + (p ? f.typical - r50(f.typical * (1 - p / 100)) : 0); }, 0);
    if (s.save && SV.extra[s.id]) total += s.save;
  }
  return { total };
}

function svUpdate() {
  const { total } = svTotals(), d = SVD, el = document.getElementById('svTotal'); if (!el) return;
  el.innerHTML = `<div class="val num" style="color:var(--good)">${zlr(total)}</div><div class="sub">miesięcznie · ${zlr(total * 12)} rocznie</div>`;
  const left = d.income_median - d.expense_median, goal = Math.round(d.income_median * SV.target / 100), need = goal - left;
  document.getElementById('svGoal').innerHTML = need <= 0
    ? `Typowy miesiąc już spełnia ten cel – zostaje ok. <b>${zlr(left)}</b>.`
    : `Żeby odkładać ${SV.target}% dochodów (${zlr(goal)}), w typowym miesiącu brakuje <b>${zlr(need)}</b>. `
      + (total ? (total >= need ? `<span style="color:var(--good)">Wybrane oszczędności wystarczą.</span>` : `Wybrane oszczędności pokrywają ${Math.round(total / need * 100)}% tej kwoty.`) : 'Wybierz poniżej, z czego możesz zrezygnować.');
  document.querySelectorAll('[data-cut]').forEach(b => b.classList.toggle('on', (SV.cuts[b.dataset.cat] || 0) === +b.dataset.cut));
  document.querySelectorAll('[data-limit]').forEach(td => {
    const f = d.sections.find(s => s.id === 'flex').items.find(x => String(x.category_id) === td.dataset.limit), p = SV.cuts[f.category_id] || 0;
    td.innerHTML = p ? `limit <b class="num">${zlr(r50(f.typical * (1 - p / 100)))}</b> · <span style="color:var(--good)">−${zlr(f.typical - r50(f.typical * (1 - p / 100)))}</span><br><button class="btn small" onclick="svSetLimit(${f.category_id},${r50(f.typical * (1 - p / 100))})">Ustaw jako limit</button>` : '<span class="muted small">bez zmian</span>';
  });
}

async function vSavings(main) {
  const d = SVD = await api('savings?' + qs({ person: F.person }));
  const people = S.people.length > 1 ? `<div class="seg" role="group" aria-label="Osoba"><button class="${F.person ? '' : 'on'}" onclick="F.person=null;render()">Razem</button>` +
    S.people.map(p => `<button class="${F.person === p.id ? 'on' : ''}" onclick="F.person=${p.id};render()"><i class="dot" style="background:${pcolor(p.id)}"></i>${esc(p.name)}</button>`).join('') + '</div>' : '';
  let h = `<div class="bar"><h1>Oszczędności</h1>${people}</div>`;
  if (d.empty) { main.innerHTML = h + `<div class="empty"><b>Za mało danych</b>${esc(d.reason || 'Wczytaj wyciągi z kilku miesięcy.')}</div>`; return; }
  const left = d.income_median - d.expense_median;
  h += `<div class="figs">
    <div class="fig"><div class="lab">Typowy miesiąc</div><div class="val num" style="color:${left >= 0 ? 'var(--ink)' : 'var(--bad)'}">${left >= 0 ? '+' : '−'}${zlr(Math.abs(left))}</div>
      <div class="sub">wpływy ${zlr(d.income_median)} · wydatki ${zlr(d.expense_median)}<br>mediana z ${d.n} mies.; średnio ${d.net >= 0 ? '+' : '−'}${zlr(Math.abs(d.net))}</div></div>
    <div class="fig"><div class="lab">Wybrane oszczędności</div><div id="svTotal"></div></div>
    <div class="fig"><div class="lab">Cel</div><div class="seg small" role="group" aria-label="Cel oszczędzania" style="margin:4px 0 8px">${[5, 10, 15, 20].map(p => `<button class="${SV.target === p ? 'on' : ''}" onclick="SV.target=${p};svSave();render()">${p}%</button>`).join('')}</div><div class="sub" id="svGoal" style="font-size:13px"></div></div></div>`;

  for (const s of d.sections) {
    h += `<div class="panel"><h2>${s.title}<span>${s.id === 'growth' ? 'do sprawdzenia' : s.confidence === 'pewne' ? 'konkretne kwoty' : 'wymaga zmiany nawyków'}</span></h2><p class="muted small" style="margin:-6px 0 12px">${esc(s.lead)}</p>`;
    if (s.id === 'recurring') {
      h += `<table class="plan">` + s.items.map(r => `<tr><td class="ck"><input type="checkbox" aria-label="Rezygnuję" ${SV.cancel.includes(r.phrase) ? 'checked' : ''} onchange="svToggle('${esc(r.phrase)}',this.checked)"></td>
        <td><b style="font-weight:600">${esc(r.name)}</b><div class="muted small">${esc(r.category)} · ${r.freq}${r.variable ? ' · kwota zmienna' : ''}${r.person_id && S.people.length > 1 ? ` · <i class="dot" style="background:${pcolor(r.person_id)}"></i> ${esc(pname(r.person_id))}` : ''}</div></td>
        <td>${r.rise ? `<span class="chip bad">podrożało z ${zl(r.rise.before)} na ${zl(r.rise.now)}</span>` : ''}</td>
        <td class="r num">${r.variable ? '<span class="muted small">ok.</span> ' : ''}${zl(r.amount)}<div class="muted small">${zlr(r.yearly)} rocznie</div></td>
        <td class="r"><button class="btn small" onclick="svTx('${esc(r.phrase).replace(/'/g, '')}','')">Transakcje</button></td></tr>`).join('') + `</table>
        <p class="muted small" style="margin:10px 0 0">Zaznaczenie niczego nie anuluje – to tylko wyliczenie. Rezygnację trzeba zrobić u usługodawcy, a potem usunąć pozycję z Planu.</p>`;
    } else if (s.id === 'flex') {
      h += `<table class="plan">` + s.items.map(f => `<tr><td style="width:28%"><b style="font-weight:600">${esc(f.category)}</b><div class="muted small">${f.top.map(t => esc(t.name)).join(', ')}</div></td>
        <td>${spark(f.months)}<div class="muted small">typowo <b class="num">${zlr(f.typical)}</b>/mies.${f.trend > 0.15 ? ` · <span style="color:var(--bad)">ostatnio ${zlr(f.last3)}</span>` : ''}${f.budget ? ` · limit ${zlr(f.budget)}` : ''}</div></td>
        <td><div class="seg small" role="group" aria-label="Ogranicz o">${[0, 10, 20, 30].map(p => `<button data-cut="${p}" data-cat="${f.category_id}" onclick="svCut(${f.category_id},${p})">${p ? '−' + p + '%' : '0'}</button>`).join('')}</div></td>
        <td class="r small" data-limit="${f.category_id}" style="min-width:170px"></td></tr>`).join('') + '</table>';
    } else if (s.id === 'growth') {
      h += `<table class="plan">` + s.items.map(g => `<tr class="click" onclick="svTx('','${g.category_id ?? 'none'}')"><td><b style="font-weight:600">${esc(g.category)}</b>${g.fixed ? '<div class="muted small">stała opłata – sprawdź, czy to podwyżka</div>' : ''}</td>
        <td class="r num muted">${zlr(g.before)}</td><td class="r">→</td><td class="r num">${zlr(g.last3)}</td><td class="r num" style="color:var(--bad)">+${zlr(g.diff)}${g.pct ? ` <span class="small">(+${g.pct}%)</span>` : ''}</td></tr>`).join('') + '</table>';
    } else if (s.id === 'small') {
      h += `<table class="plan">` + s.items.map(t => `<tr><td>${esc(t.name)}<div class="muted small">${esc(t.category || 'bez kategorii')}</div></td><td class="r small muted">${String(t.n).replace('.', ',')} × w miesiącu</td><td class="r num">${zlr(t.amount)}/mies.</td></tr>`).join('') + '</table>';
    } else if (s.id === 'fees') {
      h += `<table class="plan">` + s.items.map(t => `<tr><td>${esc(t.name)}</td><td class="r num">${zl(t.amount)}</td></tr>`).join('') + '</table>';
    } else if (s.id === 'cheaper') {
      h += `<table class="plan"><tr><th>Produkt</th><th class="r">Płacisz średnio</th><th>Najtaniej</th><th class="r">Różnica</th></tr>` + s.items.map(c => `<tr><td>${esc(c.name)}<div class="muted small">${Object.entries(c.stores).map(([k, v]) => `${esc(k)} ${zl(v)}`).join(' · ')}</div></td>
        <td class="r num">${zl(c.avg)}</td><td><b style="font-weight:600">${esc(c.best_store)}</b> <span class="num">${zl(c.best)}</span></td><td class="r num" style="color:var(--good)">−${zl(c.save)}/mies.</td></tr>`).join('') + '</table>';
    }
    if (s.save) h += `<label class="check" style="margin-top:12px;display:flex;gap:8px;align-items:center"><input type="checkbox" ${SV.extra[s.id] ? 'checked' : ''} onchange="SV.extra['${s.id}']=this.checked;svSave();svUpdate()"> <span>Uwzględnij w podsumowaniu: <b class="num">${zlr(s.save)}</b> miesięcznie${s.id === 'small' ? ' (o jedną trzecią mniej drobnych zakupów)' : ''}</span></label>`;
    h += `</div>`;
  }
  h += `<p class="muted small">Analiza obejmuje ${d.n} pełnych miesięcy (${fmtRange(d.months[0] + '-01', addMonths(d.months[d.months.length - 1] + '-01', 0).slice(0, 8) + lastDay(+d.months[d.months.length - 1].slice(0, 4), +d.months[d.months.length - 1].slice(5)))}), tylko konta budżetowe i gotówkę; przelewy między własnymi kontami są pominięte. Wybory na tej stronie zapamiętuje ta przeglądarka.</p>`;
  main.innerHTML = h;
  svUpdate();
}
function svToggle(phrase, on) { SV.cancel = SV.cancel.filter(p => p !== phrase); if (on) SV.cancel.push(phrase); svSave(); svUpdate(); }
function svCut(cid, p) { SV.cuts[cid] = p; svSave(); svUpdate(); }
async function svSetLimit(cid, value) {
  try { await api('categories/' + cid, { body: { budget: value } }); const c = S.categories.find(x => x.id === cid); if (c) c.budget = value; toast(`Ustawiono limit ${zlr(value)} miesięcznie – widać go w Przeglądzie.`); } catch (e) { toast(e.message); }
}
function svTx(q, category) { F.mode = 'range'; F.from = SVD.months[0] + '-01'; F.to = SVD.data_to; go('transakcje', { q, category }); }
