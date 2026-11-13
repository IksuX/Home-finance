"""Budżet domowy – promocje z gazetek dopasowane do produktów, które naprawdę kupujecie.

Źródła (pobierane z komputera użytkownika, najwyżej kilka razy dziennie, z przerwą między zapytaniami):
  - blix.pl – publikuje oficjalne gazetki sieci (Biedronka, Lidl, Kaufland, Netto, Dino…) razem z listą
    produktów i cen z każdej strony; to ten sam materiał co interaktywne gazetki na stronach sklepów,
  - lidl.pl – bieżące promocje spożywcze ze sklepu Lidla (dane, które strona pokazuje w przeglądarce),
  - gazetki wgrane ręcznie (PDF albo zdjęcie) – odczytywane tym samym OCR co paragony.
"""
import gzip, json, re, statistics, threading, time, urllib.parse, urllib.request, zlib
from datetime import date, datetime, timedelta
from html.parser import HTMLParser

import core

SCHEMA = """
CREATE TABLE IF NOT EXISTS promo_offers(id TEXT PRIMARY KEY, source TEXT, store TEXT, name TEXT, brand TEXT, price INTEGER, old_price INTEGER,
  discount INTEGER, start TEXT, end TEXT, page INTEGER, link TEXT, image TEXT, leaflet_id TEXT, note TEXT, fetched TEXT);
CREATE TABLE IF NOT EXISTS promo_leaflets(id TEXT PRIMARY KEY, source TEXT, store TEXT, name TEXT, start TEXT, end TEXT, pages INTEGER, offers INTEGER, url TEXT, fetched TEXT);
CREATE TABLE IF NOT EXISTS promo_watch(id INTEGER PRIMARY KEY, phrase TEXT UNIQUE, created TEXT);
CREATE TABLE IF NOT EXISTS promo_state(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS promo_cart(id TEXT PRIMARY KEY, store TEXT, name TEXT, price INTEGER, start TEXT, end TEXT, link TEXT, note TEXT,
  qty INTEGER DEFAULT 1, added TEXT);
"""

# sklepy na blix.pl: identyfikator w adresie → nazwa; domyślnie włączone te, w których zwykle robi się zakupy spożywcze
STORES = {
    "biedronka": "Biedronka", "lidl": "Lidl", "kaufland": "Kaufland", "netto": "Netto", "dino": "Dino", "auchan": "Auchan",
    "carrefour": "Carrefour", "aldi": "Aldi", "stokrotka": "Stokrotka", "intermarche": "Intermarché", "polomarket": "POLOmarket",
    "lewiatan": "Lewiatan", "zabka": "Żabka", "rossmann": "Rossmann", "hebe": "Hebe", "pepco": "Pepco", "action": "Action",
}
DEFAULT_STORES = ["biedronka", "lidl", "kaufland"]
BLIX = "https://blix.pl"
LIDL_API = "https://www.lidl.pl/q/api/search"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
MAX_LEAFLETS = 8          # na sklep – aktualne i nadchodzące
REFRESH_HOURS = 12
STOP = {"Z", "W", "I", "DO", "NA", "OD", "ZA", "PO", "BEZ", "LUB", "SZT", "OPAK", "PAK", "LUZ", "KG", "G", "ML", "L", "MIX", "WYBRANE", "RODZAJE",
        "RÓŻNE", "ROZNE", "PROMO", "PROM", "NOWOSC", "A", "THE", "OF"}


def ensure(conn):
    conn.executescript(SCHEMA)


def state(conn, key, default=None):
    r = conn.execute("SELECT value FROM promo_state WHERE key=?", (key,)).fetchone()
    return json.loads(r["value"]) if r else default


def set_state(conn, key, value):
    conn.execute("INSERT OR REPLACE INTO promo_state(key,value) VALUES(?,?)", (key, json.dumps(value, ensure_ascii=False)))
    conn.commit()


# ---------------------------------------------------------------- sieć
def _get(url, want_json=False, timeout=30, referer=None):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.6", "Accept-Encoding": "gzip, deflate",
        "Accept": "application/json, text/plain, */*" if want_json else "text/html,application/xhtml+xml,*/*;q=0.8",
        "Referer": referer or (BLIX + "/")})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        enc = (r.headers.get("Content-Encoding") or "").lower()
        if enc == "gzip" or raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        elif enc == "deflate":
            raw = zlib.decompress(raw)
        text = raw.decode(r.headers.get_content_charset() or "utf-8", errors="replace")
    return json.loads(text) if want_json else text


