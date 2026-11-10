"""Budżet domowy – baza danych, import wyciągów, kategoryzacja, analiza."""
import csv, hashlib, io, os, re, sqlite3, unicodedata
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

VERSION = "0.1.0"
DATA_DIR = os.environ.get("BUDZET_DATA") or os.path.expanduser("~/Library/Application Support/BudzetDomowy")
DB_PATH = os.path.join(DATA_DIR, "budzet.db")
RECEIPT_DIR = os.path.join(DATA_DIR, "paragony")

SCHEMA = """
CREATE TABLE IF NOT EXISTS people(id INTEGER PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS accounts(id INTEGER PRIMARY KEY, bank TEXT, label TEXT, person_id INTEGER, UNIQUE(bank,label));
CREATE TABLE IF NOT EXISTS categories(id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, kind TEXT NOT NULL, budget INTEGER DEFAULT 0, sort INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS rules(id INTEGER PRIMARY KEY, pattern TEXT NOT NULL, category_id INTEGER NOT NULL, sign INTEGER DEFAULT 0, user INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS item_rules(name TEXT PRIMARY KEY, category_id INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS imports(id INTEGER PRIMARY KEY, filename TEXT, bank TEXT, created TEXT, added INTEGER, duplicates INTEGER);
CREATE TABLE IF NOT EXISTS transactions(id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL, date TEXT NOT NULL, amount INTEGER NOT NULL,
  currency TEXT DEFAULT 'PLN', description TEXT, counterparty TEXT, bank_category TEXT, category_id INTEGER, cat_source TEXT,
  hash TEXT UNIQUE, import_id INTEGER, note TEXT);
CREATE INDEX IF NOT EXISTS tx_date ON transactions(date);
CREATE TABLE IF NOT EXISTS receipts(id INTEGER PRIMARY KEY, date TEXT, store TEXT, total INTEGER DEFAULT 0, payment TEXT, person_id INTEGER,
  transaction_id INTEGER, file TEXT, preview TEXT, ocr_text TEXT, engine TEXT, created TEXT, checked INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS receipt_items(id INTEGER PRIMARY KEY, receipt_id INTEGER NOT NULL, name TEXT, qty REAL DEFAULT 1,
  unit_price INTEGER DEFAULT 0, amount INTEGER DEFAULT 0, category_id INTEGER, pos INTEGER DEFAULT 0);
"""

# (nazwa, rodzaj): expense = wydatek, income = przychód, transfer = nie liczy się do budżetu
CATEGORIES = [
    ("Zakupy spożywcze", "expense"), ("Napoje", "expense"), ("Słodycze i przekąski", "expense"), ("Alkohol", "expense"),
    ("Chemia domowa", "expense"), ("Kosmetyki i higiena", "expense"), ("Restauracje i kawiarnie", "expense"),
    ("Mieszkanie", "expense"), ("Rachunki i media", "expense"), ("Paliwo", "expense"), ("Transport", "expense"),
    ("Samochód", "expense"), ("Zdrowie", "expense"), ("Dzieci", "expense"), ("Zwierzęta", "expense"),
    ("Odzież i obuwie", "expense"), ("Dom i ogród", "expense"), ("Elektronika", "expense"), ("Zakupy online", "expense"),
    ("Subskrypcje", "expense"), ("Rozrywka i kultura", "expense"), ("Sport", "expense"), ("Edukacja", "expense"),
    ("Podróże", "expense"), ("Ubezpieczenia", "expense"), ("Kredyty i raty", "expense"), ("Podatki i urzędy", "expense"),
    ("Opłaty bankowe", "expense"), ("Gotówka", "expense"), ("Darowizny", "expense"), ("Inne wydatki", "expense"),
    ("Wynagrodzenie", "income"), ("Świadczenia", "income"), ("Zwroty", "income"), ("Inne przychody", "income"),
    ("Przelewy wewnętrzne", "transfer"), ("Oszczędności i inwestycje", "transfer"),
]

