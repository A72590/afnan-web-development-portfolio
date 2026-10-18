import os, tempfile, unittest
from db import DB, AppError


class T(unittest.TestCase):
    def setUp(self):
        self.p = os.path.join(tempfile.mkdtemp(), "t.db")
        self.d = DB(self.p)
        self.d.save_product(None, "SOAP1", "Soap", "pcs", "50", "70", "0", "10")
        self.pid = self.d.products()[0]["id"]
        self.d.save_party("customer", None, "Shop A", "", "", "100")
        self.d.save_party("supplier", None, "Supp", "", "", "0")
        self.cid = self.d.parties("customer")[0]["id"]
        self.sid = self.d.parties("supplier")[0]["id"]

    def stock(self):
        return self.d.products()[0]["stock"]

    def test_all(self):
        d = self.d
        with self.assertRaises(AppError):
            d.save_product(None, "soap1", "X", "pcs", "1", "1", "0", "0")  # duplicate code
        d.create_purchase(self.sid, "2026-01-01", [(self.pid, 100, "50")], "2000")
        self.assertEqual(self.stock(), 100)
        self.assertEqual(d.balance("supplier", self.sid), 300000)
        with self.assertRaises(AppError):
            d.create_sale(self.cid, "2026-01-02", [(self.pid, 101, "70")], "0")
        self.assertEqual(self.stock(), 100)
        sid = d.create_sale(self.cid, "2026-01-02", [(self.pid, 30, "70")], "1000")
        self.assertEqual(self.stock(), 70)
        self.assertEqual(d.balance("customer", self.cid), 10000 + 210000 - 100000)
        d.create_return("customer", self.cid, self.pid, 5, "2026-01-03", "x", "resalable", sid)
        self.assertEqual(self.stock(), 75)
        d.create_return("customer", self.cid, self.pid, 5, "2026-01-03", "x", "damaged", sid)
        self.assertEqual(self.stock(), 75)
        with self.assertRaises(AppError):  # only 30 sold, 10 returned
            d.create_return("customer", self.cid, self.pid, 21, "2026-01-03", "x", "resalable", sid)
        self.assertEqual(d.balance("customer", self.cid), 10000 + 210000 - 100000 - 70000)
        with self.assertRaises(AppError):
            d.add_payment("customer", self.cid, "2026-01-04", "99999")
        d.add_payment("customer", self.cid, "2026-01-04", "500")
        self.assertEqual(d.balance("customer", self.cid), 10000 + 210000 - 100000 - 70000 - 50000)
        d.create_return("supplier", self.sid, self.pid, 10, "2026-01-05", "bad", "damaged")
        self.assertEqual(self.stock(), 65)
        self.assertEqual(d.balance("supplier", self.sid), 300000 - 50000)
        d.add_payment("supplier", self.sid, "2026-01-06", "2500")
        self.assertEqual(d.balance("supplier", self.sid), 0)
        with self.assertRaises(AppError):
            d.create_return("supplier", self.sid, self.pid, 1000, "2026-01-05", "", "damaged")
        self.assertEqual(len(d.payments("customer", "shop", "2026-01-01", "2026-12-31")), 1)
        self.assertEqual(d.dashboard()["stock"], 65)
        d.backup(self.p + ".bak")
        self.assertTrue(os.path.getsize(self.p + ".bak") > 0)


unittest.main()
