"""Budżet domowy – planowanie: wykrywanie powtarzających się płatności, plan wydatków i przychodów, prognoza."""
import calendar, statistics
from datetime import date, timedelta

import core

FREQ = {      # nazwa: (opis, dni, miesiące – gdy powtarza się co miesiąc kalendarzowy)
    "once": ("jednorazowo", 0, 0),
    "weekly": ("co tydzień", 7, 0),
    "biweekly": ("co 2 tygodnie", 14, 0),
    "monthly": ("co miesiąc", 30, 1),
    "bimonthly": ("co 2 miesiące", 61, 2),
    "quarterly": ("co kwartał", 91, 3),
    "halfyear": ("co pół roku", 182, 6),
    "yearly": ("co rok", 365, 12),
}
BANDS = [("weekly", 5, 9), ("biweekly", 12, 17), ("monthly", 25, 36), ("bimonthly", 55, 68), ("quarterly", 80, 102), ("halfyear", 165, 200), ("yearly", 340, 390)]

SCHEMA = """
CREATE TABLE IF NOT EXISTS plans(id INTEGER PRIMARY KEY, name TEXT NOT NULL, amount INTEGER NOT NULL, category_id INTEGER, person_id INTEGER,
  freq TEXT NOT NULL DEFAULT 'once', start TEXT NOT NULL, until TEXT, phrase TEXT, variable INTEGER DEFAULT 0, source TEXT DEFAULT 'manual', note TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS plan_marks(plan_id INTEGER NOT NULL, due TEXT NOT NULL, status TEXT NOT NULL, PRIMARY KEY(plan_id, due));
CREATE TABLE IF NOT EXISTS plan_ignore(key TEXT PRIMARY KEY);
"""


def ensure(conn):
    conn.executescript(SCHEMA)


def add_months(d, k):
    m = d.month - 1 + k
    y, m = d.year + m // 12, m % 12 + 1
    last = calendar.monthrange(y, m)[1]
    return date(y, m, last if d.day == calendar.monthrange(d.year, d.month)[1] and d.day >= 28 else min(d.day, last))


def step(d, freq, n=1):
    _, days, months = FREQ[freq]
    return add_months(d, months * n) if months else d + timedelta(days=days * n)