RULES = {  # kategoria: wzorce po przecinku (bez polskich znaków, wielkie litery; dopasowanie od początku słowa)
    "Zakupy spożywcze": "BIEDRONKA,LIDL,KAUFLAND,AUCHAN,CARREFOUR,ZABKA,DINO,STOKROTKA,NETTO,ALDI,LEWIATAN,SPOLEM,INTERMARCHE,DELIKATESY,PIEKARNIA,FRISCO,POLOMARKET,TOPAZ,GROSZEK,FRESHMARKET,MAKRO,SELGROS,SPAR,WARZYWNIAK,MASARNIA",
    "Restauracje i kawiarnie": "MCDONALD,KFC,PIZZ,RESTAURAC,PYSZNE,GLOVO,UBER EATS,UBER *EATS,WOLT,STARBUCKS,COSTA COFFEE,KEBAB,BURGER,SUSHI,KAWIARNIA,CAFE,BISTRO,CUKIERNIA,LODZIARNIA",
    "Paliwo": "ORLEN,SHELL,CIRCLE K,LOTOS,MOYA,AMIC,STACJA PALIW,BP ",
    "Transport": "PKP,INTERCITY,KOLEJE,MPK,ZTM,UBER,BOLT,FREENOW,JAKDOJADE,PARKING,AUTOSTRAD,KOLEO,FLIXBUS,SKYCASH,MOBILET",
    "Samochód": "WARSZTAT,WULKANIZ,AUTO SERWIS,MYJNIA,INTERCARS,STACJA KONTROLI",
    "Mieszkanie": "CZYNSZ,SPOLDZIELNIA,WSPOLNOTA,NAJEM",
    "Rachunki i media": "TAURON,PGE,ENEA,ENERGA,PGNIG,WODOCIAG,ORANGE,T-MOBILE,UPC,VECTRA,NETIA,INEA,ABONAMENT RTV,P4 SP,POLKOMTEL,ODPADY,SMIECI",
    "Zdrowie": "APTEKA,DOZ,GEMINI,MEDICOVER,LUXMED,LUX MED,ENEL-MED,PRZYCHODNIA,STOMATOLOG,DENTYST,LEKARZ,ZIKO,SUPER-PHARM,SUPERPHARM,DIAGNOSTYKA",
    "Kosmetyki i higiena": "ROSSMANN,HEBE,DOUGLAS,SEPHORA,DM DROGERIE,FRYZJER",
    "Odzież i obuwie": "ZARA,H&M,RESERVED,CCC,DEICHMANN,ZALANDO,SINSAY,CROPP,MOHITO,VINTED,HALFPRICE,TK MAXX,EOBUWIE",
    "Dom i ogród": "IKEA,CASTORAMA,LEROY,OBI,JYSK,BRICO,ACTION,PEPCO,TEDI",
    "Elektronika": "MEDIA EXPERT,RTV EURO,MEDIA MARKT,X-KOM,MORELE,KOMPUTRONIK",
    "Zakupy online": "ALLEGRO,AMAZON,ALIEXPRESS,TEMU,INPOST,EMPIK",
    "Subskrypcje": "NETFLIX,SPOTIFY,HBO,DISNEY,YOUTUBE,APPLE.COM,ICLOUD,GOOGLE,MICROSOFT,ADOBE,CANAL+,AMAZON PRIME,OPENAI,ANTHROPIC,CLAUDE.AI",
    "Rozrywka i kultura": "KINO,CINEMA,MULTIKINO,HELIOS,TEATR,MUZEUM,EVENTIM,STEAM,PLAYSTATION,BILETY",
    "Sport": "SILOWNIA,FITNESS,BASEN,MULTISPORT,DECATHLON",
    "Dzieci": "PRZEDSZKOL,ZLOBEK,SMYK,ZABAWK",
    "Edukacja": "UDEMY,KSIEGARNIA,SZKOLA,CZESNE",
    "Podróże": "BOOKING,AIRBNB,RYANAIR,WIZZ,HOTEL,NOCLEG",
    "Ubezpieczenia": "PZU,WARTA,ALLIANZ,UBEZPIECZ,POLISA,LINK4,GENERALI,HESTIA",
    "Kredyty i raty": "KREDYT,LEASING,SPLATA RATY,RATA ",
    "Podatki i urzędy": "URZAD SKARBOWY,ZUS,PODATEK,OPLATA SKARBOWA",
    "Opłaty bankowe": "PROWIZJA,OPLATA ZA KARTE,OPLATA ZA PROWADZENIE,ODSETKI",
    "Gotówka": "WYPLATA GOTOWKI,WYPLATA Z BANKOMATU,WYPLATA W BANKOMACIE,BANKOMAT,EURONET,PLANET CASH",
    "Darowizny": "DAROWIZNA,OFIARA,FUNDACJA,SIEPOMAGA,ZRZUTKA",
    "Przelewy wewnętrzne": "PRZELEW WLASNY,PRZELEW WEWNETRZNY",
    "Oszczędności i inwestycje": "LOKATA,KONTO OSZCZEDNOSCIOWE,CEL OSZCZEDNOSCIOWY,XTB,IKZE,OBLIGACJE",
}
INCOME_RULES = {
    "Wynagrodzenie": "WYNAGRODZENIE,PENSJA,PREMIA,UMOWA O PRACE,UMOWA ZLECENI",
    "Świadczenia": "800+,500+,ZASILEK,SWIADCZENIE,ZUS",
    "Zwroty": "ZWROT",
}
BANK_CATEGORY_MAP = {  # kategorie nadawane przez mBank -> nasze
    "ZYWNOSC": "Zakupy spożywcze", "JEDZENIE POZA DOMEM": "Restauracje i kawiarnie", "PALIWO": "Paliwo",
    "PRZEJAZDY": "Transport", "ZDROWIE": "Zdrowie", "ODZIEZ": "Odzież i obuwie", "WYPLATA GOTOWKI": "Gotówka",
    "CZYNSZ": "Mieszkanie", "ELEKTRONIKA": "Elektronika", "ROZRYWKA": "Rozrywka i kultura", "PODROZE": "Podróże",
    "WYNAGRODZENIE": "Wynagrodzenie", "UBEZPIECZENIA": "Ubezpieczenia", "PODATKI": "Podatki i urzędy",
    "CHEMIA": "Chemia domowa", "KOSMETYKI": "Kosmetyki i higiena", "MULTIMEDIA": "Subskrypcje", "SPORT": "Sport",
    "AUTO": "Samochód", "WYPOSAZENIE": "Dom i ogród", "EDUKACJA": "Edukacja", "OPLATY I ODSETKI": "Opłaty bankowe",
    "TV, INTERNET, TELEFON": "Rachunki i media", "ENERGIA": "Rachunki i media", "WODA, GAZ": "Rachunki i media",
}


