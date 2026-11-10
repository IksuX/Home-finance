"""Paragony: odczyt tekstu (OCR) i rozbijanie na pozycje."""
import json, os, re, shutil, subprocess
from datetime import date, timedelta
import core
from core import norm

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.environ.get("PATH", "") + ":/opt/homebrew/bin:/usr/local/bin"

STORES = ["BIEDRONKA", "LIDL", "KAUFLAND", "AUCHAN", "CARREFOUR", "ZABKA", "ROSSMANN", "HEBE", "DINO", "STOKROTKA", "NETTO", "ALDI",
          "LEWIATAN", "SPOLEM", "INTERMARCHE", "ORLEN", "SHELL", "CIRCLE K", "CASTORAMA", "LEROY MERLIN", "IKEA", "PEPCO", "ACTION",
          "DECATHLON", "MEDIA EXPERT", "EMPIK", "SMYK", "JYSK", "OBI", "TOPAZ", "POLOMARKET", "SUPER-PHARM", "APTEKA", "MCDONALD", "KFC"]
STORE_CATEGORY = {"ROSSMANN": "Kosmetyki i higiena", "HEBE": "Kosmetyki i higiena", "ORLEN": "Paliwo", "SHELL": "Paliwo", "CIRCLE K": "Paliwo",
                  "CASTORAMA": "Dom i ogród", "LEROY MERLIN": "Dom i ogród", "IKEA": "Dom i ogród", "JYSK": "Dom i ogród", "OBI": "Dom i ogród",
                  "PEPCO": "Dom i ogród", "ACTION": "Dom i ogród", "DECATHLON": "Sport", "MEDIA EXPERT": "Elektronika", "EMPIK": "Rozrywka i kultura",
                  "SMYK": "Dzieci", "SUPER-PHARM": "Zdrowie", "APTEKA": "Zdrowie", "MCDONALD": "Restauracje i kawiarnie", "KFC": "Restauracje i kawiarnie"}
