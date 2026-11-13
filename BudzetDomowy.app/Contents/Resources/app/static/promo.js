// ---------- promocje z gazetek ----------
const PM = { data: null, onlyCheaper: true, q: '', results: null, poll: null, offers: {}, cart: [], withInfo: (() => { try { return localStorage.getItem('pmInfo') !== '0'; } catch (e) { return true; } })() };
const pepper = q => 'https://www.pepper.pl/search?q=' + encodeURIComponent(q);
const ceneo = q => 'https://www.ceneo.pl/;szukaj-' + encodeURIComponent(q).replace(/%20/g, '+');
const offerDates = o => o.start && o.end ? (o.start === o.end ? fmtDay(o.start) : `${fmtDay(o.start)} – ${fmtDay(o.end)}`) : o.end ? `do ${fmtDay(o.end)}` : '';
const searchTerm = name => name.replace(/[\d.,]+\s*(g|kg|ml|l|szt|%)\b/gi, ' ').replace(/[^\p{L}\s]/gu, ' ').split(/\s+/).filter(w => w.length > 2).slice(0, 3).join(' ');

function pmCartBtn(o) {
  PM.offers[o.id] = o;
  const inCart = PM.cart.some(c => c.id === o.id);
  return `<button class="btn small cartbtn${inCart ? ' on' : ''}" data-oid="${esc(o.id)}" onclick="pmCartToggle(this.dataset.oid)" title="${inCart ? 'Usuń z listy zakupów' : 'Dodaj do listy zakupów'}" aria-label="${inCart ? 'Usuń z listy zakupów' : 'Dodaj do listy zakupów'}">${inCart ? '✓' : '+'}</button>`;
}
function offerRow(o, typical) {
  const cheaper = typical && o.price && o.price < typical * 0.97;
  return `<div class="offer${o.upcoming ? ' soon' : ''}">
    <span class="st">${esc(o.store)}</span>
    <span class="nm">${esc(o.name)}${o.note ? ` <span class="muted small">· ${esc(o.note)}</span>` : ''}</span>
    <span class="pr num">${o.price ? `<b style="color:${cheaper ? 'var(--good)' : 'inherit'}">${zl(o.price)}</b>` : ''}${o.old_price ? ` <s class="muted small">${zl(o.old_price)}</s>` : ''}${o.discount ? ` <span class="chip good">−${o.discount}%</span>` : ''}</span>
    <span class="dt small ${o.upcoming ? '' : 'muted'}">${o.upcoming ? 'od ' + fmtDay(o.start) : offerDates(o)}</span>
    ${o.link ? `<a class="small" href="${esc(o.link)}" target="_blank" rel="noopener">${o.page ? 'gazetka, s. ' + o.page : 'w sklepie'} ↗</a>` : '<span></span>'}
    ${pmCartBtn(o)}
  </div>`;
}

