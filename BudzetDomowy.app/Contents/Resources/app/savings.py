"""Budżet domowy – gdzie można zaoszczędzić. Wszystko liczone lokalnie z wyciągów i paragonów.

Każda sugestia ma szacunek miesięcznej oszczędności (w groszach) i poziom pewności:
  "pewne"   – konkretna kwota, którą da się po prostu przestać płacić (opłata, abonament),
  "możliwe" – wymaga zmiany nawyku (mniej jedzenia na mieście, tańszy sklep).
"""
import calendar, statistics
from datetime import date, timedelta

import core
import plan

# kategorie, w których zwykle da się coś przyciąć bez rezygnowania z rzeczy niezbędnych
FLEXIBLE = ["Restauracje i kawiarnie", "Słodycze i przekąski", "Alkohol", "Napoje", "Zakupy online", "Odzież i obuwie",
            "Rozrywka i kultura", "Elektronika", "Kosmetyki i higiena", "Dom i ogród", "Podróże", "Inne wydatki", "Gotówka"]
# stałe zobowiązania – rosną, ale „przyciąć 20%” nie ma sensu; tu szukamy podwyżek i dublujących się usług
FIXED = ["Mieszkanie", "Kredyty i raty", "Podatki i urzędy", "Ubezpieczenia", "Rachunki i media", "Subskrypcje", "Sport", "Edukacja", "Dzieci", "Zdrowie"]
RECURRING_CATS = {"Subskrypcje", "Rachunki i media", "Sport", "Rozrywka i kultura", "Ubezpieczenia", "Opłaty bankowe", "Edukacja", "Zakupy online", "Inne wydatki", None}
SMALL = 3000          # „drobny” wydatek: do 30 zł
PERIOD = 12           # ile pełnych miesięcy analizujemy


