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
    "Kaucja za opakowania": "KAUCJ,OPAK BEZ KAUCJI,OPAKOWANIE ZWROTNE",
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
FLEX = r"\d{1,5}\s?[.,]\s?\d{1,2}"          # w aplikacjach sklepów zdarza się "2.9" zamiast "2,90"
QTY = (r"(?P<qty>\d{1,4}(?:\s?[.,]\s?\d{1,3})?)\s*(?:SZT\.?|KG|L|OP\.?|G)?\s*[X×*＊•]\s*(?P<unit>" + FLEX + r")\s*=?\s*(?P<total>-?\s?" + FLEX
       + r")\s*(?P<vat>[A-G])?")
RX_FULL = re.compile(r"^(?P<name>.+?)\s+" + QTY + r"$", re.I)
RX_QTY = re.compile(r"^" + QTY + r"$", re.I)
RX_SIMPLE = re.compile(r"^(?P<name>.*[A-Za-z]{2}.*?)\s+(?P<total>" + PRICE + r")\s*(?P<vat>[A-G])?$")
RX_END = re.compile(r"SPRZED\w*\.?\s*OPOD|SUMA PTU|^PTU\b|^KWOTA [A-G]\b|SUMA\s*(PLN)?\s*:?\s*\d|^SUMA\b|^RAZEM|DO ZAPLATY|PODSUMA|^PLATNOSC")
RX_DEPOSIT = re.compile(r"OPAKOWANIA ZWROTNE|^KAUCJ|ZWROT KAUCJI")
RX_TOTAL = re.compile(r"(?:SUMA\s*(?:PLN)?|DO ZAPLATY|RAZEM(?:\s*PLN)?)\s*:?\s*(" + PRICE + ")")


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
        direct = path.lower().endswith((".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"))      # oryginał daje lepszy odczyt niż podgląd JPG
        img = path if direct or not (preview and os.path.exists(preview)) else preview
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
    """Skleja fragmenty tekstu w wiersze (nazwa po lewej, cena po prawej). Porównuje wysokość z najbliższym
    w poziomie fragmentem wiersza, więc radzi sobie także z lekko przekrzywionym zdjęciem."""
    frags = [dict(f, c=f["y"] + f["h"] / 2, text=re.sub(r"[ØøΘθ]", "0", f["text"])) for f in frags if f["text"].strip()]   # przekreślone zero
    frags.sort(key=lambda f: (round(f["c"], 3), f["x"]))
    rows = []
    for f in sorted(frags, key=lambda f: f["x"]):
        best, bd = None, None
        for r in rows:
            near = min(r, key=lambda g: abs((g["x"] + g["w"]) - f["x"]))
            d = abs(near["c"] - f["c"])
            if d < 0.6 * min(near["h"], f["h"]) and (bd is None or d < bd):
                best, bd = r, d
        if best is None:
            rows.append([f])
        else:
            best.append(f)
    rows.sort(key=lambda r: min(g["c"] for g in r))
    return [" ".join(g["text"] for g in sorted(r, key=lambda g: g["x"])) for r in rows]


# ---------- rozumienie paragonu ----------
RX_DISCOUNT = re.compile(r"RABAT|OPUST|UPUST|OBNIZ|ZNIZK|KUPON|PROMOC|LIDL PLUS|BONIFIK|TANIEJ|GRATIS")
RX_SAVED = re.compile(r"(?:SUMA RABAT\w*|RAZEM RABAT\w*|LACZN\w* RABAT\w*|RABAT\w* LACZN\w*|UDZIELON\w* RABAT\w*|ZAOSZCZEDZ\w*|OSZCZEDZASZ|OSZCZEDNOSC\w*)\D{0,30}?(" + PRICE + ")")
RX_NEG = re.compile(r"(?:-\s?(\d{1,5},\d{2})|(\d{1,5},\d{2})\s?-)\s*[A-G]?\s*$")
RX_CARD = re.compile(r"KARTA|KARTY|KARTĄ|LIDL PAY|PAY\b|VISA|MASTERCARD|MAESTRO|BLIK|BEZGOT|ZBLIZ|PLATNOSC ELEKTR|TERMINAL")


