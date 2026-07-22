"""Oil Godown Inventory Management — Streamlit app.

Stock is tracked by OIL TYPE only (no tanks): current stock of an oil type is
all inflows minus all outflows.
"""

from datetime import date

import pandas as pd
import streamlit as st

import db

st.set_page_config(page_title="Oil Godown Inventory", page_icon="🛢️", layout="wide")


# Pages an "operator" is allowed to see. Everything else is manager-only. This
# is only used if a separate `admin_password` secret is configured; otherwise a
# single password grants full access.
OPERATOR_PAGES = [
    "Dashboard",
    "Incoming Stock Entry",
    "Outgoing Stock Entry",
    "History & Logs",
    "Stock & Rate History",
    "Edit / Correct Entries",
    "Data & Backups",
]


def _secret(name):
    try:
        return st.secrets[name]
    except Exception:
        return None


def require_login():
    """Password gate with two roles: `admin_password` (manager → all pages) and
    `app_password` (operator → safe daily pages). If no admin password is set,
    the app password grants full access. No password set (local) = no gate."""
    operator_pw = _secret("app_password")
    admin_pw = _secret("admin_password")

    if operator_pw is None and admin_pw is None:
        st.session_state["role"] = "admin"
        return

    if st.session_state.get("auth_ok"):
        return

    st.title("🔒 Oil Godown Inventory")
    st.caption("Please enter your password to continue.")
    entered = st.text_input("Password", type="password")
    if entered:
        role = None
        if admin_pw is not None and entered == admin_pw:
            role = "admin"
        elif operator_pw is not None and entered == operator_pw:
            role = "operator" if admin_pw is not None else "admin"
        if role:
            st.session_state["auth_ok"] = True
            st.session_state["role"] = role
            st.rerun()
        else:
            st.error("Incorrect password. Please try again.")
    st.stop()


@st.cache_resource(show_spinner=False)
def _ensure_db_ready():
    """Run schema setup / migration once per app start, not on every rerun."""
    db.init_db()
    return True


# Cached reads: these keep navigation and typing snappy by not re-querying the
# database on every rerun. `st.cache_data.clear()` is called after every write
# so saved changes show up immediately; the short TTL keeps other devices fresh.
@st.cache_data(ttl=60, show_spinner=False)
def load_oil_types():
    return db.get_oil_types()


@st.cache_data(ttl=60, show_spinner=False)
def load_stock_by_oil_type():
    return db.get_stock_by_oil_type()


@st.cache_data(ttl=60, show_spinner=False)
def load_transactions(start=None, end=None, oil_type_id=None, txn_type="All"):
    return db.get_transactions(start, end, oil_type_id, txn_type)


@st.cache_data(ttl=60, show_spinner=False)
def load_editable_transactions():
    return db.get_editable_transactions()


@st.cache_data(ttl=60, show_spinner=False)
def load_stock_ledger(oil_type_id):
    return db.get_stock_ledger(oil_type_id)


require_login()

try:
    _ensure_db_ready()
except Exception as e:
    st.error("⚠️ The app couldn't connect to the database.")
    st.markdown(
        "This almost always means the **`db_url`** secret is wrong or incomplete. "
        "Please check, in the app's **Settings → Secrets**, that the whole Neon "
        "connection string is present and ends with **`sslmode=require`**."
    )
    with st.expander("Technical details (for troubleshooting)"):
        st.code(str(e))
    st.stop()


def page_dashboard():
    st.title("🛢️ Current Stock & Inventory Valuation")

    by_oil = load_stock_by_oil_type()

    total_stock = by_oil["current_stock"].sum()
    total_value = by_oil["total_value"].sum()

    c1, c2, c3 = st.columns(3)
    c1.metric("Total Stock (all oils)", f"{total_stock:,.0f} L")
    c2.metric("Total Inventory Value", f"₹{total_value:,.0f}")
    c3.metric("Oil Types", f"{len(by_oil)}")

    if by_oil.empty:
        st.info("No oil types yet. Add them on the **Setup & Manage** page, then log stock.")
        return

    st.subheader("Stock & Value by Oil Type")
    cols = st.columns(len(by_oil))
    for col, (_, row) in zip(cols, by_oil.iterrows()):
        with col:
            st.metric(row["oil_type"], f"{row['current_stock']:,.0f} L")
            st.caption(f"Avg rate: ₹{row['weighted_avg_rate']:,.2f} | Value: ₹{row['total_value']:,.0f}")

    st.divider()

    st.subheader("Stock by Oil Type")
    display = by_oil[["oil_type", "current_stock", "weighted_avg_rate", "total_value"]].rename(
        columns={
            "oil_type": "Oil Type",
            "current_stock": "Current Stock (L)",
            "weighted_avg_rate": "Weighted Avg Rate (₹)",
            "total_value": "Total Value (₹)",
        }
    )
    st.dataframe(display.style.format({
        "Current Stock (L)": "{:,.0f}",
        "Weighted Avg Rate (₹)": "{:,.2f}",
        "Total Value (₹)": "{:,.0f}",
    }), hide_index=True, use_container_width=True)

    st.subheader("Current Stock by Oil Type")
    chart_df = by_oil.set_index("oil_type")[["current_stock"]].rename(
        columns={"current_stock": "Current Stock (L)"}
    )
    st.bar_chart(chart_df)


