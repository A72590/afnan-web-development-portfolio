"""Distribution Manager - data layer. Money is stored as integer paisa."""
import csv
import sqlite3
from datetime import date
from decimal import Decimal, InvalidOperation

DB_FILE = "distribution.db"


class AppError(Exception):
    pass


def to_paisa(text):
    try:
        v = Decimal(str(text).strip().replace(",", "") or "0")
    except InvalidOperation:
        raise AppError("Invalid amount: %r" % text)
    if v < 0:
        raise AppError("Amount cannot be negative")
    return int((v * 100).quantize(Decimal("1")))


def pkr(p):
    return "PKR {:,.2f}".format(p / 100)


def to_qty(text):
    try:
        q = int(str(text).strip())
    except ValueError:
        raise AppError("Quantity must be a whole number")
    if q <= 0:
        raise AppError("Quantity must be greater than zero")
    return q


def check_date(d):
    try:
        date.fromisoformat(d)
    except (ValueError, TypeError):
        raise AppError("Date must be YYYY-MM-DD")
    return d


SCHEMA = """
CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL COLLATE NOCASE,
 name TEXT NOT NULL, unit TEXT NOT NULL DEFAULT 'pcs', purchase_price INTEGER NOT NULL DEFAULT 0,
 sale_price INTEGER NOT NULL DEFAULT 0, stock INTEGER NOT NULL DEFAULT 0 CHECK(stock>=0),
 low_threshold INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS suppliers(id INTEGER PRIMARY KEY, name TEXT NOT NULL, phone TEXT DEFAULT '',
 address TEXT DEFAULT '', opening_balance INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS customers(id INTEGER PRIMARY KEY, name TEXT NOT NULL, phone TEXT DEFAULT '',
 address TEXT DEFAULT '', opening_balance INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS purchases(id INTEGER PRIMARY KEY, invoice_no TEXT UNIQUE NOT NULL,
 supplier_id INTEGER NOT NULL REFERENCES suppliers(id), date TEXT NOT NULL, total INTEGER NOT NULL, paid INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS purchase_items(id INTEGER PRIMARY KEY, purchase_id INTEGER NOT NULL REFERENCES purchases(id),
 product_id INTEGER NOT NULL REFERENCES products(id), qty INTEGER NOT NULL, price INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS sales(id INTEGER PRIMARY KEY, invoice_no TEXT UNIQUE NOT NULL,
 customer_id INTEGER NOT NULL REFERENCES customers(id), date TEXT NOT NULL, total INTEGER NOT NULL, paid INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS sale_items(id INTEGER PRIMARY KEY, sale_id INTEGER NOT NULL REFERENCES sales(id),
 product_id INTEGER NOT NULL REFERENCES products(id), qty INTEGER NOT NULL, price INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS returns(id INTEGER PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN('customer','supplier')),
 party_id INTEGER NOT NULL, product_id INTEGER NOT NULL REFERENCES products(id), qty INTEGER NOT NULL,
 date TEXT NOT NULL, reason TEXT DEFAULT '', invoice_id INTEGER, condition TEXT NOT NULL,
 unit_price INTEGER NOT NULL, amount INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN('customer','supplier')),
 party_id INTEGER NOT NULL, date TEXT NOT NULL, amount INTEGER NOT NULL CHECK(amount>0), note TEXT DEFAULT '');
"""