class _Leaflets(HTMLParser):
    def __init__(self):
        super().__init__(); self.items = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "div" and a.get("data-leaflet-id"):
            self.items.append(a)


def blix_leaflet_ids(html, slug):
    p = _Leaflets(); p.feed(html)
    ids = []
    for a in p.items:
        if a.get("data-brand-slug") not in (None, slug) or "leaflet--archival" in (a.get("class") or ""):
            continue
        lid = (a.get("data-leaflet-id") or "").strip()
        if lid.isdigit() and lid not in ids:
            ids.append(lid)
    return ids[:MAX_LEAFLETS]


def _d(v):
    if isinstance(v, dict):
        v = v.get("date")
    return (v or "")[:10] or None


def parse_blix(j, slug):
    v = j.get("viewer") or {}
    lid = str(j.get("id") or "")
    store = (j.get("brand") or {}).get("name") or STORES.get(slug, slug)
    leaflet = dict(id=f"blix:{lid}", source="blix", store=store, name=(v.get("leaflet_name") or "Gazetka").strip(),
                   start=_d(v.get("date_start")), end=_d(v.get("date_end")), pages=len(v.get("pages") or []),
                   offers=len(j.get("productOffers") or []), url=v.get("leaflet_url") or f"{BLIX}/sklep/{slug}/gazetka/{lid}/")
    offers = []
    for o in j.get("productOffers") or []:
        page = int(o.get("pageNumber") or 0) + 1
        name = " ".join((o.get("name") or "").split())
        if not name:
            continue
        price = o.get("price")
        offers.append(dict(id=f"blix:{o.get('productLeafletPageUuid') or f'{lid}-{page}-{name}-{price}'}", source="blix", store=store, name=name,
                           brand=(o.get("brandName") or "").strip() or None, price=int(price) if isinstance(price, (int, float)) and price > 0 else None,
                           old_price=None, discount=int(o.get("percentDiscount") or 0) or None,
                           start=_d(o.get("dateStart")) or leaflet["start"], end=_d(o.get("dateEnd")) or leaflet["end"], page=page,
                           link=f"{BLIX}/sklep/{slug}/gazetka/{lid}/?pageNumber={page}", image=o.get("image") or None, leaflet_id=leaflet["id"], note=None))
    return leaflet, offers


def _zl(v):
    return int(round(float(v) * 100)) if isinstance(v, (int, float)) and v > 0 else None


def parse_lidl_item(item):
    try:
        g = item["gridbox"]["data"]
    except (KeyError, TypeError):
        return None
    root = g.get("price") or {}
    plus = g.get("lidlPlus") or []
    coupon = bool(plus) and root.get("price") is None
    pb = (plus[0].get("price") or {}) if coupon else root
    price, old = _zl(pb.get("price")), _zl(pb.get("oldPrice"))
    if not price or not g.get("fullTitle"):
        return None
    if old and old <= price:
        old = None
    notes = ["z aplikacją Lidl Plus"] if coupon else []
    pack = ((pb.get("packaging") or {}).get("text") or "")
    m = re.search(r"przy zakupie[^.*]{0,25}", pack)
    if m:
        notes.append(m.group(0).strip())
    url = g.get("canonicalUrl") or ""
    return dict(id=f"lidlpl:{g.get('productId') or g.get('erpNumber') or g['fullTitle']}", source="lidl.pl", store="Lidl", name=" ".join(g["fullTitle"].split()),
                brand=(g.get("brand") or {}).get("name") if isinstance(g.get("brand"), dict) else None, price=price, old_price=old,
                discount=(pb.get("discount") or {}).get("percentageDiscount"), start=None, end=None, page=None,
                link=("https://www.lidl.pl" + url) if url.startswith("/") else url or "https://www.lidl.pl", image=g.get("image"), leaflet_id=None,
                note="; ".join(notes) or None)


def fetch_lidl_pl(log):
    out, offset, total = [], 0, None
    while (total is None or offset < total) and offset < 480:
        q = urllib.parse.urlencode({"locale": "pl_PL", "assortment": "PL", "version": "2.1.0", "fetchsize": 48,
                                    "sort": "storeStartDate-desc", "category.id": "10068374", "offset": offset})
        d = _get(f"{LIDL_API}?{q}", want_json=True, referer="https://www.lidl.pl/")
        total = d.get("numFound", 0) if total is None else total
        items = d.get("items") or []
        if not items:
            break
        out += [x for x in (parse_lidl_item(i) for i in items) if x]
        offset += 48
        time.sleep(0.7)
    log(f"lidl.pl: {len(out)} promocji")
    return out



