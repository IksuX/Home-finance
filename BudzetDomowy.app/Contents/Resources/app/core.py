"""Budżet domowy – baza danych, import wyciągów, kategoryzacja, analiza."""
import csv, hashlib, io, os, re, sqlite3, unicodedata
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

VERSION = "0.9.6"
DATA_DIR = os.environ.get("BUDZET_DATA") or os.path.expanduser("~/Library/Application Support/BudzetDomowy")
DB_PATH = os.path.join(DATA_DIR, "budzet.db")
RECEIPT_DIR = os.path.join(DATA_DIR, "paragony")

SCHEMA = """
CREATE TABLE IF NOT EXISTS people(id INTEGER PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS accounts(id INTEGER PRIMARY KEY, bank TEXT, label TEXT, person_id INTEGER, UNIQUE(bank,label));
CREATE TABLE IF NOT EXISTS settlements(id INTEGER PRIMARY KEY, name TEXT NOT NULL, patterns TEXT NOT NULL, category_id INTEGER, window INTEGER DEFAULT 40);
CREATE TABLE IF NOT EXISTS settlement_items(settlement_id INTEGER NOT NULL, transaction_id INTEGER NOT NULL, PRIMARY KEY(settlement_id, transaction_id));
CREATE TABLE IF NOT EXISTS no_pair(transaction_id INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS balances(id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL, date TEXT NOT NULL, amount INTEGER NOT NULL);
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
    "Alkohol": "DUZY BEN,MONOPOLOWY,ALKOHOLE,WINIARNIA",
    "Zakupy spożywcze": "CARREFOUR EXPRESS,MAKRO CASH,ODIDO,API MARKET,EUROSPAR,DELIKATESY CENTRUM,BIEDRONKA,LIDL,KAUFLAND,AUCHAN,CARREFOUR,ZABKA,DINO,STOKROTKA,NETTO,ALDI,LEWIATAN,SPOLEM,INTERMARCHE,DELIKATESY,PIEKARNIA,FRISCO,POLOMARKET,TOPAZ,GROSZEK,FRESHMARKET,MAKRO,SELGROS,SPAR,WARZYWNIAK,MASARNIA",
    "Restauracje i kawiarnie": "BOLT FOOD,WOLT,STOP CAFE,NORTH FISH,SPHINX,DOMINOS,PIZZA HUT,SUBWAY,MAX PREMIUM BURGERS,BAR ,MCDONALD,KFC,PIZZ,RESTAURAC,PYSZNE,GLOVO,UBER EATS,UBER *EATS,WOLT,STARBUCKS,COSTA COFFEE,KEBAB,BURGER,SUSHI,KAWIARNIA,CAFE,BISTRO,CUKIERNIA,LODZIARNIA",
    "Paliwo": "MOL ,AVIA,TOTAL,STATOIL,ORLEN,SHELL,CIRCLE K,LOTOS,MOYA,AMIC,STACJA PALIW,BP ",
    "Transport": "POLREGIO,KOLEJE SLASKIE,KZK GOP,MZK,ZKM,E-TOLL,AUTOSTRADA,PKP,INTERCITY,KOLEJE,MPK,ZTM,UBER,BOLT,FREENOW,JAKDOJADE,PARKING,AUTOSTRAD,KOLEO,FLIXBUS,SKYCASH,MOBILET",
    "Samochód": "WARSZTAT,WULKANIZ,AUTO SERWIS,MYJNIA,INTERCARS,STACJA KONTROLI",
    "Mieszkanie": "CZYNSZ,SPOLDZIELNIA,WSPOLNOTA,NAJEM",
    "Rachunki i media": "PLAY ,PLUS GSM,NJU,HEYAH,TAURON,PGE,ENEA,ENERGA,PGNIG,WODOCIAG,ORANGE,T-MOBILE,UPC,VECTRA,NETIA,INEA,ABONAMENT RTV,P4 SP,POLKOMTEL,ODPADY,SMIECI",
    "Zdrowie": "ALAB,SYNEVO,OPTYK,APTEKA,DOZ,GEMINI,MEDICOVER,LUXMED,LUX MED,ENEL-MED,PRZYCHODNIA,STOMATOLOG,DENTYST,LEKARZ,ZIKO,SUPER-PHARM,SUPERPHARM,DIAGNOSTYKA",
    "Kosmetyki i higiena": "NOTINO,NATURA,BARBER,KOSMETYCZ,ROSSMANN,HEBE,DOUGLAS,SEPHORA,DM DROGERIE,FRYZJER",
    "Odzież i obuwie": "LPP,HOUSE ,BERSHKA,PRIMARK,4F,ZARA,H&M,RESERVED,CCC,DEICHMANN,ZALANDO,SINSAY,CROPP,MOHITO,VINTED,HALFPRICE,TK MAXX,EOBUWIE",
    "Dom i ogród": "BRICOMARCHE,MERCATOR,JULA,AGATA MEBLE,BLACK RED WHITE,HOME&YOU,KOMFORT,IKEA,CASTORAMA,LEROY,OBI,JYSK,BRICO,ACTION,PEPCO,TEDI",
    "Elektronika": "NEONET,EURO-NET,MEDIA EXPERT,RTV EURO,MEDIA MARKT,X-KOM,MORELE,KOMPUTRONIK",
    "Zakupy online": "OLX,SHEIN,ALLEGRO,AMAZON,ALIEXPRESS,TEMU,INPOST,EMPIK",
    "Subskrypcje": "APPLE.COM/BILL,YOUTUBE PREMIUM,MAX.COM,HBO MAX,PLAYER.PL,SKYSHOWTIME,AUDIOTEKA,LEGIMI,STORYTEL,NETFLIX,SPOTIFY,HBO,DISNEY,YOUTUBE,APPLE.COM,ICLOUD,GOOGLE,MICROSOFT,ADOBE,CANAL+,AMAZON PRIME,OPENAI,ANTHROPIC,CLAUDE.AI",
    "Rozrywka i kultura": "KINO,CINEMA,MULTIKINO,HELIOS,TEATR,MUZEUM,EVENTIM,STEAM,PLAYSTATION,BILETY",
    "Sport": "MEDICOVER SPORT,BENEFIT SYSTEMS,MAXI ZOO_,SILOWNIA,FITNESS,BASEN,MULTISPORT,DECATHLON",
    "Zwierzęta": "ZOOPLUS,MAXI ZOO,KAKADU,WETERYNA,KARMA",
    "Dzieci": "SMYK,TIGER ,PRZEDSZKOL,ZLOBEK,SMYK,ZABAWK",
    "Edukacja": "UDEMY,KSIEGARNIA,SZKOLA,CZESNE",
    "Podróże": "BOOKING,AIRBNB,RYANAIR,WIZZ,HOTEL,NOCLEG",
    "Ubezpieczenia": "PZU,WARTA,ALLIANZ,UBEZPIECZ,POLISA,LINK4,GENERALI,HESTIA",
    "Kredyty i raty": "KREDYT,LEASING,SPLATA RATY,RATA ",
    "Podatki i urzędy": "URZAD SKARBOWY,ZUS,PODATEK,OPLATA SKARBOWA",
    "Opłaty bankowe": "OPLATA ZA PRZELEW,OPLATA MIESIECZNA,OPLATA ZA KARTE,OPLATA ZA SMS,PROWIZJA,OPLATA ZA KARTE,OPLATA ZA PROWADZENIE,ODSETKI",
    "Gotówka": "WYPLATA GOTOWKI,WYPLATA Z BANKOMATU,WYPLATA W BANKOMACIE,BANKOMAT,EURONET,PLANET CASH",
    "Darowizny": "PARAFIA,KOSCIOL,PARAFII,COLLECTA,CARITAS,WOSP,DAROWIZNA,OFIARA,FUNDACJA,SIEPOMAGA,ZRZUTKA",
    "Przelewy wewnętrzne": "PRZELEW WLASNY,PRZELEW WEWNETRZNY",
    "Oszczędności i inwestycje": "LOKATA,KONTO OSZCZEDNOSCIOWE,CEL OSZCZEDNOSCIOWY,XTB,IKZE,OBLIGACJE",
}
INCOME_RULES = {
    "Wynagrodzenie": "WYNAGRODZENIE,PENSJA,PREMIA,UMOWA O PRACE,UMOWA ZLECENI",
    "Świadczenia": "800+,500+,ZASILEK,SWIADCZENIE,ZUS",
    "Zwroty": "ZWROT,REKLAMACJA,ANULOWANIE,CHARGEBACK",
    "Inne przychody": "KAPITALIZACJA ODSETEK,ODSETKI,CASHBACK,PREMIA ZA,NAGRODA",
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


# pośrednicy płatności: w polu odbiorcy jest ich nazwa, a prawdziwy sklep jest w tytule przelewu
PROCESSORS = ["PAYPRO", "PRZELEWY24", "PRZELEWY 24", "DOTPAY", "PAYU", "TPAY", "KRAJOWY INTEGRATOR PLATNOSCI", "BLUE MEDIA", "BLUEMEDIA",
              "AUTOPAY", "PAYPAL", "STRIPE", "ADYEN", "IMOJE", "PAYNOW", "ESERVICE", "ESPAGO", "CASHBILL", "HOTPAY", "SUMUP", "ZEN.COM",
              "PAYLANE", "PAYTEL", "POLSKIE EPLATNOSCI", "ELAVON", "GLOBAL PAYMENTS", "FISERV", "WORLDLINE", "NEXI", "EPAYMENTS"]
MARKETPLACES = ["ALLEGRO", "VINTED", "OLX", "EBAY", "AMAZON"]


def is_processor(text):
    t = norm(text)
    return any(re.search(r"(?<![A-Z0-9])" + re.escape(p), t) for p in PROCESSORS)


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
    for table, col, typ in (("receipt_items", "discount", "INTEGER DEFAULT 0"), ("receipts", "saved", "INTEGER DEFAULT 0"),
                            ("receipts", "kind", "TEXT DEFAULT 'paragon'"), ("receipts", "ocr_json", "TEXT"), ("receipts", "file_hash", "TEXT"),
                            ("accounts", "kind", "TEXT DEFAULT 'budget'"), ("accounts", "name", "TEXT"), ("transactions", "balance", "INTEGER"), ("transactions", "manual", "INTEGER DEFAULT 0"), ("settlements", "mode", "TEXT DEFAULT 'auto'"), ("transactions", "booked", "TEXT"), ("transactions", "src", "TEXT"), ("people", "fullname", "TEXT"), ("transactions", "pair_id", "INTEGER")):
        if col not in [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]:     # uzupełnienie baz z wersji 0.1
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
    if not conn.execute("SELECT 1 FROM categories LIMIT 1").fetchone():
        for i, (name, kind) in enumerate(CATEGORIES):
            conn.execute("INSERT INTO categories(name,kind,sort) VALUES(?,?,?)", (name, kind, i))
        ids = {r["name"]: r["id"] for r in conn.execute("SELECT id,name FROM categories")}
        for src, sign in ((RULES, 0), (INCOME_RULES, 1)):
            for cat, spec in src.items():
                for pat in spec.split(","):
                    if pat.strip():
                        conn.execute("INSERT INTO rules(pattern,category_id,sign,user) VALUES(?,?,?,0)", (pat, ids[cat], sign))
    if conn.execute("PRAGMA user_version").fetchone()[0] < 3:      # nowości wersji 0.3
        conn.execute("INSERT OR IGNORE INTO categories(name,kind,sort) VALUES('Kaucja za opakowania','expense',30)")
        conn.execute("PRAGMA user_version=3")
    if conn.execute("PRAGMA user_version").fetchone()[0] < 9:      # 0.9: odświeżone wbudowane reguły (dla kategorii o pierwotnych nazwach)
        ids = {r["name"]: r["id"] for r in conn.execute("SELECT id,name FROM categories")}
        for src, sign in ((RULES, 0), (INCOME_RULES, 1)):
            for cat, spec in src.items():
                if cat in ids:
                    conn.execute("DELETE FROM rules WHERE user=0 AND category_id=? AND sign=?", (ids[cat], sign))
                    for pat in dict.fromkeys(spec.split(",")):
                        if pat.strip():
                            conn.execute("INSERT INTO rules(pattern,category_id,sign,user) VALUES(?,?,?,0)", (pat, ids[cat], sign))
        conn.execute("PRAGMA user_version=9")
        conn.commit()
        refresh_settlement_categories(conn)      # przelicza też kategorie nadane przez rozliczenia (już z kontrolą wydatek/przychód)
    if conn.execute("PRAGMA user_version").fetchone()[0] < 10:     # 0.9.3: przychody z własnej firmy
        conn.execute("INSERT OR IGNORE INTO categories(name,kind,sort) VALUES('Wypłaty z firmy','income',1)")
        conn.execute("PRAGMA user_version=10")
        conn.commit()
    if conn.execute("PRAGMA user_version").fetchone()[0] < 11:     # 0.9.4: pary przelewów zapamiętują drugą stronę
        conn.execute("PRAGMA user_version=11")
        conn.commit()
        reclassify_transfers(conn)
    if conn.execute("PRAGMA user_version").fetchone()[0] < 8:      # nowości wersji 0.8
        conn.execute("INSERT OR IGNORE INTO categories(name,kind,sort) VALUES('Wydatki do zwrotu','transfer',40)")
        conn.execute("PRAGMA user_version=8")
    conn.commit()
    return conn


def cat_id(conn, name):
    r = conn.execute("SELECT id FROM categories WHERE name=?", (name,)).fetchone()
    return r["id"] if r else None


# ---------- kategoryzacja ----------
def own_name_regex(conn):
    """Imiona i nazwiska domowników tak, jak zapisuje je bank – w obu kolejnościach i z drugim imieniem."""
    alts = []
    for r in conn.execute("SELECT fullname FROM people WHERE IFNULL(fullname,'')!=''"):
        for full in re.split(r"[;,\n]+", r["fullname"]):
            w = norm(full).split()
            if len(w) >= 2:
                first, last = re.escape(w[0]), re.escape(w[-1])
                alts += [rf"{first}\s+(?:[A-Z]+\s+)?{last}", rf"{last}\s+{first}"]
    return re.compile(r"(?<![A-Z])(?:" + "|".join(alts) + r")(?![A-Z])") if alts else None


def rule_regex(pattern):
    base = norm(pattern)
    if not base:
        return None
    return re.compile(r"(?<![A-Z0-9])" + re.escape(base).replace(r"\ ", r"\s+") + (r"(?![A-Z0-9])" if pattern.endswith(" ") else ""))


def sign_ok(kind, amount):
    """Wydatek dostaje tylko kategorię wydatku, wpływ tylko przychodu; kategorie „poza budżetem” pasują do obu."""
    return kind == "transfer" or kind is None or (kind == "expense") == (amount < 0)


class Categorizer:
    """Kolejność: reguły użytkownika, wbudowane reguły sprzedawców, kategoria z banku, a na końcu to, co użytkownik
    sam wybrał wcześniej dla tego samego sprzedawcy (tylko dla transakcji, których nic innego nie rozpoznało)."""
    def __init__(self, conn):
        self.rules = []
        for r in conn.execute("SELECT pattern,category_id,sign,user FROM rules"):
            rx = rule_regex(r["pattern"])
            if rx:
                self.rules.append((r["user"], len(norm(r["pattern"])), rx, r["category_id"], r["sign"]))
        self.own = own_name_regex(conn)
        if self.own:      # gdy znamy Wasze nazwiska, „przelew wewnętrzny” (w mBanku: między klientami mBanku) nie oznacza już przelewu do siebie
            legacy = rule_regex("PRZELEW WEWNETRZNY").pattern
            self.rules = [r for r in self.rules if r[0] or r[2].pattern != legacy]
        self.rules.sort(key=lambda x: (-x[0], -x[1], -abs(x[4])))
        self.internal = cat_id(conn, "Przelewy wewnętrzne")
        self.kind = {r["id"]: r["kind"] for r in conn.execute("SELECT id,kind FROM categories")}
        self.bankmap = {k: cat_id(conn, v) for k, v in BANK_CATEGORY_MAP.items()}
        self.refund, self.other_in = cat_id(conn, "Zwroty"), cat_id(conn, "Inne przychody")
        votes = {}
        for r in conn.execute("SELECT description,counterparty,amount,category_id FROM transactions WHERE cat_source='manual' AND category_id IS NOT NULL"):
            k = merchant(r["description"], r["counterparty"])
            if len(k) >= 4:
                v = votes.setdefault((k, r["amount"] > 0), {})
                v[r["category_id"]] = v.get(r["category_id"], 0) + 1
        self.learned = {k: max(v, key=v.get) for k, v in votes.items()}

    def _fit(self, cid, amount, text):
        kind = self.kind.get(cid)
        if sign_ok(kind, amount):
            return cid
        if kind == "expense" and amount > 0:      # wpływ od sklepu: zwrot towaru albo sprzedaż na portalu
            if any(m in text for m in MARKETPLACES) and not re.search(r"ZWROT|REKLAMAC|ANUL", text):
                return self.other_in or self.refund
            return self.refund
        return None

    def match(self, text, amount=0, bank_category=None, key=None):
        t = norm(text)
        for user, _, rx, cid, sign in self.rules:
            if not user:
                break
            if sign and (amount > 0) != (sign > 0):
                continue
            if rx.search(t):
                fit = self._fit(cid, amount, t)
                if fit:
                    return fit, "rule"
        if self.own and self.internal and self.own.search(t) and re.search(r"PRZELEW|WYPLATA Z CELU|P2P|BLIK", t):
            return self.internal, "rule"      # przelew do siebie albo między Wami
        for user, _, rx, cid, sign in self.rules:
            if user:
                continue
            if sign and (amount > 0) != (sign > 0):
                continue
            if rx.search(t):
                fit = self._fit(cid, amount, t)
                if fit:
                    return fit, "rule"
        b = self.bankmap.get(norm(bank_category))
        if b:
            fit = self._fit(b, amount, t)
            if fit:
                return fit, "bank"
        if key and (key, amount > 0) in self.learned:
            cid = self.learned[(key, amount > 0)]
            if sign_ok(self.kind.get(cid), amount):
                return cid, "learned"
        return None, None


def recategorize(conn, only_auto=True):
    """Przelicza kategorie transakcji, których użytkownik nie ustawił ręcznie."""
    c = Categorizer(conn)
    n = 0
    for r in conn.execute("SELECT id,description,counterparty,amount,bank_category,category_id FROM transactions "
                          "WHERE cat_source IS NULL OR cat_source IN ('rule','bank','learned')").fetchall():
        cid, src = c.match(f"{r['counterparty'] or ''} {r['description'] or ''}", r["amount"], r["bank_category"], merchant(r["description"], r["counterparty"]))
        if cid != r["category_id"]:
            conn.execute("UPDATE transactions SET category_id=?, cat_source=? WHERE id=?", (cid, src, r["id"]))
            n += 1
    conn.commit()
    return n


PROTECTED = ("paired", "transfer", "group")      # kategorie z parowania przelewów i rozliczeń – reguły ich nie ruszają


def _user_rules(conn, extra=None):
    """Reguły użytkownika w kolejności pierwszeństwa (dłuższa fraza wygrywa, przy równej – ta z ograniczeniem do znaku)."""
    kind = {r["id"]: r["kind"] for r in conn.execute("SELECT id,kind FROM categories")}
    name = {r["id"]: r["name"] for r in conn.execute("SELECT id,name FROM categories")}
    out = []
    for r in conn.execute("SELECT r.id,r.pattern,r.category_id,r.sign FROM rules r WHERE r.user=1"):
        rx = rule_regex(r["pattern"])
        if rx and (not extra or norm(r["pattern"]) != norm(extra["pattern"])):
            out.append(dict(id=r["id"], pattern=r["pattern"], cid=r["category_id"], sign=r["sign"], rx=rx))
    if extra:
        out.append(dict(extra, id=None, rx=rule_regex(extra["pattern"])))
    out.sort(key=lambda x: (-len(norm(x["pattern"])), -abs(x["sign"] or 0), x["id"] is None))
    for x in out:
        x["category"] = name.get(x["cid"]); x["kind"] = kind.get(x["cid"])
    return out


def _hits(rule, t, amount):
    return (not rule["sign"] or (amount > 0) == (rule["sign"] > 0)) and rule["rx"].search(t) and sign_ok(rule["kind"], amount)


def rule_conflicts(conn, extra=None):
    """Transakcje, do których pasuje kilka reguł użytkownika z różnymi kategoriami.
    Zwraca {id reguły lub None dla nowej: [{pattern, category, n, wins}]} – wins mówi, czy ta reguła wygrywa z tamtą."""
    rules = _user_rules(conn, extra)
    pairs = {}
    for r in conn.execute("SELECT description,counterparty,amount FROM transactions"):
        t = norm(f"{r['counterparty'] or ''} {r['description'] or ''}")
        m = [x for x in rules if _hits(x, t, r["amount"])]
        for i, a in enumerate(m):
            for b in m[i + 1:]:
                if a["cid"] != b["cid"]:
                    k = (a["id"], b["id"]); pairs[k] = pairs.get(k, 0) + 1
    by = {x["id"]: x for x in rules}
    out = {}
    for (a, b), n in pairs.items():      # a stoi wyżej w kolejności, więc wygrywa
        out.setdefault(a, []).append(dict(pattern=by[b]["pattern"], category=by[b]["category"], n=n, wins=True, id=b))
        out.setdefault(b, []).append(dict(pattern=by[a]["pattern"], category=by[a]["category"], n=n, wins=False, id=a))
    return out


def apply_rule_everywhere(conn, pattern, category_id):
    """Zdejmuje ręczną kategorię z transakcji pasujących do reguły, żeby reguła mogła je przeliczyć."""
    rx = rule_regex(pattern)
    k = conn.execute("SELECT kind FROM categories WHERE id=?", (category_id,)).fetchone()
    sign = {"expense": -1, "income": 1}.get(k["kind"] if k else None, 0)
    n = 0
    for r in conn.execute("SELECT id,description,counterparty,amount FROM transactions WHERE cat_source='manual'").fetchall():
        if (not sign or (r["amount"] > 0) == (sign > 0)) and rx.search(norm(f"{r['counterparty'] or ''} {r['description'] or ''}")) and sign_ok(k["kind"] if k else None, r["amount"]):
            conn.execute("UPDATE transactions SET cat_source='rule' WHERE id=?", (r["id"],)); n += 1
    return n


KINDS = {"budget": "w budżecie", "cash": "gotówka", "savings": "oszczędnościowe", "benefit": "800+ i świadczenia", "invest": "inwestycyjne", "other": "inne poza budżetem"}
IN_BUDGET = ("budget", "cash")      # gotówka w portfelu też jest częścią budżetu
MANUAL = "Ręczne"       # konta dodane ręcznie, bez wyciągów


WALLETS = ["REVOLUT", "WISE", "TRANSFERWISE", "ZEN.COM", "CURVE", "SKRILL", "N26", "BUNQ"]      # konta zasilane kartą


def detect_internal(conn):
    """Paruje przelewy między własnymi kontami (ta sama kwota, przeciwny znak, do 4 dni różnicy – wygrywa najbliższa data).
    Płatność kartą bierze udział tylko wtedy, gdy to doładowanie portfela, np. Revolut.
    Przelew między kontami budżetu to „Przelewy wewnętrzne”; przelew na konto poza budżetem lub z niego to „Oszczędności i inwestycje”."""
    internal, saving = cat_id(conn, "Przelewy wewnętrzne"), cat_id(conn, "Oszczędności i inwestycje")
    if not internal:
        return 0
    side = {r["id"] for r in conn.execute("SELECT id FROM accounts WHERE IFNULL(kind,'budget') NOT IN ('budget','cash')")}
    rows = conn.execute("SELECT id,account_id,date,amount,description,counterparty FROM transactions "
                        "WHERE (cat_source IS NULL OR cat_source IN ('rule','bank','learned')) AND pair_id IS NULL "
                        "AND id NOT IN (SELECT transaction_id FROM no_pair)").fetchall()
    owner = {r["id"]: r["person_id"] for r in conn.execute("SELECT id,person_id FROM accounts")}
    who = {}      # imię (i nazwisko z ustawień) każdej osoby – do sprawdzania przelewów między Wami
    for p in conn.execute("SELECT id,name,fullname FROM people"):
        parts = [norm(p["name"])] + [norm(x) for x in re.split(r"[;,]", p["fullname"] or "") if x.strip()]
        parts = [re.escape(x).replace(r"\ ", r"\s+") for x in parts if len(x) >= 3]
        if parts:
            who[p["id"]] = re.compile(r"(?<![A-Z])(?:" + "|".join(parts) + r")(?![A-Z])")
    text_of = {r["id"]: norm(f"{r['counterparty'] or ''} {r['description'] or ''}") for r in rows}
    _wc = {}
    def words(i):
        if i not in _wc:
            _wc[i] = set(_words(text_of[i])) - STOP
        return _wc[i]
    ins = {}
    for r in rows:
        if r["amount"] > 0:
            ins.setdefault(r["amount"], []).append(r)
    options = []      # wszystkie możliwe pary; potem przydział od najbliższej daty, ta sama osoba ma pierwszeństwo
    for r in rows:
        text = norm(f"{r['counterparty'] or ''} {r['description'] or ''}")
        if r["amount"] >= 0 or ("KART" in text and not any(w in text for w in WALLETS)):
            continue
        d = date.fromisoformat(r["date"])
        for c in ins.get(-r["amount"], []):
            gap = abs((date.fromisoformat(c["date"]) - d).days)
            po, pi = owner.get(r["account_id"]), owner.get(c["account_id"])
            cross = po != pi
            if cross and gap and not (who.get(pi) and who[pi].search(text_of[r["id"]])) and not (who.get(po) and who[po].search(text_of[c["id"]])):
                continue      # przelew między Wami: tego samego dnia albo z imieniem odbiorcy/nadawcy w opisie – inaczej to przypadkowa zbieżność kwot
            if c["account_id"] != r["account_id"] and gap <= 4:
                common = len(words(r["id"]) & words(c["id"]))      # przy remisie dat wygrywa para o podobnym opisie
                options.append((gap, cross, -common, r["id"], c["id"], r["account_id"], c["account_id"]))
    options.sort()
    used, n = set(), 0
    for gap, _, _c, out_id, in_id, out_acc, in_acc in options:
        if out_id in used or in_id in used:
            continue
        used |= {out_id, in_id}
        cat = saving if saving and (out_acc in side or in_acc in side) else internal
        conn.execute("UPDATE transactions SET category_id=?, cat_source='transfer', pair_id=? WHERE id=?", (cat, in_id, out_id))
        conn.execute("UPDATE transactions SET category_id=?, cat_source='transfer', pair_id=? WHERE id=?", (cat, out_id, in_id))
        n += 1
    conn.commit()
    return n


def link_pair(conn, a, b):
    """Ręczne powiązanie dwóch transakcji z różnych kont jako przelewu między nimi (kwoty nie muszą być równe)."""
    ta, tb = (conn.execute("SELECT t.*, x.kind akind FROM transactions t JOIN accounts x ON x.id=t.account_id WHERE t.id=?", (i,)).fetchone() for i in (a, b))
    if not ta or not tb:
        raise ValueError("Nie ma takiej transakcji.")
    if ta["account_id"] == tb["account_id"]:
        raise ValueError("Obie transakcje są z tego samego konta.")
    if (ta["amount"] > 0) == (tb["amount"] > 0):
        raise ValueError("Powiązać można tylko wypływ z jednego konta z wpływem na drugie.")
    for t in (ta, tb):
        if t["pair_id"]:
            unlink_pair(conn, t["id"])
        conn.execute("DELETE FROM no_pair WHERE transaction_id=?", (t["id"],))
    side = any(t["akind"] not in ("budget", "cash") for t in (ta, tb))
    cat = cat_id(conn, "Oszczędności i inwestycje" if side else "Przelewy wewnętrzne")
    conn.execute("UPDATE transactions SET category_id=?, cat_source='paired', pair_id=? WHERE id=?", (cat, b, a))
    conn.execute("UPDATE transactions SET category_id=?, cat_source='paired', pair_id=? WHERE id=?", (cat, a, b))
    conn.commit()


def unlink_pair(conn, tid):
    t = conn.execute("SELECT pair_id FROM transactions WHERE id=?", (tid,)).fetchone()
    ids = [i for i in (tid, t["pair_id"] if t else None) if i]
    for i in ids:
        conn.execute("UPDATE transactions SET category_id=NULL, cat_source=NULL, pair_id=NULL WHERE id=?", (i,))
    conn.commit()
    for i in ids:      # po ręcznym rozłączeniu program nie połączy ich z powrotem sam
        conn.execute("INSERT OR IGNORE INTO no_pair(transaction_id) VALUES(?)", (i,))
    conn.commit()
    recategorize(conn)


def reclassify_transfers(conn):
    """Po zmianie rodzaju lub właściciela konta: rozpoznaje przelewy między kontami od nowa."""
    conn.execute("UPDATE transactions SET category_id=NULL, cat_source=NULL, pair_id=NULL WHERE cat_source='transfer'")
    conn.commit()
    recategorize(conn)
    return detect_internal(conn)


def atm_feeds_cash(conn):
    """Czy wypłaty z bankomatu zasilają portfel gotówki (kategoria „Gotówka” ustawiona jako „poza budżetem”)."""
    r = conn.execute("SELECT kind FROM categories WHERE name='Gotówka'").fetchone()
    return bool(r and r["kind"] == "transfer")


def _day_edge(conn, acc, d, last):
    """Ostatnia (albo pierwsza) operacja dnia z saldem, ustalona z samych sald – bez zakładania kolejności wierszy w pliku."""
    if not d:
        return None
    rows = [dict(r) for r in conn.execute("SELECT id,date,balance,amount FROM transactions WHERE account_id=? AND date=? AND balance IS NOT NULL ORDER BY id", (acc, d))]
    if last:
        before = {r["balance"] - r["amount"] for r in rows}
        pick = [r for r in rows if r["balance"] not in before] or rows[:1]
    else:
        after = {r["balance"] for r in rows}
        pick = [r for r in rows if r["balance"] - r["amount"] not in after] or rows[-1:]
    return pick[0]


def balance_at(conn, acc, day):
    """Stan konta na dany dzień: (kwota, źródło, data). Źródła: wpisany stan + późniejsze operacje, saldo z wyciągu, same operacje."""
    a = conn.execute("SELECT kind,person_id FROM accounts WHERE id=?", (acc,)).fetchone()
    s = conn.execute("SELECT date,amount FROM balances WHERE account_id=? AND date<=? ORDER BY date DESC,id DESC LIMIT 1", (acc, day)).fetchone()
    t = _day_edge(conn, acc, conn.execute("SELECT MAX(date) FROM transactions WHERE account_id=? AND date<=? AND balance IS NOT NULL", (acc, day)).fetchone()[0], last=True)
    if s and not (t and t["date"] > s["date"]):
        moved = conn.execute("SELECT IFNULL(SUM(amount),0) FROM transactions WHERE account_id=? AND date>? AND date<=?", (acc, s["date"], day)).fetchone()[0]
        if a and a["kind"] == "cash" and atm_feeds_cash(conn):      # wypłaty z bankomatu tej osoby trafiają do portfela
            moved -= conn.execute("SELECT IFNULL(SUM(t.amount),0) FROM transactions t JOIN accounts x ON x.id=t.account_id JOIN categories c ON c.id=t.category_id "
                                  "WHERE c.name='Gotówka' AND IFNULL(x.kind,'budget')='budget' AND x.person_id=? AND t.date>? AND t.date<=?",
                                  (a["person_id"], s["date"], day)).fetchone()[0]
        return s["amount"] + moved, "snapshot", s["date"]
    if t:
        return t["balance"], "statement", t["date"]
    # dzień sprzed pierwszej operacji w wyciągu z saldem: stan = saldo po pierwszej operacji minus jej kwota
    f = _day_edge(conn, acc, conn.execute("SELECT MIN(date) FROM transactions WHERE account_id=? AND balance IS NOT NULL", (acc,)).fetchone()[0], last=False)
    if f and day < f["date"] and not conn.execute("SELECT 1 FROM transactions WHERE account_id=? AND date<=? LIMIT 1", (acc, day)).fetchone():
        return f["balance"] - f["amount"], "statement", day
    flows = conn.execute("SELECT IFNULL(SUM(amount),0) s, COUNT(*) n, MAX(date) d FROM transactions WHERE account_id=? AND date<=?", (acc, day)).fetchone()
    return (flows["s"], "flows", flows["d"]) if flows["n"] else (None, None, None)


def cash_wallet(conn, person):
    """Portfel gotówki danej osoby; tworzy go przy pierwszym użyciu."""
    r = conn.execute("SELECT id FROM accounts WHERE kind='cash' AND person_id=? ORDER BY id LIMIT 1", (person,)).fetchone()
    if r:
        return r["id"]
    name = conn.execute("SELECT name FROM people WHERE id=?", (person,)).fetchone()
    return conn.execute("INSERT INTO accounts(bank,label,person_id,kind) VALUES(?,?,?,'cash')", (MANUAL, f"Gotówka – {name['name'] if name else person}", person)).lastrowid


def budget_flow(conn, dfrom, dto, person=None):
    """Pieniądze na kontach budżetu (z gotówką) na początek i koniec okresu. Wymaga znanego stanu każdego konta:
    z salda w wyciągu albo z wpisanego salda otwarcia."""
    accs = [dict(r) for r in conn.execute("SELECT a.*, (SELECT COUNT(*) FROM transactions t WHERE t.account_id=a.id) n, "
                                          "(SELECT COUNT(*) FROM balances b WHERE b.account_id=a.id) s FROM accounts a "
                                          "WHERE IFNULL(a.kind,'budget') IN ('budget','cash')" + (" AND a.person_id=?" if person else ""), [person] if person else [])]
    before = (date.fromisoformat(dfrom) - timedelta(days=1)).isoformat()
    start = end = 0
    missing = []
    for a in accs:
        if not a["n"] and not a["s"]:
            continue
        b0, s0, _ = balance_at(conn, a["id"], before)
        b1, s1, _ = balance_at(conn, a["id"], dto)
        if s0 in ("snapshot", "statement") and s1 in ("snapshot", "statement"):
            start += b0; end += b1
        else:
            missing.append(a["name"] or (a["label"] if a["bank"] == MANUAL else f"{a['bank']} {a['label']}"))
    return dict(start=start, end=end, missing=missing, before=before)


GROUPS = [("budget", "Konta bieżące"), ("cash", "Gotówka"), ("savings", "Oszczędności"), ("benefit", "800+ i świadczenia"), ("invest", "Inwestycje"), ("other", "Inne")]


def networth(conn, person=None):
    """Stan posiadania: najnowsze znane stany wszystkich kont i ich suma na koniec każdego z 12 ostatnich miesięcy."""
    accs = [dict(r) for r in conn.execute("SELECT * FROM accounts" + (" WHERE person_id=?" if person else ""), [person] if person else [])]
    def known(a, day):
        bal, src, d = balance_at(conn, a["id"], day)
        return (bal, d) if src in ("snapshot", "statement") else (None, None)
    groups, unknown, total = {k: 0 for k, _ in GROUPS}, [], 0
    for a in accs:
        bal, d = known(a, "9999-12-31")
        nm = a["name"] or (a["label"] if a["bank"] == MANUAL else f"{a['bank']} {a['label']}")
        if bal is None:
            unknown.append(dict(id=a["id"], name=nm))
        else:
            groups[a["kind"] or "budget"] = groups.get(a["kind"] or "budget", 0) + bal
            total += bal
    today = date.today()
    monthly = []
    for m in month_range(today, 12):
        y, mo = int(m[:4]), int(m[5:])
        end = (date(y + (mo == 12), mo % 12 + 1, 1) - timedelta(days=1))
        day = min(end, today).isoformat()
        vals = [known(a, day)[0] for a in accs]
        monthly.append(dict(month=m, total=sum(v for v in vals if v is not None), accounts=sum(1 for v in vals if v is not None)))
    return dict(total=total, known=len(accs) - len(unknown), unknown=unknown, monthly=monthly,
                groups=[dict(kind=k, name=n, amount=groups.get(k, 0)) for k, n in GROUPS if any((a["kind"] or "budget") == k for a in accs)])


def accounts_overview(conn, dfrom, dto):
    out = []
    for a in conn.execute("SELECT a.*, (SELECT COUNT(*) FROM transactions t WHERE t.account_id=a.id) n FROM accounts a ORDER BY a.kind!='budget', a.bank, a.label"):
        f = conn.execute("SELECT IFNULL(SUM(CASE WHEN amount>0 THEN amount END),0) i, IFNULL(SUM(CASE WHEN amount<0 THEN -amount END),0) o "
                         "FROM transactions WHERE account_id=? AND date>=? AND date<=?", (a["id"], dfrom, dto)).fetchone()
        bal, src, bdate = balance_at(conn, a["id"], "9999-12-31")      # stan zawsze według najnowszych danych; okres dotyczy tylko wpłat i wypłat
        out.append(dict(id=a["id"], bank=a["bank"], label=a["label"], name=a["name"] or (a["label"] if a["bank"] == MANUAL else f"{a['bank']} {a['label']}"),
                        kind=a["kind"] or "budget", person_id=a["person_id"], n=a["n"], manual=a["bank"] == MANUAL, inflow=f["i"], outflow=f["o"],
                        balance=bal, balance_source=src, balance_date=bdate,
                        snapshots=[dict(r) for r in conn.execute("SELECT id,date,amount FROM balances WHERE account_id=? ORDER BY date DESC,id DESC LIMIT 24", (a["id"],))]))
    return out


_NOISE = (r"ZAKUP PRZY UZYCIU KARTY( W KRAJU| ZA GRANICA| - INTERNET)?|PLATNOSC KARTA|PLATNOSC KARTY|TRANSAKCJA KARTA|TR\.KART|PLATNOSC BLIK|ZAKUP BLIK|"
          r"BLIK|PRZELEW (ZEWNETRZNY |WEWNETRZNY |NATYCHMIASTOWY |EXPRESS ELIXIR )?(PRZYCHODZACY|WYCHODZACY)?|ZLECENIE STALE|POLECENIE ZAPLATY|"
          r"SP\.? ?Z ?O\.? ?O\.?|SP\.? ?K\.?|S\.A\.|SPOLKA AKCYJNA|DATA TRANSAKCJI.*|NR KARTY.*|ZAMOWIENIE|ZAM\.|NR ZAM\w*|TRANSAKCJA|PLATNOSC|"
          r"P24-[A-Z0-9-]+|PAYU-?\w*|TR-[A-Z0-9-]+|ID:?\s?\w+|REF:?\s?\w+|UL\.? .*|WWW\.|HTTPS?://")
STOP = {"DLA", "ZA", "NA", "OD", "DO", "NR", "THE", "AND", "PLN", "EUR", "USD", "SKLEP", "SERWIS", "ONLINE", "POLSKA", "POLAND", "PL",
        "ROZLICZENIE", "ROZLICZENIA", "ZAMOWIENIE", "ZAMOWIENIA", "ZAMOWIENIU", "ZAKUP", "ZAKUPU", "ZAKUPY", "OPLATA", "OPLATY", "FAKTURA", "FAKTURY",
        "FV", "ZAPLATA", "ZAPLATY", "DOKUMENT", "TYTUL", "NUMER", "KLIENT", "KLIENTA", "USLUGA", "USLUGI", "TOWAR", "TOWARU", "RACHUNEK", "RACHUNKU",
        "WPLATA", "WPLATY", "DOPLATA", "ABONAMENT", "ZLECENIE", "PRZELEW", "KONTO", "PLATNOSCI", "TRANSAKCJI", "NUMERZE", "ODBIORCA", "NADAWCA", "PAYMENT", "ORDER"}


def _words(t):
    t = re.sub(_NOISE, " ", t)
    t = re.sub(r"\d{2}[.-]\d{2}[.-]\d{2,4}|\d{4}[.-]\d{2}[.-]\d{2}|\b\d+\b|[*/\\,;:()\[\]\"'#]", " ", t)
    return [w for w in t.split() if len(w) > 1 and not w.isdigit() and not re.fullmatch(r"[A-Z]?\d+[A-Z]?", w)]


def strip_processors(t):
    for p in PROCESSORS:
        t = re.sub(r"(?<![A-Z0-9])" + re.escape(p) + r"\S*", " ", t)
    return t


def merchant(description, counterparty=""):
    """Krótka nazwa sprzedawcy do zestawień i podpowiedzi reguł. Gdy odbiorcą jest pośrednik płatności
    (PayPro/Przelewy24, PayU, Tpay, PayPal…), sprzedawca jest brany z tytułu przelewu albo deskryptora karty."""
    cp, desc = norm(counterparty), norm(description)
    for t in (cp, desc):
        m = re.search(r"(?:PAYPAL|PAYU|P24|PRZELEWY24|STRIPE|SUMUP|ZEN\.COM)\s?\*\s?([A-Z0-9][A-Z0-9 .&-]{2,})", t)      # PAYPAL *SPOTIFY
        if m:
            w = _words(m.group(1))
            if w:
                return " ".join(w[:2])
    if cp and not is_processor(cp):
        w = _words(cp)
        if w:
            return " ".join(w[:2])
    w = [x for x in _words(strip_processors(desc)) if x not in STOP]
    if w:
        return " ".join(w[:2])
    return " ".join(_words(cp)[:2]) if cp else ""


def rule_phrases(description, counterparty=""):
    """Podpowiedzi fraz do reguły: nazwa sprzedawcy, odbiorca (jeśli to nie pośrednik) i znaczące słowa z tytułu."""
    out = []
    def add(p):
        p = p.strip()
        if len(p) >= 3 and p not in out and not p.isdigit():
            out.append(p)
    add(merchant(description, counterparty))
    cp = norm(counterparty)
    if cp and not is_processor(cp):
        add(" ".join(_words(cp)[:3]))
    words = [x for x in _words(strip_processors(norm(description))) if x not in STOP and len(x) >= 3]
    for i in range(len(words)):
        add(words[i])
        if i + 1 < len(words):
            add(words[i] + " " + words[i + 1])
        if len(out) >= 6:
            break
    return out[:6]


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
                        counterparty=get(r, "Nadawca/Odbiorca"), bank_category=get(r, "Kategoria"), booked=parse_date(get(r, "Data księgowania")),
                        account=get(r, "Rachunek") or default_label, balance=parse_amount(get(r, "Saldo po operacji"))))
    return "mBank", out, 0


def parse_ing(text, filename):
    lines = text.splitlines()
    hi = next(i for i, l in enumerate(lines) if "Data transakcji" in l and "Dane kontrahenta" in l)
    rows = _rows(lines[hi:])
    head = [clean(h) for h in rows[0]]
    idx = lambda name: next((i for i, h in enumerate(head) if h.startswith(name)), None)
    c_date, c_cp, c_title, c_det, c_book = idx("Data transakcji"), idx("Dane kontrahenta"), idx("Tytuł"), idx("Szczegóły"), idx("Data księgowania")
    c_amt, c_acc, c_bal = idx("Kwota transakcji"), idx("Konto"), idx("Saldo po transakcji")
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
                        counterparty=get(r, c_cp), bank_category="", account=get(r, c_acc) or "ING", balance=parse_amount(get(r, c_bal)),
                        booked=parse_date(get(r, c_book))))
    return "ING", out, skipped


BANK_CODES = {"1050": "ING", "1140": "mBank", "1020": "PKO BP", "1090": "Santander", "1240": "Pekao", "1160": "Millennium", "2490": "Alior",
              "1750": "BNP Paribas", "1600": "BNP Paribas", "2030": "BNP Paribas", "1940": "Credit Agricole", "1870": "Nest Bank", "1540": "BOŚ",
              "1680": "VeloBank", "1320": "Bank Pocztowy", "1930": "Bank Polskiej Spółdzielczości", "1610": "SGB", "2130": "VW Bank", "1840": "Santander Consumer"}


def nrb_label(acc):
    d = re.sub(r"\D", "", acc or "")
    if len(d) == 26:
        return d[:2] + " " + " ".join(d[i:i + 4] for i in range(2, 26, 4))
    return clean(acc).lstrip("/")


def _mt_decode(raw):
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    pl = "ąćęłńóśźżĄĆĘŁŃÓŚŹŻ"
    best = max(("cp1250", "cp852", "iso-8859-2"), key=lambda e: sum(raw.decode(e, "replace").count(ch) for ch in pl))
    return raw.decode(best, "replace")


def is_mt940(text):
    return bool(re.search(r"(?m)^:20:", text) and re.search(r"(?m)^:61:", text))


def _mt86(text):
    """Pole :86: – w polskich bankach podzielone na podpola ~00, ~20…~26 (tytuł), ~27…~29 lub ~32/~33 (kontrahent)."""
    text = text.replace("\n", "")
    m = re.match(r"^\s*\d{3}([~^<>|])", text) or re.search(r"([~^<>|])(?:00|20)", text)
    if not m:
        return clean(text), ""
    parts = {}
    for chunk in text.split(m.group(1))[1:]:
        if len(chunk) >= 2 and chunk[:2].isdigit():
            parts.setdefault(chunk[:2], []).append(chunk[2:])
    get = lambda *codes: " ".join(clean(" ".join(parts.get(k, []))) for k in codes if parts.get(k)).strip()
    title = get("20", "21", "22", "23", "24", "25", "26")
    who = get("32", "33") or get("27", "28", "29")
    kind = get("00")
    if kind and re.search(r"[A-Za-z]{4}", kind) and not re.fullmatch(r"[A-Z]{2}\d{2}", kind):
        title = (kind + " " + title).strip()
    return clean(title), clean(who)


def parse_mt940(text, filename):
    """Wyciąg MT940 (pliki .sta/.mt940). Saldo po każdej operacji jest liczone od salda otwarcia :60F:."""
    lines, tags = text.replace("\r", "").split("\n"), []
    for l in lines:
        m = re.match(r"^:(\d{2}[A-Z]?):(.*)$", l)
        if m:
            tags.append([m.group(1), m.group(2)])
        elif tags and l.strip() and not l.startswith(("-}", "{", "-")):
            tags[-1][1] += "\n" + l
    out, acc, bal, cur, bank = [], None, None, "PLN", None
    for tag, val in tags:
        if tag == "25":
            acc = nrb_label(val.split("\n")[0])
            digits = re.sub(r"\D", "", val)
            bank = BANK_CODES.get(digits[2:6]) if len(digits) >= 26 else bank
        elif tag in ("60F", "60M"):
            m = re.match(r"([CD])(\d{6})([A-Z]{3})([\d,]+)", val.strip())
            if m:
                bal = parse_amount(m.group(4)) * (-1 if m.group(1) == "D" else 1)
                cur = m.group(3)
        elif tag == "61":
            m = re.match(r"(\d{2})(\d{2})(\d{2})(\d{4})?(R?[CD])[A-Z]?([\d,]+)", val.strip())
            if not m:
                continue
            y, mo, d = 2000 + int(m.group(1)), int(m.group(2)), int(m.group(3))
            booked = None
            if m.group(4):
                bm, bd = int(m.group(4)[:2]), int(m.group(4)[2:])
                by = y + (1 if bm < mo - 6 else -1 if bm > mo + 6 else 0)
                try:
                    booked = date(by, bm, bd).isoformat()
                except ValueError:
                    pass
            amt = parse_amount(m.group(6))
            amt = -amt if m.group(5) in ("D", "RC") else amt
            if bal is not None:
                bal += amt
            try:
                day = date(y, mo, d).isoformat()
            except ValueError:
                continue
            out.append(dict(fmt="mt940", date=day, booked=booked, amount=amt, currency=cur, description="", counterparty="", bank_category="",
                            account=acc or "MT940", balance=bal))
        elif tag == "86" and out and not out[-1]["description"] and not out[-1]["counterparty"]:
            out[-1]["description"], out[-1]["counterparty"] = _mt86(val)
    if not out:
        raise ValueError("Plik MT940 nie zawiera żadnych operacji.")
    return bank or "Inny bank", out, 0


def xlsx_rows(raw):
    """Arkusz .xlsx (np. wyciąg Revolut „Excel”) jako lista wierszy – bez zewnętrznych bibliotek."""
    import zipfile, xml.etree.ElementTree as ET
    z = zipfile.ZipFile(io.BytesIO(raw))
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns):
            shared.append("".join(t.text or "" for t in si.iter("{%s}t" % ns["m"])))
    sheet = next(n for n in sorted(z.namelist()) if n.startswith("xl/worksheets/sheet"))
    out = []
    for row in ET.fromstring(z.read(sheet)).iter("{%s}row" % ns["m"]):
        cells = {}
        for cel in row.findall("m:c", ns):
            ref = re.match(r"([A-Z]+)", cel.get("r", "A")).group(1)
            col = 0
            for ch in ref:
                col = col * 26 + ord(ch) - 64
            v = cel.find("m:v", ns)
            if cel.get("t") == "s" and v is not None:
                val = shared[int(v.text)]
            elif cel.get("t") == "inlineStr":
                val = "".join(t.text or "" for t in cel.iter("{%s}t" % ns["m"]))
            else:
                val = v.text if v is not None else ""
            cells[col - 1] = val
        if cells:
            out.append([cells.get(i, "") for i in range(max(cells) + 1)])
    return out


def _xl_date(v):
    """Data z arkusza: tekst albo liczba dni od 1899-12-30."""
    if re.fullmatch(r"\d+(\.\d+)?", str(v or "")) and 20000 < float(v) < 80000:
        return (date(1899, 12, 30) + timedelta(days=int(float(v)))).isoformat()
    return parse_date(str(v or "")[:10])


def parse_revolut(rows, filename):
    """Wyciąg Revolut (CSV albo Excel, po angielsku lub po polsku). Wczytywane są operacje w PLN; inne waluty są pomijane."""
    head = [norm(h) for h in rows[0]]
    def col(*names):
        return next((i for i, h in enumerate(head) for n in names if h.startswith(n)), None)
    c_type, c_prod, c_start, c_done = col("TYPE", "TYP", "RODZAJ"), col("PRODUCT", "PRODUKT"), col("STARTED", "DATA ROZPOCZ"), col("COMPLETED", "DATA ZAKONCZ", "DATA UKONCZ")
    c_desc, c_amt, c_fee, c_cur, c_state, c_bal = col("DESCRIPTION", "OPIS"), col("AMOUNT", "KWOTA"), col("FEE", "OPLATA", "PROWIZJA"), col("CURRENCY", "WALUTA"), col("STATE", "STAN", "STATUS"), col("BALANCE", "SALDO")
    g = lambda r, i: clean(str(r[i])) if i is not None and i < len(r) else ""
    out, skipped, foreign = [], 0, 0
    for r in rows[1:]:
        d = _xl_date(g(r, c_start)) or _xl_date(g(r, c_done))
        amt = parse_amount(g(r, c_amt).replace(".", ",") if re.fullmatch(r"-?\d+\.\d{1,2}", g(r, c_amt)) else g(r, c_amt))
        if not d or amt is None:
            continue
        if re.search(r"REVERT|DECLIN|PEND|FAIL|COFNI|ODRZUC|OCZEK|ANULOW|WSTRZYM", norm(g(r, c_state))):
            skipped += 1
            continue
        cur = g(r, c_cur).upper() or "PLN"
        if cur != "PLN":
            foreign += 1
            continue
        fee = parse_amount(g(r, c_fee).replace(".", ",") if re.fullmatch(r"-?\d+\.\d{1,2}", g(r, c_fee)) else g(r, c_fee)) or 0
        bal = g(r, c_bal)
        typ, desc = g(r, c_type), g(r, c_desc)
        out.append(dict(fmt="revolut", date=d, booked=_xl_date(g(r, c_done)), amount=amt - abs(fee), currency=cur,
                        description=" ".join(x for x in (typ.replace("_", " ").title() if typ else "", desc) if x), counterparty=desc, bank_category="",
                        account=f"{g(r, c_prod) or 'Current'} {cur}",
                        balance=parse_amount(bal.replace(".", ",") if re.fullmatch(r"-?\d+\.\d{1,2}", bal) else bal) if bal else None))
    if not out:
        raise ValueError("W pliku Revolut nie ma operacji w złotych." + (f" Pominięto {foreign} operacji w innych walutach." if foreign else ""))
    return "Revolut", out, skipped + foreign


def is_revolut_header(cells):
    h = [norm(x) for x in cells]
    return any(x.startswith(("STARTED DATE", "DATA ROZPOCZ")) for x in h) and any(x.startswith(("PRODUCT", "PRODUKT")) for x in h)


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
        raise ValueError("Wyciągu w PDF nie da się wiarygodnie odczytać. Pobierz ten sam okres jako MT940 (plik .sta) albo CSV – "
                         "zawierają te same transakcje i saldo. Już wczytane transakcje zostaną rozpoznane, nic się nie zdubluje.")
    head = raw[:4000].decode("latin-1")
    if is_mt940(head) or (filename.lower().endswith((".sta", ".mt940", ".940")) and ":61:" in raw.decode("latin-1")):
        return parse_mt940(_mt_decode(raw), filename)
    if raw[:2] == b"PK":      # arkusz Excel
        try:
            rows = xlsx_rows(raw)
        except Exception:
            raise ValueError("Nie udało się otworzyć arkusza. Zapisz go jako CSV i wczytaj ponownie.")
        i = next((k for k, r in enumerate(rows[:15]) if is_revolut_header(r)), None)
        if i is not None:
            return parse_revolut(rows[i:], filename)
        raw = "\n".join(";".join(str(x).replace(";", ",") for x in r) for r in rows).encode("utf-8")
    text = decode(raw)
    first = next((l for l in text.splitlines()[:15] if l.strip()), "")
    for l in text.splitlines()[:15]:
        cells = next(csv.reader([l], delimiter=max(",;\t", key=l.count)), [])
        if is_revolut_header(cells):
            lines = text.splitlines()
            k = lines.index(l)
            return parse_revolut(list(csv.reader(io.StringIO("\n".join(lines[k:])), delimiter=max(",;\t", key=l.count))), filename)
    if "#Data operacji" in text:
        return parse_mbank(text, filename)
    if "Data transakcji" in text and "Dane kontrahenta" in text:
        return parse_ing(text, filename)
    return parse_generic(text, filename, mapping)


def same_account(a, b):
    """Czy dwie etykiety konta z wyciągów oznaczają ten sam rachunek (pełny numer, sam numer bez nazwy albo numer zamaskowany)."""
    da, db = re.sub(r"\D", "", a or ""), re.sub(r"\D", "", b or "")
    if len(da) < 8 or len(db) < 8:
        return False
    short, long_ = sorted((da, db), key=len)
    return short == long_ or long_.endswith(short[-10:]) or (len(short) == 8 and long_.startswith(short[:4]) and long_.endswith(short[4:]))


def import_statement(conn, raw, filename, assign=None, mapping=None):
    """assign: {etykieta konta: id osoby albo {person, kind}} dla kont, których jeszcze nie znamy.
    Ponowne wczytanie tego samego okresu niczego nie dubluje: znane transakcje są pomijane, a jeśli nowy plik
    ma saldo albo inny układ kolumn, istniejące rekordy dostają saldo i zachowują kategorie, opisy i paragony."""
    bank, rows, skipped = parse_statement(raw, filename, mapping)
    if bank is None:
        return {"need_mapping": rows}
    if not rows:
        raise ValueError("W pliku nie ma żadnych transakcji.")
    assign = assign or {}
    existing = [dict(r) for r in conn.execute("SELECT id,label FROM accounts WHERE bank=?", (bank,))]
    known = {r["label"]: r["id"] for r in existing}
    labels = sorted({r["account"] for r in rows})
    for l in labels:      # to samo konto pod inną etykietą (np. wyciąg w innym układzie)
        if l not in known:
            hit = next((e for e in existing if same_account(e["label"], l)), None)
            if hit:
                known[l] = hit["id"]
    unknown = [l for l in labels if l not in known and l not in assign]
    if unknown:
        return {"need_person": unknown, "bank": bank, "count": len(rows)}
    for l in labels:
        if l not in known:
            a = assign[l] if isinstance(assign[l], dict) else {"person": assign[l]}
            kind = a.get("kind") if a.get("kind") in KINDS else "budget"
            known[l] = conn.execute("INSERT INTO accounts(bank,label,person_id,kind) VALUES(?,?,?,?)", (bank, l, int(a["person"]), kind)).lastrowid
    imp = conn.execute("INSERT INTO imports(filename,bank,created,added,duplicates) VALUES(?,?,?,0,0)",
                       (filename, bank, datetime.now().isoformat(timespec="seconds"))).lastrowid
    c = Categorizer(conn)
    src = rows[0].get("fmt", "csv")
    first_day = min(r["date"] for r in rows)
    seen, added, dup, updated = {}, 0, 0, 0
    claimed, fresh = set(), []
    for r in rows:      # 1. przebieg: transakcje znane co do joty
        acc = known[r["account"]]
        key = (acc, r["date"], r["amount"], norm(r["description"]), norm(r["counterparty"]))
        seen[key] = seen.get(key, 0) + 1          # numer kolejny identycznych operacji tego samego dnia
        r["_acc"], r["_hash"] = acc, hashlib.sha1(repr(key + (seen[key],)).encode()).hexdigest()
        old = conn.execute("SELECT id,balance FROM transactions WHERE hash=?", (r["_hash"],)).fetchone()
        if old:
            dup += 1
            claimed.add(old["id"])
            if r.get("balance") is not None and old["balance"] != r["balance"]:
                conn.execute("UPDATE transactions SET balance=? WHERE id=?", (r["balance"], old["id"]))
                updated += 1
        else:
            fresh.append(r)
    for r in fresh:     # 2. przebieg: ta sama operacja zapisana inaczej (inny układ pliku) albo naprawdę nowa
        acc = r["_acc"]
        dates = {d for d in (r["date"], r.get("booked")) if d}
        dates |= {f"{y}-{m}-{d}" for y, m, d in re.findall(r"(20\d\d)[-.](\d\d)[-.](\d\d)", r["description"] or "")}      # „Płatność kartą 2026-06-01”
        cands = [t for t in conn.execute("SELECT id,date,booked,src,description,counterparty FROM transactions WHERE account_id=? AND amount=? AND IFNULL(manual,0)=0 "
                                         "AND date BETWEEN date(?,'-5 day') AND date(?,'+5 day') ORDER BY id", (acc, r["amount"], r["date"], r["date"]))
                 if t["id"] not in claimed]
        twin = next((t for t in cands if t["date"] == r["date"]), None) or next((t for t in cands if t["date"] in dates or (t["booked"] and t["booked"] in dates)), None)
        if not twin and src != "csv":      # inny format pliku: data transakcji w CSV a data księgowania w MT940 – ta sama operacja, jeśli zgadza się opis
            mine = set(_words(norm(f"{r['counterparty']} {r['description']}"))) - STOP
            twin = next((t for t in sorted(cands, key=lambda t: abs((date.fromisoformat(t["date"]) - date.fromisoformat(r["date"])).days))
                         if (t["src"] or "csv") != src and t["date"] >= first_day and abs((date.fromisoformat(t["date"]) - date.fromisoformat(r["date"])).days) <= 4
                         and mine & (set(_words(norm(f"{t['counterparty'] or ''} {t['description'] or ''}"))) - STOP)), None)
        if twin:
            claimed.add(twin["id"])
            dup += 1
            conn.execute("UPDATE transactions SET hash=?, balance=IFNULL(?,balance), booked=IFNULL(booked,?) WHERE id=?", (r["_hash"], r.get("balance"), r.get("booked"), twin["id"]))
            updated += r.get("balance") is not None
            continue
        cid, csrc = c.match(f"{r['counterparty']} {r['description']}", r["amount"], r["bank_category"], merchant(r["description"], r["counterparty"]))
        claimed.add(conn.execute("INSERT INTO transactions(account_id,date,amount,currency,description,counterparty,bank_category,category_id,cat_source,hash,import_id,balance,booked,src) "
                                 "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (acc, r["date"], r["amount"], r["currency"], r["description"], r["counterparty"],
                                                                        r["bank_category"], cid, csrc, r["_hash"], imp, r.get("balance"), r.get("booked"), src)).lastrowid)
        added += 1
    conn.execute("UPDATE imports SET added=?, duplicates=? WHERE id=?", (added, dup, imp))
    conn.commit()
    apply_settlement_categories(conn)
    transfers = detect_internal(conn)
    dates = [r["date"] for r in rows]
    return {"bank": bank, "added": added, "duplicates": dup, "updated": updated, "skipped": skipped, "transfers": transfers,
            "from": min(dates), "to": max(dates), "accounts": labels}


# ---------- rozliczenia: grupy transakcji, które mają się zerować (opłata i jej zwrot) ----------
def _matcher(patterns):
    pats = [norm(p) for p in re.split(r"[\n;]+", patterns or "") if len(norm(p)) >= 3]
    if not pats:
        return lambda text: False
    rx = re.compile("|".join(r"(?<![A-Z0-9])" + re.escape(p).replace(r"\ ", r"\s+") for p in pats))
    return lambda text: bool(rx.search(text))


def settlement_members(conn, patterns, person=None):
    m = _matcher(patterns)
    q = ("SELECT t.id,t.date,t.amount,t.description,t.counterparty,t.note,a.person_id,a.bank,a.label FROM transactions t "
         "JOIN accounts a ON a.id=t.account_id" + (" WHERE a.person_id=?" if person else "") + " ORDER BY t.date,t.id")
    return [dict(r) for r in conn.execute(q, [person] if person else []) if m(norm(f"{r['counterparty'] or ''} {r['description'] or ''}"))]


def picked_members(conn, sid, person=None):
    """Transakcje wskazane ręcznie w rozliczeniu."""
    q = ("SELECT t.id,t.date,t.amount,t.description,t.counterparty,t.note,a.person_id,a.bank,a.label FROM settlement_items i "
         "JOIN transactions t ON t.id=i.transaction_id JOIN accounts a ON a.id=t.account_id WHERE i.settlement_id=?"
         + (" AND a.person_id=?" if person else "") + " ORDER BY t.date,t.id")
    return [dict(r) for r in conn.execute(q, [sid, person] if person else [sid])]


def all_members(conn, s, person=None):
    rows = {t["id"]: t for t in (settlement_members(conn, s["patterns"], person) if (s["patterns"] or "").strip() else [])}
    for t in picked_members(conn, s["id"], person):
        rows[t["id"]] = t
    return sorted(rows.values(), key=lambda t: (t["date"], t["id"]))


def pair_up(members, window, last_day):
    """Łączy każde obciążenie ze zwrotem na tę samą kwotę, który przyszedł w ciągu `window` dni (albo do 3 dni wcześniej)."""
    charges = [t for t in members if t["amount"] < 0]
    refunds = [t for t in members if t["amount"] > 0]
    used = set()
    for ch in charges:
        d = date.fromisoformat(ch["date"])
        best = None
        for rf in refunds:
            gap = (date.fromisoformat(rf["date"]) - d).days
            if rf["id"] not in used and rf["amount"] == -ch["amount"] and -3 <= gap <= window and (best is None or abs(gap) < abs(best[1])):
                best = (rf, gap)
        if best:
            used.add(best[0]["id"])
            ch["status"], ch["pair"] = "settled", dict(id=best[0]["id"], date=best[0]["date"], days=best[1])
        else:      # zwrot może jeszcze przyjść, jeśli od obciążenia do końca danych minęło mniej niż okno
            ch["status"] = "waiting" if (date.fromisoformat(last_day) - d).days <= window else "missing"
    for rf in refunds:
        rf["status"] = "refund" if rf["id"] in used else "extra"
    return charges, refunds


def settlements_report(conn, dfrom=None, dto=None, person=None):
    last_day = conn.execute("SELECT MAX(date) FROM transactions").fetchone()[0] or date.today().isoformat()
    cats = {r["id"]: r["name"] for r in conn.execute("SELECT id,name FROM categories")}
    out = []
    for s in conn.execute("SELECT * FROM settlements ORDER BY name").fetchall():
        if (s["mode"] or "auto") == "manual":      # zestaw wskazany ręcznie: liczy się suma, kwoty nie muszą być parami równe
            members = all_members(conn, s, person)
            costs, refunds = [t for t in members if t["amount"] < 0], [t for t in members if t["amount"] > 0]
            bal = sum(t["amount"] for t in members)
            latest = max((t["date"] for t in costs), default=None)
            status = ("settled" if bal == 0 else "extra" if bal > 0 else
                      "waiting" if latest and (date.fromisoformat(last_day) - date.fromisoformat(latest)).days <= (s["window"] or 40) else "missing")
            in_period = any((not dfrom or t["date"] >= dfrom) and (not dto or t["date"] <= dto) for t in members)
            out.append(dict(id=s["id"], mode="manual", name=s["name"], patterns="", category_id=s["category_id"], category=cats.get(s["category_id"]),
                            window=s["window"] or 40, count=len(members), balance=bal, status=status, in_period=in_period or not members,
                            costs=costs, refunds=refunds, cost_sum=-sum(t["amount"] for t in costs), refund_sum=sum(t["amount"] for t in refunds),
                            missing=int(status == "missing"), waiting=int(status == "waiting"), extra=int(status == "extra"),
                            missing_in_period=int(status == "missing" and in_period), months=[], items=[t["id"] for t in members]))
            continue
        members = all_members(conn, s, person)
        charges, refunds = pair_up(members, s["window"] or 40, last_day)
        months = {}
        for ch in charges:
            m = months.setdefault(ch["date"][:7], dict(month=ch["date"][:7], charged=0, refunded=0, open=0, extra=0, items=[]))
            m["charged"] += -ch["amount"]
            if ch["status"] == "settled":
                m["refunded"] += -ch["amount"]
            else:
                m["open"] += -ch["amount"]
            m["items"].append(ch)
        for rf in refunds:
            if rf["status"] == "extra":
                m = months.setdefault(rf["date"][:7], dict(month=rf["date"][:7], charged=0, refunded=0, open=0, extra=0, items=[]))
                m["extra"] += rf["amount"]
                m["items"].append(rf)
        rows = sorted(months.values(), key=lambda m: m["month"], reverse=True)
        for m in rows:
            st = {i["status"] for i in m["items"]}
            m["status"] = "missing" if "missing" in st else "waiting" if "waiting" in st else "extra" if "extra" in st else "settled"
        shown = [m for m in rows if (not dfrom or m["month"] >= dfrom[:7]) and (not dto or m["month"] <= dto[:7])]
        out.append(dict(id=s["id"], mode="auto", name=s["name"], patterns=s["patterns"], category_id=s["category_id"], category=cats.get(s["category_id"]),
                        window=s["window"] or 40, count=len(members), balance=sum(t["amount"] for t in members),
                        missing=sum(1 for c in charges if c["status"] == "missing"), waiting=sum(1 for c in charges if c["status"] == "waiting"),
                        extra=sum(1 for r in refunds if r["status"] == "extra"),
                        missing_in_period=sum(1 for m in shown for i in m["items"] if i["status"] == "missing"), months=shown))
    return out


def apply_settlement_categories(conn):
    """Transakcje z rozliczenia, które ma ustawioną kategorię, dostają ją (o ile użytkownik nie wybrał innej ręcznie)."""
    for s in conn.execute("SELECT * FROM settlements WHERE category_id IS NOT NULL").fetchall():
        kind = (conn.execute("SELECT kind FROM categories WHERE id=?", (s["category_id"],)).fetchone() or {"kind": None})["kind"]
        for t in all_members(conn, s):
            if sign_ok(kind, t["amount"]):      # kategoria wydatku tylko dla kosztów, przychodu tylko dla wpływów
                conn.execute("UPDATE transactions SET category_id=?, cat_source='group' WHERE id=? AND IFNULL(cat_source,'')!='manual'", (s["category_id"], t["id"]))
    conn.commit()


def refresh_settlement_categories(conn):
    conn.execute("UPDATE transactions SET category_id=NULL, cat_source=NULL WHERE cat_source='group'")
    conn.commit()
    recategorize(conn)
    apply_settlement_categories(conn)
    detect_internal(conn)


def settlement_suggestions(conn):
    """Podpowiedzi: wpływy z „ZWROT” w opisie, które nie należą jeszcze do żadnego rozliczenia."""
    matchers = [_matcher(s["patterns"]) for s in conn.execute("SELECT patterns FROM settlements") if (s["patterns"] or "").strip()]
    seen, out = set(), []
    for r in conn.execute("SELECT description,counterparty FROM transactions WHERE amount>0 ORDER BY date DESC"):
        text = norm(f"{r['counterparty'] or ''} {r['description'] or ''}")
        if "ZWROT" not in text or any(m(text) for m in matchers):
            continue
        core = re.sub(r"ZWROT\w*|OPLAT\w*|OPL\.?|PROWIZJ\w*|PRZELEW\w*|\d{2}[./-]\d{2}[./-]\d{2,4}|\b\d+\b", " ", text)
        words = [w for w in core.split() if len(w) >= 3][:3]
        phrase = " ".join(words)
        if len(phrase) >= 4 and phrase not in seen:
            seen.add(phrase)
            out.append(dict(phrase=phrase, example=clean(r["description"])[:80]))
        if len(out) >= 4:
            break
    return out


# ---------- analiza ----------
def entries(conn, dfrom=None, dto=None, person=None):
    """Lista pozycji budżetu. Transakcja z podpiętym paragonem jest rozbijana na pozycje paragonu."""
    q = ("SELECT t.id,t.date,t.amount,t.description,t.counterparty,t.category_id,a.person_id FROM transactions t "
         "JOIN accounts a ON a.id=t.account_id WHERE IFNULL(a.kind,'budget') IN ('budget','cash')")      # konta poza budżetem nie wchodzą do zestawień
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
    span = (date.fromisoformat(dto).year - date.fromisoformat(dfrom).year) * 12 + date.fromisoformat(dto).month - date.fromisoformat(dfrom).month + 1
    months = month_range(date.fromisoformat(dto), max(12, min(span, 120)))      # wykres miesięczny obejmuje cały wybrany zakres (do 10 lat)
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
    sav = cat_id(conn, "Oszczędności i inwestycje")
    atm = cat_id(conn, "Gotówka") if atm_feeds_cash(conn) else None      # wypłata z bankomatu zostaje w budżecie (w portfelu)
    moved = sum(e["amount"] for e in sel if kind(e) == "transfer" and e["category"] != atm)
    return dict(flow=dict(budget_flow(conn, dfrom, dto, person), transfers=moved), period={"from": dfrom, "to": dto, "months": n_months}, income=inc, expense=exp, balance=inc - exp,
                saved=-sum(e["amount"] for e in sel if sav and e["category"] == sav),      # przelane na konta poza budżetem (minus wypłaty z nich)
                count=len({e["tx"] for e in sel}),
                uncategorized=sum(1 for e in sel if e["category"] is None),
                expense_by_category=expense_rows, income_by_category=by_cat("income"),
                monthly=[dict(month=r["month"], income=r["income"], expense=r["expense"],
                              people=[dict(id=k, **v) for k, v in r["people"].items()]) for r in monthly],
                people=per, merchants=[dict(name=a, amount=b, count=c) for a, b, c in merchants])
