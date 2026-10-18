"""Distribution Manager - Tkinter UI (Phase 1). Run: python app.py"""
import os
import tkinter as tk
from datetime import date
from tkinter import ttk, messagebox, filedialog

from db import DB, AppError, pkr, DB_FILE

BASE = os.path.dirname(os.path.abspath(__file__))
db = DB(os.path.join(BASE, DB_FILE))
today = lambda: date.today().isoformat()


def guard(fn):
    def w(*a, **k):
        try:
            return fn(*a, **k)
        except AppError as e:
            messagebox.showerror("Error", str(e))
    return w


class Table(ttk.Frame):
    """Sortable table. columns: [(title, width)]."""
    def __init__(self, parent, columns, height=14):
        super().__init__(parent)
        self.tv = ttk.Treeview(self, columns=[c[0] for c in columns], show="headings", height=height)
        for t, w in columns:
            self.tv.heading(t, text=t, command=lambda t=t: self.sort(t))
            self.tv.column(t, width=w, anchor="w")
        sb = ttk.Scrollbar(self, command=self.tv.yview)
        self.tv.configure(yscrollcommand=sb.set)
        self.tv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.rev = False
        self.ids = {}

    def fill(self, rows):  # rows: [(key, values)]
        self.tv.delete(*self.tv.get_children())
        for k, v in rows:
            self.tv.insert("", "end", iid=str(k), values=v)

    def selected(self):
        s = self.tv.selection()
        return int(s[0]) if s else None

    def values(self):
        return [self.tv.item(i)["values"] for i in self.tv.get_children()]

    def headers(self):
        return list(self.tv["columns"])

    def sort(self, col):
        def key(i):
            v = str(self.tv.set(i, col)).replace(",", "").replace("PKR ", "")
            try:
                return (0, float(v))
            except ValueError:
                return (1, v.lower())
        items = sorted(self.tv.get_children(), key=key, reverse=self.rev)
        for n, i in enumerate(items):
            self.tv.move(i, "", n)
        self.rev = not self.rev


class Form(tk.Toplevel):
    """Generic modal form. fields: [(label, initial, choices|None)]."""
    def __init__(self, parent, title, fields, on_ok):
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.on_ok = on_ok
        self.vars = []
        for r, (lbl, init, choices) in enumerate(fields):
            ttk.Label(self, text=lbl).grid(row=r, column=0, sticky="w", padx=8, pady=4)
            v = tk.StringVar(value=init)
            w = ttk.Combobox(self, textvariable=v, values=choices, state="readonly", width=38) if choices else ttk.Entry(self, textvariable=v, width=40)
            w.grid(row=r, column=1, padx=8, pady=4)
            self.vars.append(v)
        ttk.Button(self, text="Save", command=self.ok).grid(row=len(fields), column=1, sticky="e", padx=8, pady=8)
        self.grab_set()

    @guard
    def ok(self):
        self.on_ok([v.get() for v in self.vars])
        self.destroy()


def bar(parent, search=True, dates=False):
    f = ttk.Frame(parent)
    f.pack(fill="x", pady=4)
    s, a, b = tk.StringVar(), tk.StringVar(), tk.StringVar()
    if search:
        ttk.Label(f, text="Search:").pack(side="left")
        ttk.Entry(f, textvariable=s, width=22).pack(side="left", padx=4)
    if dates:
        ttk.Label(f, text="From (YYYY-MM-DD):").pack(side="left")
        ttk.Entry(f, textvariable=a, width=11).pack(side="left", padx=4)
        ttk.Label(f, text="To:").pack(side="left")
        ttk.Entry(f, textvariable=b, width=11).pack(side="left", padx=4)
    return f, s, a, b


def btn(f, text, cmd):
    ttk.Button(f, text=text, command=guard(cmd)).pack(side="left", padx=3)


def names(rows):
    return {"%s (#%d)" % (r["name"], r["id"]): r["id"] for r in rows}


def pick(label, m):
    if label not in m:
        raise AppError("Please select from the list")
    return m[label]


class Page(ttk.Frame):
    def refresh(self):
        pass