ITEM_WORDS = {  # początki słów na paragonach (skróty kasowe, bez polskich znaków); spacja na końcu = całe słowo; kolejność ma znaczenie
    "Dzieci": "PIELUCH,PAMPERS,DADA ,BOBOVITA,GERBER,HIPP ,MLEKO MODYF,ZABAWK,SMOCZEK",
    "Paliwo": "PB95,PB 95,PB98,DIESEL,LPG ,BENZYNA,VERVA,EFECTA,OLEJ NAP",
    "Zwierzęta": "KARMA,WHISKAS,PEDIGREE,ZWIREK,FELIX ,SHEBA,PURINA",
    "Zakupy spożywcze": "SER ,SEREK,MLEKO,JOGURT,MASLO,SMIETAN,KEFIR,TWAROG,JAJ,CHLEB,BULK,BAGIETK,SZYNK,KIELBAS,PAROWK,BOCZEK,MIESO,KURCZAK,FILET,SCHAB,LOSOS,SLEDZ,TUNCZYK,MAKARON,RYZ ,MAKA ,KASZA,CUKIER ,OLEJ ,OLIWA,OCET,POMIDOR,OGOREK,ZIEMNIAK,CEBULA,MARCHEW,PAPRYK,SALATA,JABLK,BANAN,CYTRYN,POMARANCZ,WINOGRON,TRUSKAW,KETCHUP,MUSZTARD,MAJONEZ,DZEM,MIOD ,PLATKI SN,MUSLI,PIEROGI,PIZZA,ZUPA",
    "Alkohol": "PIWO,WINO ,WODKA,WHISK,LIKIER,CYDR,PROSECCO,SZAMPAN ,RUM ,GIN ,NALEWKA,ZUBR,TYSKIE,LECH ,PERLA,HARNAS,TATRA ,DESPERADOS,HEINEKEN,CARLSBERG,ZUBROWKA,ZOLADKOWA,KSIAZECE,OKOCIM",
    "Napoje": "WODA,SOK ,NAPOJ,COLA,COCA,PEPSI,FANTA,SPRITE,TYMBARK,HORTEX,KAWA,HERBATA,NEKTAR,OSHEE,ENERGY,TIGER,RED BULL,MONSTER,LEMONIADA,KUBUS,CISOWIANKA,ZYWIEC ZDR,MUSZYNIANKA,NALECZOWIANKA",
    "Słodycze i przekąski": "CZEKOLAD,BATON,CUKIERK,CIASTK,CIASTO,CHIPS,CHRUPK,PALUSZK,ZELKI,LODY,WAFEL,WAFL,LIZAK,GUMA ,PRALIN,HERBATNIK,KRAKERS,ORZESZK,POPCORN,MILKA,WEDEL,HARIBO,KINDER,SNICKERS,LAYS,PRINCE POLO,DELICJE,NUTELLA,DRAZE,PIERNIK,PACZEK,DROZDZOWK",
    "Chemia domowa": "DOMESTOS,PLYN,PROSZEK DO,KAPSULK,TABLETKI DO,TABL DO,ODPLAMIACZ,WYBIELACZ,PAPIER TOAL,PAP.TOAL,RECZNIK PAP,RECZ.PAP,WORKI,GABKA,GABKI,SCIERK,ODSWIEZACZ,FAIRY,LUDWIK,PERSIL,VIZIR,ARIEL,LENOR,FINISH,CIF ,AJAX,ZMYWAK,FOLIA,CHUSTECZKI,TORBA,REKLAMOWKA",
    "Kosmetyki i higiena": "SZAMPON,MYDLO,ZEL POD,ZEL DO,PASTA DO Z,SZCZOTECZK,DEZODORANT,ANTYPERSP,KREM DO,KREM NA,BALSAM,PODPASKI,TAMPON,MASZYNK,GOLENI,PATYCZKI,WACIKI,PLATKI KOSM,ODZYWKA,PERFUM,NIVEA,DOVE ,COLGATE,ELMEX,GILLETTE",
    "Zdrowie": "IBUPROM,APAP,WITAMIN,PLASTRY OPATR,KROPLE DO",
    "Odzież i obuwie": "SKARPET,KOSZULK,SPODNIE,BLUZA,KURTKA,BUTY ,RAJSTOP,BIELIZN,T-SHIRT",
    "Dom i ogród": "ZAROWK,BATERI,SWIEC,DONICZK,ZIEMIA ,NAWOZ,GARNEK,PATELN,TALERZ,KUBEK",
}
PRICE = r"-?\d{1,5}\s?[.,]\s?\d{2}"
QTY = r"(?P<qty>\d{1,4}(?:\s?[.,]\s?\d{1,3})?)\s*(?:SZT\.?|KG|L|OP\.?|G)?\s*[X×*]\s*(?P<unit>" + PRICE + r")\s*=?\s*(?P<total>" + PRICE + r")\s*(?P<vat>[A-G])?"
RX_FULL = re.compile(r"^(?P<name>.+?)\s+" + QTY + r"$", re.I)
RX_QTY = re.compile(r"^" + QTY + r"$", re.I)
RX_SIMPLE = re.compile(r"^(?P<name>.*[A-Za-z]{2}.*?)\s+(?P<total>" + PRICE + r")\s*(?P<vat>[A-G])?$")
RX_END = re.compile(r"SPRZED\w*\.?\s*OPOD|SUMA PTU|^PTU\b|SUMA\s*(PLN)?\s*:?\s*\d|^SUMA\b|^RAZEM|DO ZAPLATY|PODSUMA")
RX_TOTAL = re.compile(r"(?:SUMA\s*(?:PLN)?|DO ZAPLATY|RAZEM(?:\s*PLN)?)\s*:?\s*(" + PRICE + ")")
RX_DISCOUNT = re.compile(r"RABAT|OPUST|UPUST|OBNIZKA|PROMOCJA")


def money(s):
    return int(round(float(re.sub(r"\s", "", s).replace(",", ".")) * 100))


# ---------- OCR ----------
def _run(cmd, timeout=120):
    return subprocess.run(cmd, capture_output=True, timeout=timeout, env=dict(os.environ, PATH=PATH))


def _vision_cmd():
    """Zwraca polecenie uruchamiające pomocnika Vision (kompiluje go przy pierwszym użyciu)."""
    if os.uname().sysname != "Darwin":
        return None
    src, binary = os.path.join(HERE, "ocr.swift"), os.path.join(core.DATA_DIR, "ocr-helper")
    if os.path.exists(binary) and os.path.getmtime(binary) >= os.path.getmtime(src):
        return [binary]
    try:
        if _run(["xcode-select", "-p"], 10).returncode != 0:
            return None
        r = _run(["xcrun", "swiftc", "-O", src, "-o", binary], 300)
        if r.returncode == 0:
            return [binary]
        return ["xcrun", "swift", src]
    except Exception:
        return None


