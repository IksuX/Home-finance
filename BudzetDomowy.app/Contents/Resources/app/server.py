"""Budżet domowy – lokalny serwer aplikacji (działa wyłącznie na tym komputerze)."""
import csv, io, json, mimetypes, os, re, sys, threading, time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

import core
import receipts as rc
import plan as pl
import savings as sv

PORT = int(os.environ.get("BUDZET_PORT", "8765"))
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
LOCK = threading.Lock()


class ApiError(Exception):
    pass


def rows(cur):
    return [dict(r) for r in cur]


def receipt_json(conn, rid):
    r = conn.execute("SELECT * FROM receipts WHERE id=?", (rid,)).fetchone()
    if not r:
        raise ApiError("Nie ma takiego paragonu.")
    d = dict(r)
    d["items"] = rows(conn.execute("SELECT * FROM receipt_items WHERE receipt_id=? ORDER BY pos,id", (rid,)))
    d["transaction"] = None
    if r["transaction_id"]:
        t = conn.execute("SELECT t.id,t.date,t.amount,t.description,t.counterparty,a.person_id FROM transactions t "
                         "JOIN accounts a ON a.id=t.account_id WHERE t.id=?", (r["transaction_id"],)).fetchone()
        d["transaction"] = dict(t) if t else None
    return d


EMPTY = dict(kind="paragon", store="", date=None, total=0, payment=None, saved=0, items=[])


def read_receipt(conn, rid, frags=None):
    """Odczytuje dokument (OCR, jeśli nie podano gotowych fragmentów) i zapisuje jego pozycje od nowa."""
    r = conn.execute("SELECT * FROM receipts WHERE id=?", (rid,)).fetchone()
    engine = r["engine"]
    if frags is None:
        frags, engine = rc.ocr(os.path.join(core.RECEIPT_DIR, r["file"]), os.path.join(core.RECEIPT_DIR, r["preview"]))
    text_rows = rc.to_rows(frags) if frags else []
    p = rc.parse_receipt(text_rows) if text_rows else EMPTY
    conn.execute("UPDATE receipts SET kind=?,date=?,store=?,total=?,payment=?,saved=?,ocr_text=?,ocr_json=?,engine=?,checked=0 WHERE id=?",
                 (p["kind"], p["date"], p["store"], p["total"], p["payment"], p["saved"], "\n".join(text_rows),
                  json.dumps(frags) if frags else None, engine, rid))
    conn.execute("DELETE FROM receipt_items WHERE receipt_id=?", (rid,))
    for i, it in enumerate(p["items"]):
        conn.execute("INSERT INTO receipt_items(receipt_id,name,qty,unit_price,amount,discount,category_id,pos) VALUES(?,?,?,?,?,?,?,?)",
                     (rid, it["name"], it["qty"], it["unit_price"], it["amount"], it["discount"], rc.item_category(conn, it["name"], p["store"]), i))
    conn.commit()


def add_receipt(conn, raw, filename, person):
    ext = os.path.splitext(filename)[1].lower() or ".jpg"
    if ext not in (".jpg", ".jpeg", ".png", ".pdf", ".heic", ".tif", ".tiff", ".webp"):
        raise ApiError("Paragon lub faktura musi być zdjęciem (JPG, PNG, HEIC) albo plikiem PDF.")
    import hashlib
    digest = hashlib.sha1(raw).hexdigest()
    dup = conn.execute("SELECT id FROM receipts WHERE file_hash=?", (digest,)).fetchone()
    if dup:                                   # ten sam plik już był wczytany
        return dict(receipt_json(conn, dup["id"]), duplicate=True)
    rid = conn.execute("INSERT INTO receipts(created,person_id,file_hash) VALUES(?,?,?)", (datetime.now().isoformat(timespec="seconds"), person, digest)).lastrowid
    path = os.path.join(core.RECEIPT_DIR, f"{rid}{ext}")
    with open(path, "wb") as f:
        f.write(raw)
    preview = os.path.join(core.RECEIPT_DIR, f"{rid}-podglad.jpg")
    if not rc.make_preview(path, preview):
        preview = path
    conn.execute("UPDATE receipts SET file=?,preview=? WHERE id=?", (os.path.basename(path), os.path.basename(preview), rid))
    conn.commit()
    read_receipt(conn, rid)
    rc.match_transactions(conn)
    return receipt_json(conn, rid)


def update_receipt(conn, rid, b):
    for k in ("date", "store", "payment", "person_id", "checked", "kind"):
        if k in b:
            conn.execute(f"UPDATE receipts SET {k}=? WHERE id=?", (b[k] or None, rid))
    for k in ("total", "saved"):
        if k in b:
            conn.execute(f"UPDATE receipts SET {k}=? WHERE id=?", (int(b[k] or 0), rid))
    if "transaction_id" in b:
        conn.execute("UPDATE receipts SET transaction_id=? WHERE id=?", (b["transaction_id"] or None, rid))
    if "items" in b:
        store = conn.execute("SELECT store FROM receipts WHERE id=?", (rid,)).fetchone()["store"]
        old = {r["id"]: r for r in conn.execute("SELECT * FROM receipt_items WHERE receipt_id=?", (rid,))}
        conn.execute("DELETE FROM receipt_items WHERE receipt_id=?", (rid,))
        for i, it in enumerate(b["items"]):
            name = (it.get("name") or "").strip()
            if not name:
                continue
            cid = it.get("category_id") or rc.item_category(conn, name, store)
            prev = old.get(it.get("id"))
            if prev is not None and it.get("category_id") and prev["category_id"] != cid:
                # użytkownik zmienił kategorię pozycji – zapamiętujemy ją dla tej nazwy
                conn.execute("INSERT OR REPLACE INTO item_rules(name,category_id) VALUES(?,?)", (core.norm(name), cid))
            conn.execute("INSERT INTO receipt_items(receipt_id,name,qty,unit_price,amount,discount,category_id,pos) VALUES(?,?,?,?,?,?,?,?)",
                         (rid, name, float(it.get("qty") or 1), int(it.get("unit_price") or 0), int(it.get("amount") or 0),
                          int(it.get("discount") or 0), cid, i))
    conn.commit()
    if b.get("rematch"):
        rc.match_transactions(conn)
    return receipt_json(conn, rid)