_lock = threading.Lock()


def refresh(connect, stores=None, force=False):
    """Pobiera gazetki w tle. connect() – funkcja otwierająca nowe połączenie z bazą (wątek ma własne)."""
    if not _lock.acquire(blocking=False):
        return False
    def run():
        conn = connect(); ensure(conn)
        msgs, errors = [], []
        log = msgs.append
        try:
            chosen = stores or state(conn, "stores", DEFAULT_STORES)
            set_state(conn, "running", dict(started=datetime.now().isoformat(timespec="seconds"), step="start"))
            today = date.today().isoformat()
            now = datetime.now().isoformat(timespec="seconds")
            got_leaflets, got_offers = [], []
            for slug in chosen:
                name = STORES.get(slug, slug)
                set_state(conn, "running", dict(started=now, step=name))
                try:
                    ids = blix_leaflet_ids(_get(f"{BLIX}/sklep/{slug}/"), slug)
                except Exception as e:
                    errors.append(f"{name}: {_why(e)}"); continue
                if not ids:
                    errors.append(f"{name}: brak aktualnych gazetek na blix.pl"); continue
                n = 0
                for lid in ids:
                    time.sleep(1.0)
                    try:
                        j = _get(f"{BLIX}/getleaflet/{slug}/{lid}/", want_json=True, referer=f"{BLIX}/sklep/{slug}/gazetka/{lid}/")
                    except Exception as e:
                        errors.append(f"{name} {lid}: {_why(e)}"); continue
                    lf, offs = parse_blix(j, slug)
                    if lf["end"] and lf["end"] < today:
                        continue
                    got_leaflets.append(lf); got_offers += offs; n += len(offs)
                log(f"{name}: {len([l for l in got_leaflets if l['store'] == name])} gazetek, {n} produktów")
            if "lidl" in chosen:
                set_state(conn, "running", dict(started=now, step="lidl.pl"))
                try:
                    got_offers += fetch_lidl_pl(log)
                except Exception as e:
                    errors.append(f"lidl.pl: {_why(e)}")
            if got_offers:
                # zastępujemy tylko to, co udało się pobrać; wgrane ręcznie zostają
                srcs = {o["source"] for o in got_offers}
                for s in srcs:
                    conn.execute("DELETE FROM promo_offers WHERE source=?", (s,))
                if got_leaflets:
                    conn.execute("DELETE FROM promo_leaflets WHERE source='blix'")
                for lf in got_leaflets:
                    conn.execute("INSERT OR REPLACE INTO promo_leaflets VALUES(:id,:source,:store,:name,:start,:end,:pages,:offers,:url,:fetched)", dict(lf, fetched=now))
                for o in got_offers:
                    conn.execute("INSERT OR REPLACE INTO promo_offers VALUES(:id,:source,:store,:name,:brand,:price,:old_price,:discount,:start,:end,:page,:link,:image,:leaflet_id,:note,:fetched)",
                                 dict(o, fetched=now))
            conn.execute("DELETE FROM promo_offers WHERE end IS NOT NULL AND end < ?", (today,))
            conn.commit()
            set_state(conn, "last", dict(at=now, ok=bool(got_offers), messages=msgs, errors=errors[:12], offers=len(got_offers)))
            if got_offers:
                set_state(conn, "last_ok", now)
        except Exception as e:
            set_state(conn, "last", dict(at=datetime.now().isoformat(timespec="seconds"), ok=False, messages=msgs, errors=errors + [_why(e)]))
        finally:
            conn.execute("DELETE FROM promo_state WHERE key='running'"); conn.commit(); conn.close()
            _lock.release()
    threading.Thread(target=run, daemon=True).start()
    return True


def _why(e):
    s = str(e)
    if "403" in s or "503" in s:
        return "serwis odmówił pobrania (zabezpieczenie przed robotami) – spróbuj później albo otwórz gazetkę w przeglądarce"
    if "timed out" in s or "urlopen error" in s:
        return "brak połączenia z internetem albo serwis nie odpowiada"
    return s[:160]