def engine_status():
    if os.uname().sysname == "Darwin":
        try:
            if _run(["xcode-select", "-p"], 10).returncode == 0:
                return {"engine": "vision", "ok": True}
        except Exception:
            pass
    if shutil.which("tesseract", path=PATH):
        return {"engine": "tesseract", "ok": True}
    return {"engine": None, "ok": False}


def make_preview(src, dst):
    """Podgląd JPG do wyświetlania w przeglądarce (HEIC i PDF nie wszędzie się wyświetlają)."""
    try:
        if os.uname().sysname == "Darwin":
            if _run(["sips", "-s", "format", "jpeg", "-Z", "2400", src, "--out", dst], 60).returncode == 0:
                return True
        if src.lower().endswith(".pdf") and shutil.which("pdftoppm", path=PATH):
            if _run(["pdftoppm", "-jpeg", "-r", "200", "-singlefile", src, dst[:-4]], 60).returncode == 0:
                return True
        from PIL import Image, ImageOps
        ImageOps.exif_transpose(Image.open(src)).convert("RGB").save(dst, "JPEG", quality=88)
        return True
    except Exception:
        return False


def ocr(path, preview=None):
    """Zwraca (fragmenty tekstu z położeniem, nazwa silnika)."""
    cmd = _vision_cmd()
    if cmd:
        try:
            r = _run(cmd + [path])
            if r.returncode == 0:
                return json.loads(r.stdout)["lines"], "vision"
        except Exception:
            pass
    if shutil.which("tesseract", path=PATH):
        img = preview if preview and os.path.exists(preview) else path
        r = _run(["tesseract", img, "stdout", "-l", "pol", "--psm", "6", "tsv"])
        if r.returncode != 0:
            r = _run(["tesseract", img, "stdout", "--psm", "6", "tsv"])
        if r.returncode == 0:
            frags, W, H = [], 1, 1
            for line in r.stdout.decode("utf-8", "replace").splitlines()[1:]:
                c = line.split("\t")
                if len(c) < 12:
                    continue
                if c[0] == "1":
                    W, H = max(1, int(c[8])), max(1, int(c[9]))
                elif c[0] == "5" and c[11].strip():
                    frags.append(dict(text=c[11], x=int(c[6]) / W, y=int(c[7]) / H, w=int(c[8]) / W, h=int(c[9]) / H))
            return frags, "tesseract"
    return None, None


