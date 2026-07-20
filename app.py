"""Oil Godown Inventory Management — Streamlit app."""

from datetime import date

import pandas as pd
import streamlit as st

import db

st.set_page_config(page_title="Oil Godown Inventory", page_icon="🛢️", layout="wide")


def _app_password():
    """Return the configured app password, or None if none is set (local use)."""
    try:
        return st.secrets["app_password"]
    except Exception:
        return None


def require_login():
    """Password gate. Active only when an `app_password` secret is configured
    (i.e. when deployed online). Skipped for local runs so testing stays easy."""
    expected = _app_password()
    if expected is None:
        return  # no password set -> local use, no gate

    if st.session_state.get("auth_ok"):
        return

    st.title("🔒 Oil Godown Inventory")
    st.caption("Please enter the password to continue.")
    entered = st.text_input("Password", type="password")
    if entered:
        if entered == expected:
            st.session_state["auth_ok"] = True
            st.rerun()
        else:
            st.error("Incorrect password. Please try again.")
    st.stop()


require_login()

try:
    db.init_db()
except Exception as e:
    st.error("⚠️ The app couldn't connect to the database.")
    st.markdown(
        "This almost always means the **`db_url`** secret is wrong or incomplete. "
        "Please check, in the app's **Settings → Secrets**, that:\n\n"
        "- the whole connection string from Neon is present on one line, and\n"
        "- it ends with **`sslmode=require`** (with the final **e**)."
    )
    with st.expander("Technical details (for troubleshooting)"):
        st.code(str(e))
    st.stop()


def page_dashboard():
    st.title("🛢️ Current Stock & Inventory Valuation")

    by_oil = db.get_stock_by_oil_type()
    by_tank = db.get_stock_by_tank()

    total_stock = by_oil["current_stock"].sum()
    total_value = by_oil["total_value"].sum()
    total_capacity = by_tank["capacity"].sum()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Stock (all oils)", f"{total_stock:,.0f} L")
    c2.metric("Total Inventory Value", f"₹{total_value:,.0f}")
    c3.metric("Tanks in Use", f"{len(by_tank)}")
    c4.metric("Overall Fill", f"{(total_stock / total_capacity * 100 if total_capacity else 0):.1f}%")

    st.subheader("Stock Value by Oil Type")
    cols = st.columns(len(by_oil)) if len(by_oil) else []
    for col, (_, row) in zip(cols, by_oil.iterrows()):
        with col:
            st.metric(row["oil_type"], f"{row['current_stock']:,.0f} L")
            st.caption(f"Avg rate: ₹{row['weighted_avg_rate']:,.2f} | Value: ₹{row['total_value']:,.0f}")

    st.divider()

    left, right = st.columns(2)
    with left:
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

    with right:
        st.subheader("Stock by Tank")
        display_t = by_tank[["name", "oil_type", "capacity", "current_volume", "fill_pct"]].rename(
            columns={
                "name": "Tank",
                "oil_type": "Oil Type",
                "capacity": "Capacity (L)",
                "current_volume": "Current Volume (L)",
                "fill_pct": "Fill %",
            }
        )
        st.dataframe(display_t.style.format({
            "Capacity (L)": "{:,.0f}",
            "Current Volume (L)": "{:,.0f}",
            "Fill %": "{:.1f}%",
        }), hide_index=True, use_container_width=True)

    st.subheader("Tank Capacity vs. Current Volume")
    chart_df = by_tank.set_index("name")[["capacity", "current_volume"]].rename(
        columns={"capacity": "Capacity", "current_volume": "Current Volume"}
    )
    st.bar_chart(chart_df)