class Dashboard(Page):
    def __init__(self, p):
        super().__init__(p, padding=12)
        self.lbl = ttk.Label(self, font=("Segoe UI", 12), justify="left")
        self.lbl.pack(anchor="w")
        ttk.Label(self, text="Low-stock alerts", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(12, 2))
        self.t = Table(self, [("Code", 100), ("Product", 240), ("Stock", 80), ("Threshold", 80)])
        self.t.pack(fill="both", expand=True)

    def refresh(self):
        d = db.dashboard()
        self.lbl.config(text="Total products: %d\nAvailable stock (units): %d   |   Stock value: %s\nToday's sales: %s\n"
                             "Customers owe us: %s\nWe owe suppliers: %s" % (
                                 d["products"], d["stock"], pkr(d["stock_value"]), pkr(d["today_sales"]),
                                 pkr(d["receivable"]), pkr(d["payable"])))
        self.t.fill([(r["id"], (r["code"], r["name"], r["stock"], r["low_threshold"])) for r in d["low"]])


class Products(Page):
    def __init__(self, p):
        super().__init__(p, padding=8)
        f, self.s, _, _ = bar(self)
        self.s.trace_add("write", lambda *a: self.refresh())
        btn(f, "Add", self.add)
        btn(f, "Edit", self.edit)
        self.t = Table(self, [("Code", 90), ("Name", 220), ("Unit", 60), ("Purchase", 100), ("Sale", 100),
                              ("Stock", 70), ("Low at", 70), ("Stock value", 120)])
        self.t.pack(fill="both", expand=True)

    def refresh(self):
        self.t.fill([(r["id"], (r["code"], r["name"], r["unit"], pkr(r["purchase_price"]), pkr(r["sale_price"]),
                                r["stock"], r["low_threshold"], pkr(r["value"]))) for r in db.products(self.s.get())])

    def form(self, r):
        g = (lambda k, d="": r[k] if r else d)
        money = lambda k: "%.2f" % (r[k] / 100) if r else "0"
        pid = r["id"] if r else None
        Form(self, "Product", [("Code / SKU", g("code"), None), ("Name", g("name"), None), ("Unit", g("unit", "pcs"), None),
                               ("Purchase price", money("purchase_price"), None), ("Sale price", money("sale_price"), None),
                               ("Current stock", str(g("stock", 0)), None), ("Low-stock threshold", str(g("low_threshold", 0)), None)],
             lambda v: (db.save_product(pid, v[0], v[1], v[2], v[3], v[4], v[5], v[6]), self.refresh()))

    def add(self):
        self.form(None)

    def edit(self):
        i = self.t.selected()
        if i is None:
            raise AppError("Select a product first")
        self.form(db.one("SELECT * FROM products WHERE id=?", (i,)))


class Parties(Page):
    def __init__(self, p, kind):
        super().__init__(p, padding=8)
        self.kind = kind
        f, self.s, _, _ = bar(self)
        self.s.trace_add("write", lambda *a: self.refresh())
        btn(f, "Add", self.add)
        btn(f, "Edit", self.edit)
        btn(f, "View details", self.view)
        self.t = Table(self, [("Name", 200), ("Phone", 110), ("Address", 220), ("Opening", 100), ("Outstanding", 120)])
        self.t.pack(fill="both", expand=True)

    def refresh(self):
        self.t.fill([(r["id"], (r["name"], r["phone"], r["address"], pkr(r["opening_balance"]), pkr(r["balance"])))
                     for r in db.parties(self.kind, self.s.get())])

    def form(self, r):
        pid = r["id"] if r else None
        fields = [("Name", r["name"] if r else "", None), ("Phone", r["phone"] if r else "", None),
                  ("Address", r["address"] if r else "", None)]
        if not r:
            fields.append(("Opening balance (PKR)", "0", None))
        Form(self, self.kind.title(), fields,
             lambda v: (db.save_party(self.kind, pid, v[0], v[1], v[2], v[3] if len(v) > 3 else "0"), self.refresh()))

    def add(self):
        self.form(None)

    def sel(self):
        i = self.t.selected()
        if i is None:
            raise AppError("Select a row first")
        return i

    def edit(self):
        self.form(db.one("SELECT * FROM %s WHERE id=?" % db._table(self.kind), (self.sel(),)))

    def view(self):
        i = self.sel()
        s = db.summary(self.kind, i)
        inv = "sale" if self.kind == "customer" else "purchase"
        rows = [r for r in db.invoices(inv) if r["party"] == db.one("SELECT name FROM %s WHERE id=?" % db._table(self.kind), (i,))[0]]
        w = tk.Toplevel(self)
        w.title("Account details")
        ttk.Label(w, justify="left", padding=8, text="Opening balance: %s\nInvoiced: %s (paid at invoice: %s)\nReturns: %s\n"
                  "Later payments: %s\nOUTSTANDING: %s" % (pkr(s["opening"]), pkr(s["invoiced"]), pkr(s["invoice_paid"]),
                                                           pkr(s["returns"]), pkr(s["payments"]), pkr(s["balance"]))).pack(anchor="w")
        t = Table(w, [("Type", 90), ("Date", 90), ("Ref/Product", 160), ("Amount", 110)], height=10)
        t.pack(fill="both", expand=True)
        data = [("%s inv" % inv, r["date"], r["invoice_no"], pkr(r["total"])) for r in rows]
        data += [("Return", r["date"], r["product"], pkr(r["amount"])) for r in db.returns(self.kind) if r["party_id"] == i]
        data += [("Payment", r["date"], r["note"], pkr(r["amount"])) for r in db.payments(self.kind) if r["party_id"] == i]
        t.fill(list(enumerate(sorted(data, key=lambda x: x[1], reverse=True))))