def page_incoming():
    st.title("📥 Incoming Stock Entry (Unloading)")

    oil_types = load_oil_types()
    if oil_types.empty:
        st.warning("No oil types configured yet. Add them on the **Setup & Manage** page first.")
        return

    with st.form("incoming_form", clear_on_submit=True):
        entry_date = st.date_input("Date", value=date.today())
        oil_type_name = st.selectbox("Oil Type", oil_types["name"])
        quantity = st.number_input("Quantity Added", min_value=0.0, step=100.0, format="%.2f")
        rate = st.number_input("Purchase Rate per Unit", min_value=0.0, step=0.5, format="%.2f")
        supplier = st.text_input("Supplier Name / Batch No.")
        submitted = st.form_submit_button("Save Incoming Entry")

    if submitted:
        oil_type_id = int(oil_types.loc[oil_types["name"] == oil_type_name, "id"].iloc[0])
        if quantity <= 0:
            st.error("Quantity must be greater than zero.")
        elif rate <= 0:
            st.error("Rate must be greater than zero.")
        else:
            db.add_incoming(entry_date.isoformat(), oil_type_id, quantity, rate, supplier)
            st.cache_data.clear()
            st.success(f"Logged {quantity:,.0f} L of {oil_type_name} into stock.")
            st.rerun()


def page_outgoing():
    st.title("📤 Outgoing Stock Entry (Tanker Filling)")

    oil_types = load_oil_types()
    if oil_types.empty:
        st.warning("No oil types configured yet. Add them on the **Setup & Manage** page first.")
        return

    stock = load_stock_by_oil_type().set_index("oil_type")["current_stock"].to_dict()

    with st.form("outgoing_form", clear_on_submit=True):
        entry_date = st.date_input("Date", value=date.today())
        oil_type_name = st.selectbox(
            "Oil Type",
            oil_types["name"],
            format_func=lambda n: f"{n}  (in stock: {stock.get(n, 0):,.0f} L)",
        )
        quantity = st.number_input("Quantity Out", min_value=0.0, step=100.0, format="%.2f")
        buyer = st.text_input("Tanker Number / Buyer")
        notes = st.text_area("Notes", height=80)
        submitted = st.form_submit_button("Save Outgoing Entry")

    if submitted:
        oil_type_id = int(oil_types.loc[oil_types["name"] == oil_type_name, "id"].iloc[0])
        available = stock.get(oil_type_name, 0)
        if quantity <= 0:
            st.error("Quantity must be greater than zero.")
        elif quantity > available:
            st.error(f"Cannot dispatch {quantity:,.0f} L — only {available:,.0f} L of "
                     f"{oil_type_name} is in the godown.")
        else:
            try:
                db.add_outgoing(entry_date.isoformat(), oil_type_id, quantity, buyer, notes)
                st.cache_data.clear()
                st.success(f"Logged {quantity:,.0f} L of {oil_type_name} out.")
                st.rerun()
            except ValueError as e:
                st.error(str(e))


def page_history():
    st.title("📜 History & Transaction Logs")

    oil_types = load_oil_types()

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        start_date = st.date_input("Start Date", value=None)
    with col2:
        end_date = st.date_input("End Date", value=None)
    with col3:
        oil_filter = st.selectbox("Oil Type", ["All"] + oil_types["name"].tolist())
    with col4:
        txn_type = st.selectbox("Transaction Type", ["All", "In", "Out"])

    oil_type_id = None
    if oil_filter != "All":
        oil_type_id = int(oil_types.loc[oil_types["name"] == oil_filter, "id"].iloc[0])

    df = load_transactions(
        start_date.isoformat() if isinstance(start_date, date) else None,
        end_date.isoformat() if isinstance(end_date, date) else None,
        oil_type_id,
        txn_type,
    )

    display = df.rename(columns={
        "date": "Date", "type": "Type", "oil_type": "Oil Type",
        "quantity": "Quantity", "rate": "Rate", "party": "Supplier / Buyer", "notes": "Notes",
    })
    st.dataframe(display, hide_index=True, use_container_width=True)
    st.caption(f"{len(df)} transaction(s)")

    st.download_button(
        "Download Filtered Log as CSV",
        data=display.to_csv(index=False).encode("utf-8"),
        file_name="oil_inventory_transactions.csv",
        mime="text/csv",
    )