def _fix_signs(line):
    line = re.sub(r"(?<![^\W\d])Q?@(?=[,.]\d)|(?<=[\d,.])@|@(?=\d)", "0", line)   # „@,161”, „Q@,234”, „6@pr” – przekreślone zero jako @
    line = re.sub(r"(?<![^\W\d])[eEoO](?=,\d)", "0", line)        # „e,888kg” – zero odczytane jako litera
    line = re.sub(r"(?<=\s)=(?=\s?\d)", "-", line)                 # minus odczytany jako „=”
    return re.sub(r"(\d)[.,]{2,}\s?(\d)", r"\1,\2", line)            # „1.,51”


def tidy(line):
    """Ujednolica zapis: różne myślniki -> minus, '6, 98' -> '6,98', '6.98' -> '6,98'."""
    line = _fix_signs(re.sub(r"[–—−‒~]", "-", re.sub(r"\s+", " ", line)).strip())
    return re.sub(r"(\d)\s?([.,])\s?(\d{2})(?!\d)", r"\1,\3", line)


def find_date(text, hints=()):
    """Szuka daty: 2026-01-19, 19.01.2026, 19/01/26. Toleruje różne myślniki, odstępy i literę O zamiast zera."""
    text = re.sub(r"[–—−‒_]", "-", text)
    text = re.sub(r"(?<=\d)\s?([-./])\s?(?=\d)", r"\1", text)
    text = re.sub(r"(?<=[\d\-./])O(?=[\d\-./])", "0", text)

    def valid(y, mo, d):
        try:
            dt = date(int(y), int(mo), int(d))
            return dt.isoformat() if 2015 <= dt.year <= date.today().year + 1 else None
        except ValueError:
            return None

    def fix(v, limit):          # "81" zamiast "01": przekreślone zero bywa czytane jako 8
        return "0" + v[1] if len(v) == 2 and int(v) > limit and v[0] == "8" else v

    def scan(t):
        found = []
        for m in re.finditer(r"(?<!\d)(?:(2[08]\d{2})[-./](\d{1,2})[-./](\d{1,2})|(\d{1,2})[-./](\d{1,2})[-./](2[08]\d{2}))(?!\d)", t):
            y, mo, d = (m.group(1), m.group(2), m.group(3)) if m.group(1) else (m.group(6), m.group(5), m.group(4))
            exact = valid(y, mo, d)
            r = exact or valid("20" + y[2:], fix(mo, 12), fix(d, 31))
            if r:
                found.append((0 if exact else 1, r))
        for m in re.finditer(r"DATA\D{0,12}(\d{2})[-./](\d{2})[-./](\d{2})(?!\d)", t):      # potwierdzenie z terminala: 24/01/26
            r = valid("20" + m.group(3), m.group(2), m.group(1)) or valid("20" + m.group(3), fix(m.group(2), 12), fix(m.group(1), 31))
            if r:
                found.append((0, r))
        if found:
            dates = [r for _, r in found]
            return max(sorted(found), key=lambda f: (dates.count(f[1]), -f[0]))[1]      # data potwierdzona w dwóch miejscach wygrywa

    for h in hints:
        i = text.find(h)
        if i >= 0:
            r = scan(text[i:i + 80])
            if r:
                return r
    return scan(text)


def find_store(rows, N):
    text, head = "\n".join(N), "\n".join(N[:10])
    s = next((s for s in STORES if s in head), None) or next((s for s in STORES if s in text), None)
    if s:
        return s.title()
    return next((rows[i].strip() for i in range(min(6, len(rows))) if len(re.findall(r"[A-Za-z]", rows[i])) >= 3), "")


def total_candidates(N):
    """Wszystkie miejsca na paragonie, gdzie wydrukowano zapłaconą kwotę (płatność, potwierdzenie z terminala, Suma/Razem)."""
    P = "(" + PRICE + r")(?!\s?\d)"
    cands = []
    pay = (r"^PLATNOSC\b.*?" + P + r"\s*(?:PLN|ZL)?$", r"^KWOTA\s*:\s*" + P, r"(?:KARTA PLATNICZA|LIDL PAY|GOTOWKA|BLIK)\D*" + P)
    for n in N:      # każdy wiersz liczy się raz
        m = next((m for rx in pay for m in [re.search(rx, n)] if m and money(m.group(1)) > 0), None)
        if m:
            cands.append(money(m.group(1)))
    for i, n in enumerate(N):
        if re.search(r"^PLATNOSC\b|^KWOTA\s*:", n):
            continue
        if "PTU" in n or "RABAT" in n or "ZWROTNE" in n or (i and re.match(r"^KWOTA [A-H]\b", N[i - 1])):      # „Suma” pod tabelą VAT to suma podatku
            continue
        m = re.search(r"(?:SUMA\s*(?:PLN)?|DO ZAPLATY|RAZEM(?:\s*PLN)?)\s*:?\s*" + P, n)
        if m:
            cands.append(abs(money(m.group(1))))
        elif re.search(r"^(SUMA( PLN)?|DO ZAPLATY|RAZEM( PLN)?)\s*:?$", n) and i + 1 < len(N) and re.fullmatch(PRICE + r"\s*(PLN|ZL)?", N[i + 1]):
            cands.append(abs(money(re.match(PRICE, N[i + 1]).group(0))))      # kwota w osobnym wierszu pod napisem SUMA
    return [c for c in cands if c]