def _month_add(d, k):
    m = d.month - 1 + k
    return date(d.year + m // 12, m % 12 + 1, 1)


def _r50(v):
    """Zaokrąglenie limitu do 50 zł w dół – limity „ładne” łatwiej zapamiętać."""
    return max(0, int(v // 5000) * 5000)


def analyze(conn, person=None, products=None, today=None):
    today = today or date.today()
    last_tx = conn.execute("SELECT MAX(date) d FROM transactions").fetchone()["d"]
    if not last_tx:
        return dict(empty=True)
    data_to = min(today, date.fromisoformat(last_tx))
    # pełne miesiące: jeśli wyciągi kończą się pod koniec miesiąca, ten miesiąc też się liczy
    end = data_to.replace(day=1) if data_to.day < calendar.monthrange(data_to.year, data_to.month)[1] - 2 else _month_add(data_to, 1)
    start = _month_add(end, -PERIOD)
    first_tx = conn.execute("SELECT MIN(date) d FROM transactions").fetchone()["d"]
    if first_tx and first_tx[:7] > start.isoformat()[:7]:
        start = _month_add(date.fromisoformat(first_tx), 1 if first_tx[8:] > "05" else 0)
    months = []
    m = start
    while m < end:
        months.append(m.isoformat()[:7]); m = _month_add(m, 1)
    if len(months) < 2:
        return dict(empty=True, reason="Za mało danych – potrzeba wyciągów z co najmniej dwóch pełnych miesięcy.")
    n = len(months)
    recent = months[-3:]

    txs = [t for t in plan._budget_txs(conn, start.isoformat()) if t["date"][:7] in months and (not person or t["person_id"] == person)]
    cats = {r["id"]: dict(r) for r in conn.execute("SELECT id,name,kind,budget FROM categories")}
    cname = lambda cid: cats[cid]["name"] if cid in cats else None

    income = sum(t["amount"] for t in txs if t["amount"] > 0 and (t["ckind"] or "income") == "income")
    expense = -sum(t["amount"] for t in txs if t["amount"] < 0 and (t["ckind"] or "expense") == "expense")
    refunds = sum(t["amount"] for t in txs if t["amount"] > 0 and cname(t["category_id"]) == "Zwroty")
    exp = [t for t in txs if t["amount"] < 0 and (t["ckind"] or "expense") == "expense"]

    per_cat = {}
    for t in exp:
        c = per_cat.setdefault(t["category_id"], {m: 0 for m in months})
        c[t["date"][:7]] -= t["amount"]

    out = []

    # 1. Stałe opłaty i subskrypcje – lista do przejrzenia, z podwyżkami
    recurring = []
    for s in plan.detect(conn, today, everything=True):
        if s["amount"] >= 0 or (person and s["person_id"] != person):
            continue
        cat = cname(s["category_id"])
        if cat not in RECURRING_CATS:
            continue      # czynszu, raty czy przedszkola nie „wyłączymy” jednym kliknięciem
        hist = [a for _, a in s["history"]]
        older = hist[:-3]
        rise = None
        if len(older) >= 2 and not s["variable"]:
            base = statistics.median(older)
            if base and (s["amount"] - base) / abs(base) <= -0.05:      # kwoty są ujemne: bardziej ujemna = droższa
                since = next((d for d, a in s["history"] if a <= base * 1.03), s["last"])      # pierwsza wyższa płatność
                rise = dict(before=-int(base), now=-s["amount"], since=since)
        recurring.append(dict(name=s["name"], phrase=s["phrase"], category=cat or "bez kategorii", category_id=s["category_id"],
                              freq=s["freq_label"], amount=-s["amount"], monthly=-s["monthly"], yearly=-s["monthly"] * 12,
                              variable=s["variable"], last=s["last"], count=s["count"], rise=rise, person_id=s["person_id"]))
    recurring.sort(key=lambda r: -r["monthly"])
    subs = [r for r in recurring if r["category"] == "Subskrypcje"]
    if recurring:
        rises = [r for r in recurring if r["rise"]]
        out.append(dict(id="recurring", kind="list", title="Stałe opłaty i subskrypcje",
                        lead=f"{len(recurring)} regularnych płatności, razem ok. {sum(r['monthly'] for r in recurring) / 100:.0f} zł miesięcznie. "
                             "Zaznacz te, z których możesz zrezygnować albo które da się zmienić na tańsze – kwota trafi do podsumowania na górze."
                             + (f" {len(subs)} subskrypcji – warto sprawdzić, czy korzystacie z każdej." if len(subs) >= 3 else "")
                             + (f" {len(rises)} {'płatność podrożała' if len(rises) == 1 else 'płatności podrożały'} w ostatnich miesiącach." if rises else ""),
                        items=recurring, confidence="pewne"))

    # 2. Kategorie elastyczne – limit o 10–30% niższy niż typowy miesiąc
    flex = []
    for cid, ms in per_cat.items():
        name = cname(cid) or "Bez kategorii"
        if name not in FLEXIBLE and cid is not None:
            continue
        vals = [ms[m] for m in months]
        avg, med, last3 = sum(vals) / n, statistics.median(vals), sum(ms[m] for m in recent) / len(recent)
        if avg < 10000:      # poniżej 100 zł miesięcznie szkoda zachodu
            continue
        typical = max(med, avg * 0.8)      # przy rzadkich dużych wydatkach (wyjazdy) mediana to prawie zero – wtedy średnia
        merchants = {}
        for t in exp:
            if t["category_id"] == cid:
                k = core.merchant(t["description"], t["counterparty"]) or "?"
                mm = merchants.setdefault(k, [0, 0]); mm[0] -= t["amount"]; mm[1] += 1
        top = sorted(merchants.items(), key=lambda kv: -kv[1][0])[:4]
        flex.append(dict(category_id=cid, category=name, avg=int(avg), median=int(med), last3=int(last3), typical=int(typical),
                         budget=cats[cid]["budget"] if cid in cats else 0, trend=(last3 - avg) / avg if avg else 0,
                         count=sum(1 for t in exp if t["category_id"] == cid) / n,
                         top=[dict(name=k.title()[:30], amount=int(v[0] / n), n=round(v[1] / n, 1)) for k, v in top],
                         months=[ms[m] for m in months]))
    flex.sort(key=lambda f: -f["typical"])
    if flex:
        out.append(dict(id="flex", kind="cut", title="Wydatki, które da się ograniczyć",
                        lead="Kategorie bez stałych zobowiązań. Wybierz, o ile chcesz je przyciąć – program zaproponuje miesięczny limit "
                             "i pokaże go w Przeglądzie. Wyliczenie startuje od typowego miesiąca (mediana), więc jednorazowe duże zakupy go nie zawyżają.",
                        items=flex, confidence="możliwe"))

    # 3. Rosnące wydatki – ostatnie 3 miesiące wyraźnie powyżej średniej
    growth = []
    for cid, ms in per_cat.items():
        name = cname(cid) or "Bez kategorii"
        vals = [ms[m] for m in months[:-3]] or [0]
        before, last3 = sum(vals) / len(vals), sum(ms[m] for m in recent) / len(recent)
        if len(months) >= 6 and last3 - before > 15000 and (before == 0 or (last3 - before) / before > 0.25):
            growth.append(dict(category_id=cid, category=name, before=int(before), last3=int(last3), diff=int(last3 - before),
                               pct=round((last3 - before) / before * 100) if before else None, fixed=name in FIXED))
    growth.sort(key=lambda g: -g["diff"])
    if growth:
        out.append(dict(id="growth", kind="info", title="Co ostatnio rośnie",
                        lead=f"Ostatnie 3 miesiące w porównaniu z wcześniejszymi {len(months) - 3}. Wzrost nie musi być zły (np. sezonowe opłaty), "
                             "ale to pierwsze miejsca, w które warto zajrzeć.", items=growth[:8], confidence="możliwe"))

    # 4. Drobne, częste zakupy
    small = [t for t in exp if -t["amount"] <= SMALL and (cname(t["category_id"]) not in RECURRING_CATS | {"Transport", "Zdrowie", "Paliwo", "Dzieci", "Edukacja"}
                                                         or cname(t["category_id"]) in (None, "Inne wydatki", "Zakupy online"))]
    if small:
        by = {}
        for t in small:
            k = core.merchant(t["description"], t["counterparty"]) or "?"
            b = by.setdefault(k, [0, 0, cname(t["category_id"])]); b[0] -= t["amount"]; b[1] += 1
        monthly = -sum(t["amount"] for t in small) / n
        if monthly >= 15000:
            top = sorted(by.items(), key=lambda kv: -kv[1][0])[:6]
            out.append(dict(id="small", kind="habit", title="Drobne zakupy",
                            lead=f"Płatności do {SMALL // 100} zł: średnio {len(small) / n:.0f} w miesiącu, razem ok. {monthly / 100:.0f} zł. "
                                 "Pojedynczo nie bolą, ale w roku to " + f"{monthly * 12 / 100:,.0f}".replace(",", " ") + " zł. "
                                 "Zaplanowane większe zakupy raz w tygodniu zwykle ograniczają takie wydatki o jedną trzecią.",
                            monthly=int(monthly), count=round(len(small) / n), save=int(monthly * 0.3),
                            items=[dict(name=k.title()[:30], category=v[2], amount=int(v[0] / n), n=round(v[1] / n, 1)) for k, v in top],
                            confidence="możliwe"))

    # 5. Opłaty bankowe (po odjęciu zwrotów tych opłat)
    fees = [t for t in exp if cname(t["category_id"]) == "Opłaty bankowe"]
    if fees:
        paid = -sum(t["amount"] for t in fees)
        back = sum(t["amount"] for t in txs if t["amount"] > 0 and "OPLAT" in core.norm(t["description"] or "") and "ZWROT" in core.norm(t["description"] or ""))
        net = paid - back
        if net > 1000 * n / 12:
            by = {}
            for t in fees:
                k = core.norm((t["description"] or "")[:40]) or "?"
                by[k] = by.get(k, 0) - t["amount"]
            out.append(dict(id="fees", kind="fixed", title="Opłaty bankowe",
                            lead=f"W {n} {'miesiącach' if n > 4 else 'miesiące'} {paid / 100:.0f} zł opłat" + (f", z czego {back / 100:.0f} zł wróciło" if back else "")
                                 + ". Większość banków ma konta bez opłat albo zwalnia z nich po spełnieniu warunków (wpływy, płatności kartą).",
                            save=int(net / n), items=[dict(name=k.title(), amount=v) for k, v in sorted(by.items(), key=lambda kv: -kv[1])[:5]],
                            confidence="pewne"))

    # 6. Tańsze zakupy – te same produkty taniej w innym sklepie (z paragonów)
    if products:
        cutoff = start.isoformat()
        rows = [p for p in products if p["date"] >= cutoff]
        prods = {}
        for p in rows:
            prods.setdefault(p["key"], []).append(p)
        cheaper = []
        for key, g in prods.items():
            if len(g) < 3:
                continue
            by_store = {}
            for p in g:
                st = (p["store"] or "?").strip()
                s = by_store.setdefault(st, [0, 0]); s[0] += p["paid"] * p["qty"]; s[1] += p["qty"]
            if len(by_store) < 2:
                continue
            avg = {st: v[0] / v[1] for st, v in by_store.items() if v[1]}
            best = min(avg, key=avg.get)
            qty = sum(p["qty"] for p in g)
            paid_avg = sum(p["paid"] * p["qty"] for p in g) / qty
            if paid_avg <= 0 or (paid_avg - avg[best]) / paid_avg < 0.1:
                continue
            names = [p["name"] for p in g]
            cheaper.append(dict(name=max(set(names), key=names.count), best_store=best, best=int(avg[best]), avg=int(paid_avg),
                                stores={k: int(v) for k, v in avg.items()}, qty=round(qty, 2),
                                save=int((paid_avg - avg[best]) * qty / n)))
        cheaper.sort(key=lambda c: -c["save"])
        if cheaper:
            out.append(dict(id="cheaper", kind="shop", title="Te same produkty taniej",
                            lead="Z paragonów: produkty kupowane co najmniej 3 razy, które w innym sklepie wychodziły wyraźnie taniej (cena po rabatach).",
                            items=cheaper[:12], save=sum(c["save"] for c in cheaper[:12]), confidence="możliwe"))

    monthly_exp = {m: 0 for m in months}; monthly_inc = {m: 0 for m in months}
    for t in txs:
        if t["amount"] < 0 and (t["ckind"] or "expense") == "expense":
            monthly_exp[t["date"][:7]] -= t["amount"]
        elif t["amount"] > 0 and (t["ckind"] or "income") == "income":
            monthly_inc[t["date"][:7]] += t["amount"]
    return dict(empty=False, months=months, n=n, expense_median=int(statistics.median(monthly_exp.values())),
                income_median=int(statistics.median(monthly_inc.values())), monthly=[dict(month=m, income=monthly_inc[m], expense=monthly_exp[m]) for m in months], income=int(income / n), expense=int(expense / n), refunds=int(refunds / n),
                net=int((income - expense) / n), rate=round((income - expense) / income * 100, 1) if income else None,
                data_to=data_to.isoformat(), sections=out)