def page_edit():
    st.title("✏️ Edit / Correct Entries")
    st.caption("Fix or remove a single entry that was logged by mistake. Stock levels are "
               "corrected automatically.")

    txns = load_editable_transactions()
    if txns.empty:
        st.info("There are no transactions to edit yet.")
        return

    oil_types = load_oil_types()

    def _label(i):
        r = txns.iloc[i]
        return (f"{r['type']}  |  {r['date']}  |  {r['oil_type']}  |  "
                f"{r['quantity']:,.0f} L  |  {r['party'] or ''}")

    idx = st.selectbox("Choose the entry to fix", range(len(txns)), format_func=_label)
    row = txns.iloc[idx]
    ttype = row["type"]
    txn_id = int(row["id"])

    st.divider()

    with st.form("edit_form"):
        st.markdown(f"**Editing this {'incoming' if ttype == 'In' else 'outgoing'} entry**")
        try:
            default_date = date.fromisoformat(str(row["date"]))
        except Exception:
            default_date = date.today()
        new_date = st.date_input("Date", value=default_date)

        oil_names = oil_types["name"].tolist()
        oil_default = oil_types.loc[oil_types["id"] == row["oil_type_id"], "name"]
        oil_idx = oil_names.index(oil_default.iloc[0]) if not oil_default.empty else 0
        oil_name = st.selectbox("Oil Type", oil_names, index=oil_idx)
        new_oil_id = int(oil_types.loc[oil_types["name"] == oil_name, "id"].iloc[0])

        new_qty = st.number_input("Quantity", min_value=0.0, value=float(row["quantity"]),
                                  step=100.0, format="%.2f")
        new_rate = new_party = new_notes = None
        if ttype == "In":
            new_rate = st.number_input("Purchase Rate per Unit", min_value=0.0,
                                       value=float(row["rate"] or 0), step=0.5, format="%.2f")
            new_party = st.text_input("Supplier / Batch No.", value=row["party"] or "")
        else:
            new_party = st.text_input("Tanker Number / Buyer", value=row["party"] or "")
            new_notes = st.text_area("Notes", value=row["notes"] or "", height=80)

        saved = st.form_submit_button("💾 Save changes")

    if saved:
        if new_qty <= 0:
            st.error("Quantity must be greater than zero.")
        elif ttype == "In" and new_rate <= 0:
            st.error("Rate must be greater than zero.")
        else:
            try:
                if ttype == "In":
                    db.update_incoming(txn_id, new_date.isoformat(), new_oil_id, new_qty,
                                       new_rate, new_party)
                else:
                    db.update_outgoing(txn_id, new_date.isoformat(), new_oil_id, new_qty,
                                       new_party, new_notes)
                st.cache_data.clear()
                st.success("Entry updated — stock has been corrected.")
                st.rerun()
            except Exception as e:
                st.error(str(e))

    st.divider()
    st.subheader("Delete this entry")
    st.write("Removing an entry also corrects the stock. To avoid accidents, tick the box first.")
    confirm = st.checkbox("Yes, permanently delete the entry selected above")
    if st.button("🗑️ Delete entry", disabled=not confirm):
        try:
            if ttype == "In":
                db.delete_incoming(txn_id)
            else:
                db.delete_outgoing(txn_id)
            st.cache_data.clear()
            st.success("Entry deleted — stock has been corrected.")
            st.rerun()
        except Exception as e:
            st.error(str(e))


def page_ledger():
    st.title("📈 Stock & Rate History")
    st.caption("For each oil type, see how its stock quantity and its average rate changed "
               "after every incoming and outgoing entry. The rate uses FIFO — the oldest oil "
               "is counted as sold first.")

    oil_types = load_oil_types()
    if oil_types.empty:
        st.info("No oil types yet. Add them on the **Setup & Manage** page.")
        return

    oil_name = st.selectbox("Oil Type", oil_types["name"])
    oid = int(oil_types.loc[oil_types["name"] == oil_name, "id"].iloc[0])

    ledger = load_stock_ledger(oid)
    if ledger.empty:
        st.info("No transactions for this oil type yet.")
        return

    st.dataframe(
        ledger.style.format({
            "Stock After (L)": "{:,.0f}",
            "Avg Rate After (₹)": "{:,.2f}",
            "Value After (₹)": "{:,.0f}",
        }),
        hide_index=True, use_container_width=True,
    )

    st.download_button(
        "⬇️ Download this history as CSV",
        data=ledger.to_csv(index=False).encode("utf-8"),
        file_name=f"stock_history_{oil_name}_{date.today().isoformat()}.csv",
        mime="text/csv",
    )

    st.subheader("Average rate over time")
    st.line_chart(ledger, x="Date", y="Avg Rate After (₹)")
    st.subheader("Stock quantity over time")
    st.line_chart(ledger, x="Date", y="Stock After (L)")