def stale(conn):
    last = state(conn, "last")
    return not last or datetime.fromisoformat(last["at"]) < datetime.now() - timedelta(hours=REFRESH_HOURS)


# ---------------------------------------------------------------- dopasowanie
def tokens(text):
    t = core.norm(text or "")
    out = []
    for w in re.findall(r"[A-Z]+|\d+", t):          # „PLASTRY300” → PLASTRY, 300
        if len(w) < 3 or w in STOP or w.isdigit():
            continue
        out.append(w)
    return out


def _tok_eq(p, o):
    """p – słowo z paragonu (często skrócone), o – słowo z gazetki (pełne)."""
    if p == o:
        return True
    if len(p) >= 3 and o.startswith(p):              # skrót z paragonu: „JOG” = „JOGURT”, „TOAL” = „TOALETOWY”
        return True
    if len(p) >= 5 and len(o) >= 5 and abs(len(p) - len(o)) <= 3:     # odmiana: „MASLO”/„MASLA”, „PLASTRY”/„PLASTRACH”
        k = min(len(p), len(o)) - 1
        return p[:k] == o[:k]
    return False


def match_score(product_tokens, offer_tokens):
    """Ułamek słów z nazwy produktu (z paragonu) znalezionych w nazwie z gazetki. Pierwsze słowo produktu (co to jest)
    musi odpowiadać jednemu z dwóch pierwszych słów z gazetki – inaczej „banany” pasowałyby do „batonik bananowy”."""
    if not product_tokens or not offer_tokens:
        return 0
    if not any(_tok_eq(product_tokens[0], o) for o in offer_tokens[:2]):
        return 0
    hit = sum(1 for p in product_tokens if any(_tok_eq(p, o) for o in offer_tokens))
    return hit / len(product_tokens)


def current_offers(conn, store=None):
    today = date.today().isoformat()
    sql = "SELECT * FROM promo_offers WHERE (end IS NULL OR end>=?)"
    args = [today]
    if store:
        sql += " AND store=?"; args.append(store)
    return [dict(r) for r in conn.execute(sql + " ORDER BY start, store, name", args)]


def report(conn, products, person=None):
    """products – wiersze z product_rows (paragony). Zwraca dopasowania dla często kupowanych i obserwowanych."""
    today = date.today().isoformat()
    seen, offers = set(), []
    for o in current_offers(conn):      # ta sama oferta bywa w kilku wersjach gazetki
        k = (o["store"], core.norm(o["name"]), o["price"], o["start"])
        if k in seen:
            continue
        seen.add(k)
        if o["price"] is not None and o["price"] < 30:      # „0,01 zł z kartą” – kupon, nie cena do porównań
            o["note"] = "; ".join(x for x in (o["note"], f"cena {o['price']} gr – zwykle kupon albo gratis przy zakupie") if x)
            o["price"] = None
        o["tok"] = tokens(o["name"]) + [t for t in tokens(o["brand"] or "") if t not in tokens(o["name"])]
        o["upcoming"] = bool(o["start"] and o["start"] > today)
        offers.append(o)
    index = {}
    for o in offers:      # szybkie wyszukiwanie po pierwszych literach głównego słowa
        for t in o["tok"][:2]:
            index.setdefault(t[:3], []).append(o)
    since = (date.today() - timedelta(days=183)).isoformat()
    groups = {}
    for p in products:
        if p["date"] >= since:
            groups.setdefault(p["key"], []).append(p)
    mine = []
    for key, g in groups.items():
        if len(g) < 2:
            continue
        names = [x["name"] for x in g]
        name = max(set(names), key=names.count)
        tok = tokens(name)
        if len(tok) == 0:
            continue
        paid = [x["paid"] for x in g if x["paid"]]
        stores = [x["store"] for x in g if x["store"]]
        hits = []
        for o in {id(x): x for x in index.get(tok[0][:3], [])}.values():
            s = match_score(tok, o["tok"])
            if s >= (0.99 if len(tok) <= 2 else 0.66):
                hits.append(dict({k: v for k, v in o.items() if k != "tok"}, score=round(s, 2)))
        typical = int(statistics.median(paid[-6:])) if paid else None
        hits.sort(key=lambda h: (-h["score"], h["price"] or 10 ** 9))
        top = hits[0]["score"] if hits else 0
        best = min((h["price"] for h in hits if h["price"] and h["score"] == top), default=None)
        mine.append(dict(key=key, name=name, n=len(g), typical=typical, store=max(set(stores), key=stores.count) if stores else None,
                         offers=hits[:8], best=best, cheaper=bool(best and typical and best < typical * 0.97)))
    mine = [m for m in mine if m["offers"]]
    mine.sort(key=lambda m: (not m["cheaper"], -((m["typical"] or 0) - (m["best"] or 0)) * m["n"], -m["n"]))
    watch = []
    for w in conn.execute("SELECT * FROM promo_watch ORDER BY phrase"):
        tok = tokens(w["phrase"])
        hits = [dict({k: v for k, v in o.items() if k != "tok"}) for o in offers
                if tok and all(any(_tok_eq(t, x) for x in o["tok"]) for t in tok)]
        hits.sort(key=lambda h: h["price"] or 10 ** 9)
        watch.append(dict(id=w["id"], phrase=w["phrase"], offers=hits[:12], count=len(hits)))
    leaflets = [dict(r) for r in conn.execute("SELECT * FROM promo_leaflets WHERE end IS NULL OR end>=? ORDER BY store, start", (today,))]
    return dict(mine=mine, watch=watch, leaflets=leaflets, offers_total=len(offers), stores=state(conn, "stores", DEFAULT_STORES),
                all_stores=STORES, last=state(conn, "last"), last_ok=state(conn, "last_ok"), running=state(conn, "running"), stale=stale(conn))


