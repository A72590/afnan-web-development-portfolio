# Distribution Manager (Phase 1)
Offline Windows app: Python 3.9+ (with Tkinter, included in the python.org installer) + SQLite. No extra packages.

    cd path\to\folder
    python app.py

Data is stored in `distribution.db` next to `app.py` (use "Backup database" in the sidebar). Tests: `python test_db.py`.
Balance = opening + invoiced - paid at invoice - returns - later payments. Amounts are stored as integer paisa.
In the Sales/Purchases list the number shown in the "Invoice" ID for returns is the database id (e.g. S-00003 -> 3).