def tx_query(q):
    sql = ("FROM transactions t JOIN accounts a ON a.id=t.account_id LEFT JOIN categories c ON c.id=t.category_id "
           "LEFT JOIN receipts r ON r.transaction_id=t.id LEFT JOIN transactions pt ON pt.id=t.pair_id LEFT JOIN accounts pa ON pa.id=pt.account_id WHERE 1=1")
    args = []
    if q.get("from"): sql += " AND t.date>=?"; args.append(q["from"])
    if q.get("to"): sql += " AND t.date<=?"; args.append(q["to"])
    if q.get("person"): sql += " AND a.person_id=?"; args.append(int(q["person"]))
    if q.get("account"): sql += " AND a.id=?"; args.append(int(q["account"]))
    if q.get("category") == "none": sql += " AND t.category_id IS NULL"
    elif q.get("category"): sql += " AND t.category_id=?"; args.append(int(q["category"]))
    if q.get("sign") == "neg": sql += " AND t.amount<0"
    if q.get("sign") == "pos": sql += " AND t.amount>0"
    if q.get("q"):
        for w in q["q"].split():
            amt = core.parse_amount(w) if re.fullmatch(r"\d+([.,]\d{1,2})?", w) else None      # liczba = szukaj też po kwocie
            sql += " AND (NORM(IFNULL(t.description,'')||' '||IFNULL(t.counterparty,'')||' '||IFNULL(t.note,'')) LIKE ?" + (" OR ABS(t.amount)=?" if amt else "") + ")"
            args += [f"%{core.norm(w)}%"] + ([amt] if amt else [])      # bez polskich znaków i wielkości liter: „szkola” znajdzie „SZKOŁA”
    return sql, args


def product_key(name):
    t = re.sub(r"[^A-Z0-9,.% ]", " ", core.norm(name)).split()
    while len(t) > 1 and len(t[-1]) == 1:      # pojedyncze znaki na końcu to zwykle śmieci z odczytu albo litera VAT
        t.pop()
    return " ".join(t)


def product_rows(conn, person=None):
    """Wszystkie pozycje z dokumentów z ceną jednostkową; nazwy różniące się literówką z odczytu trafiają do jednego produktu."""
    import difflib
    # tylko dokumenty, w których pozycje zgadzają się z sumą (albo zatwierdzone ręcznie) – błąd odczytu nie udaje wtedy zmiany ceny
    sql = ("SELECT i.name,i.qty,i.amount,i.discount,i.unit_price,r.date,r.store,r.id receipt_id,c.name category FROM receipt_items i "
           "JOIN receipts r ON r.id=i.receipt_id LEFT JOIN categories c ON c.id=i.category_id WHERE r.date IS NOT NULL AND i.qty>0 AND i.amount>0 "
           "AND IFNULL(c.name,'')!='Kaucja za opakowania' "
           "AND (r.checked=1 OR r.total=(SELECT SUM(amount) FROM receipt_items x WHERE x.receipt_id=r.id))")
    data = rows(conn.execute(sql + (" AND r.person_id=?" if person else "") + " ORDER BY r.date,r.id,i.pos", [person] if person else []))
    counts = {}
    for d in data:
        d["key"] = product_key(d["name"])
        counts[d["key"]] = counts.get(d["key"], 0) + 1
    canon, mapping = [], {}
    for key in sorted(counts, key=lambda k: (-counts[k], k)):
        digits = re.findall(r"\d+", key)
        hit = next((c for c in canon if re.findall(r"\d+", c) == digits and difflib.SequenceMatcher(None, c, key).ratio() >= 0.88), None)
        mapping[key] = hit or key
        if not hit:
            canon.append(key)
    for d in data:
        d["key"] = mapping[d["key"]]
        gross = d["amount"] + (d["discount"] or 0)
        d["price"] = d["unit_price"] if d["unit_price"] and abs(round(d["qty"] * d["unit_price"]) - gross) <= 1 else round(gross / d["qty"])      # cena regularna za sztukę / kg
        d["paid"] = round(d["amount"] / d["qty"])                                 # cena po rabacie
    return data