class Invoices(Page):
    """Sales (kind='sale') or purchases (kind='purchase'): list + create."""
    def __init__(self, p, kind):
        super().__init__(p, padding=8)
        self.kind = kind
        f, self.s, self.a, self.b = bar(self, dates=True)
        btn(f, "Search", self.refresh)
        btn(f, "New invoice", self.new)
        btn(f, "View items", self.view)
        self.t = Table(self, [("Invoice", 90), ("Date", 90), ("Party", 200), ("Total", 110), ("Paid", 110), ("Due", 110)])
        self.t.pack(fill="both", expand=True)

    def refresh(self):
        self.t.fill([(r["id"], (r["invoice_no"], r["date"], r["party"], pkr(r["total"]), pkr(r["paid"]), pkr(r["due"])))
                     for r in db.invoices(self.kind, self.s.get(), self.a.get(), self.b.get())])

    def view(self):
        i = self.t.selected()
        if i is None:
            raise AppError("Select an invoice")
        w = tk.Toplevel(self)
        w.title("Invoice items")
        t = Table(w, [("Code", 90), ("Product", 200), ("Qty", 60), ("Price", 100), ("Line total", 110)], height=8)
        t.pack(fill="both", expand=True)
        t.fill([(r["id"], (r["code"], r["name"], r["qty"], pkr(r["price"]), pkr(r["line"]))) for r in db.invoice_items(self.kind, i)])

    def new(self):
        sale = self.kind == "sale"
        parties = names(db.parties("customer" if sale else "supplier"))
        prods = {"%s - %s" % (r["code"], r["name"]): r for r in db.products()}
        w = tk.Toplevel(self)
        w.title("New sales invoice" if sale else "New purchase invoice")
        w.grab_set()
        items = []
        top = ttk.Frame(w, padding=8)
        top.pack(fill="x")
        party, dt, paid = tk.StringVar(), tk.StringVar(value=today()), tk.StringVar(value="0")
        ttk.Label(top, text="Customer/Shop:" if sale else "Supplier:").grid(row=0, column=0)
        ttk.Combobox(top, textvariable=party, values=list(parties), state="readonly", width=30).grid(row=0, column=1, padx=4)
        ttk.Label(top, text="Date:").grid(row=0, column=2)
        ttk.Entry(top, textvariable=dt, width=12).grid(row=0, column=3, padx=4)
        add = ttk.Frame(w, padding=8)
        add.pack(fill="x")
        pv, qv, rv = tk.StringVar(), tk.StringVar(value="1"), tk.StringVar()
        pc = ttk.Combobox(add, textvariable=pv, values=list(prods), state="readonly", width=30)
        pc.pack(side="left")
        for lbl, v, wd in (("Qty", qv, 6), ("Price", rv, 10)):
            ttk.Label(add, text=lbl).pack(side="left", padx=(8, 2))
            ttk.Entry(add, textvariable=v, width=wd).pack(side="left")
        pc.bind("<<ComboboxSelected>>", lambda e: rv.set("%.2f" % (prods[pv.get()]["sale_price" if sale else "purchase_price"] / 100)))
        t = Table(w, [("Product", 240), ("Qty", 60), ("Price", 100), ("Line total", 110)], height=8)
        t.pack(fill="both", expand=True, padx=8)
        tot = ttk.Label(w, text="Total: PKR 0.00", font=("Segoe UI", 11, "bold"))
        tot.pack(anchor="e", padx=8)

        def redraw():
            t.fill([(n, (x[3], x[1], pkr(x[2]), pkr(x[1] * x[2]))) for n, x in enumerate(items)])
            tot.config(text="Total: " + pkr(sum(x[1] * x[2] for x in items)))

        @guard
        def add_item():
            from db import to_qty, to_paisa
            if pv.get() not in prods:
                raise AppError("Select a product")
            pr = to_paisa(rv.get())
            if pr <= 0:
                raise AppError("Price must be greater than zero")
            items.append((prods[pv.get()]["id"], to_qty(qv.get()), pr, pv.get()))
            redraw()

        def remove_item():
            n = t.selected()
            if n is not None:
                items.pop(n)
                redraw()
        ttk.Button(add, text="Add item", command=add_item).pack(side="left", padx=8)
        ttk.Button(add, text="Remove selected", command=remove_item).pack(side="left")
        bot = ttk.Frame(w, padding=8)
        bot.pack(fill="x")
        ttk.Label(bot, text="Paid now (PKR):").pack(side="left")
        ttk.Entry(bot, textvariable=paid, width=12).pack(side="left", padx=4)

        @guard
        def save():
            pid = pick(party.get(), parties)
            lines = [(x[0], x[1], x[2]) for x in items]
            (db.create_sale if sale else db.create_purchase)(pid, dt.get(), lines, paid.get())
            w.destroy()
            self.refresh()
            messagebox.showinfo("Saved", "Invoice saved.")
        self.save_btn = ttk.Button(bot, text="Save invoice", command=save)
        self.save_btn.pack(side="right")


