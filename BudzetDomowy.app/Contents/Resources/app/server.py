"""Budżet domowy – lokalny serwer aplikacji (działa wyłącznie na tym komputerze)."""
import csv, io, json, mimetypes, os, re, sys, threading, time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

import core
import receipts as rc

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


def add_receipt(conn, raw, filename, person):
    ext = os.path.splitext(filename)[1].lower() or ".jpg"
    if ext not in (".jpg", ".jpeg", ".png", ".pdf", ".heic", ".tif", ".tiff", ".webp"):
        raise ApiError("Paragon musi być zdjęciem (JPG, PNG, HEIC) albo plikiem PDF.")
    rid = conn.execute("INSERT INTO receipts(created,person_id) VALUES(?,?)", (datetime.now().isoformat(timespec="seconds"), person)).lastrowid
    path = os.path.join(core.RECEIPT_DIR, f"{rid}{ext}")
    with open(path, "wb") as f:
        f.write(raw)
    preview = os.path.join(core.RECEIPT_DIR, f"{rid}-podglad.jpg")
    if not rc.make_preview(path, preview):
        preview = path
    frags, engine = rc.ocr(path, preview)
    text_rows = rc.to_rows(frags) if frags else []
    p = rc.parse_receipt(text_rows) if text_rows else dict(store="", date=None, total=0, payment=None, items=[])
    conn.execute("UPDATE receipts SET date=?,store=?,total=?,payment=?,file=?,preview=?,ocr_text=?,engine=? WHERE id=?",
                 (p["date"], p["store"], p["total"], p["payment"], os.path.basename(path), os.path.basename(preview),
                  "\n".join(text_rows), engine, rid))
    for i, it in enumerate(p["items"]):
        conn.execute("INSERT INTO receipt_items(receipt_id,name,qty,unit_price,amount,category_id,pos) VALUES(?,?,?,?,?,?,?)",
                     (rid, it["name"], it["qty"], it["unit_price"], it["amount"], rc.item_category(conn, it["name"], p["store"]), i))
    conn.commit()
    rc.match_transactions(conn)
    return receipt_json(conn, rid)


def update_receipt(conn, rid, b):
    for k in ("date", "store", "total", "payment", "person_id", "checked"):
        if k in b:
            conn.execute(f"UPDATE receipts SET {k}=? WHERE id=?", (b[k] or None if k != "total" else int(b[k] or 0), rid))
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
            conn.execute("INSERT INTO receipt_items(receipt_id,name,qty,unit_price,amount,category_id,pos) VALUES(?,?,?,?,?,?,?)",
                         (rid, name, float(it.get("qty") or 1), int(it.get("unit_price") or 0), int(it.get("amount") or 0), cid, i))
    conn.commit()
    if b.get("rematch"):
        rc.match_transactions(conn)
    return receipt_json(conn, rid)


def tx_query(q):
    sql = ("FROM transactions t JOIN accounts a ON a.id=t.account_id LEFT JOIN categories c ON c.id=t.category_id "
           "LEFT JOIN receipts r ON r.transaction_id=t.id WHERE 1=1")
    args = []
    if q.get("from"): sql += " AND t.date>=?"; args.append(q["from"])
    if q.get("to"): sql += " AND t.date<=?"; args.append(q["to"])
    if q.get("person"): sql += " AND a.person_id=?"; args.append(int(q["person"]))
    if q.get("account"): sql += " AND a.id=?"; args.append(int(q["account"]))
    if q.get("category") == "none": sql += " AND t.category_id IS NULL"
    elif q.get("category"): sql += " AND t.category_id=?"; args.append(int(q["category"]))
    if q.get("q"):
        for w in q["q"].split():
            sql += " AND (t.description LIKE ? OR t.counterparty LIKE ? OR t.note LIKE ?)"
            args += [f"%{w}%"] * 3
    return sql, args