async function vPromo(main) {
  const d = PM.data = await api('promo?' + qs({ person: F.person }));
  PM.cart = d.cart || [];
  const people = S.people.length > 1 ? `<div class="seg" role="group" aria-label="Osoba"><button class="${F.person ? '' : 'on'}" onclick="F.person=null;render()">Razem</button>` +
    S.people.map(p => `<button class="${F.person === p.id ? 'on' : ''}" onclick="F.person=${p.id};render()"><i class="dot" style="background:${pcolor(p.id)}"></i>${esc(p.name)}</button>`).join('') + '</div>' : '';
  let h = `<div class="bar"><h1>Promocje</h1>${people}</div>`;

  const last = d.last, run = d.running;
  h += `<div class="panel" style="padding:14px 18px"><div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap">
    <div style="flex:1;min-width:260px">${run ? `<span class="spin"></span> Pobieram gazetki${run.step && run.step !== 'start' ? `: <b>${esc(run.step)}</b>` : ''}…`
      : d.last_ok ? `Gazetki pobrane ${fmtWhen(d.last_ok)} · <b>${d.offers_total.toLocaleString('pl-PL')}</b> aktualnych ofert${last && !last.ok ? ` <span class="muted">(ostatnia próba ${fmtWhen(last.at)} nieudana)</span>` : ''}`
      : last ? `Nie udało się pobrać gazetek (${fmtWhen(last.at)}).` : 'Gazetki nie były jeszcze pobierane.'}
      <div class="muted small">Program sam pobiera aktualne i nadchodzące gazetki wybranych sieci (z blix.pl, gdzie sieci publikują swoje gazetki z listą produktów) oraz promocje ze strony lidl.pl, najwyżej co ${12} godzin.</div></div>
    <button class="btn small ${last ? '' : 'primary'}" ${run ? 'disabled' : ''} onclick="pmRefresh()">Pobierz teraz</button></div>
    <div class="stores">${Object.entries(d.all_stores).map(([k, n]) => `<label class="chipbox"><input type="checkbox" ${d.stores.includes(k) ? 'checked' : ''} onchange="pmStores()" value="${k}"> ${esc(n)}</label>`).join('')}</div>
    ${last && last.errors && last.errors.length ? `<div class="note warn" style="margin:10px 0 0;display:block"><b>Nie wszystko udało się pobrać</b><ul style="margin:4px 0 0 18px;padding:0">${last.errors.map(e => `<li class="small">${esc(e)}</li>`).join('')}</ul></div>` : ''}</div>`;

  h += `<div class="panel" id="pmcart">${pmCartHtml()}</div>`;
  h += `<div class="panel"><h2>Szukaj w gazetkach</h2><form onsubmit="event.preventDefault();pmSearch(this.q.value)" style="display:flex;gap:8px">
      <input type="search" name="q" value="${esc(PM.q)}" placeholder="np. masło, kawa Lavazza, pampers" style="flex:1"><button class="btn primary">Szukaj</button></form>
    <div id="pmres">${PM.results ? pmResults() : ''}</div></div>`;

  const mine = d.mine.filter(m => !PM.onlyCheaper || m.cheaper);
  h += `<div class="panel"><h2 style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">Wasze produkty w promocji<span>${d.mine.length} z paragonów z ostatnich 6 miesięcy</span>
      <label class="check" style="margin-left:auto;font-size:13px;display:flex;gap:6px;align-items:center"><input type="checkbox" ${PM.onlyCheaper ? 'checked' : ''} onchange="PM.onlyCheaper=this.checked;render()"> tylko taniej niż zwykle płacicie</label></h2>
    <p class="muted small" style="margin:-6px 0 12px">Produkty kupione co najmniej dwa razy, dopasowane po nazwie z paragonu. Porównaj gramaturę – na paragonie i w gazetce może być inne opakowanie.</p>
    ${mine.length ? mine.map(m => `<div class="pm-item"><div class="pm-head"><div><b style="font-weight:600">${esc(m.name)}</b>
        <div class="muted small">kupione ${m.n}× · zwykle ${m.typical ? zl(m.typical) : '—'}${m.store ? ' w ' + esc(m.store) : ''}</div></div>
        ${m.cheaper ? `<span class="chip good">taniej o ${zl(m.typical - m.best)}</span>` : ''}
        <span class="links small"><a href="${pepper(searchTerm(m.name))}" target="_blank" rel="noopener">Pepper ↗</a> <a href="${ceneo(searchTerm(m.name))}" target="_blank" rel="noopener">Ceneo ↗</a></span></div>
        ${m.offers.slice(0, 4).map(o => offerRow(o, m.typical)).join('')}</div>`).join('')
      : `<div class="empty"><b>${d.offers_total ? 'Brak trafień' : 'Brak gazetek'}</b>${d.offers_total ? (PM.onlyCheaper && d.mine.length ? 'Żaden z Waszych produktów nie jest teraz tańszy niż zwykle. Odznacz filtr, żeby zobaczyć wszystkie promocje.' : 'W bieżących gazetkach nie ma produktów z Waszych paragonów. Dodaj obserwowane produkty poniżej.') : 'Kliknij „Pobierz teraz”.'}</div>`}</div>`;

  h += `<div class="panel"><h2>Obserwowane<span>produkty, na które czekacie</span></h2>
    <form onsubmit="event.preventDefault();pmWatch(this.p.value)" style="display:flex;gap:8px;margin-bottom:12px"><input type="text" name="p" placeholder="np. kawa ziarnista, pampers 4, olej rzepakowy" style="flex:1"><button class="btn">Obserwuj</button></form>
    ${d.watch.length ? d.watch.map(w => `<div class="pm-item"><div class="pm-head"><div><b style="font-weight:600">${esc(w.phrase)}</b><div class="muted small">${w.count ? `${w.count} ${plural(w.count, 'oferta', 'oferty', 'ofert')} w gazetkach` : 'teraz brak w gazetkach'}</div></div>
        <span class="links small"><a href="${pepper(w.phrase)}" target="_blank" rel="noopener">Pepper ↗</a> <a href="${ceneo(w.phrase)}" target="_blank" rel="noopener">Ceneo ↗</a> <button class="btn small" onclick="pmUnwatch(${w.id})">Usuń</button></span></div>
        ${w.offers.slice(0, 6).map(o => offerRow(o, null)).join('')}</div>`).join('') : '<span class="muted small">Nic jeszcze nie obserwujecie.</span>'}</div>`;

  const byStore = {};
  d.leaflets.forEach(l => (byStore[l.store] ||= []).push(l));
  h += `<div class="panel"><h2>Aktualne gazetki</h2>${Object.keys(byStore).length ? `<table class="plan">${Object.entries(byStore).map(([st, ls]) => ls.map((l, i) => `<tr>
      <td>${i ? '' : `<b style="font-weight:600">${esc(st)}</b>`}</td><td>${esc(l.name)}${l.source === 'upload' ? ' <span class="chip">wgrana</span>' : ''}</td><td class="small">${offerDates(l)}${l.start && l.start > new Date().toISOString().slice(0, 10) ? ' <span class="chip warn">nadchodząca</span>' : ''}</td>
      <td class="r small muted">${l.offers || 0} produktów</td><td class="r">${l.url ? `<a class="btn small" href="${esc(l.url)}" target="_blank" rel="noopener">Otwórz ↗</a>` : ''}</td></tr>`).join('')).join('')}</table>`
    : '<span class="muted small">Brak pobranych gazetek.</span>'}</div>`;

  h += `<div class="panel"><h2>Wgraj gazetkę<span>PDF albo zdjęcie – gdy sklepu nie ma na liście</span></h2>
    <form class="form" onsubmit="pmUpload(event)" style="max-width:560px">
      <span style="display:flex;gap:10px"><label style="flex:1">Sklep<input type="text" name="s" list="pmstores" required placeholder="np. Lewiatan"></label>
        <label>Od<input type="date" name="f"></label><label>Do<input type="date" name="t"></label></span>
      <datalist id="pmstores">${Object.values(d.all_stores).map(n => `<option value="${esc(n)}">`).join('')}</datalist>
      <label>Plik<input type="file" name="file" accept=".pdf,image/*" required></label>
      <div class="actions"><button class="btn">Odczytaj gazetkę</button></div></form>
    <p class="muted small">Program odczyta nazwy i ceny tak jak z paragonów i dopasuje je do Waszych produktów. Odczyt gazetek bywa mniej dokładny niż paragonów – sprawdź cenę na stronie gazetki.</p></div>`;

  main.innerHTML = h;
  clearTimeout(PM.poll);
  if (run) PM.poll = setTimeout(() => { if (view === 'promocje') render(); }, 2500);
}
function fmtWhen(s) { const d = s.slice(0, 10), t = s.slice(11, 16), today = new Date().toISOString().slice(0, 10); return d === today ? `dziś o ${t}` : `${fmtDay(d)} o ${t}`; }
function pmResults() {
  const r = PM.results;
  return r.length ? `<div style="margin-top:12px">${r.map(o => offerRow(o, null)).join('')}</div>` : `<p class="muted small" style="margin:12px 0 0">W bieżących gazetkach nie ma „${esc(PM.q)}”. <a href="${pepper(PM.q)}" target="_blank" rel="noopener">Szukaj na Pepper ↗</a> · <a href="${ceneo(PM.q)}" target="_blank" rel="noopener">w sklepach internetowych (Ceneo) ↗</a></p>`;
}
async function pmSearch(q) { PM.q = q.trim(); if (!PM.q) { PM.results = null; return render(); } PM.results = await api('promo/search?' + qs({ q: PM.q })); document.getElementById('pmres').innerHTML = pmResults(); }
async function pmRefresh() { const r = await api('promo/refresh', { body: {} }); if (!r.started) toast('Gazetki już się pobierają.'); render(); }
async function pmStores() {
  const stores = [...document.querySelectorAll('.stores input:checked')].map(i => i.value);
  await api('promo/stores', { body: { stores } }); toast('Zapisano. Kliknij „Pobierz teraz”, żeby pobrać gazetki z nowej listy.');
}
async function pmWatch(p) { try { await api('promo/watch', { body: { phrase: p } }); render(); } catch (e) { toast(e.message); } }
async function pmUnwatch(id) { await api('promo/watch', { body: { remove: id } }); render(); }
async function pmUpload(ev) {
  ev.preventDefault(); const f = ev.target, file = f.file.files[0]; if (!file) return;
  toast('Odczytuję gazetkę…');
  try {
    const r = await api('promo/upload', { method: 'POST', raw: file, headers: { 'X-Filename': encodeURIComponent(file.name), 'X-Store': encodeURIComponent(f.s.value), 'X-From': f.f.value, 'X-To': f.t.value } });
    toast(`Odczytano ${r.count} ${plural(r.count, 'produkt', 'produkty', 'produktów')} z gazetki.`); render();
  } catch (e) { toast(e.message); }
}