def find_total(N):
    """Kwota faktycznie zapłacona: wartość powtarzająca się najczęściej. Przy remisie między „107,90” a „187,98”
    wygrywa ta z mniejszą liczbą ósemek – przekreślone zero bywa czytane jako 8, odwrotnie prawie nigdy."""
    cands = total_candidates(N)
    if not cands:
        return 0
    ranked = sorted(set(cands), key=lambda c: (-cands.count(c), str(c).count("8"), -max(i for i, x in enumerate(cands) if x == c)))
    return ranked[0]


RX_LOOSE = re.compile(r"^(?P<qty>\d{1,4}(?:[.,]\d{1,3})?)\s*(?:KG|SZT\.?)?\s*%?\s*[X×*＊•].*?(?P<total>-?\s?" + FLEX + r")\s*[A-G]?$", re.I)


def zero_alts(v):
    """Warianty kwoty przy założeniu, że któraś ósemka (albo szóstka) to źle odczytane przekreślone zero."""
    t = str(abs(v)); pos = [i for i, c in enumerate(t) if c in "86"][:4]
    out = set()
    for mask in range(1, 1 << len(pos)):
        u = list(t)
        for k, p in enumerate(pos):
            if mask >> k & 1:
                u[p] = "0"
        out.add(int("".join(u)) * (1 if v >= 0 else -1))
    return sorted(out, key=lambda x: abs(x - v))