def page_incoming():
    st.title("📥 Incoming Stock Entry (Unloading)")

    oil_types = db.get_oil_types()
    if oil_types.empty:
        st.warning("No oil types configured yet.")
        return

    oil_type_name = st.selectbox("Oil Type", oil_types["name"], key="in_oil_type")
    oil_type_id = int(oil_types.loc[oil_types["name"] == oil_type_name, "id"].iloc[0])

    tanks = db.get_tanks(oil_type_id=oil_type_id)
    if tanks.empty:
        st.warning("No tanks configured for this oil type.")
        return

    with st.form("incoming_form", clear_on_submit=True):
        entry_date = st.date_input("Date", value=date.today())
        tank_label = st.selectbox(
            "Underground Tank",
            tanks.apply(lambda r: f"{r['name']} ({r['current_volume']:,.0f}/{r['capacity']:,.0f} L)", axis=1),
        )
        tank_id = int(tanks.iloc[
            tanks.apply(lambda r: f"{r['name']} ({r['current_volume']:,.0f}/{r['capacity']:,.0f} L)", axis=1).tolist().index(tank_label)
        ]["id"])

        quantity = st.number_input("Quantity Added", min_value=0.0, step=100.0, format="%.2f")
        rate = st.number_input("Purchase Rate per Unit", min_value=0.0, step=0.5, format="%.2f")
        supplier = st.text_input("Supplier Name / Batch No.")

        submitted = st.form_submit_button("Save Incoming Entry")

    if submitted:
        tank_row = tanks.loc[tanks["id"] == tank_id].iloc[0]
        if quantity <= 0:
            st.error("Quantity must be greater than zero.")
        elif rate <= 0:
            st.error("Rate must be greater than zero.")
        elif tank_row["current_volume"] + quantity > tank_row["capacity"]:
            available_space = tank_row["capacity"] - tank_row["current_volume"]
            st.error(
                f"This exceeds tank capacity. Only {available_space:,.0f} L of space left in {tank_row['name']}."
            )
        else:
            db.add_incoming(entry_date.isoformat(), oil_type_id, tank_id, quantity, rate, supplier)
            st.success(f"Logged {quantity:,.0f} L of {oil_type_name} into {tank_row['name']}.")
            st.rerun()


def page_outgoing():
    st.title("📤 Outgoing Stock Entry (Tanker Filling)")

    oil_types = db.get_oil_types()
    if oil_types.empty:
        st.warning("No oil types configured yet.")
        return

    oil_type_name = st.selectbox("Oil Type", oil_types["name"], key="out_oil_type")
    oil_type_id = int(oil_types.loc[oil_types["name"] == oil_type_name, "id"].iloc[0])

    tanks = db.get_tanks(oil_type_id=oil_type_id)
    if tanks.empty:
        st.warning("No tanks configured for this oil type.")
        return

    with st.form("outgoing_form", clear_on_submit=True):
        entry_date = st.date_input("Date", value=date.today())
        tank_label = st.selectbox(
            "Underground Tank",
            tanks.apply(lambda r: f"{r['name']} (available: {r['current_volume']:,.0f} L)", axis=1),
        )
        tank_id = int(tanks.iloc[
            tanks.apply(lambda r: f"{r['name']} (available: {r['current_volume']:,.0f} L)", axis=1).tolist().index(tank_label)
        ]["id"])

        quantity = st.number_input("Quantity Out", min_value=0.0, step=100.0, format="%.2f")
        buyer = st.text_input("Tanker Number / Buyer")
        notes = st.text_area("Notes", height=80)

        submitted = st.form_submit_button("Save Outgoing Entry")

    if submitted:
        tank_row = tanks.loc[tanks["id"] == tank_id].iloc[0]
        if quantity <= 0:
            st.error("Quantity must be greater than zero.")
        elif quantity > tank_row["current_volume"]:
            st.error(
                f"Cannot dispatch {quantity:,.0f} L — only {tank_row['current_volume']:,.0f} L "
                f"available in {tank_row['name']}."
            )
        else:
            try:
                db.add_outgoing(entry_date.isoformat(), oil_type_id, tank_id, quantity, buyer, notes)
                st.success(f"Logged {quantity:,.0f} L of {oil_type_name} out of {tank_row['name']}.")
                st.rerun()
            except ValueError as e:
                st.error(str(e))