def api(method, path, q, body, raw, headers):
    conn = core.connect()
    try:
        m = re.match(r"^/api/(\w+)(?:/(\d+))?(?:/(\w+))?$", path.replace("/receipts/rereadall", "/receipts/0/rereadall").replace("/settlements/preview", "/settlements/0/preview").replace("/rules/preview", "/rules/0/preview").replace("/categories/order", "/categories/0/order").replace("/transactions/bulk", "/transactions/0/bulk").replace("/rules/conflicts", "/rules/0/conflicts").replace("/plans/from", "/plans/0/from"))
        if not m:
            raise ApiError("Nieznany adres.")
        res, oid, sub = m.group(1), int(m.group(2)) if m.group(2) else None, m.group(3)

        if res == "state":
            b = conn.execute("SELECT MIN(date) a, MAX(date) b, COUNT(*) n FROM transactions").fetchone()
            return dict(version=core.VERSION, people=rows(conn.execute("SELECT * FROM people ORDER BY id")),
                        accounts=rows(conn.execute("SELECT a.*, (SELECT COUNT(*) FROM transactions t WHERE t.account_id=a.id) n FROM accounts a ORDER BY bank,label")),
                        categories=rows(conn.execute("SELECT * FROM categories ORDER BY sort,id")),
                        rules=rows(conn.execute("SELECT r.*, c.name category FROM rules r JOIN categories c ON c.id=r.category_id WHERE r.user=1 ORDER BY r.id DESC")),
                        imports=rows(conn.execute("SELECT * FROM imports ORDER BY id DESC LIMIT 20")),
                        first=b["a"], last=b["b"], tx_count=b["n"], ocr=rc.engine_status(), platform="win" if os.name == "nt" else "mac", data_dir=core.DATA_DIR, kinds=core.KINDS, atm_feeds_cash=core.atm_feeds_cash(conn))

        if res == "summary":
            return core.summary(conn, q.get("from"), q.get("to"), int(q["person"]) if q.get("person") else None)

        if res == "transactions" and method == "GET" and not oid and not q.get("ids_only"):
            sql, args = tx_query(q)
            total = conn.execute("SELECT COUNT(*) n, IFNULL(SUM(t.amount),0) s " + sql, args).fetchone()
            lim, off = int(q.get("limit", 200)), int(q.get("offset", 0))
            data = rows(conn.execute("SELECT t.id,t.date,t.amount,t.currency,t.description,t.counterparty,t.category_id,t.cat_source,t.note,"
                                     "a.person_id,a.bank,a.label account,a.kind account_kind,a.id account_id,t.manual,r.id receipt_id,t.pair_id,pt.date pair_date,pt.amount pair_amount,"
                                     "pa.bank pair_bank,pa.label pair_account " + sql + " ORDER BY t.date DESC,t.id DESC LIMIT ? OFFSET ?", args + [lim, off]))
            for d in data:
                d["merchant"] = core.merchant(d["description"], d["counterparty"])
                d["processor"] = core.is_processor(d["counterparty"])
                d["phrases"] = core.rule_phrases(d["description"], d["counterparty"])
            return dict(total=total["n"], sum=total["s"], rows=data)

        if res == "transactions" and method == "POST" and sub == "bulk":   # edycja grupowa
            ids = [int(i) for i in body.get("ids") or []]
            if not ids:
                raise ApiError("Nie zaznaczono żadnej transakcji.")
            changed = skipped = 0
            for part in range(0, len(ids), 500):
                chunk = ids[part:part + 500]
                ph = ",".join("?" * len(chunk))
                if "category_id" in body:
                    cid = body["category_id"] or None
                    k = conn.execute("SELECT kind FROM categories WHERE id=?", (cid,)).fetchone() if cid else None
                    for t in conn.execute(f"SELECT id,amount FROM transactions WHERE id IN ({ph})", chunk).fetchall():
                        if k and not core.sign_ok(k["kind"], t["amount"]):
                            skipped += 1; continue
                        conn.execute("UPDATE transactions SET category_id=?, cat_source='manual' WHERE id=?", (cid, t["id"])); changed += 1
                if "note" in body:
                    note = (body["note"] or "").strip() or None
                    changed += conn.execute(f"UPDATE transactions SET note=? WHERE id IN ({ph})", [note] + chunk).rowcount
            conn.commit()
            return dict(changed=changed, skipped=skipped)
        if res == "transactions" and method == "GET" and q.get("ids_only"):
            sql, args = tx_query(q)
            return [r["id"] for r in conn.execute("SELECT t.id " + sql, args)]
        if res == "transactions" and method == "POST" and not oid:      # wpis ręczny, którego nie ma w wyciągach
            import uuid
            d = core.parse_date(body.get("date"))
            amt = int(body.get("amount") or 0)
            if not d or not amt:
                raise ApiError("Podaj datę i kwotę.")
            acc = int(body["account_id"]) if body.get("account_id") else core.cash_wallet(conn, int(body["person_id"]))
            conn.execute("INSERT INTO transactions(account_id,date,amount,currency,description,counterparty,category_id,cat_source,hash,note,manual) "
                         "VALUES(?,?,?,'PLN',?,'',?,'manual',?,?,1)", (acc, d, amt, (body.get("description") or "").strip() or ("Przychód" if amt > 0 else "Wydatek"),
                                                                   body.get("category_id") or None, "manual-" + uuid.uuid4().hex, (body.get("note") or "").strip() or None))
            conn.commit()
            return {"ok": True}
        if res == "transactions" and method == "DELETE":
            if not conn.execute("SELECT 1 FROM transactions WHERE id=? AND manual=1", (oid,)).fetchone():
                raise ApiError("Usunąć można tylko wpisy dodane ręcznie. Transakcje z wyciągu cofniesz w zakładce Wczytaj wyciąg.")
            conn.execute("UPDATE receipts SET transaction_id=NULL WHERE transaction_id=?", (oid,))
            conn.execute("DELETE FROM transactions WHERE id=?", (oid,))
            conn.commit()
            return {"ok": True}
        if res == "networth":
            return core.networth(conn, int(q["person"]) if q.get("person") else None)
        if res == "transactions" and method == "GET" and oid and sub == "pairs":
            t = conn.execute("SELECT * FROM transactions WHERE id=?", (oid,)).fetchone()
            return rows(conn.execute("SELECT t.id,t.date,t.amount,t.description,t.counterparty,a.bank,a.label account,a.kind account_kind,a.person_id FROM transactions t "
                                     "JOIN accounts a ON a.id=t.account_id WHERE t.account_id!=? AND (t.amount>0)!=(?>0) AND t.pair_id IS NULL "
                                     "AND t.date BETWEEN date(?,'-7 day') AND date(?,'+7 day') ORDER BY ABS(ABS(t.amount)-?), ABS(julianday(t.date)-julianday(?)) LIMIT 10",
                                     (t["account_id"], t["amount"], t["date"], t["date"], abs(t["amount"]), t["date"])))
        if res == "transactions" and method == "POST" and oid and sub == "link":
            try:
                core.link_pair(conn, oid, int(body["other"]))
            except ValueError as e:
                raise ApiError(str(e))
            return {"ok": True}
        if res == "transactions" and method == "POST" and oid and sub == "unlink":
            core.unlink_pair(conn, oid)
            return {"ok": True}
        if res == "transactions" and method == "POST" and oid:
            if "category_id" in body:
                if body["category_id"]:
                    t = conn.execute("SELECT amount FROM transactions WHERE id=?", (oid,)).fetchone()
                    k = conn.execute("SELECT kind,name FROM categories WHERE id=?", (body["category_id"],)).fetchone()
                    if t and k and not core.sign_ok(k["kind"], t["amount"]):
                        raise ApiError(f"„{k['name']}” to kategoria {'wydatków' if k['kind'] == 'expense' else 'przychodów'}, a to jest {'wpływ' if t['amount'] > 0 else 'wydatek'}.")
                conn.execute("UPDATE transactions SET category_id=?, cat_source='manual' WHERE id=?", (body["category_id"] or None, oid))
            if "note" in body:
                conn.execute("UPDATE transactions SET note=? WHERE id=?", ((body["note"] or "").strip() or None, oid))
            conn.commit()
            return {"ok": True}

        if res == "savings" and method == "GET":
            person = int(q["person"]) if q.get("person") else None
            return sv.analyze(conn, person, product_rows(conn, person))
        if res == "plan" and method == "GET":
            return pl.report(conn, max(1, min(24, int(q.get("months") or 6))), int(q["person"]) if q.get("person") else None)
        if res == "plans" and method == "POST" and sub == "from":
            try:
                return pl.from_transactions(conn, [int(i) for i in body.get("ids") or []][:2000])
            except ValueError as e:
                raise ApiError(str(e))
        if res == "plans" and method == "POST" and oid and sub == "mark":
            due = core.parse_date(body.get("due"))
            if body.get("status") in ("paid", "skipped"):
                conn.execute("INSERT OR REPLACE INTO plan_marks(plan_id,due,status) VALUES(?,?,?)", (oid, due, body["status"]))
            else:
                conn.execute("DELETE FROM plan_marks WHERE plan_id=? AND due=?", (oid, due))
            conn.commit()
            return {"ok": True}
        if res == "plans" and method == "POST" and sub is None:
            try:
                return {"id": pl.save(conn, body, oid)}
            except ValueError as e:
                raise ApiError(str(e))
        if res == "plans" and method == "DELETE":
            conn.execute("DELETE FROM plans WHERE id=?", (oid,)); conn.execute("DELETE FROM plan_marks WHERE plan_id=?", (oid,)); conn.commit()
            return {"ok": True}
        if res == "plan_ignore" and method == "POST":
            if body.get("undo"):
                conn.execute("DELETE FROM plan_ignore WHERE key=?", (body.get("key"),))
            else:
                conn.execute("INSERT OR IGNORE INTO plan_ignore(key) VALUES(?)", (body.get("key"),))
            conn.commit()
            return {"ok": True}
        if res == "rules" and method == "GET" and sub == "conflicts":
            return {str(k): v for k, v in core.rule_conflicts(conn).items()}
        if res == "rules" and method == "POST" and sub == "preview":
            rx = core.rule_regex(body.get("pattern") or "")
            if not rx or len(core.norm(body.get("pattern"))) < 3:
                return dict(count=0, rows=[], processor=False)
            k = conn.execute("SELECT kind FROM categories WHERE id=?", (body.get("category_id") or 0,)).fetchone()
            kind = k["kind"] if k else None
            hits = [dict(r) for r in conn.execute("SELECT t.id,t.date,t.amount,t.description,t.counterparty,t.category_id,t.cat_source,c.name category FROM transactions t "
                                                  "LEFT JOIN categories c ON c.id=t.category_id ORDER BY t.date DESC")
                    if rx.search(core.norm(f"{r['counterparty'] or ''} {r['description'] or ''}")) and core.sign_ok(kind, r["amount"])]
            sign = {"expense": -1, "income": 1}.get(kind, 0)
            conf = core.rule_conflicts(conn, dict(pattern=body.get("pattern"), cid=body.get("category_id"), sign=sign)).get(None, [])
            return dict(count=len(hits), manual=sum(1 for h in hits if h["cat_source"] == "manual"),
                        protected=sum(1 for h in hits if h["cat_source"] in core.PROTECTED),
                        same=sum(1 for h in hits if h["category_id"] == body.get("category_id")),
                        rows=hits[:8], conflicts=conf, replaces=next((dict(r) for r in conn.execute("SELECT r.pattern,c.name category FROM rules r JOIN categories c ON c.id=r.category_id WHERE r.user=1 AND r.pattern=?", (core.norm(body.get("pattern")),))), None), processor=core.is_processor(body.get("pattern")))
        if res == "rules" and method == "POST" and not oid:
            pat = core.norm(body.get("pattern"))
            if len(pat) < 3:
                raise ApiError("Fraza reguły musi mieć co najmniej 3 znaki.")
            k = conn.execute("SELECT kind FROM categories WHERE id=?", (int(body["category_id"]),)).fetchone()
            sign = {"expense": -1, "income": 1}.get(k["kind"] if k else None, 0)      # reguła działa tylko na pasującą stronę
            conn.execute("DELETE FROM rules WHERE user=1 AND pattern=?", (pat,))
            conn.execute("INSERT INTO rules(pattern,category_id,sign,user) VALUES(?,?,?,1)", (pat, int(body["category_id"]), sign))
            if body.get("override"):
                core.apply_rule_everywhere(conn, pat, int(body["category_id"]))
            conn.commit()
            return {"changed": core.recategorize(conn)}
        if res == "rules" and method == "POST" and oid and sub == "apply":
            r = conn.execute("SELECT pattern,category_id FROM rules WHERE id=? AND user=1", (oid,)).fetchone()
            if not r:
                raise ApiError("Nie ma takiej reguły.")
            core.apply_rule_everywhere(conn, r["pattern"], r["category_id"])
            conn.commit()
            return {"changed": core.recategorize(conn)}
        if res == "rules" and method == "DELETE":
            conn.execute("DELETE FROM rules WHERE id=? AND user=1", (oid,))
            conn.commit()
            return {"changed": core.recategorize(conn)}

        if res == "people" and method == "POST":
            name = (body.get("name") or "").strip()
            if not name:
                raise ApiError("Podaj imię.")
            if oid:
                conn.execute("UPDATE people SET name=? WHERE id=?", (name, oid))
                if "fullname" in body:
                    conn.execute("UPDATE people SET fullname=? WHERE id=?", ((body["fullname"] or "").strip() or None, oid))
            else:
                conn.execute("INSERT INTO people(name,fullname) VALUES(?,?)", (name, (body.get("fullname") or "").strip() or None))
            conn.commit()
            if "fullname" in body:
                core.refresh_settlement_categories(conn)
            return {"ok": True}

        if res == "accounts" and method == "GET":
            b = conn.execute("SELECT MIN(date) a, MAX(date) b FROM transactions").fetchone()
            today = datetime.now().date().isoformat()
            return core.accounts_overview(conn, q.get("from") or b["a"] or today, q.get("to") or today)
        if res == "accounts" and method == "POST" and oid and sub == "balance":
            d = core.parse_date(body.get("date")) or datetime.now().date().isoformat()
            conn.execute("DELETE FROM balances WHERE account_id=? AND date=?", (oid, d))
            conn.execute("INSERT INTO balances(account_id,date,amount) VALUES(?,?,?)", (oid, d, int(body.get("amount") or 0)))
            conn.commit()
            return {"ok": True}
        if res == "accounts" and method == "POST" and oid:
            for k in ("person_id", "kind", "name"):
                if k in body:
                    if k == "kind" and body[k] not in core.KINDS:
                        raise ApiError("Nieznany rodzaj konta.")
                    conn.execute(f"UPDATE accounts SET {k}=? WHERE id=?", (body[k] or None, oid))
            conn.commit()
            core.reclassify_transfers(conn)
            return {"ok": True}
        if res == "accounts" and method == "POST":
            name = (body.get("name") or "").strip()
            if not name:
                raise ApiError("Podaj nazwę konta.")
            kind = body.get("kind") if body.get("kind") in core.KINDS else "savings"
            if kind == "cash":
                aid = core.cash_wallet(conn, int(body["person_id"]))
                if body.get("amount") not in (None, ""):
                    conn.execute("INSERT INTO balances(account_id,date,amount) VALUES(?,?,?)", (aid, datetime.now().date().isoformat(), int(body["amount"])))
                conn.commit()
                return {"id": aid}
            try:
                aid = conn.execute("INSERT INTO accounts(bank,label,person_id,kind) VALUES(?,?,?,?)", (core.MANUAL, name, int(body["person_id"]), kind)).lastrowid
            except Exception:
                raise ApiError("Konto o tej nazwie już istnieje.")
            if body.get("amount") not in (None, ""):
                conn.execute("INSERT INTO balances(account_id,date,amount) VALUES(?,?,?)", (aid, datetime.now().date().isoformat(), int(body["amount"])))
            conn.commit()
            return {"id": aid}
        if res == "accounts" and method == "DELETE":
            if conn.execute("SELECT 1 FROM transactions WHERE account_id=? AND IFNULL(manual,0)=0 LIMIT 1", (oid,)).fetchone():
                raise ApiError("To konto ma transakcje z wyciągów. Żeby je usunąć, cofnij wczytanie plików w zakładce Wczytaj wyciąg.")
            conn.execute("DELETE FROM balances WHERE account_id=?", (oid,))
            conn.execute("DELETE FROM transactions WHERE account_id=?", (oid,))
            conn.execute("DELETE FROM accounts WHERE id=?", (oid,))
            conn.commit()
            return {"ok": True}
        if res == "balances" and method == "DELETE":
            conn.execute("DELETE FROM balances WHERE id=?", (oid,))
            conn.commit()
            return {"ok": True}

        if res == "categories" and method == "POST" and sub == "order":
            for i, cid in enumerate(body.get("ids") or []):
                conn.execute("UPDATE categories SET sort=? WHERE id=?", (i, int(cid)))
            conn.commit()
            return {"ok": True}
        if res == "categories" and method == "POST":
            if oid:
                for k in ("name", "kind", "budget"):
                    if k in body:
                        conn.execute(f"UPDATE categories SET {k}=? WHERE id=?", (body[k], oid))
            else:
                name = (body.get("name") or "").strip()
                if not name:
                    raise ApiError("Podaj nazwę kategorii.")
                try:
                    conn.execute("INSERT INTO categories(name,kind,sort) VALUES(?,?,999)", (name, body.get("kind", "expense")))
                except Exception:
                    raise ApiError("Taka kategoria już istnieje.")
            conn.commit()
            return {"ok": True}
        if res == "categories" and method == "DELETE":
            conn.execute("UPDATE transactions SET category_id=NULL, cat_source=NULL WHERE category_id=?", (oid,))
            conn.execute("UPDATE receipt_items SET category_id=NULL WHERE category_id=?", (oid,))
            conn.execute("DELETE FROM rules WHERE category_id=?", (oid,))
            conn.execute("DELETE FROM item_rules WHERE category_id=?", (oid,))
            conn.execute("DELETE FROM categories WHERE id=?", (oid,))
            conn.commit()
            return {"ok": True}

        if res == "import" and method == "POST":
            name = unquote(headers.get("X-Filename", "wyciag.csv"))
            try:
                out = core.import_statement(conn, raw, name, json.loads(unquote(headers.get("X-Assign", "{}"))),
                                            json.loads(unquote(headers.get("X-Mapping", "null"))))
            except StopIteration:
                raise ApiError("Nie rozpoznaję układu tego pliku.")
            except ValueError as e:
                raise ApiError(str(e))
            if "added" in out:
                out["receipts_matched"] = rc.match_transactions(conn)
            return out
        if res == "imports" and method == "DELETE":
            conn.execute("UPDATE receipts SET transaction_id=NULL WHERE transaction_id IN (SELECT id FROM transactions WHERE import_id=?)", (oid,))
            conn.execute("DELETE FROM transactions WHERE import_id=?", (oid,))
            conn.execute("DELETE FROM settlement_items WHERE transaction_id NOT IN (SELECT id FROM transactions)")
            conn.execute("DELETE FROM imports WHERE id=?", (oid,))
            conn.execute("DELETE FROM accounts WHERE bank!=? AND id NOT IN (SELECT DISTINCT account_id FROM transactions)", (core.MANUAL,))
            conn.execute("DELETE FROM balances WHERE account_id NOT IN (SELECT id FROM accounts)")
            conn.commit()
            return {"ok": True}

        if res == "receipts":
            if method == "GET" and not oid:
                return rows(conn.execute("SELECT r.id,r.kind,r.date,r.store,r.total,r.payment,r.person_id,r.transaction_id,r.checked,r.engine,"
                                         "r.saved+(SELECT IFNULL(SUM(discount),0) FROM receipt_items i WHERE i.receipt_id=r.id) saved,"
                                         "(SELECT COUNT(*) FROM receipt_items i WHERE i.receipt_id=r.id) n,"
                                         "(SELECT IFNULL(SUM(amount),0) FROM receipt_items i WHERE i.receipt_id=r.id) items_sum "
                                         "FROM receipts r ORDER BY IFNULL(r.date,r.created) DESC, r.id DESC"))
            if method == "GET" and sub == "candidates":
                r = conn.execute("SELECT * FROM receipts WHERE id=?", (oid,)).fetchone()
                d = r["date"] or r["created"][:10]
                return rows(conn.execute("SELECT t.id,t.date,t.amount,t.description,t.counterparty,a.person_id FROM transactions t JOIN accounts a ON a.id=t.account_id "
                                         "WHERE t.amount<0 AND t.date BETWEEN date(?,'-5 day') AND date(?,?) "
                                         "AND t.id NOT IN (SELECT transaction_id FROM receipts WHERE transaction_id IS NOT NULL) "
                                         "ORDER BY ABS(t.amount+?), ABS(julianday(t.date)-julianday(?)) LIMIT 8",
                                         (d, d, "+40 day" if r["kind"] == "faktura" else "+10 day", r["total"] or 0, d)))
            if method == "POST" and sub == "reread":
                with LOCK:
                    conn.execute("UPDATE receipts SET transaction_id=NULL WHERE id=?", (oid,))
                    read_receipt(conn, oid)
                    rc.match_transactions(conn)
                return receipt_json(conn, oid)
            if method == "POST" and sub == "rereadall":
                ids = [r["id"] for r in conn.execute("SELECT id FROM receipts WHERE checked=0")]
                with LOCK:
                    for i in ids:
                        conn.execute("UPDATE receipts SET transaction_id=NULL WHERE id=?", (i,))
                        read_receipt(conn, i)
                    return {"count": len(ids), "matched": rc.match_transactions(conn)}
            if method == "GET":
                return receipt_json(conn, oid)
            if method == "POST" and not oid:
                with LOCK:
                    return add_receipt(conn, raw, unquote(headers.get("X-Filename", "paragon.jpg")), int(q["person"]) if q.get("person") else None)
            if method == "POST":
                return update_receipt(conn, oid, body)
            if method == "DELETE":
                r = conn.execute("SELECT file,preview FROM receipts WHERE id=?", (oid,)).fetchone()
                for f in {r["file"], r["preview"]} if r else ():
                    if f and os.path.exists(os.path.join(core.RECEIPT_DIR, f)):
                        os.remove(os.path.join(core.RECEIPT_DIR, f))
                conn.execute("DELETE FROM receipt_items WHERE receipt_id=?", (oid,))
                conn.execute("DELETE FROM receipts WHERE id=?", (oid,))
                conn.commit()
                return {"ok": True}

        if res == "items":
            where, args = " WHERE 1=1", []
            if q.get("from"): where += " AND r.date>=?"; args.append(q["from"])
            if q.get("to"): where += " AND r.date<=?"; args.append(q["to"])
            if q.get("person"): where += " AND r.person_id=?"; args.append(int(q["person"]))
            sql = "FROM receipt_items i JOIN receipts r ON r.id=i.receipt_id LEFT JOIN categories c ON c.id=i.category_id" + where
            tot = conn.execute("SELECT COUNT(*) n, IFNULL(SUM(r.saved),0) extra, IFNULL(SUM(r.total),0) paid, "
                               "IFNULL(SUM((SELECT SUM(discount) FROM receipt_items i WHERE i.receipt_id=r.id)),0) disc, "
                               "SUM(CASE WHEN r.saved+(SELECT IFNULL(SUM(discount),0) FROM receipt_items i WHERE i.receipt_id=r.id)>0 THEN 1 ELSE 0 END) with_disc "
                               "FROM receipts r" + where, args).fetchone()
            return dict(products=rows(conn.execute("SELECT MIN(i.name) name, SUM(i.amount) amount, SUM(i.qty) qty, COUNT(*) n, MAX(c.name) category "
                                                   + sql + " GROUP BY UPPER(i.name) ORDER BY amount DESC LIMIT 40", args)),
                        categories=rows(conn.execute("SELECT IFNULL(c.name,'Bez kategorii') name, SUM(i.amount) amount, COUNT(*) n "
                                                     + sql + " GROUP BY c.name ORDER BY amount DESC", args)),
                        savings=dict(total=tot["extra"] + tot["disc"], paid=tot["paid"], receipts=tot["n"], with_discount=tot["with_disc"] or 0,
                                     stores=rows(conn.execute("SELECT r.store name, COUNT(*) n, SUM(r.total) paid, SUM(r.saved+(SELECT IFNULL(SUM(discount),0) "
                                                              "FROM receipt_items i WHERE i.receipt_id=r.id)) saved_sum FROM receipts r" + where +
                                                              " GROUP BY r.store HAVING saved_sum>0 ORDER BY saved_sum DESC LIMIT 8", args)),
                                     products=rows(conn.execute("SELECT MIN(i.name) name, SUM(i.discount) saved, SUM(i.amount) paid, COUNT(*) n " + sql +
                                                                " AND i.discount>0 GROUP BY UPPER(i.name) ORDER BY saved DESC LIMIT 10", args))))

        if res in ("products", "product"):
            data = product_rows(conn, int(q["person"]) if q.get("person") else None)
            if res == "product":
                return [d for d in data if d["key"] == q.get("name")]
            data = [d for d in data if (not q.get("from") or d["date"] >= q["from"]) and (not q.get("to") or d["date"] <= q["to"])]
            groups = {}
            for d in data:
                groups.setdefault(d["key"], []).append(d)
            out, up, down, base, now = [], 0, 0, 0, 0
            for key, g in groups.items():
                names = [d["name"] for d in g]
                qty, paid = sum(d["qty"] for d in g), sum(d["amount"] for d in g)
                first, last = g[0], g[-1]
                comparable = first["date"] != last["date"]
                change = last["price"] - first["price"] if comparable else None
                if comparable:
                    w = qty / len(g)
                    base += first["price"] * w; now += last["price"] * w
                    up += change > 0; down += change < 0
                out.append(dict(key=key, name=max(set(names), key=names.count), category=g[-1]["category"], n=len(g), qty=round(qty, 3), paid=paid,
                                saved=sum(d["discount"] or 0 for d in g), avg_paid=round(paid / qty), first=first["price"], last=last["price"],
                                first_date=first["date"], last_date=last["date"], change=change,
                                pct=(round(change / first["price"] * 100, 1) if comparable and first["price"] else None),
                                min=min(d["price"] for d in g), max=max(d["price"] for d in g), stores=sorted({d["store"] or "" for d in g})))
            out.sort(key=lambda p: -p["paid"])
            skipped = conn.execute("SELECT COUNT(*) FROM receipts r WHERE r.checked=0 AND r.total!=(SELECT IFNULL(SUM(amount),0) FROM receipt_items x WHERE x.receipt_id=r.id)"
                                   + (" AND r.date>=?" if q.get("from") else "") + (" AND r.date<=?" if q.get("to") else ""),
                                   [x for x in (q.get("from"), q.get("to")) if x]).fetchone()[0]
            return dict(skipped=skipped, products=out, up=up, down=down, same=sum(1 for p in out if p["change"] == 0),
                        basket=(round((now / base - 1) * 100, 1) if base else None), compared=up + down + sum(1 for p in out if p["change"] == 0))

        if res == "settlements":
            if method == "GET":
                return dict(groups=core.settlements_report(conn, q.get("from"), q.get("to"), int(q["person"]) if q.get("person") else None),
                            suggestions=core.settlement_suggestions(conn))
            if method == "POST" and sub == "preview":
                m = core.settlement_members(conn, body.get("patterns") or "")
                return dict(count=len(m), balance=sum(t["amount"] for t in m), rows=m[-10:][::-1])
            if method == "POST":
                name, pats = (body.get("name") or "").strip(), "\n".join(p.strip() for p in re.split(r"[\n;]+", body.get("patterns") or "") if len(core.norm(p)) >= 3)
                manual = body.get("mode") == "manual"
                items = [int(i) for i in body.get("items") or []]
                if not name:
                    raise ApiError("Podaj nazwę rozliczenia.")
                if manual and not items:
                    raise ApiError("Dodaj co najmniej jedną transakcję.")
                if not manual and not pats:
                    raise ApiError("Podaj co najmniej jedną frazę (minimum 3 znaki).")
                args = (name, "" if manual else pats, body.get("category_id") or None, max(1, min(400, int(body.get("window") or 40))), "manual" if manual else "auto")
                if oid:
                    conn.execute("UPDATE settlements SET name=?,patterns=?,category_id=?,window=?,mode=? WHERE id=?", args + (oid,))
                else:
                    oid = conn.execute("INSERT INTO settlements(name,patterns,category_id,window,mode) VALUES(?,?,?,?,?)", args).lastrowid
                conn.execute("DELETE FROM settlement_items WHERE settlement_id=?", (oid,))
                for i in items if manual else []:
                    conn.execute("INSERT OR IGNORE INTO settlement_items(settlement_id,transaction_id) VALUES(?,?)", (oid, i))
                conn.commit()
                core.refresh_settlement_categories(conn)
                return {"ok": True}
            if method == "DELETE":
                conn.execute("DELETE FROM settlement_items WHERE settlement_id=?", (oid,))
                conn.execute("DELETE FROM settlements WHERE id=?", (oid,))
                conn.commit()
                core.refresh_settlement_categories(conn)
                return {"ok": True}

        if res == "quit" and method == "POST":
            threading.Thread(target=lambda: (time.sleep(0.3), os._exit(0)), daemon=True).start()
            return {"ok": True}
        raise ApiError("Nieznane polecenie.")
    finally:
        conn.close()