def occurrences(p, dfrom, dto):
    """Terminy planu w przedziale [dfrom, dto]."""
    start = date.fromisoformat(p["start"])
    until = date.fromisoformat(p["until"]) if p.get("until") else None
    if p["freq"] == "once":
        return [start] if dfrom <= start <= dto else []
    out, n = [], 0
    d = start
    if d < dfrom and not FREQ[p["freq"]][2]:      # przeskok o pełne okresy, żeby nie liczyć od zera przy starych planach
        n = max(0, (dfrom - start).days // FREQ[p["freq"]][1] - 1)
        d = step(start, p["freq"], n)
    while d <= dto and n < 2000:
        if until and d > until:
            break
        if d >= dfrom:
            out.append(d)
        n += 1
        d = step(start, p["freq"], n)      # zawsze od daty startu, żeby 31. dzień nie „uciekał” na 28.
    return out


def _text(t):
    return core.norm(f"{t['counterparty'] or ''} {t['description'] or ''}")


def _budget_txs(conn, dfrom):
    return [dict(r) for r in conn.execute(
        "SELECT t.id,t.date,t.amount,t.description,t.counterparty,t.category_id,a.person_id,c.kind ckind FROM transactions t "
        "JOIN accounts a ON a.id=t.account_id LEFT JOIN categories c ON c.id=t.category_id "
        "WHERE IFNULL(a.kind,'budget') IN ('budget','cash') AND t.pair_id IS NULL AND IFNULL(c.kind,'') != 'transfer' AND t.date>=? ORDER BY t.date", (dfrom,))]


def _matcher(p):
    rx = core.rule_regex(p["phrase"]) if p.get("phrase") and len(core.norm(p["phrase"])) >= 3 else None
    key = core.norm(p["phrase"] or "")
    return lambda t: (t["amount"] > 0) == (p["amount"] > 0) and bool(rx and rx.search(_text(t)) or key and core.merchant(t["description"], t["counterparty"]) == key)


def detect(conn, today=None):
    """Płatności i wpływy, które powtarzają się regularnie u tego samego odbiorcy."""
    today = today or date.today()
    last_tx = conn.execute("SELECT MAX(date) d FROM transactions").fetchone()["d"]
    ref = min(today, date.fromisoformat(last_tx)) if last_tx else today
    txs = _budget_txs(conn, (ref - timedelta(days=550)).isoformat())
    groups = {}
    for t in txs:
        k = core.merchant(t["description"], t["counterparty"])
        if len(k) < 3:
            continue
        g = groups.setdefault((k, t["amount"] > 0), {})
        g.setdefault(t["date"], []).append(t)
    ignored = {r["key"] for r in conn.execute("SELECT key FROM plan_ignore")}
    planned = [_matcher(dict(p)) for p in conn.execute("SELECT * FROM plans WHERE freq!='once'")]
    out = []
    for (k, pos), byday in groups.items():
        days = sorted(byday)
        if len(days) < 2:
            continue
        ds = [date.fromisoformat(d) for d in days]
        gaps = [(b - a).days for a, b in zip(ds, ds[1:])]
        med = statistics.median(gaps)
        band = next((b for b in BANDS if b[1] <= med <= b[2]), None)
        if not band:
            continue
        freq = band[0]
        fit = sum(1 for g in gaps if band[1] <= g <= band[2]) / len(gaps)
        need = 2 if freq in ("halfyear", "yearly") else 3
        if len(ds) < need or fit < 0.7:
            continue
        amounts = [sum(t["amount"] for t in byday[d]) for d in days]
        recent = amounts[-6:]
        typical = int(statistics.median(amounts[-3:]))
        spread = (max(recent) - min(recent)) / abs(typical) if typical else 1
        if freq in ("halfyear", "yearly") and (spread > 0.25 or abs(amounts[-1]) < 2000):      # rzadkie i bardzo różne kwoty – to raczej przypadek
            continue
        if freq in ("weekly", "biweekly") and spread > 0.6:       # cotygodniowe zakupy w sklepie to nie stała płatność
            continue
        period = FREQ[freq][1]
        if (ref - ds[-1]).days > period * 1.6 + 5:      # przestało się powtarzać
            continue
        key = f"{k}|{'+' if pos else '-'}"
        if key in ignored:
            continue
        last_t = byday[days[-1]][-1]
        if any(m(last_t) for m in planned):
            continue
        nxt = step(ds[-1], freq)
        while nxt < ref - timedelta(days=3):
            nxt = step(nxt, freq)
        cats = [t["category_id"] for d in days[-6:] for t in byday[d] if t["category_id"]]
        cp = (last_t["counterparty"] or "").strip()
        nice = " ".join(cp.split()[:3]) if cp and not core.is_processor(cp) and core.norm(cp).startswith(k.split()[0]) else k
        nice = nice.title() if nice.isupper() else nice
        out.append(dict(key=key, name=nice[:40], phrase=k, amount=typical, variable=spread > 0.1, freq=freq, freq_label=FREQ[freq][0],
                        count=len(ds), last=days[-1], next=nxt.isoformat(), min=min(recent), max=max(recent),
                        category_id=max(set(cats), key=cats.count) if cats else None, person_id=last_t["person_id"],
                        monthly=round(typical * 30.4 / period)))
    out.sort(key=lambda s: s["monthly"])      # największe wydatki (najbardziej ujemne) na górze, przychody na końcu
    return out


def report(conn, months=6, person=None, today=None):
    today = today or date.today()
    first = today.replace(day=1)
    horizon = add_months(first, months) - timedelta(days=1)
    last_tx = conn.execute("SELECT MAX(date) d FROM transactions").fetchone()["d"]
    data_to = date.fromisoformat(last_tx) if last_tx else today
    plans = [dict(r) for r in conn.execute("SELECT p.*, c.name category FROM plans p LEFT JOIN categories c ON c.id=p.category_id ORDER BY p.amount")]
    if person:
        plans = [p for p in plans if not p["person_id"] or p["person_id"] == person]
    marks = {(r["plan_id"], r["due"]): r["status"] for r in conn.execute("SELECT * FROM plan_marks")}
    look_back = first - timedelta(days=62)      # zaległe z dwóch poprzednich miesięcy
    txs = _budget_txs(conn, (look_back - timedelta(days=20)).isoformat())
    used, occ = set(), []
    for p in plans:
        match = _matcher(p)
        tol = 15 if p["freq"] == "once" else max(3, min(10, FREQ[p["freq"]][1] // 3))
        cand = [t for t in txs if match(t)] if p.get("phrase") else []
        for d in occurrences(p, look_back, horizon):
            st, paid = marks.get((p["id"], d.isoformat())), None
            if not st:
                best = None
                for t in cand:
                    if t["id"] in used:
                        continue
                    gap = abs((date.fromisoformat(t["date"]) - d).days)
                    if gap > tol:
                        continue
                    if not p["variable"] and abs(t["amount"] - p["amount"]) > abs(p["amount"]) * 0.3:
                        continue
                    if not best or gap < best[0]:
                        best = (gap, t)
                if best:
                    used.add(best[1]["id"]); paid = best[1]; st = "paid"
            if not st:
                st = "overdue" if d < data_to - timedelta(days=tol) and d < today else "due"
            if d < first and st != "overdue":
                continue      # z poprzednich miesięcy pokazujemy tylko zaległe
            occ.append(dict(plan_id=p["id"], name=p["name"], due=d.isoformat(), amount=paid["amount"] if paid else p["amount"], planned=p["amount"],
                            category=p["category"], category_id=p["category_id"], person_id=p["person_id"], status=st, freq=p["freq"],
                            tx=dict(id=paid["id"], date=paid["date"], amount=paid["amount"]) if paid else None))
    occ.sort(key=lambda o: (o["due"], o["amount"]))

    # średnie wydatki spoza planu z 6 pełnych miesięcy – codzienne zakupy, paliwo itd.
    m0 = add_months(first, -6)
    hist = [t for t in _budget_txs(conn, m0.isoformat()) if t["date"] < first.isoformat() and (not person or t["person_id"] == person)]
    have = sorted({t["date"][:7] for t in hist})
    matchers = [_matcher(p) for p in plans if p.get("phrase")]
    unplanned = [t for t in hist if t["amount"] < 0 and (t["ckind"] or "expense") == "expense" and not any(m(t) for m in matchers)]
    unplanned_in = [t for t in hist if t["amount"] > 0 and (t["ckind"] or "income") == "income" and not any(m(t) for m in matchers)]
    def med(rows, sign):      # mediana miesięcznych sum – jeden duży zakup nie zawyża prognozy
        sums = {m: 0 for m in have}
        for t in rows:
            sums[t["date"][:7]] += sign * t["amount"]
        return int(statistics.median(sums.values())) if sums else 0
    avg_out, avg_in = med(unplanned, -1), med(unplanned_in, 1)

    flow = core.budget_flow(conn, first.isoformat(), data_to.isoformat(), person) if data_to >= first else core.budget_flow(conn, data_to.isoformat(), data_to.isoformat(), person)
    money = None if flow["missing"] else flow["end"]
    forecast, run = [], money
    for i in range(months):
        ms = add_months(first, i); key = ms.isoformat()[:7]
        mo = [o for o in occ if o["due"][:7] == key and (not person or not o["person_id"] or o["person_id"] == person)]
        future = [o for o in mo if o["status"] in ("due", "overdue")]      # to, co jeszcze przed nami
        if i == 0:
            future += [o for o in occ if o["due"] < key + "-01" and o["status"] == "overdue" and (not person or not o["person_id"] or o["person_id"] == person)]
        pin = sum(o["amount"] for o in mo if o["amount"] > 0); pout = -sum(o["amount"] for o in mo if o["amount"] < 0)
        fin = sum(o["amount"] for o in future if o["amount"] > 0); fout = -sum(o["amount"] for o in future if o["amount"] < 0)
        # zwykłe wydatki: w bieżącym miesiącu tylko proporcjonalnie do dni, które zostały
        share = 1.0
        if i == 0:
            dim = calendar.monthrange(ms.year, ms.month)[1]
            share = max(0, dim - max(data_to.day if data_to >= ms else 0, 0)) / dim
        rest = int((avg_in - avg_out) * share)      # wpływy i wydatki spoza planu (mediana), netto
        net = fin - fout + rest
        if run is not None:
            run += net
        forecast.append(dict(month=key, plan_in=pin, plan_out=pout, rest=rest, net=pin - pout + avg_in - avg_out, end=run))
    for p in plans:
        nxt = [o for o in occ if o["plan_id"] == p["id"] and o["status"] in ("due", "overdue")]
        p["next"] = nxt[0]["due"] if nxt else None
        p["freq_label"] = FREQ.get(p["freq"], ("?",))[0]
        p["monthly"] = p["amount"] if p["freq"] == "monthly" else (round(p["amount"] * 30.4 / FREQ[p["freq"]][1]) if p["freq"] != "once" else 0)
    return dict(today=today.isoformat(), data_to=data_to.isoformat(), horizon=horizon.isoformat(), plans=plans, occurrences=occ, forecast=forecast,
                money=money, money_missing=flow["missing"], avg_unplanned=avg_out, avg_unplanned_in=avg_in, history_months=len(have),
                suggestions=detect(conn, today), freqs={k: v[0] for k, v in FREQ.items()})


def save(conn, body, oid=None):
    name = (body.get("name") or "").strip()
    amt = int(body.get("amount") or 0)
    start = core.parse_date(body.get("start"))
    freq = body.get("freq") or "once"
    if not name or not amt or not start or freq not in FREQ:
        raise ValueError("Podaj nazwę, kwotę i datę.")
    until = core.parse_date(body.get("until")) if body.get("until") else None
    vals = (name, amt, body.get("category_id") or None, body.get("person_id") or None, freq, start, until,
            core.norm(body.get("phrase") or "") or None, 1 if body.get("variable") else 0, body.get("source") or "manual", (body.get("note") or "").strip() or None)
    if oid:
        conn.execute("UPDATE plans SET name=?,amount=?,category_id=?,person_id=?,freq=?,start=?,until=?,phrase=?,variable=?,source=?,note=? WHERE id=?", vals + (oid,))
    else:
        oid = conn.execute("INSERT INTO plans(name,amount,category_id,person_id,freq,start,until,phrase,variable,source,note,created) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                           vals + (date.today().isoformat(),)).lastrowid
    conn.commit()
    return oid