def to_rows(frags):
    """Skleja fragmenty leżące na tej samej wysokości w wiersze (nazwa po lewej, cena po prawej)."""
    frags = sorted((f for f in frags if f["text"].strip()), key=lambda f: f["y"] + f["h"] / 2)
    if not frags:
        return []
    hs = sorted(f["h"] for f in frags)
    tol = hs[len(hs) // 2] * 0.55
    rows, cur, cy = [], [], None
    for f in frags:
        c = f["y"] + f["h"] / 2
        if cy is not None and abs(c - cy) > tol:
            rows.append(cur); cur = []
        cur.append(f)
        cy = c if len(cur) == 1 else (cy * (len(cur) - 1) + c) / len(cur)
    rows.append(cur)
    return [" ".join(f["text"] for f in sorted(r, key=lambda f: f["x"])) for r in rows]


# ---------- rozumienie paragonu ----------
def parse_receipt(rows):
    N = [norm(r) for r in rows]
    text = "\n".join(N)
    res = dict(store="", date=None, total=0, payment=None, items=[])
    head = "\n".join(N[:10])
    res["store"] = next((s for s in STORES if s in head), None) or next((s for s in STORES if s in text), None) \
        or next((rows[i].strip() for i in range(min(6, len(rows))) if len(re.findall(r"[A-Za-z]", rows[i])) >= 3), "")
    res["store"] = res["store"].title() if res["store"].isupper() else res["store"]
    for m in re.finditer(r"(\d{4})[-./](\d{2})[-./](\d{2})|(\d{2})[-./](\d{2})[-./](\d{4})", text):
        y, mo, d = (m.group(1), m.group(2), m.group(3)) if m.group(1) else (m.group(6), m.group(5), m.group(4))
        try:
            dt = date(int(y), int(mo), int(d))
            if 2015 <= dt.year <= date.today().year + 1:
                res["date"] = dt.isoformat(); break
        except ValueError:
            pass
    for n in N:
        if "PTU" in n:
            continue
        m = RX_TOTAL.search(n)
        if m:
            res["total"] = abs(money(m.group(1)))
    if re.search(r"KARTA|KARTĄ|BLIK|BEZGOT", text):
        res["payment"] = "card"
    elif "GOTOWKA" in text:
        res["payment"] = "cash"

    start = next((i + 1 for i, n in enumerate(N) if "PARAGON" in n and "FISK" in n), 0)
    pending = None
    for raw, n in zip(rows[start:], N[start:]):
        if RX_END.search(n):
            break
        line = re.sub(r"\s+", " ", raw).strip()
        line = re.sub(r"(\d)\s?([.,])\s?(\d{2})(?!\d)", r"\1,\3", line)
        if RX_DISCOUNT.search(n):
            m = re.search(PRICE, line)
            if m and res["items"]:
                res["items"][-1]["amount"] -= abs(money(m.group(0)))
            pending = None
            continue
        m = RX_FULL.match(line)
        if m:
            name = m.group("name")
        else:
            m = RX_QTY.match(line)
            if m:
                name = pending or ""
            else:
                m = RX_SIMPLE.match(line)
                if not m:
                    pending = line if re.search(r"[A-Za-z]{3}", line) else None
                    continue
                name = m.group("name")
                if pending and len(name) < 3:
                    name = pending
        pending = None
        total = money(m.group("total"))
        gd = m.groupdict()
        qty = float(re.sub(r"\s", "", gd["qty"]).replace(",", ".")) if gd.get("qty") else 1.0
        unit = money(gd["unit"]) if gd.get("unit") else total
        name = re.sub(r"\s+[A-Ga-g]$", "", name.strip()) if gd.get("qty") or not gd.get("vat") else name.strip()
        name = name.strip(" .:-_|")
        if not name or total == 0:
            continue
        res["items"].append(dict(name=name, qty=qty, unit_price=unit, amount=total))
    if not res["total"]:
        res["total"] = sum(i["amount"] for i in res["items"])
    return res


def item_category(conn, name, store):
    n = norm(name)
    r = conn.execute("SELECT category_id FROM item_rules WHERE name=?", (n,)).fetchone()
    if r:
        return r["category_id"]
    for cat, words in ITEM_WORDS.items():
        for w in words.split(","):
            if re.search(r"(?<![A-Z])" + re.escape(w.strip()) + (r"(?![A-Z])" if w.endswith(" ") else ""), n):
                return core.cat_id(conn, cat)
    s = norm(store)
    for k, cat in STORE_CATEGORY.items():
        if k in s:
            return core.cat_id(conn, cat)
    return core.cat_id(conn, "Zakupy spożywcze")


def match_transactions(conn):
    """Łączy paragony z transakcjami kartą: ta sama kwota, data paragonu do 4 dni przed księgowaniem."""
    n = 0
    for r in conn.execute("SELECT * FROM receipts WHERE transaction_id IS NULL AND date IS NOT NULL AND total>0 AND IFNULL(payment,'')!='cash'").fetchall():
        d = date.fromisoformat(r["date"])
        cands = conn.execute("SELECT t.id,t.description,t.counterparty,t.date FROM transactions t WHERE t.amount=? AND t.date BETWEEN ? AND ? "
                             "AND t.id NOT IN (SELECT transaction_id FROM receipts WHERE transaction_id IS NOT NULL) ORDER BY t.date",
                             (-r["total"], (d - timedelta(days=1)).isoformat(), (d + timedelta(days=4)).isoformat())).fetchall()
        if not cands:
            continue
        key = norm(r["store"]).split(" ")[0] if r["store"] else ""
        best = next((c for c in cands if key and key in norm(f"{c['description']} {c['counterparty']}")), cands[0] if len(cands) == 1 else None)
        if best:
            conn.execute("UPDATE receipts SET transaction_id=? WHERE id=?", (best["id"], r["id"]))
            n += 1
    conn.commit()
    return n
