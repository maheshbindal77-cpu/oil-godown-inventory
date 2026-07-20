# Oil Godown Inventory

A simple app to track oil stock, purchases, dispatches, and stock valuation.

---

## How to start the app (just double-click)

**On Windows:** double-click **`Start Oil Inventory (Windows).bat`**

**On Mac:** double-click **`Start Oil Inventory (Mac).command`**

A black/white window will open. The **first time only**, it installs what it needs
(this takes a minute). After that, your web browser opens automatically with the app.

> **Keep that window open** while you use the app. To stop the app, just close it.

### First-time setup (only if the app says Python is missing)

1. Install Python from **https://www.python.org/downloads**
2. On Windows, on the first install screen **tick "Add python.exe to PATH"**.
3. Double-click the Start file again.

---

## Where your data is stored

Everything you enter is saved in a single file next to the app:

```
oil_inventory.db
```

That one file **is** your entire inventory. Keep it safe.

---

## Backups — never lose your records

The app protects your data in three ways:

1. **Automatic daily backup** — every day the app is opened, it saves a dated copy
   into the **`backups`** folder automatically. Old copies are kept (last 60).
2. **Manual backup** — open the **"Data & Backups"** page and click
   **"Create backup now"** any time (e.g. after entering a lot of records).
3. **Download a copy off this computer** — on the same page, click
   **"Download database file"** and save it to **Google Drive / OneDrive / email / a
   USB stick**. Do this regularly.

If a computer ever dies or a file is deleted, you restore from any of these copies
using the **"Restore from a backup"** option on the Data & Backups page.

### 🔒 Strongest protection (recommended)

Put this whole app folder inside a cloud-synced folder — **OneDrive** (built into
Windows) or **Google Drive**. Then **every change is copied to the cloud
automatically**, with version history, and nothing is ever tied to one machine.

---

## Moving the app to another computer

Copy the **whole folder** (including `oil_inventory.db` if you want the existing
data). On the new computer, double-click the Start file for that operating system.

> When sending updated app files to someone who already uses it, **do not overwrite
> their `oil_inventory.db`** — that would erase their records. Send only the other
> files.

---

## What's in this folder

| File | What it is |
|------|-----------|
| `Start Oil Inventory (Windows).bat` | Double-click to run on Windows |
| `Start Oil Inventory (Mac).command` | Double-click to run on Mac |
| `app.py` | The app screens |
| `db.py` | Data storage and backup logic |
| `oil_inventory.db` | **Your data** (created automatically on first run) |
| `backups/` | Automatic dated copies of your data |
| `requirements.txt` | List of components the app needs |