class Returns(Page):
    def __init__(self, p, kind):
        super().__init__(p, padding=8)
        self.kind = kind
        f, _, self.a, self.b = bar(self, search=False, dates=True)
        btn(f, "Filter", self.refresh)
        btn(f, "New return", self.new)
        self.t = Table(self, [("Date", 90), ("Party", 150), ("Product", 150), ("Qty", 50), ("Condition", 80),
                              ("Amount", 100), ("Invoice", 70), ("Reason", 180)])
        self.t.pack(fill="both", expand=True)

    def refresh(self):
        self.t.fill([(r["id"], (r["date"], r["party"], r["product"], r["qty"], r["condition"], pkr(r["amount"]),
                                r["invoice_id"] or "-", r["reason"])) for r in db.returns(self.kind, self.a.get(), self.b.get())])

    def new(self):
        cust = self.kind == "customer"
        parties = names(db.parties(self.kind))
        prods = {"%s - %s" % (r["code"], r["name"]): r["id"] for r in db.products()}
        Form(self, "Customer return" if cust else "Return to supplier",
             [("Customer/Shop" if cust else "Supplier", "", list(parties)), ("Product", "", list(prods)), ("Quantity", "1", None),
              ("Date", today(), None), ("Reason", "", None), ("Condition", "resalable", ["resalable", "damaged"]),
              ("Original invoice ID (optional, number shown in list)", "", None)],
             lambda v: (db.create_return(self.kind, pick(v[0], parties), pick(v[1], prods), v[2], v[3], v[4], v[5],
                                         int(v[6]) if v[6].strip().isdigit() else None), self.refresh()))


class Payments(Page):
    def __init__(self, p, kind):
        super().__init__(p, padding=8)
        self.kind = kind
        f, self.s, self.a, self.b = bar(self, dates=True)
        btn(f, "Search", self.refresh)
        btn(f, "Record payment", self.new)
        self.t = Table(self, [("Date", 90), ("Party", 220), ("Amount", 110), ("Note", 250)])
        self.t.pack(fill="both", expand=True)

    def refresh(self):
        self.t.fill([(r["id"], (r["date"], r["party"], pkr(r["amount"]), r["note"]))
                     for r in db.payments(self.kind, self.s.get(), self.a.get(), self.b.get())])

    def new(self):
        parties = names(db.parties(self.kind))
        Form(self, "Payment received" if self.kind == "customer" else "Payment made",
             [("Customer/Shop" if self.kind == "customer" else "Supplier", "", list(parties)), ("Amount (PKR)", "", None),
              ("Date", today(), None), ("Note", "", None)],
             lambda v: (db.add_payment(self.kind, pick(v[0], parties), v[2], v[1], v[3]), self.refresh()))