def page_history():
    st.title("📜 History & Transaction Logs")

    oil_types = db.get_oil_types()
    tanks_all = db.get_tanks()

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        start_date = st.date_input("Start Date", value=None)
    with col2:
        end_date = st.date_input("End Date", value=None)
    with col3:
        oil_filter = st.selectbox("Oil Type", ["All"] + oil_types["name"].tolist())
    with col4:
        txn_type = st.selectbox("Transaction Type", ["All", "In", "Out"])

    tank_filter = st.selectbox("Tank", ["All"] + tanks_all["name"].tolist())

    oil_type_id = None
    if oil_filter != "All":
        oil_type_id = int(oil_types.loc[oil_types["name"] == oil_filter, "id"].iloc[0])

    tank_id = None
    if tank_filter != "All":
        tank_id = int(tanks_all.loc[tanks_all["name"] == tank_filter, "id"].iloc[0])

    df = db.get_transactions(
        start_date=start_date.isoformat() if isinstance(start_date, date) else None,
        end_date=end_date.isoformat() if isinstance(end_date, date) else None,
        oil_type_id=oil_type_id,
        tank_id=tank_id,
        txn_type=txn_type,
    )

    display = df.rename(columns={
        "date": "Date", "type": "Type", "oil_type": "Oil Type", "tank": "Tank",
        "quantity": "Quantity", "rate": "Rate", "party": "Supplier / Buyer", "notes": "Notes",
    })
    st.dataframe(display, hide_index=True, use_container_width=True)
    st.caption(f"{len(df)} transaction(s)")

    csv = display.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download Filtered Log as CSV",
        data=csv,
        file_name="oil_inventory_transactions.csv",
        mime="text/csv",
    )


def page_backups():
    st.title("💾 Data & Backups")
    st.caption("Your data is stored in a hosted cloud database, backed up automatically "
               "by the provider. Use the buttons below to also keep your own copies.")

    st.subheader("Download your own backup copy")
    st.write("Download everything as spreadsheets you can open in Excel and save to "
             "Google Drive, email, or a USB stick. Doing this now and then gives you a "
             "personal copy in your own hands.")

    all_txns = db.get_transactions()
    stock = db.get_stock_by_oil_type()
    tanks = db.get_stock_by_tank()

    col1, col2, col3 = st.columns(3)
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
    with col3:
        st.download_button(
            "⬇️ Tanks (CSV)",
            data=tanks.to_csv(index=False).encode("utf-8"),
            file_name=f"oil_tanks_{date.today().isoformat()}.csv",
            mime="text/csv",
        )

    st.divider()

    st.subheader("How your data is kept safe")
    st.markdown(
        "- **One shared copy online** — you and anyone else you give the link to always "
        "see the same up-to-date records, from any device.\n"
        "- **Automatic cloud backups** — the database provider keeps the data on "
        "professional servers with their own backups.\n"
        "- **Your own copies** — download the CSV files above every so often for an extra "
        "copy that lives with you."
    )