def fix_outlier_discounts(items):
    """Gdy na paragonie jest dużo rabatów o podobnym udziale w cenie (np. „Lidl Plus voucher” ≈ 7% każdej pozycji),
    rabat wielokrotnie większy, który po zamianie 8/6 na 0 wraca do typowego udziału, jest poprawiany."""
    ratios = sorted(d / (it["amount"] + it["discount"]) for it in items for d in it.get("disc_lines", [])
                    if it["amount"] + it["discount"] > 0 and d / (it["amount"] + it["discount"]) < 0.3)
    if len(ratios) < 5:
        return
    med = ratios[len(ratios) // 2]
    for it in items:
        gross = it["amount"] + it["discount"]
        for j, d in enumerate(it.get("disc_lines", [])):
            if gross > 0 and d / gross > 0.4:
                fit = [a for a in zero_alts(d) if 0.6 * med <= a / gross <= 1.6 * med]
                if fit:
                    it["disc_lines"][j] = fit[0]
                    it["discount"] += fit[0] - d
                    it["amount"] -= fit[0] - d


def repair_amounts(res):
    """Gdy pozycje nie sumują się do zapłaconej kwoty, szuka pojedynczej lub podwójnej zamiany 8->0, która to naprawia."""
    items = res["items"]
    locked = set()
    for k, it in enumerate(items):          # najpierw spójność wiersza: ilość x cena = wartość
        gross = it["amount"] + it["discount"]
        ok = lambda q, u, g: abs(round(q * u) - g) <= 1
        if ok(it["qty"], it["unit_price"], gross):
            locked.add(k)
            continue
        qtys = [it["qty"]] + ([round(it["qty"] - 8, 3)] if 8 <= it["qty"] < 9 else [])      # waga "0,611" odczytana jako "8,611"
        fix = next(((q, u, g) for g in [gross] + zero_alts(gross) for q in qtys for u in [it["unit_price"]] + zero_alts(it["unit_price"]) if ok(q, u, g)), None)
        if fix:
            it["qty"], it["unit_price"], it["amount"] = fix[0], fix[1], fix[2] - it["discount"]
            locked.add(k)
    total = res["total"]
    need = total - sum(i["amount"] for i in items)
    if not total or need == 0:
        return
    moves = []                               # (pozycja, pole, nowa wartość, zmiana sumy pozycji, koszt)
    for k, it in enumerate(items):
        if it["discount"]:
            moves += [(k, "discount", d, it["discount"] - d, 1) for d in zero_alts(it["discount"]) + (it.get("disc_alts") or [])]
        if k not in locked and not it.get("alts"):
            moves += [(k, "amount", a, a - it["amount"], 1.5) for a in zero_alts(it["amount"]) if a > 0]
        for q, u, t, c in it.get("alts") or []:
            moves.append((k, "alt", (q, u, t), (t - it["discount"]) - it["amount"], c))
    singles = sorted((m for m in moves if m[3] == need), key=lambda m: m[4])
    pick = singles[:1]
    if not pick:      # do czterech poprawek w różnych pozycjach: pary sum w słowniku, potem łączenie
        pairs = {}
        for i, x in enumerate(moves):
            for y in moves[i + 1:]:
                if x[0] != y[0]:
                    pairs.setdefault(x[3] + y[3], []).append((x[4] + y[4], [x, y]))
        best = min(pairs.get(need, []), key=lambda p: p[0], default=None)
        if not best:
            for x in moves:
                for c, pr in pairs.get(need - x[3], []):
                    if x[0] not in (pr[0][0], pr[1][0]) and (best is None or c + x[4] < best[0]):
                        best = (c + x[4], [x] + pr)
        if not best and len(moves) <= 120:
            for sm, lst in pairs.items():
                for c1, p1 in lst:
                    for c2, p2 in pairs.get(need - sm, []):
                        ks = {m[0] for m in p1 + p2}
                        if len(ks) == 4 and (best is None or c1 + c2 < best[0]):
                            best = (c1 + c2, p1 + p2)
        pick = best[1] if best else None
    for k, field, val, _, _c in pick or []:
        if field == "alt":
            items[k]["qty"], items[k]["unit_price"], items[k]["amount"] = val[0], val[1], val[2] - items[k]["discount"]
        elif field == "discount":
            items[k]["amount"] += items[k]["discount"] - val
            items[k]["discount"] = val
        else:
            items[k]["amount"] = val


# ---------- wiersz pozycji „nazwa  ilość * cena  wartość  VAT” odporny na błędy odczytu ----------
RX_ITEM = re.compile(r"^(?P<name>.*?)\s*(?<![\d,.])(?P<qty>\d{1,4}(?:[.,]\d{1,3})?)\s*(?:KG|SZT\.?|OP\.?|L)?\s*%?\s*[X×*＊•]\s*"
                     r"(?P<nums>-?\d[\d\s.,\-]*?)\s*(?:(?<=\d)[A-H]|\s[A-H0O©®@&]|[©®])?\s*$", re.I)


def _num_variants(s, money_fmt=True):
    """Możliwe prawdziwe wartości liczby odczytanej z błędem: ósemka zamiast zera (przekreślone 0 w czcionce paragonu)
    i jeden nadmiarowy znak. Zwraca {wartość w groszach lub tysięcznych: liczba poprawek}."""
    s = s.replace(".", ",").strip()
    pat = r"\d{1,5},\d{1,2}" if money_fmt else r"\d{1,4}(?:,\d{1,3})?"
    seeds = {s: 0}
    for i in range(len(s)):
        t = s[:i] + s[i + 1:]
        if t and t not in seeds:
            seeds[t] = 2.5         # nadmiarowy znak jest rzadszy niż ósemka zamiast zera
    out = {}
    for t, c in seeds.items():
        pos = [i for i, ch in enumerate(t) if ch == "8"][:4]
        for mask in range(1 << len(pos)):
            u = list(t)
            for k, p in enumerate(pos):
                if mask >> k & 1:
                    u[p] = "0"
            u = "".join(u)
            if re.fullmatch(pat, u):
                ip, _, dp = u.partition(",")
                v = int(ip) * 100 + int((dp + "00")[:2]) if money_fmt else round(float(u.replace(",", ".")), 3)
                cost = c + bin(mask).count("1")
                if v not in out or out[v] > cost:
                    out[v] = cost
    return out


def split_item(line):
    """Rozbiera wiersz pozycji i wybiera taki odczyt liczb, przy którym ilość × cena = wartość (z dokładnością do grosza).
    Zwraca (nazwa, ilość, cena, wartość) albo None."""
    m = RX_ITEM.match(line)
    if not m:      # „1% 7,19 7,19 C” – gwiazdka odczytana jako procent
        alt = re.sub(r"(?<=\s)(\d{1,2})\s?%\s+(?=\d+[.,]\d{2}\s+-?\d+[.,]\d{2}\s*[A-H]?\s*$)", r"\1 * ", line)
        m = RX_ITEM.match(alt) if alt != line else None
    if not m:
        return None
    nums = m.group("nums").strip()
    toks = re.findall(r"-?\d+(?:[.,]\d+)?", nums)
    pairs = []
    if len(toks) == 2:
        pairs.append((toks[0], toks[1], 0))
    blob = re.sub(r"\s", "", nums)
    neg = "-" in blob[1:]
    blob_np = blob.replace("-", "")
    for i in range(2, len(blob_np) - 2):      # sklejone liczby, np. „5,195,19”
        a, b = blob_np[:i], blob_np[i:]
        if re.search(r"[.,]", a) and re.search(r"[.,]", b) and not b.startswith((",", ".")):
            pairs.append((a, ("-" if neg else "") + b, 1 if len(toks) != 2 else 2))
    best, cands = None, {}
    for qv, qc in _num_variants(m.group("qty"), money_fmt=False).items():
        if not qv:
            continue
        if not float(qv).is_integer() and qv >= 5:      # 8,246 kg papryki – raczej „0,246” z ósemką zamiast zera
            qc += 2
        for a, b, pc in pairs:
            negative = b.startswith("-")
            uvars, tvars = _num_variants(a.lstrip("-")), _num_variants(b.lstrip("-"))
            for uv, uc in uvars.items():
                exp = int(qv * uv + 0.5 + 1e-9)       # sklep zaokrągla wartość do grosza „połówką w górę”
                for tv in (exp, exp - 1, exp + 1):
                    if tv in tvars and tv:
                        cost = qc + uc + tvars[tv] + pc + (1.5 if tv != exp else 0)
                        val = -tv if negative else tv
                        if best is None or cost < best[0]:
                            best = (cost, qv, uv, val)
                        if cost <= 6 and (val not in cands or cands[val][0] > cost):
                            cands[val] = (cost, qv, uv, val)
        for a, b, pc in pairs:            # jedna z liczb nieczytelna: wartość z ilości × cena albo cena z wartości / ilość
            negative = b.startswith("-")
            for uv, uc in _num_variants(a.lstrip("-")).items():
                if uc == 0 and uv:
                    t = int(qv * uv + 0.5 + 1e-9)
                    cand = (qc + pc + 3.5, qv, uv, -t if negative else t)
                    best = cand if best is None or cand[0] < best[0] else best
                    cands.setdefault(cand[3], cand)
            for tv, tc in (_num_variants(b.lstrip("-")).items() if float(qv).is_integer() else []):
                if tv and tc <= 1:
                    cand = (qc + tc + pc + (2 if qv == 1 else 3), qv, round(tv / qv), -tv if negative else tv)
                    best = cand if best is None or cand[0] < best[0] else best
                    if cand[3] not in cands or cands[cand[3]][0] > cand[0]:
                        cands[cand[3]] = cand
    if not best or best[0] > 6:
        return None
    name = re.sub(r"(?<=[^\W\d])\d{6,}$", "", m.group("name").strip()).strip(" .:-_|")
    alts = [] if best[0] == 0 else [c[1:] + (c[0] - best[0],) for c in sorted(cands.values()) if c[3] != best[3] and c[0] <= best[0] + 2.5][:4]
    return name, best[1], best[2], best[3], alts      # alts: inne spójne odczyty (z dodatkowym kosztem), gdyby suma się nie zgadzała


def parse_receipt(rows):
    rows = [re.sub(r"[ØøΘθ]", "0", r) for r in rows]      # przekreślone zero
    N = [norm(tidy(r)) for r in rows]
    text = "\n".join(N)
    if "FAKTURA" in text and not ("PARAGON" in text and "FISK" in text):
        return parse_invoice(rows, N)
    raw_norm = [norm(r) for r in rows]
    res = dict(kind="paragon", store=find_store(rows, N), date=find_date("\n".join(raw_norm)), total=find_total(N), payment=None, saved=0, items=[])
    if RX_CARD.search(text):
        res["payment"] = "card"
    elif "GOTOWKA" in text:
        res["payment"] = "cash"
    printed_saved = max([abs(money(m.group(1))) for m in RX_SAVED.finditer(text)] or [0])

    # początek listy pozycji: po napisie PARAGON FISKALNY, a gdy go nie ma (e-paragony) – po wierszu z datą
    start = next((i + 1 for i, n in enumerate(N) if "PARAGON" in n and "FISK" in n), None)
    if start is None:
        start = next((i + 1 for i, n in enumerate(raw_norm[:15]) if find_date(n) and len(n) <= 40), 0)
    zone, pending, extra = "items", None, 0

    def add(name, m, deposit=False):
        gd = m.groupdict()
        total = money(m.group("total"))
        qty = float(re.sub(r"\s", "", gd["qty"]).replace(",", ".")) if gd.get("qty") else 1.0
        unit = money(gd["unit"]) if gd.get("unit") else total
        name = name.strip()
        last = name.split(" ")[-1]
        if " " in name and len(last) == 1 and norm(last) in tuple("ABCDEFG") and (gd.get("qty") or not gd.get("vat")):
            name = name[:-1].strip()        # litera stawki VAT doklejona do nazwy
        name = re.sub(r"(\s+(?:[^\w\s%]\S?|\S[^\w\s%.,]))+$", "", name).strip(" .:-_|")      # krótkie śmieci z odczytu na końcu nazwy
        name = re.sub(r"(?<=[^\W\d])\d{6,}$", "", name)                                  # kod towaru doklejony do nazwy (Bluza0494601)
        if name and total != 0 and (total > 0 or gd.get("qty")):
            res["items"].append(dict(name=name, qty=qty, unit_price=unit, amount=total, discount=0, deposit=deposit))

    for raw, n in zip(rows[start:], N[start:]):
        if RX_SAVED.search(n):
            continue
        line = tidy(raw)
        if RX_DEPOSIT.search(n):                 # kaucje za opakowania są wypisane pod sumą towarów
            zone = "deposit"
            if "ZWROTNE" in n:
                pending = None
                continue
        elif zone == "items" and RX_END.search(n):
            zone = "done"
        elif zone == "deposit" and (RX_END.search(n) or not re.search(r"\d", n)):
            zone = "done"
        if zone == "done":
            continue
        si = split_item(line)
        if si and (si[0] or pending):
            nm, q, u, t, alts = si
            nm = nm if nm and re.search(r"[^\W\d]{2}", nm) else (pending or nm)
            nm = re.sub(r"(\s+(?:[^\w\s%]\S?|\S[^\w\s%.,]))+$", "", nm).strip(" .:-_|")
            nm = re.sub(r"\s+[A-G]$", "", nm)          # litera stawki VAT między nazwą a ilością (Biedronka)
            if nm and t:
                res["items"].append(dict(name=nm, qty=q, unit_price=u, amount=t, discount=0, deposit=zone == "deposit", alts=alts))
            pending = None
            continue
        m = RX_FULL.match(line)
        if m:
            add(m.group("name"), m, zone == "deposit"); pending = None
            continue
        m = RX_QTY.match(line)
        if m:
            if pending:
                add(pending, m, zone == "deposit")
            pending = None
            continue
        if pending and re.search(r"\d\s*%?\s*[X×*＊•]\s*\d", line, re.I):      # wiersz "ilość * cena wartość" odczytany z błędem
            m = RX_LOOSE.match(line)
            total = money(m.group("total")) if m else None
            qty = float(m.group("qty").replace(",", ".")) if m else 1.0
            res["items"].append(dict(name=re.sub(r"(?<=[^\W\d])\d{6,}$", "", pending.strip()), qty=qty or 1.0, unit_price=round(total / qty) if total and qty else 0,
                                     amount=total, discount=0, deposit=zone == "deposit"))
            pending = None
            continue
        neg = RX_NEG.search(line)
        if zone == "items" and (RX_DISCOUNT.search(n) or neg):
            prices = re.findall(PRICE, line)
            if neg or prices:
                val = abs(money(neg.group(1) or neg.group(2))) if neg else abs(money(prices[-1]))
                raw3 = re.search(r"(\d+),(\d{3})(?!\d)", line)
                if res["items"] and res["items"][-1]["amount"] is not None:
                    it = res["items"][-1]
                    if raw3:      # „-0,089”: któraś cyfra jest nadmiarowa
                        dp = raw3.group(2)
                        alts = {int(raw3.group(1)) * 100 + int(dp[:i] + dp[i + 1:]) for i in range(3)} - {val}
                        it.setdefault("disc_alts", []).extend(it["discount"] + a for a in alts)
                    if val > it["amount"]:        # rabat większy niż pozycja: „-8,40” zamiast „-0,40”
                        val = next((v for v in zero_alts(val) if 0 < v <= it["amount"]), it["amount"])
                    it["amount"] -= val; it["discount"] += val
                    it.setdefault("disc_lines", []).append(val)
                else:
                    extra += val
            pending = None
            continue
        m = RX_SIMPLE.match(line)
        if m and zone == "items":
            name = m.group("name")
            add(pending if pending and len(name) < 3 else name, m); pending = None
            continue
        pending = line if re.search(r"[^\W\d]{3}", line) else None
    # sumy częściowe wydrukowane na paragonie: towary i kaucje
    goods = next((money(m.group(1)) for n in N for m in [re.search(r"^(?:SUMA PLN|RAZEM)\s*(" + PRICE + r")(?!\s?\d)", n)] if m), 0)
    dep = next((money(m.group(1)) for n in N for m in [re.search(r"OPAKOWANIA ZWROTNE SUMA\s*(-?\s?" + PRICE + ")", n)] if m), None)
    if dep is not None:
        deps = [i for i in res["items"] if i["deposit"]]
        if any(i["amount"] is None for i in deps) or sum(i["amount"] for i in deps) != dep:
            res["items"] = [i for i in res["items"] if not i["deposit"]]
            if dep:
                res["items"].append(dict(name="Kaucja za opakowania" if dep > 0 else "Zwrot kaucji", qty=1.0, unit_price=dep, amount=dep, discount=0, deposit=True))
        if goods and res["total"] and goods + dep != res["total"] and goods == res["total"]:
            res["total"] = goods + dep
    target = (goods if goods and dep is not None else res["total"]) or 0
    missing = [i for i in res["items"] if i["amount"] is None]
    known = sum(i["amount"] for i in res["items"] if i["amount"] is not None and not (i["deposit"] and dep is not None))
    if len(missing) == 1 and target - known > 0:
        missing[0]["amount"] = target - known          # jedyna nieodczytana kwota wynika z sumy paragonu
        missing[0]["unit_price"] = round(missing[0]["amount"] / missing[0]["qty"])
    res["items"] = [i for i in res["items"] if i["amount"] is not None]
    fix_outlier_discounts(res["items"])
    repair_amounts(res)
    got = sum(i["amount"] for i in res["items"])
    if res["items"] and got != res["total"]:      # suma pozycji zgadza się z inną wydrukowaną kwotą (albo jej wersją bez błędu 8/0)
        alts = set(total_candidates(N))
        alts |= {v for c in list(alts) for v in zero_alts(c)}
        if got in alts:
            res["total"] = got
    found = sum(i["discount"] for i in res["items"])
    res["saved"] = extra + max(0, printed_saved - found - extra)     # rabaty z podsumowania, których nie przypisano do pozycji
    if not res["total"]:
        res["total"] = sum(i["amount"] for i in res["items"])
    return res


# ---------- faktury ----------
IPRICE = r"\d{1,3}(?:[ .]\d{3})+,\d{2}|\d+,\d{2}"
UNITS = r"USŁ\.?|SZT\.?|KG|G|L|ML|OP\.?|KPL\.?|M2|M3|MB|M|USL\.?|GODZ\.?|H|KWH|MC|MIES\.?"


def imoney(s):
    return int(round(float(re.sub(r"[ .](?=\d{3})", "", s).replace(",", ".")) * 100))


def parse_invoice(rows, N):
    text = "\n".join(N)
    res = dict(kind="faktura", store="", payment="card", saved=0, items=[], total=0,
               date=find_date("\n".join(norm(r) for r in rows), ("DATA WYSTAWIENIA", "WYSTAWIONO", "DATA SPRZEDAZY", "DATA DOSTAWY")))
    i = next((k for k, n in enumerate(N) if n.startswith("SPRZEDAWCA")), None)
    if i is not None:
        same = re.sub(r"^SPRZEDAWCA\s*:?", "", tidy(rows[i]), flags=re.I).strip()
        same = re.split(r"\s{2,}|NABYWCA.*", same, flags=re.I)[0].strip()
        res["store"] = same or next((re.split(r"\s{3,}", rows[k].strip())[0] for k in range(i + 1, min(i + 4, len(rows))) if re.search(r"[A-Za-z]{3}", rows[k])), "")
    res["store"] = res["store"] or find_store(rows, N)
    for key in (r"DO ZAPLATY", r"RAZEM DO ZAPLATY", r"KWOTA DO ZAPLATY", r"RAZEM BRUTTO", r"WARTOSC BRUTTO", r"RAZEM"):
        for n in N:
            m = re.search(key + r"\D{0,25}?((?:" + IPRICE + r")(?:\D+(?:" + IPRICE + r"))*)", n)
            if m:
                res["total"] = imoney(re.findall(IPRICE, m.group(1))[-1])
        if res["total"]:
            break
    for raw, n in zip(rows, N):
        line = tidy(raw)
        m = re.match(r"^(\d{1,3})[.)]?\s+(?P<body>.*[A-Za-z]{2}.*)$", line)
        prices = re.findall(IPRICE, line)
        if RX_DISCOUNT.search(n) and prices and not m:
            res["saved"] += imoney(prices[-1])
            continue
        if not m or len(prices) < 2 or re.search(r"RAZEM|W TYM|STAWKA|NIP|REGON|KONTO", n):
            continue
        body = m.group("body")
        q = re.search(r"\s(\d+(?:,\d+)?)\s*(?:" + UNITS + r")(?=\s|$)", body, flags=re.I)
        cut = q.start() if q else re.search(IPRICE, body).start()
        name = body[:cut].strip(" .:-|")
        if len(name) < 2:
            continue
        gross = imoney(prices[-1])
        res["items"].append(dict(name=name, qty=float(q.group(1).replace(",", ".")) if q else 1.0, unit_price=gross, amount=gross, discount=0))
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
    cid, _ = core.Categorizer(conn).match(store or "", -1)      # kategoria wynikająca z nazwy sprzedawcy
    return cid or core.cat_id(conn, "Inne wydatki")


def match_transactions(conn):
    """Łączy paragony i faktury z transakcjami z wyciągu.
    Kwota musi się zgadzać co do grosza (suma dokumentu albo suma jego pozycji); data transakcji:
    paragon od 2 dni przed do 7 dni po, faktura do 35 dni po. Przy kilku kandydatach decyduje nazwa sklepu, potem najbliższa data."""
    n = 0
    taken = {r[0] for r in conn.execute("SELECT transaction_id FROM receipts WHERE transaction_id IS NOT NULL")}
    for r in conn.execute("SELECT r.*, (SELECT IFNULL(SUM(amount),0) FROM receipt_items i WHERE i.receipt_id=r.id) items_sum "
                          "FROM receipts r WHERE transaction_id IS NULL AND date IS NOT NULL").fetchall():
        d = date.fromisoformat(r["date"])
        amounts = [a for a in {r["total"], r["items_sum"]} if a and a > 0]
        if not amounts:
            continue
        after = 35 if r["kind"] == "faktura" else 7
        cands = conn.execute("SELECT t.id,t.description,t.counterparty,t.date,t.amount FROM transactions t WHERE t.amount IN (%s) AND t.date BETWEEN ? AND ?"
                             % ",".join("?" * len(amounts)), [-a for a in amounts] + [(d - timedelta(days=2)).isoformat(), (d + timedelta(days=after)).isoformat()]).fetchall()
        cands = [c for c in cands if c["id"] not in taken]
        if not cands:
            continue
        words = [w for w in re.split(r"[^A-Z0-9]+", norm(r["store"])) if len(w) >= 4][:2]
        named = [c for c in cands if any(w in norm(f"{c['description']} {c['counterparty']}") for w in words)]
        if r["payment"] == "cash" and not named:
            continue            # paragon gotówkowy łączymy tylko wtedy, gdy zgadza się też sklep
        pool = named or cands
        pool.sort(key=lambda c: (c["amount"] != -r["total"], abs((date.fromisoformat(c["date"]) - d).days)))
        best = pool[0]
        taken.add(best["id"])
        conn.execute("UPDATE receipts SET transaction_id=? WHERE id=?", (best["id"], r["id"]))
        n += 1
    conn.commit()
    return n