// ---------- lista zakupów ----------
function pmCartHtml() {
  const c = PM.cart;
  if (!c.length) return `<h2>Lista zakupów</h2><p class="muted small" style="margin:0">Klikaj <b>+</b> przy ofertach poniżej, żeby zebrać listę zakupów. Potem skopiujesz ją albo wyślesz do Listonic, Przypomnień, Notatek czy innej aplikacji.</p>
    <form onsubmit="event.preventDefault();pmCartOwn(this.n.value);this.reset()" style="display:flex;gap:8px;margin-top:10px"><input type="text" name="n" placeholder="Dopisz coś spoza gazetek, np. chleb" style="flex:1"><button class="btn small">Dopisz</button></form>`;
  const by = pmGroups();
  const sum = c.reduce((a, i) => a + (i.price || 0) * i.qty, 0), unknown = c.filter(i => !i.price).length;
  return `<h2 style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">Lista zakupów<span>${c.length} ${plural(c.length, 'pozycja', 'pozycje', 'pozycji')}${sum ? ` · ok. ${zl(sum)}${unknown ? ' + ' + unknown + ' bez ceny' : ''}` : ''}</span>
      <button class="btn small danger" style="margin-left:auto" onclick="pmCartClear()">Wyczyść</button></h2>
    ${Object.entries(by).map(([st, items]) => `<div class="cart-store"><div class="cart-st">${esc(st)}</div>${items.map(i => `<div class="cart-row">
      <input type="number" min="1" max="99" value="${i.qty}" aria-label="Ilość" onchange="pmCartQty('${esc(i.id)}',this.value)">
      <span class="nm">${esc(i.name)}${i.end ? ` <span class="muted small">· do ${fmtDay(i.end)}</span>` : ''}${i.note ? ` <span class="muted small">· ${esc(i.note)}</span>` : ''}</span>
      <span class="num">${i.price ? zl(i.price * i.qty) : ''}</span>
      <button class="btn small" aria-label="Usuń" onclick="pmCartRemove('${esc(i.id)}')">✕</button></div>`).join('')}</div>`).join('')}
    <form onsubmit="event.preventDefault();pmCartOwn(this.n.value);this.reset()" style="display:flex;gap:8px;margin:10px 0 14px"><input type="text" name="n" placeholder="Dopisz coś spoza gazetek, np. chleb" style="flex:1"><button class="btn small">Dopisz</button></form>
    <div class="export">
      <label class="check" style="display:flex;gap:6px;align-items:center;font-size:13px"><input type="checkbox" ${PM.withInfo ? 'checked' : ''} onchange="PM.withInfo=this.checked;try{localStorage.setItem('pmInfo',this.checked?'1':'0')}catch(e){}"> ze sklepem i ceną</label>
      <button class="btn small primary" onclick="pmCopy('lines')">Kopiuj listę</button>
      <button class="btn small" onclick="pmCopy('comma')" title="Wszystko w jednej linii, po przecinku">Kopiuj w jednej linii</button>
      ${navigator.share ? `<button class="btn small" onclick="pmShare()">Udostępnij…</button>` : ''}
      <a class="btn small" style="text-decoration:none" href="#" onclick="this.href=pmMail();">Wyślij e-mailem</a>
      <button class="btn small" onclick="pmDownload()">Pobierz .txt</button>
    </div>
    <p class="muted small" style="margin:10px 0 0">Listonic nie ma importu z innych programów, więc lista idzie przez schowek: skopiuj ją, otwórz listę w Listonic (na telefonie albo na listonic.com) i wklej w pole dodawania produktu. Jeśli wklei się jako jeden produkt, użyj „Kopiuj w jednej linii” albo wyślij listę e-mailem na telefon i dodawaj z niej. Przypomnienia, Notatki, Google Keep i Todoist dzielą wklejoną listę na osobne pozycje same.</p>`;
}
function pmGroups() {      // sklepy alfabetycznie, dopisane ręcznie na końcu
  const by = {}; [...PM.cart].sort((a, b) => (a.store ? 0 : 1) - (b.store ? 0 : 1) || (a.store || '').localeCompare(b.store || '', 'pl')).forEach(i => (by[i.store || 'Pozostałe'] ||= []).push(i));
  return by;
}
function pmCartText(mode) {
  const by = pmGroups();
  const item = i => (i.qty > 1 ? `${i.qty}× ` : '') + i.name + (PM.withInfo && i.price ? ` (${zl(i.price)}${i.end ? ', do ' + fmtDay(i.end) : ''})` : '');
  if (mode === 'comma') return PM.cart.map(i => (i.qty > 1 ? `${i.qty}× ` : '') + i.name).join(', ');
  if (!PM.withInfo) return PM.cart.map(item).join('\n');
  return Object.entries(by).map(([st, items]) => `${st}:\n` + items.map(item).join('\n')).join('\n\n');
}
async function pmCopy(mode) {
  const t = pmCartText(mode).replace(/\u00a0/g, ' ');
  try { await navigator.clipboard.writeText(t); }
  catch (e) { const ta = document.createElement('textarea'); ta.value = t; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); ta.remove(); }
  toast(mode === 'comma' ? 'Skopiowano listę w jednej linii.' : `Skopiowano ${PM.cart.length} ${plural(PM.cart.length, 'pozycję', 'pozycje', 'pozycji')}. Wklej je w Listonic albo innej aplikacji.`);
}
async function pmShare() { try { await navigator.share({ title: 'Lista zakupów', text: pmCartText('lines').replace(/\u00a0/g, ' ') }); } catch (e) { } }
function pmMail() { return 'mailto:?subject=' + encodeURIComponent('Lista zakupów') + '&body=' + encodeURIComponent(pmCartText('lines').replace(/\u00a0/g, ' ')); }
function pmDownload() {
  const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([pmCartText('lines').replace(/\u00a0/g, ' ')], { type: 'text/plain;charset=utf-8' }));
  a.download = `lista-zakupow-${new Date().toISOString().slice(0, 10)}.txt`; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}
async function pmCartSet(body) {
  try { PM.cart = await api('promo/cart', { body }); } catch (e) { return toast(e.message); }
  document.getElementById('pmcart').innerHTML = pmCartHtml();
  document.querySelectorAll('.cartbtn').forEach(b => { const on = PM.cart.some(c => c.id === b.dataset.oid); b.classList.toggle('on', on); b.textContent = on ? '✓' : '+'; b.title = b.ariaLabel = on ? 'Usuń z listy zakupów' : 'Dodaj do listy zakupów'; });
}
function pmCartToggle(id) {
  if (PM.cart.some(c => c.id === id)) return pmCartSet({ remove: id });
  const o = PM.offers[id]; pmCartSet({ add: { id: o.id, store: o.store, name: o.name, price: o.price, start: o.start, end: o.end, link: o.link, note: o.note } });
}
function pmCartOwn(name) { if (name.trim()) pmCartSet({ add: { name } }); }
function pmCartRemove(id) { pmCartSet({ remove: id }); }
function pmCartQty(id, q) { pmCartSet({ id, qty: +q || 1 }); }
function pmCartClear() { if (confirm('Wyczyścić listę zakupów?')) pmCartSet({ clear: true }); }