def page_setup():
    st.title("⚙️ Setup & Manage")
    st.caption("Set up your real oil types and tanks here. Day-to-day stock entry stays "
               "on the Incoming / Outgoing pages.")

    oil_types = db.get_oil_types()

    # --- Oil types ------------------------------------------------------
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
                st.success(f"Removed '{del_oil}'.")
                st.rerun()
            except Exception as e:
                st.error(str(e))

    st.divider()

    # --- Tanks ----------------------------------------------------------
    st.subheader("Tanks")
    tanks = db.get_tanks()
    if not tanks.empty:
        st.dataframe(
            tanks[["name", "oil_type", "capacity", "current_volume"]].rename(columns={
                "name": "Tank", "oil_type": "Oil Type",
                "capacity": "Capacity (L)", "current_volume": "Current Volume (L)",
            }),
            hide_index=True, use_container_width=True,
        )
    else:
        st.info("No tanks yet. Add your tanks below.")

    if oil_types.empty:
        st.warning("Add at least one oil type before creating tanks.")
    else:
        with st.form("add_tank", clear_on_submit=True):
            tname = st.text_input("Tank name / number (e.g. Tank 1)")
            toil = st.selectbox("Oil type stored in this tank", oil_types["name"])
            tcap = st.number_input("Capacity (Litres)", min_value=0.0, step=100.0, format="%.0f")
            if st.form_submit_button("➕ Add tank"):
                if not tname.strip():
                    st.error("Please enter a tank name.")
                elif tcap <= 0:
                    st.error("Capacity must be greater than zero.")
                else:
                    try:
                        oid = int(oil_types.loc[oil_types["name"] == toil, "id"].iloc[0])
                        db.add_tank(tname.strip(), oid, tcap)
                        st.success(f"Added '{tname.strip()}'.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Couldn't add: {e}")

        if not tanks.empty:
            with st.expander("Edit or remove a tank"):
                tk = st.selectbox("Choose a tank", tanks["name"], key="edit_tank")
                row = tanks.loc[tanks["name"] == tk].iloc[0]
                new_cap = st.number_input("New capacity (L)", min_value=0.0,
                                          value=float(row["capacity"]), step=100.0, format="%.0f")
                c1, c2 = st.columns(2)
                if c1.button("Save new capacity"):
                    db.update_tank_capacity(int(row["id"]), new_cap)
                    st.success("Capacity updated.")
                    st.rerun()
                if c2.button("Remove this tank"):
                    try:
                        db.delete_tank(int(row["id"]))
                        st.success(f"Removed '{tk}'.")
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))

    st.divider()
    st.info("💡 To set a tank's **opening stock**, go to the **Incoming Stock Entry** page and "
            "log the current quantity as an incoming entry (with the rate you value it at). "
            "That keeps your weighted-average rate correct from day one.")


def page_edit():
    st.title("✏️ Edit / Correct Entries")
    st.caption("Fix or remove a single entry that was logged by mistake. The tank's stock "
               "level is corrected automatically to match.")

    txns = db.get_editable_transactions()
    if txns.empty:
        st.info("There are no transactions to edit yet.")
        return

    oil_types = db.get_oil_types()
    tanks_all = db.get_tanks()

    def _label(i):
        r = txns.iloc[i]
        return (f"{r['type']}  |  {r['date']}  |  {r['oil_type']}  |  {r['tank']}  |  "
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

        tank_names = tanks_all["name"].tolist()
        tank_default = tanks_all.loc[tanks_all["id"] == row["tank_id"], "name"]
        tank_idx = tank_names.index(tank_default.iloc[0]) if not tank_default.empty else 0
        tank_name = st.selectbox("Tank", tank_names, index=tank_idx)
        new_tank_id = int(tanks_all.loc[tanks_all["name"] == tank_name, "id"].iloc[0])

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
                    db.update_incoming(txn_id, new_date.isoformat(), new_oil_id, new_tank_id,
                                       new_qty, new_rate, new_party)
                else:
                    db.update_outgoing(txn_id, new_date.isoformat(), new_oil_id, new_tank_id,
                                       new_qty, new_party, new_notes)
                st.success("Entry updated — the tank's stock has been corrected.")
                st.rerun()
            except Exception as e:
                st.error(str(e))

    st.divider()
    st.subheader("Delete this entry")
    st.write("Removing an entry also corrects the tank's stock. To avoid accidents, tick the "
             "box first.")
    confirm = st.checkbox("Yes, permanently delete the entry selected above")
    if st.button("🗑️ Delete entry", disabled=not confirm):
        try:
            if ttype == "In":
                db.delete_incoming(txn_id)
            else:
                db.delete_outgoing(txn_id)
            st.success("Entry deleted — the tank's stock has been corrected.")
            st.rerun()
        except Exception as e:
            st.error(str(e))


PAGES = {
    "Dashboard": page_dashboard,
    "Incoming Stock Entry": page_incoming,
    "Outgoing Stock Entry": page_outgoing,
    "History & Logs": page_history,
    "Edit / Correct Entries": page_edit,
    "Data & Backups": page_backups,
    "Setup & Manage": page_setup,
}

st.sidebar.title("Oil Godown Inventory")
choice = st.sidebar.radio("Navigate", list(PAGES.keys()))
PAGES[choice]()