def export_csv(q):
    conn = core.connect()
    sql, args = tx_query(q)
    out = io.StringIO()
    w = csv.writer(out, delimiter=";")
    w.writerow(["Data", "Osoba", "Bank", "Konto", "Kwota", "Waluta", "Kategoria", "Kontrahent", "Opis", "Notatka"])
    for r in conn.execute("SELECT t.date,(SELECT name FROM people p WHERE p.id=a.person_id),a.bank,a.label,t.amount,t.currency,c.name,t.counterparty,t.description,t.note "
                          + sql + " ORDER BY t.date,t.id", args):
        r = list(r)
        r[4] = f"{r[4] / 100:.2f}".replace(".", ",")
        w.writerow(r)
    conn.close()
    return ("﻿" + out.getvalue()).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def send(self, code, data, ctype="application/json; charset=utf-8", extra=None):
        if not isinstance(data, bytes):
            data = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def handle_any(self, method):
        # aplikacja odpowiada tylko na żądania z tego komputera, wysłane z jej własnej strony
        host = self.headers.get("Host", "")
        if host.split(":")[0] not in ("127.0.0.1", "localhost"):
            return self.send(403, {"error": "Niedozwolony adres."})
        origin = self.headers.get("Origin")
        if method != "GET" and origin and urlparse(origin).netloc != host:
            return self.send(403, {"error": "Niedozwolone źródło."})
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items() if v[0] != ""}
        try:
            if u.path.startswith("/api/"):
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b""
                body = {}
                if raw and self.headers.get("Content-Type", "").startswith("application/json"):
                    body = json.loads(raw)
                if u.path == "/api/export.csv":
                    return self.send(200, export_csv(q), "text/csv; charset=utf-8", {"Content-Disposition": 'attachment; filename="budzet-transakcje.csv"'})
                return self.send(200, api(method, u.path, q, body, raw, self.headers))
            if u.path.startswith("/paragon/"):
                f = os.path.join(core.RECEIPT_DIR, os.path.basename(unquote(u.path)))
                if os.path.isfile(f):
                    with open(f, "rb") as fh:
                        return self.send(200, fh.read(), mimetypes.guess_type(f)[0] or "application/octet-stream")
                return self.send(404, b"", "text/plain")
            name = "index.html" if u.path == "/" else os.path.basename(u.path)
            f = os.path.join(STATIC, name)
            if os.path.isfile(f):
                with open(f, "rb") as fh:
                    kind = {".js": "text/javascript", ".css": "text/css", ".html": "text/html", ".svg": "image/svg+xml", ".json": "application/json"}.get(os.path.splitext(f)[1].lower())
                    return self.send(200, fh.read(), (kind or mimetypes.guess_type(f)[0] or "text/plain") + "; charset=utf-8")      # Windows potrafi podać zły typ z rejestru
            self.send(404, b"", "text/plain")
        except ApiError as e:
            self.send(400, {"error": str(e)})
        except Exception as e:  # noqa
            import traceback
            traceback.print_exc()
            self.send(500, {"error": f"Błąd programu: {e}"})

    def do_GET(self): self.handle_any("GET")
    def do_POST(self): self.handle_any("POST")
    def do_DELETE(self): self.handle_any("DELETE")


def main():
    c0 = core.init_db(); pl.ensure(c0); c0.close()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Budżet domowy {core.VERSION}: http://127.0.0.1:{PORT}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