class DB:
    def __init__(self, path=DB_FILE):
        self.path = path
        self.c = sqlite3.connect(path, isolation_level=None)  # manual transactions
        self.c.row_factory = sqlite3.Row
        self.c.execute("PRAGMA foreign_keys=ON")
        self.c.executescript(SCHEMA)

    def q(self, sql, args=()):
        return self.c.execute(sql, args).fetchall()

    def one(self, sql, args=()):
        return self.c.execute(sql, args).fetchone()

    def _tx(self, fn):
        """Run fn inside one transaction; roll back on any error."""
        self.c.execute("BEGIN")
        try:
            r = fn()
            self.c.execute("COMMIT")
            return r
        except sqlite3.IntegrityError as e:
            self.c.execute("ROLLBACK")
            raise AppError("Data conflict: %s" % e)
        except Exception:
            self.c.execute("ROLLBACK")
            raise

    # ---- products
    def save_product(self, pid, code, name, unit, pp, sp, stock, low):
        code, name = code.strip(), name.strip()
        if not code or not name:
            raise AppError("Product name and code are required")
        pp, sp = to_paisa(pp), to_paisa(sp)
        try:
            stock, low = int(stock or 0), int(low or 0)
        except ValueError:
            raise AppError("Stock and threshold must be whole numbers")
        if stock < 0 or low < 0:
            raise AppError("Stock and threshold cannot be negative")
        unit = unit.strip() or "pcs"

        def f():
            if pid:
                self.c.execute("UPDATE products SET code=?,name=?,unit=?,purchase_price=?,sale_price=?,stock=?,low_threshold=? WHERE id=?",
                               (code, name, unit, pp, sp, stock, low, pid))
            else:
                self.c.execute("INSERT INTO products(code,name,unit,purchase_price,sale_price,stock,low_threshold) VALUES(?,?,?,?,?,?,?)",
                               (code, name, unit, pp, sp, stock, low))
        if self.one("SELECT 1 FROM products WHERE code=? AND id IS NOT ?", (code, pid)):
            raise AppError("Product code '%s' already exists" % code)
        self._tx(f)

    def products(self, search=""):
        s = "%" + search.strip() + "%"
        return self.q("SELECT *, stock*purchase_price AS value FROM products WHERE name LIKE ? OR code LIKE ? ORDER BY name", (s, s))

    # ---- parties
    def _table(self, kind):
        return {"customer": "customers", "supplier": "suppliers"}[kind]

    def save_party(self, kind, pid, name, phone, address, opening):
        if not name.strip():
            raise AppError("Name is required")
        ob = to_paisa(opening)
        t = self._table(kind)

        def f():
            if pid:
                self.c.execute("UPDATE %s SET name=?,phone=?,address=? WHERE id=?" % t, (name.strip(), phone, address, pid))
            else:
                self.c.execute("INSERT INTO %s(name,phone,address,opening_balance) VALUES(?,?,?,?)" % t,
                               (name.strip(), phone, address, ob))
        self._tx(f)

    def parties(self, kind, search=""):
        s = "%" + search.strip() + "%"
        rows = self.q("SELECT * FROM %s WHERE name LIKE ? OR phone LIKE ? ORDER BY name" % self._table(kind), (s, s))
        return [dict(r, balance=self.balance(kind, r["id"])) for r in rows]

    def summary(self, kind, pid):
        """Balance = opening + invoiced - paid on invoice - returns - later payments."""
        inv, col = ("sales", "customer_id") if kind == "customer" else ("purchases", "supplier_id")
        opening = self.one("SELECT opening_balance FROM %s WHERE id=?" % self._table(kind), (pid,))[0]
        invoiced, ipaid = self.one("SELECT COALESCE(SUM(total),0),COALESCE(SUM(paid),0) FROM %s WHERE %s=?" % (inv, col), (pid,))
        rets = self.one("SELECT COALESCE(SUM(amount),0) FROM returns WHERE kind=? AND party_id=?", (kind, pid))[0]
        pays = self.one("SELECT COALESCE(SUM(amount),0) FROM payments WHERE kind=? AND party_id=?", (kind, pid))[0]
        return dict(opening=opening, invoiced=invoiced, invoice_paid=ipaid, returns=rets, payments=pays,
                    balance=opening + invoiced - ipaid - rets - pays)

    def balance(self, kind, pid):
        return self.summary(kind, pid)["balance"]

    # ---- invoices (sales & purchases share logic)
    def _invoice(self, kind, party_id, dt, items, paid):
        check_date(dt)
        if not items:
            raise AppError("Add at least one product")
        sale = kind == "sale"
        paid = to_paisa(paid)
        lines = []
        for pid, qty, price in items:
            qty = to_qty(qty)
            price = price if isinstance(price, int) else to_paisa(price)
            if price <= 0:
                raise AppError("Price must be greater than zero")
            lines.append((pid, qty, price))
        total = sum(q * p for _, q, p in lines)
        if paid > total:
            raise AppError("Paid amount cannot exceed invoice total")
        head, itab, pcol, ptab = (("sales", "sale_items", "customer_id", "customers") if sale
                                  else ("purchases", "purchase_items", "supplier_id", "suppliers"))
        sign = -1 if sale else 1

        def f():
            if not self.one("SELECT 1 FROM %s WHERE id=?" % ptab, (party_id,)):
                raise AppError("Select a valid %s" % ("customer" if sale else "supplier"))
            need = {}
            for pid, qty, _ in lines:
                need[pid] = need.get(pid, 0) + qty
            for pid, qty in need.items():
                p = self.one("SELECT name,stock FROM products WHERE id=?", (pid,))
                if not p:
                    raise AppError("Unknown product")
                if sale and qty > p["stock"]:
                    raise AppError("Not enough stock for %s (available %d, requested %d)" % (p["name"], p["stock"], qty))
            n = self.one("SELECT COALESCE(MAX(id),0)+1 FROM %s" % head)[0]
            no = "%s-%05d" % ("S" if sale else "P", n)
            iid = self.c.execute("INSERT INTO %s(invoice_no,%s,date,total,paid) VALUES(?,?,?,?,?)" % (head, pcol),
                                 (no, party_id, dt, total, paid)).lastrowid
            for pid, qty, price in lines:
                self.c.execute("INSERT INTO %s(%s_id,product_id,qty,price) VALUES(?,?,?,?)" % (itab, "sale" if sale else "purchase"),
                               (iid, pid, qty, price))
                self.c.execute("UPDATE products SET stock=stock+? WHERE id=?", (sign * qty, pid))
                if not sale:
                    self.c.execute("UPDATE products SET purchase_price=? WHERE id=?", (price, pid))
            return iid
        return self._tx(f)

    def create_sale(self, customer_id, dt, items, paid):
        return self._invoice("sale", customer_id, dt, items, paid)

    def create_purchase(self, supplier_id, dt, items, paid):
        return self._invoice("purchase", supplier_id, dt, items, paid)

    def invoices(self, kind, search="", d1="", d2=""):
        head, party, col = (("sales", "customers", "customer_id") if kind == "sale"
                            else ("purchases", "suppliers", "supplier_id"))
        s = "%" + search.strip() + "%"
        return self.q("""SELECT h.*, p.name AS party, h.total-h.paid AS due FROM %s h JOIN %s p ON p.id=h.%s
            WHERE (h.invoice_no LIKE ? OR p.name LIKE ?) AND h.date>=? AND h.date<=? ORDER BY h.date DESC, h.id DESC"""
                      % (head, party, col), (s, s, d1 or "0000-00-00", d2 or "9999-99-99"))

    def invoice_items(self, kind, iid):
        itab, k = ("sale_items", "sale_id") if kind == "sale" else ("purchase_items", "purchase_id")
        return self.q("SELECT i.*, p.name, p.code, i.qty*i.price AS line FROM %s i JOIN products p ON p.id=i.product_id WHERE i.%s=?" % (itab, k), (iid,))

    # ---- returns
    def create_return(self, kind, party_id, product_id, qty, dt, reason, condition, invoice_id=None):
        """kind: 'customer' or 'supplier'. condition: 'resalable' or 'damaged'."""
        check_date(dt)
        qty = to_qty(qty)
        if condition not in ("resalable", "damaged"):
            raise AppError("Condition must be resalable or damaged")
        cust = kind == "customer"

        def f():
            p = self.one("SELECT * FROM products WHERE id=?", (product_id,))
            if not p:
                raise AppError("Select a product")
            if not self.one("SELECT 1 FROM %s WHERE id=?" % self._table(kind), (party_id,)):
                raise AppError("Select a valid party")
            price = p["sale_price"] if cust else p["purchase_price"]
            if invoice_id:
                head, itab, k, pcol = (("sales", "sale_items", "sale_id", "customer_id") if cust
                                       else ("purchases", "purchase_items", "purchase_id", "supplier_id"))
                inv = self.one("SELECT * FROM %s WHERE id=?" % head, (invoice_id,))
                if not inv or inv[pcol] != party_id:
                    raise AppError("Invoice not found for this party")
                it = self.one("SELECT COALESCE(SUM(qty),0) q, MAX(price) pr FROM %s WHERE %s=? AND product_id=?" % (itab, k),
                              (invoice_id, product_id))
                if it["q"] == 0:
                    raise AppError("Product is not on that invoice")
                done = self.one("SELECT COALESCE(SUM(qty),0) FROM returns WHERE kind=? AND invoice_id=? AND product_id=?",
                                (kind, invoice_id, product_id))[0]
                if done + qty > it["q"]:
                    raise AppError("Already returned %d of %d on this invoice; cannot return %d more" % (done, it["q"], qty))
                price = it["pr"]
            if cust and condition == "resalable":
                self.c.execute("UPDATE products SET stock=stock+? WHERE id=?", (qty, product_id))
            elif not cust:
                if qty > p["stock"]:
                    raise AppError("Not enough stock to return to supplier (available %d)" % p["stock"])
                self.c.execute("UPDATE products SET stock=stock-? WHERE id=?", (qty, product_id))
            return self.c.execute("INSERT INTO returns(kind,party_id,product_id,qty,date,reason,invoice_id,condition,unit_price,amount) VALUES(?,?,?,?,?,?,?,?,?,?)",
                                  (kind, party_id, product_id, qty, dt, reason, invoice_id, condition, price, price * qty)).lastrowid
        return self._tx(f)

    def returns(self, kind, d1="", d2=""):
        return self.q("""SELECT r.*, p.name AS party, pr.name AS product FROM returns r JOIN %s p ON p.id=r.party_id
            JOIN products pr ON pr.id=r.product_id WHERE r.kind=? AND r.date>=? AND r.date<=? ORDER BY r.date DESC, r.id DESC"""
                      % self._table(kind), (kind, d1 or "0000-00-00", d2 or "9999-99-99"))

    # ---- payments
    def add_payment(self, kind, party_id, dt, amount, note=""):
        check_date(dt)
        amt = to_paisa(amount)
        if amt <= 0:
            raise AppError("Payment must be greater than zero")

        def f():
            if not self.one("SELECT 1 FROM %s WHERE id=?" % self._table(kind), (party_id,)):
                raise AppError("Select a valid party")
            bal = self.balance(kind, party_id)
            if amt > bal:
                raise AppError("Payment exceeds outstanding balance (%s)" % pkr(bal))
            return self.c.execute("INSERT INTO payments(kind,party_id,date,amount,note) VALUES(?,?,?,?,?)",
                                  (kind, party_id, dt, amt, note)).lastrowid
        return self._tx(f)

    def payments(self, kind, search="", d1="", d2=""):
        s = "%" + search.strip() + "%"
        return self.q("""SELECT y.*, p.name AS party FROM payments y JOIN %s p ON p.id=y.party_id
            WHERE y.kind=? AND p.name LIKE ? AND y.date>=? AND y.date<=? ORDER BY y.date DESC, y.id DESC""" % self._table(kind),
                      (kind, s, d1 or "0000-00-00", d2 or "9999-99-99"))

    # ---- dashboard
    def dashboard(self):
        today = date.today().isoformat()
        return dict(
            products=self.one("SELECT COUNT(*) FROM products")[0],
            stock=self.one("SELECT COALESCE(SUM(stock),0) FROM products")[0],
            stock_value=self.one("SELECT COALESCE(SUM(stock*purchase_price),0) FROM products")[0],
            today_sales=self.one("SELECT COALESCE(SUM(total),0) FROM sales WHERE date=?", (today,))[0],
            receivable=sum(c["balance"] for c in self.parties("customer")),
            payable=sum(s["balance"] for s in self.parties("supplier")),
            low=self.q("SELECT * FROM products WHERE stock<=low_threshold ORDER BY stock"))

    # ---- backup / export
    def backup(self, dest):
        d = sqlite3.connect(dest)
        self.c.backup(d)
        d.close()

    @staticmethod
    def export_csv(path, headers, rows):
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(headers)
            w.writerows([list(r) for r in rows])