class Reports(Page):
    NAMES = ["Sales", "Purchases", "Customer returns", "Supplier returns", "Current inventory",
             "Customer balances", "Supplier balances"]

    def __init__(self, p):
        super().__init__(p, padding=8)
        f, _, self.a, self.b = bar(self, search=False, dates=True)
        self.rep = tk.StringVar(value=self.NAMES[0])
        ttk.Combobox(f, textvariable=self.rep, values=self.NAMES, state="readonly", width=20).pack(side="left", padx=4)
        btn(f, "Show", self.refresh)
        btn(f, "Export CSV", self.export)
        self.box = ttk.Frame(self)
        self.box.pack(fill="both", expand=True)
        self.t = None
        self.total = ttk.Label(self, font=("Segoe UI", 10, "bold"))
        self.total.pack(anchor="e")

    def data(self):
        n, a, b = self.rep.get(), self.a.get(), self.b.get()
        if n == "Sales" or n == "Purchases":
            rows = db.invoices("sale" if n == "Sales" else "purchase", "", a, b)
            return (["Invoice", "Date", "Party", "Total", "Paid", "Due"],
                    [(r["invoice_no"], r["date"], r["party"], pkr(r["total"]), pkr(r["paid"]), pkr(r["due"])) for r in rows],
                    "Total: " + pkr(sum(r["total"] for r in rows)))
        if n.endswith("returns"):
            rows = db.returns("customer" if n.startswith("Customer") else "supplier", a, b)
            return (["Date", "Party", "Product", "Qty", "Condition", "Amount", "Reason"],
                    [(r["date"], r["party"], r["product"], r["qty"], r["condition"], pkr(r["amount"]), r["reason"]) for r in rows],
                    "Total: " + pkr(sum(r["amount"] for r in rows)))
        if n == "Current inventory":
            rows = db.products()
            return (["Code", "Product", "Unit", "Stock", "Purchase price", "Stock value"],
                    [(r["code"], r["name"], r["unit"], r["stock"], pkr(r["purchase_price"]), pkr(r["value"])) for r in rows],
                    "Stock value: " + pkr(sum(r["value"] for r in rows)))
        rows = db.parties("customer" if n.startswith("Customer") else "supplier")
        return (["Name", "Phone", "Outstanding"], [(r["name"], r["phone"], pkr(r["balance"])) for r in rows],
                "Total outstanding: " + pkr(sum(r["balance"] for r in rows)))

    def refresh(self):
        h, rows, tot = self.data()
        if self.t:
            self.t.destroy()
        self.t = Table(self.box, [(c, 120) for c in h])
        self.t.pack(fill="both", expand=True)
        self.t.fill(list(enumerate(rows)))
        self.total.config(text=tot)

    def export(self):
        h, rows, _ = self.data()
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")],
                                            initialfile=self.rep.get().replace(" ", "_") + ".csv")
        if path:
            db.export_csv(path, h, rows)
            messagebox.showinfo("Exported", "Saved to " + path)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Distribution Manager")
        self.geometry("1100x650")
        side = tk.Frame(self, bg="#1f3a5f", width=190)
        side.pack(side="left", fill="y")
        self.main = ttk.Frame(self)
        self.main.pack(side="right", fill="both", expand=True)
        self.pages = {}
        spec = [("Dashboard", Dashboard), ("Products", Products), ("Suppliers", lambda p: Parties(p, "supplier")),
                ("Purchases", lambda p: Invoices(p, "purchase")), ("Customers", lambda p: Parties(p, "customer")),
                ("Sales", lambda p: Invoices(p, "sale")), ("Customer Returns", lambda p: Returns(p, "customer")),
                ("Supplier Returns", lambda p: Returns(p, "supplier")),
                ("Customer Payments", lambda p: Payments(p, "customer")), ("Supplier Payments", lambda p: Payments(p, "supplier")),
                ("Reports", Reports)]
        for name, cls in spec:
            self.pages[name] = cls(self.main)
            tk.Button(side, text=name, anchor="w", bg="#1f3a5f", fg="white", relief="flat", padx=14, pady=6,
                      activebackground="#2f5a8f", activeforeground="white",
                      command=lambda n=name: self.show(n)).pack(fill="x")
        tk.Button(side, text="Backup database", anchor="w", bg="#3a6a3f", fg="white", relief="flat", padx=14, pady=6,
                  command=self.backup).pack(fill="x", side="bottom")
        self.show("Dashboard")

    def show(self, name):
        for p in self.pages.values():
            p.pack_forget()
        p = self.pages[name]
        p.pack(fill="both", expand=True)
        p.refresh()

    def backup(self):
        path = filedialog.asksaveasfilename(defaultextension=".db", initialfile="backup_%s.db" % today())
        if path:
            db.backup(path)
            messagebox.showinfo("Backup", "Backup saved to " + path)


if __name__ == "__main__":
    App().mainloop()