def page_backups():
    st.title("💾 Data & Backups")
    st.caption("Your data is stored in a hosted cloud database, backed up automatically by the "
               "provider. Use the buttons below to also keep your own copies.")

    st.subheader("Download your own backup copy")
    st.write("Download everything as spreadsheets you can open in Excel and save to Google Drive, "
             "email, or a USB stick. Doing this now and then gives you a personal copy in your "
             "own hands.")

    all_txns = load_transactions()
    stock = load_stock_by_oil_type()

    col1, col2 = st.columns(2)
    with col1:
        st.download_button(
            "⬇️ All transactions (CSV)",
            data=all_txns.to_csv(index=False).encode("utf-8"),
            file_name=f"oil_transactions_{date.today().isoformat()}.csv",
            mime="text/csv",
        )
    with col2:
        st.download_button(
            "⬇️ Stock by oil type (CSV)",
            data=stock.to_csv(index=False).encode("utf-8"),
            file_name=f"oil_stock_{date.today().isoformat()}.csv",
            mime="text/csv",
        )

    st.divider()
    st.subheader("How your data is kept safe")
    st.markdown(
        "- **One shared copy online** — you and anyone else you give the link to always see the "
        "same up-to-date records, from any device.\n"
        "- **Automatic cloud backups** — the database provider keeps the data on professional "
        "servers with their own backups.\n"
        "- **Your own copies** — download the CSV files above every so often for an extra copy "
        "that lives with you."
    )


def page_setup():
    st.title("⚙️ Setup & Manage")
    st.caption("Manage the oil types you store. Day-to-day stock entry stays on the "
               "Incoming / Outgoing pages.")

    oil_types = load_oil_types()

    st.subheader("Oil Types")
    if not oil_types.empty:
        st.dataframe(oil_types[["name"]].rename(columns={"name": "Oil Type"}),
                     hide_index=True, use_container_width=True)
    else:
        st.info("No oil types yet. Add your first one below.")

    with st.form("add_oil_type", clear_on_submit=True):
        new_oil = st.text_input("New oil type name (e.g. Furnace Oil)")
        if st.form_submit_button("➕ Add oil type") and new_oil.strip():
            try:
                db.add_oil_type(new_oil.strip())
                st.cache_data.clear()
                st.success(f"Added '{new_oil.strip()}'.")
                st.rerun()
            except Exception as e:
                st.error(f"Couldn't add: {e}")

    if not oil_types.empty:
        del_oil = st.selectbox("Remove an oil type", ["—"] + oil_types["name"].tolist(), key="del_oil")
        if del_oil != "—" and st.button("Remove selected oil type"):
            try:
                oid = int(oil_types.loc[oil_types["name"] == del_oil, "id"].iloc[0])
                db.delete_oil_type(oid)
                st.cache_data.clear()
                st.success(f"Removed '{del_oil}'.")
                st.rerun()
            except Exception as e:
                st.error(str(e))


PAGES = {
    "Dashboard": page_dashboard,
    "Incoming Stock Entry": page_incoming,
    "Outgoing Stock Entry": page_outgoing,
    "History & Logs": page_history,
    "Stock & Rate History": page_ledger,
    "Edit / Correct Entries": page_edit,
    "Data & Backups": page_backups,
    "Setup & Manage": page_setup,
}

st.sidebar.title("Oil Godown Inventory")

role = st.session_state.get("role", "admin")
if role == "admin":
    visible_pages = list(PAGES.keys())
else:
    visible_pages = [p for p in PAGES if p in OPERATOR_PAGES]

choice = st.sidebar.radio("Navigate", visible_pages)

if _secret("app_password") is not None or _secret("admin_password") is not None:
    st.sidebar.divider()
    st.sidebar.caption(
        f"Signed in as: **{'Manager (full access)' if role == 'admin' else 'Operator (daily use)'}**"
    )
    if st.sidebar.button("Log out"):
        st.session_state.clear()
        st.rerun()

PAGES[choice]()