def norm(s):
    s = (s or "").upper().replace("Ł", "L")
    s = unicodedata.normalize("NFKD", s)
    return re.sub(r"\s+", " ", "".join(c for c in s if not unicodedata.combining(c))).strip()


def connect():
    os.makedirs(RECEIPT_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = connect()
    conn.executescript(SCHEMA)
    if not conn.execute("SELECT 1 FROM categories LIMIT 1").fetchone():
        for i, (name, kind) in enumerate(CATEGORIES):
            conn.execute("INSERT INTO categories(name,kind,sort) VALUES(?,?,?)", (name, kind, i))
        ids = {r["name"]: r["id"] for r in conn.execute("SELECT id,name FROM categories")}
        for src, sign in ((RULES, 0), (INCOME_RULES, 1)):
            for cat, spec in src.items():
                for pat in spec.split(","):
                    if pat.strip():
                        conn.execute("INSERT INTO rules(pattern,category_id,sign,user) VALUES(?,?,?,0)", (pat, ids[cat], sign))
    conn.commit()
    return conn


def cat_id(conn, name):
    r = conn.execute("SELECT id FROM categories WHERE name=?", (name,)).fetchone()
    return r["id"] if r else None


# ---------- kategoryzacja ----------
class Categorizer:
    def __init__(self, conn):
        self.rules = []
        for r in conn.execute("SELECT pattern,category_id,sign,user FROM rules"):
            base = norm(r["pattern"])
            if base:
                rx = re.compile(r"(?<![A-Z0-9])" + re.escape(base).replace(r"\ ", r"\s+")
                                + (r"(?![A-Z0-9])" if r["pattern"].endswith(" ") else ""))
                self.rules.append((r["user"], len(base), rx, r["category_id"], r["sign"]))
        self.rules.sort(key=lambda x: (-x[0], -x[1], -abs(x[4])))
        self.bankmap = {k: cat_id(conn, v) for k, v in BANK_CATEGORY_MAP.items()}

    def match(self, text, amount=0, bank_category=None):
        t = norm(text)
        for user, _, rx, cid, sign in self.rules:
            if sign and (amount > 0) != (sign > 0):
                continue
            if rx.search(t):
                return cid, "rule"
        b = self.bankmap.get(norm(bank_category))
        return (b, "bank") if b else (None, None)


def recategorize(conn, only_auto=True):
    """Przelicza kategorie transakcji, których użytkownik nie ustawił ręcznie."""
    c = Categorizer(conn)
    n = 0
    for r in conn.execute("SELECT id,description,counterparty,amount,bank_category,category_id FROM transactions "
                          "WHERE cat_source IS NULL OR cat_source IN ('rule','bank')").fetchall():
        cid, src = c.match(f"{r['counterparty'] or ''} {r['description'] or ''}", r["amount"], r["bank_category"])
        if cid != r["category_id"]:
            conn.execute("UPDATE transactions SET category_id=?, cat_source=? WHERE id=?", (cid, src, r["id"]))
            n += 1
    conn.commit()
    return n


def detect_internal(conn):
    """Paruje przelewy między własnymi kontami (ta sama kwota, przeciwny znak, do 3 dni różnicy)."""
    internal = cat_id(conn, "Przelewy wewnętrzne")
    if not internal:
        return 0
    rows = conn.execute("SELECT id,account_id,date,amount,description FROM transactions "
                        "WHERE (cat_source IS NULL OR cat_source IN ('rule','bank')) AND (category_id IS NULL OR category_id!=?)", (internal,)).fetchall()
    ins = {}
    for r in rows:
        if r["amount"] > 0:
            ins.setdefault(r["amount"], []).append(r)
    n = 0
    used = set()
    for r in rows:
        if r["amount"] >= 0 or "KART" in norm(r["description"]):
            continue
        d = date.fromisoformat(r["date"])
        for c in ins.get(-r["amount"], []):
            if c["id"] in used or c["account_id"] == r["account_id"]:
                continue
            if abs((date.fromisoformat(c["date"]) - d).days) <= 3:
                used.add(c["id"])
                conn.execute("UPDATE transactions SET category_id=?, cat_source='transfer' WHERE id IN (?,?)", (internal, r["id"], c["id"]))
                n += 1
                break
    conn.commit()
    return n


def merchant(description, counterparty=""):
    """Krótka nazwa sprzedawcy do zestawień i podpowiedzi reguł."""
    t = norm(counterparty) or norm(description)
    t = re.sub(r"ZAKUP PRZY UZYCIU KARTY( W KRAJU| ZA GRANICA| - INTERNET)?|PLATNOSC KARTA|TRANSAKCJA KARTA|PLATNOSC BLIK|ZAKUP BLIK|BLIK|PRZELEW (ZEWNETRZNY |WEWNETRZNY )?(PRZYCHODZACY|WYCHODZACY)?|ZLECENIE STALE|POLECENIE ZAPLATY|SP\.? ?Z ?O\.? ?O\.?|S\.A\.|DATA TRANSAKCJI.*", " ", t)
    t = re.sub(r"\d{2}[.-]\d{2}[.-]\d{2,4}|\d{4}-\d{2}-\d{2}|\b\d{3,}\b|[*/\\,;:]", " ", t)
    words = [w for w in t.split() if len(w) > 1 and not w.isdigit()]
    return " ".join(words[:2]) if words else ""


# ---------- parsowanie wyciągów ----------
def decode(raw):
    for enc in ("utf-8-sig", "cp1250", "iso-8859-2"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("cp1250", "replace")


def parse_amount(s):
    s = (s or "").replace("\xa0", "").replace(" ", "")
    m = re.search(r"[-+]?[\d.,]+", s)
    if not m:
        return None
    v = m.group(0)
    if "," in v:
        v = v.replace(".", "").replace(",", ".")
    try:
        return int((Decimal(v) * 100).quantize(Decimal(1)))
    except InvalidOperation:
        return None


def parse_date(s):
    s = (s or "").strip()[:10]
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y", "%Y.%m.%d", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def clean(s):
    return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ")).strip(" '\"")


def _rows(lines, delim=";"):
    return list(csv.reader(io.StringIO("\n".join(lines)), delimiter=delim))


def parse_mbank(text, filename):
    lines = text.splitlines()
    hi = next(i for i, l in enumerate(lines) if "#Data operacji" in l)
    default_label = "mBank"
    for i, l in enumerate(lines[:hi]):
        if l.startswith("#Numer rachunku") and i + 1 < hi:
            default_label = clean(lines[i + 1].split(";")[0]) or default_label
    rows = _rows(lines[hi:])
    head = [clean(h).lstrip("#") for h in rows[0]]
    col = {h: i for i, h in enumerate(head) if h}
    get = lambda r, name: clean(r[col[name]]) if name in col and col[name] < len(r) else ""
    out = []
    for r in rows[1:]:
        d = parse_date(r[0]) if r else None
        amt = parse_amount(get(r, "Kwota"))
        if not d or amt is None:
            continue
        cur = re.search(r"[A-Z]{3}", get(r, "Kwota"))
        desc = " ".join(x for x in (get(r, "Opis operacji"), get(r, "Tytuł")) if x)
        out.append(dict(date=d, amount=amt, currency=cur.group(0) if cur else "PLN", description=desc,
                        counterparty=get(r, "Nadawca/Odbiorca"), bank_category=get(r, "Kategoria"),
                        account=get(r, "Rachunek") or default_label))
    return "mBank", out, 0


def parse_ing(text, filename):
    lines = text.splitlines()
    hi = next(i for i, l in enumerate(lines) if "Data transakcji" in l and "Dane kontrahenta" in l)
    rows = _rows(lines[hi:])
    head = [clean(h) for h in rows[0]]
    idx = lambda name: next((i for i, h in enumerate(head) if h.startswith(name)), None)
    c_date, c_cp, c_title, c_det = idx("Data transakcji"), idx("Dane kontrahenta"), idx("Tytuł"), idx("Szczegóły")
    c_amt, c_acc = idx("Kwota transakcji"), idx("Konto")
    get = lambda r, i: clean(r[i]) if i is not None and i < len(r) else ""
    out, skipped = [], 0
    for r in rows[1:]:
        d = parse_date(get(r, c_date))
        if not d:
            continue
        amt = parse_amount(get(r, c_amt))
        if amt is None:        # blokada na karcie – transakcja jeszcze nierozliczona
            skipped += 1
            continue
        desc = " ".join(x for x in (get(r, c_title), get(r, c_det)) if x)
        out.append(dict(date=d, amount=amt, currency=get(r, c_amt + 1) or "PLN", description=desc,
                        counterparty=get(r, c_cp), bank_category="", account=get(r, c_acc) or "ING"))
    return "ING", out, skipped


def sniff_table(text):
    lines = [l for l in text.splitlines() if l.strip()]
    delim = max(";,\t", key=lambda d: sum(l.count(d) for l in lines[:40]))
    rows = _rows(lines, delim)
    for i in range(len(rows) - 1):
        if len([c for c in rows[i] if c.strip()]) >= 3 and any(parse_date(c) for c in rows[i + 1]) and not any(parse_date(c) for c in rows[i]):
            return [clean(h) for h in rows[i]], rows[i + 1:]
    return None, rows


def parse_generic(text, filename, mapping=None):
    head, rows = sniff_table(text)
    if head is None:
        raise ValueError("Nie rozpoznaję układu tego pliku. Wyeksportuj historię z banku jako CSV.")
    if not mapping:
        h = [norm(x) for x in head]
        find = lambda *keys: [i for i, x in enumerate(h) if any(k in x for k in keys)]
        dates, amts = find("DATA", "DATE"), find("KWOTA", "AMOUNT", "WARTOSC")
        desc = find("OPIS", "TYTUL", "NAZWA", "ODBIORC", "NADAWC", "KONTRAHENT", "DESCRIPTION", "SZCZEGOL")
        if not dates or not amts:
            return None, {"headers": head, "sample": [[clean(c) for c in r] for r in rows[:5]]}, 0
        mapping = {"date": dates[0], "amount": amts[0], "desc": desc}
    out = []
    g = lambda r, i: clean(r[i]) if i < len(r) else ""
    for r in rows:
        d, amt = parse_date(g(r, int(mapping["date"]))), parse_amount(g(r, int(mapping["amount"])))
        if d and amt is not None:
            out.append(dict(date=d, amount=amt, currency="PLN", bank_category="", counterparty="",
                            description=" ".join(g(r, int(i)) for i in mapping.get("desc", []) if g(r, int(i))),
                            account=os.path.splitext(filename)[0]))
    return "Inny bank", out, 0


def parse_statement(raw, filename, mapping=None):
    if raw[:4] == b"%PDF":
        raise ValueError("To plik PDF. Wyeksportuj historię rachunku z banku jako CSV – z PDF-a nie da się wiarygodnie odczytać transakcji.")
    text = decode(raw)
    if "#Data operacji" in text:
        return parse_mbank(text, filename)
    if "Data transakcji" in text and "Dane kontrahenta" in text:
        return parse_ing(text, filename)
    return parse_generic(text, filename, mapping)


def import_statement(conn, raw, filename, assign=None, mapping=None):
    """assign: {etykieta konta: id osoby} dla kont, których jeszcze nie znamy."""
    bank, rows, skipped = parse_statement(raw, filename, mapping)
    if bank is None:
        return {"need_mapping": rows}
    if not rows:
        raise ValueError("W pliku nie ma żadnych transakcji.")
    assign = assign or {}
    known = {r["label"]: r["id"] for r in conn.execute("SELECT id,label FROM accounts WHERE bank=?", (bank,))}
    labels = sorted({r["account"] for r in rows})
    unknown = [l for l in labels if l not in known and l not in assign]
    if unknown:
        return {"need_person": unknown, "bank": bank, "count": len(rows)}
    for l in labels:
        if l not in known:
            known[l] = conn.execute("INSERT INTO accounts(bank,label,person_id) VALUES(?,?,?)", (bank, l, int(assign[l]))).lastrowid
    imp = conn.execute("INSERT INTO imports(filename,bank,created,added,duplicates) VALUES(?,?,?,0,0)",
                       (filename, bank, datetime.now().isoformat(timespec="seconds"))).lastrowid
    c = Categorizer(conn)
    seen, added, dup = {}, 0, 0
    for r in rows:
        acc = known[r["account"]]
        key = (acc, r["date"], r["amount"], norm(r["description"]), norm(r["counterparty"]))
        seen[key] = seen.get(key, 0) + 1          # numer kolejny identycznych operacji tego samego dnia
        h = hashlib.sha1(repr(key + (seen[key],)).encode()).hexdigest()
        cid, src = c.match(f"{r['counterparty']} {r['description']}", r["amount"], r["bank_category"])
        try:
            conn.execute("INSERT INTO transactions(account_id,date,amount,currency,description,counterparty,bank_category,category_id,cat_source,hash,import_id) "
                         "VALUES(?,?,?,?,?,?,?,?,?,?,?)", (acc, r["date"], r["amount"], r["currency"], r["description"], r["counterparty"],
                                                          r["bank_category"], cid, src, h, imp))
            added += 1
        except sqlite3.IntegrityError:
            dup += 1
    conn.execute("UPDATE imports SET added=?, duplicates=? WHERE id=?", (added, dup, imp))
    conn.commit()
    transfers = detect_internal(conn)
    dates = [r["date"] for r in rows]
    return {"bank": bank, "added": added, "duplicates": dup, "skipped": skipped, "transfers": transfers,
            "from": min(dates), "to": max(dates), "accounts": labels}


# ---------- analiza ----------
def entries(conn, dfrom=None, dto=None, person=None):
    """Lista pozycji budżetu. Transakcja z podpiętym paragonem jest rozbijana na pozycje paragonu."""
    q = ("SELECT t.id,t.date,t.amount,t.description,t.counterparty,t.category_id,a.person_id FROM transactions t "
         "JOIN accounts a ON a.id=t.account_id WHERE 1=1")
    args = []
    if dfrom: q += " AND t.date>=?"; args.append(dfrom)
    if dto: q += " AND t.date<=?"; args.append(dto)
    if person: q += " AND a.person_id=?"; args.append(person)
    txs = conn.execute(q, args).fetchall()
    items = {}
    for r in conn.execute("SELECT r.transaction_id tid, i.amount, i.category_id FROM receipt_items i JOIN receipts r ON r.id=i.receipt_id "
                          "WHERE r.transaction_id IS NOT NULL"):
        items.setdefault(r["tid"], []).append(r)
    out = []
    for t in txs:
        base = dict(tx=t["id"], date=t["date"], person=t["person_id"], merchant=merchant(t["description"], t["counterparty"]))
        its = items.get(t["id"])
        if its and t["amount"] < 0:
            rest = t["amount"]
            for i in its:
                out.append(dict(base, amount=-i["amount"], category=i["category_id"] or t["category_id"]))
                rest += i["amount"]
            if rest:
                out.append(dict(base, amount=rest, category=t["category_id"]))
        else:
            out.append(dict(base, amount=t["amount"], category=t["category_id"]))
    return out


def month_range(d, months_back):
    y, m = d.year, d.month
    res = []
    for _ in range(months_back):
        res.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return res[::-1]


def summary(conn, dfrom, dto, person=None):
    cats = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM categories")}
    people = [dict(r) for r in conn.execute("SELECT * FROM people ORDER BY id")]
    kind = lambda e: cats[e["category"]]["kind"] if e["category"] in cats else ("income" if e["amount"] > 0 else "expense")

    bounds = conn.execute("SELECT MIN(date) a, MAX(date) b FROM transactions").fetchone()
    dfrom = dfrom or bounds["a"] or date.today().isoformat()
    dto = dto or bounds["b"] or date.today().isoformat()
    months = month_range(date.fromisoformat(dto), 12)
    all_e = entries(conn, months[0] + "-01", None, None)
    wide = entries(conn, min(dfrom, months[0] + "-01"), dto, None) if dfrom < months[0] + "-01" else all_e
    sel = [e for e in wide if dfrom <= e["date"] <= dto and (not person or e["person"] == person)]

    inc = sum(e["amount"] for e in sel if kind(e) == "income")
    exp = -sum(e["amount"] for e in sel if kind(e) == "expense")
    n_months = max(1, (date.fromisoformat(dto).year - date.fromisoformat(dfrom).year) * 12 + date.fromisoformat(dto).month - date.fromisoformat(dfrom).month + 1)

    def by_cat(k):
        agg = {}
        for e in sel:
            if kind(e) == k:
                a = agg.setdefault(e["category"], [0, 0])
                a[0] += e["amount"] if k == "income" else -e["amount"]
                a[1] += 1
        rows = [dict(id=c, name=cats[c]["name"] if c in cats else "Bez kategorii", amount=v[0], count=v[1],
                     budget=(cats[c]["budget"] * n_months if c in cats else 0)) for c, v in agg.items()]
        if k == "expense":   # kategorie z ustawionym limitem pokazujemy także bez wydatków
            for c in cats.values():
                if c["budget"] and c["kind"] == "expense" and c["id"] not in agg:
                    rows.append(dict(id=c["id"], name=c["name"], amount=0, count=0, budget=c["budget"] * n_months))
        return sorted(rows, key=lambda r: -r["amount"])

    monthly = []
    for m in months:
        row = dict(month=m, income=0, expense=0, people={p["id"]: dict(income=0, expense=0) for p in people})
        monthly.append(row)
    mi = {r["month"]: r for r in monthly}
    for e in all_e:
        r, k = mi.get(e["date"][:7]), kind(e)
        if not r or k == "transfer":
            continue
        pp = r["people"].get(e["person"])
        if not person or e["person"] == person:
            r[k] += e["amount"] if k == "income" else -e["amount"]
        if pp:
            pp[k] += e["amount"] if k == "income" else -e["amount"]

    per = []
    hh = [e for e in wide if dfrom <= e["date"] <= dto]
    for p in people:
        pi = sum(e["amount"] for e in hh if e["person"] == p["id"] and kind(e) == "income")
        pe = -sum(e["amount"] for e in hh if e["person"] == p["id"] and kind(e) == "expense")
        per.append(dict(id=p["id"], name=p["name"], income=pi, expense=pe, balance=pi - pe))

    mer = {}
    for e in sel:
        if kind(e) == "expense" and e["amount"] < 0 and e["merchant"]:
            a = mer.setdefault(e["merchant"], [0, set()])
            a[0] -= e["amount"]; a[1].add(e["tx"])
    merchants = sorted(([k, v[0], len(v[1])] for k, v in mer.items()), key=lambda x: -x[1])[:8]

    # porównanie ze średnią z 3 poprzednich pełnych miesięcy (tylko dla widoku jednego miesiąca)
    trend = {}
    if n_months == 1:
        prev = month_range(date.fromisoformat(dfrom) - timedelta(days=1), 3)
        have = {e["date"][:7] for e in wide}
        prev = [m for m in prev if m in have]
        if prev:
            for e in wide:
                if e["date"][:7] in prev and kind(e) == "expense" and (not person or e["person"] == person):
                    trend[e["category"]] = trend.get(e["category"], 0) - e["amount"]
            trend = {k: round(v / len(prev)) for k, v in trend.items()}
    expense_rows = by_cat("expense")
    for r in expense_rows:
        r["avg"] = trend.get(r["id"])
    return dict(period={"from": dfrom, "to": dto, "months": n_months}, income=inc, expense=exp, balance=inc - exp,
                count=len({e["tx"] for e in sel}),
                uncategorized=sum(1 for e in sel if e["category"] is None),
                expense_by_category=expense_rows, income_by_category=by_cat("income"),
                monthly=[dict(month=r["month"], income=r["income"], expense=r["expense"],
                              people=[dict(id=k, **v) for k, v in r["people"].items()]) for r in monthly],
                people=per, merchants=[dict(name=a, amount=b, count=c) for a, b, c in merchants])