def api(method, path, q, body, raw, headers):
    conn = core.connect()
    try:
        m = re.match(r"^/api/(\w+)(?:/(\d+))?(?:/(\w+))?$", path)
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
                        first=b["a"], last=b["b"], tx_count=b["n"], ocr=rc.engine_status(), data_dir=core.DATA_DIR)

        if res == "summary":
            return core.summary(conn, q.get("from"), q.get("to"), int(q["person"]) if q.get("person") else None)

        if res == "transactions" and method == "GET":
            sql, args = tx_query(q)
            total = conn.execute("SELECT COUNT(*) n, IFNULL(SUM(t.amount),0) s " + sql, args).fetchone()
            lim, off = int(q.get("limit", 200)), int(q.get("offset", 0))
            data = rows(conn.execute("SELECT t.id,t.date,t.amount,t.currency,t.description,t.counterparty,t.category_id,t.cat_source,t.note,"
                                     "a.person_id,a.bank,a.label account,r.id receipt_id " + sql + " ORDER BY t.date DESC,t.id DESC LIMIT ? OFFSET ?", args + [lim, off]))
            for d in data:
                d["merchant"] = core.merchant(d["description"], d["counterparty"])
            return dict(total=total["n"], sum=total["s"], rows=data)

        if res == "transactions" and method == "POST" and oid:
            if "category_id" in body:
                conn.execute("UPDATE transactions SET category_id=?, cat_source='manual' WHERE id=?", (body["category_id"] or None, oid))
            if "note" in body:
                conn.execute("UPDATE transactions SET note=? WHERE id=?", (body["note"], oid))
            conn.commit()
            return {"ok": True}

        if res == "rules" and method == "POST":
            pat = core.norm(body.get("pattern"))
            if len(pat) < 3:
                raise ApiError("Fraza reguły musi mieć co najmniej 3 znaki.")
            conn.execute("DELETE FROM rules WHERE user=1 AND pattern=?", (pat,))
            conn.execute("INSERT INTO rules(pattern,category_id,sign,user) VALUES(?,?,0,1)", (pat, int(body["category_id"])))
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
            else:
                conn.execute("INSERT INTO people(name) VALUES(?)", (name,))
            conn.commit()
            return {"ok": True}

        if res == "accounts" and method == "POST" and oid:
            conn.execute("UPDATE accounts SET person_id=? WHERE id=?", (int(body["person_id"]), oid))
            conn.commit()
            core.detect_internal(conn)
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
            conn.execute("DELETE FROM imports WHERE id=?", (oid,))
            conn.execute("DELETE FROM accounts WHERE id NOT IN (SELECT DISTINCT account_id FROM transactions)")
            conn.commit()
            return {"ok": True}

        if res == "receipts":
            if method == "GET" and not oid:
                return rows(conn.execute("SELECT r.id,r.date,r.store,r.total,r.payment,r.person_id,r.transaction_id,r.checked,r.engine,"
                                         "(SELECT COUNT(*) FROM receipt_items i WHERE i.receipt_id=r.id) n,"
                                         "(SELECT IFNULL(SUM(amount),0) FROM receipt_items i WHERE i.receipt_id=r.id) items_sum "
                                         "FROM receipts r ORDER BY IFNULL(r.date,r.created) DESC, r.id DESC"))
            if method == "GET" and sub == "candidates":
                r = conn.execute("SELECT * FROM receipts WHERE id=?", (oid,)).fetchone()
                return rows(conn.execute("SELECT t.id,t.date,t.amount,t.description,t.counterparty FROM transactions t WHERE t.amount<0 "
                                         "AND t.date BETWEEN date(?,'-3 day') AND date(?,'+7 day') ORDER BY ABS(t.amount+?) LIMIT 12",
                                         (r["date"] or "1900-01-01", r["date"] or "1900-01-01", r["total"] or 0)))
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
            sql = ("FROM receipt_items i JOIN receipts r ON r.id=i.receipt_id LEFT JOIN categories c ON c.id=i.category_id WHERE 1=1")
            args = []
            if q.get("from"): sql += " AND r.date>=?"; args.append(q["from"])
            if q.get("to"): sql += " AND r.date<=?"; args.append(q["to"])
            if q.get("person"): sql += " AND r.person_id=?"; args.append(int(q["person"]))
            return dict(products=rows(conn.execute("SELECT MIN(i.name) name, SUM(i.amount) amount, SUM(i.qty) qty, COUNT(*) n, MAX(c.name) category "
                                                   + sql + " GROUP BY UPPER(i.name) ORDER BY amount DESC LIMIT 40", args)),
                        categories=rows(conn.execute("SELECT IFNULL(c.name,'Bez kategorii') name, SUM(i.amount) amount, COUNT(*) n "
                                                     + sql + " GROUP BY c.name ORDER BY amount DESC", args)),
                        stores=rows(conn.execute("SELECT r.store name, COUNT(DISTINCT r.id) n, SUM(i.amount) amount " + sql +
                                                 " GROUP BY r.store ORDER BY amount DESC LIMIT 10", args)))

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
                    return self.send(200, fh.read(), (mimetypes.guess_type(f)[0] or "text/plain") + "; charset=utf-8")
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
    core.init_db().close()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Budżet domowy {core.VERSION}: http://127.0.0.1:{PORT}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