def search(conn, q, limit=60):
    tok = tokens(q)
    if not tok:
        return []
    out = []
    for o in current_offers(conn):
        ot = tokens(f"{o['name']} {o['brand'] or ''}")
        if all(any(_tok_eq(t, x) for x in ot) for t in tok):
            out.append(o)
    out.sort(key=lambda o: o["price"] or 10 ** 9)
    return out[:limit]


# ---------------------------------------------------------------- gazetka wgrana ręcznie
PRICE = re.compile(r"(?<![\d,.])(\d{1,3})[,.](\d{2})(?!\d)")


def from_ocr_rows(rows, store, start=None, end=None, ref="upload"):
    """Z wierszy OCR gazetki: nazwa produktu + najbliższa cena (w tym samym albo następnym wierszu)."""
    offers, pending = [], None
    for i, text in enumerate(rows):
        t = " ".join(text.split())
        prices = PRICE.findall(t)
        name = PRICE.sub(" ", t)
        name = re.sub(r"\b(ZŁ|zł|zl|ZL|/szt\.?|/kg|szt\.?)\b", " ", name)
        name = " ".join(w for w in name.split() if re.search(r"[A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż]{3,}", w))
        if len(tokens(name)) >= 1 and not prices:
            pending = name
            continue
        if prices:
            label = name if len(tokens(name)) >= 1 else pending
            if label:
                vals = sorted(int(a) * 100 + int(b) for a, b in prices)
                offers.append(dict(id=f"{ref}:{i}", source="upload", store=store, name=label[:90], brand=None, price=vals[0],
                                   old_price=vals[-1] if len(vals) > 1 and vals[-1] > vals[0] else None, discount=None,
                                   start=start, end=end, page=None, link=None, image=None, leaflet_id=ref, note="z wgranej gazetki"))
            pending = None
    return offers


# ---------------------------------------------------------------- lista zakupów
def cart(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM promo_cart ORDER BY store, added")]


def cart_change(conn, body):
    if body.get("clear"):
        conn.execute("DELETE FROM promo_cart")
    elif body.get("remove"):
        conn.execute("DELETE FROM promo_cart WHERE id=?", (body["remove"],))
    elif body.get("qty") is not None and body.get("id"):
        q = max(1, min(99, int(body["qty"])))
        conn.execute("UPDATE promo_cart SET qty=? WHERE id=?", (q, body["id"]))
    elif body.get("add"):
        o = body["add"]
        if not (o.get("name") or "").strip():
            raise ValueError("Brak nazwy produktu.")
        oid = o.get("id") or ("own:" + core.norm(o["name"]))
        conn.execute("INSERT OR IGNORE INTO promo_cart(id,store,name,price,start,end,link,note,qty,added) VALUES(?,?,?,?,?,?,?,?,1,?)",
                     (oid, o.get("store") or "", o["name"].strip()[:120], o.get("price"), o.get("start"), o.get("end"), o.get("link"), o.get("note"),
                      datetime.now().isoformat(timespec="seconds")))
    conn.commit()
    return cart(conn)
