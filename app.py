import streamlit as st
import pandas as pd
import sqlite3
import os
from datetime import datetime

# Database setup
DB_FILE = "splitwise_clone.db"


st.markdown("""
    <style>
    .settlement-suggestion {
        font-family: 'Arial', sans-serif;
        font-size: 18px;
        font-weight: bold;
        color: #2E8B57;
        background-color: #F0FFF0;
        padding: 10px;
        border-radius: 5px;
        margin-bottom: 10px;
        box-shadow: 2px 2px 5px rgba(0, 0, 0, 0.1);
    }
    </style>
""", unsafe_allow_html=True)



def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS members
                 (id INTEGER PRIMARY KEY, name TEXT UNIQUE)''')
    c.execute('''CREATE TABLE IF NOT EXISTS expenses
                 (id INTEGER PRIMARY KEY, description TEXT, amount REAL, payer TEXT, split_type TEXT, date TEXT, transaction_id TEXT UNIQUE)''')
    c.execute('''CREATE TABLE IF NOT EXISTS expense_splits
                 (id INTEGER PRIMARY KEY, expense_id INTEGER, member TEXT, amount REAL)''')
    conn.commit()
    conn.close()
    

def generate_transaction_id(date):
    # Format the date as YYYYMMDD
    date_str = date.strftime('%Y%m%d')
    
    # Count how many transactions exist on the given date
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM expenses WHERE date = ?", (date.strftime('%Y-%m-%d'),))
    transaction_count = c.fetchone()[0] + 1  # Add 1 to make the ID for the next transaction
    conn.close()
    
    # Create the transaction ID (date + count)
    transaction_id = f"{date_str}{transaction_count}"
    
    return transaction_id

    
def add_member(name):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO members (name) VALUES (?)", (name,))
        conn.commit()
    except sqlite3.IntegrityError:
        st.error(f"Member '{name}' already exists.")
    finally:
        conn.close()

def get_members():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT name FROM members")
    members = [row[0] for row in c.fetchall()]
    conn.close()
    return members

def add_expense(description, amount, payer, split_with, split_type, date):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # Generate transaction ID
    transaction_id = generate_transaction_id(date)
    
    c.execute("INSERT INTO expenses (description, amount, payer, split_type, date, transaction_id) VALUES (?, ?, ?, ?, ?, ?)",
              (description, amount, payer, split_type, date.strftime('%Y-%m-%d'), transaction_id))
    expense_id = c.lastrowid
    
    if split_type == "Equal Split":
        split_amount = amount / (len(split_with) + 1)  # +1 to include the payer
        c.execute("INSERT INTO expense_splits (expense_id, member, amount) VALUES (?, ?, ?)",
                  (expense_id, payer, amount - split_amount))
        for member in split_with:
            if member != payer:
                c.execute("INSERT INTO expense_splits (expense_id, member, amount) VALUES (?, ?, ?)",
                          (expense_id, member, -split_amount))
    elif split_type == "Payer Owes Full":
        split_amount = amount / len(split_with)
        c.execute("INSERT INTO expense_splits (expense_id, member, amount) VALUES (?, ?, ?)",
                  (expense_id, payer, -amount))
        for member in split_with:
            c.execute("INSERT INTO expense_splits (expense_id, member, amount) VALUES (?, ?, ?)",
                      (expense_id, member, split_amount))
    elif split_type == "Payer Doesn't Owe Anything":
        split_amount = amount / len(split_with)
        c.execute("INSERT INTO expense_splits (expense_id, member, amount) VALUES (?, ?, ?)",
                  (expense_id, payer, amount))
        for member in split_with:
            c.execute("INSERT INTO expense_splits (expense_id, member, amount) VALUES (?, ?, ?)",
                      (expense_id, member, -split_amount))
    
    conn.commit()
    conn.close()

def get_expenses():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        SELECT e.id, e.description, e.amount, e.payer, e.split_type, e.date, e.transaction_id,
               GROUP_CONCAT(es.member || ':' || es.amount, ', ')
        FROM expenses e
        JOIN expense_splits es ON e.id = es.expense_id
        GROUP BY e.id
        ORDER BY e.date DESC
    """)
    expenses = []
    for row in c.fetchall():
        expense = {
            'id': row[0],
            'description': row[1],
            'amount': row[2],
            'payer': row[3],
            'split_type': row[4],
            'date': row[5],
            'transaction_id': row[6],
            'splits': {split.split(':')[0]: float(split.split(':')[1]) for split in row[7].split(', ')}
        }
        expenses.append(expense)
    conn.close()
    return expenses


def calculate_balances():
    expenses = get_expenses()
    balances = {}
    for expense in expenses:
        for member, amount in expense['splits'].items():
            if member not in balances:
                balances[member] = 0
            balances[member] += amount
    return balances

def format_currency(amount):
    # Check if the amount is negative and adjust the format accordingly
    if amount < 0:
        return f"-${abs(amount):.2f}"
    else:
        return f"${amount:.2f}"

#def format_currency(amount):
 #   return f"${amount:.2f}"

def delete_transaction_by_id(transaction_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # Get the expense ID for the provided transaction_id
    c.execute("SELECT id FROM expenses WHERE transaction_id = ?", (transaction_id,))
    expense_row = c.fetchone()
    
    if expense_row:
        expense_id = expense_row[0]
        # Delete the expense and associated splits
        c.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
        c.execute("DELETE FROM expense_splits WHERE expense_id = ?", (expense_id,))
        conn.commit()
        st.success(f"Transaction {transaction_id} has been successfully deleted.")
    else:
        st.error(f"Transaction ID {transaction_id} not found.")
    
    conn.close()


def delete_all_transactions():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM expenses")
    c.execute("DELETE FROM expense_splits")
    conn.commit()
    conn.close()
    
def get_member_summary(member):
    expenses = get_expenses()
    summary = {'total_paid': 0, 'total_owed': 0}
    for expense in expenses:
        if expense['payer'] == member:
            summary['total_paid'] += expense['amount']
        if member in expense['splits']:
            summary['total_owed'] += expense['splits'][member]
    return summary


# Initialize the database
init_db()

# Sidebar for adding members
st.sidebar.header("Manage Members")

new_member = st.sidebar.text_input("Add a new member")
if st.sidebar.button("Add Member"):
    if new_member:
        add_member(new_member)
    else:
        st.sidebar.error("Please enter a member name.")

st.sidebar.write("Current members:", ", ".join(get_members()))
st.sidebar.write("")
st.sidebar.write("")



# Add expense
st.subheader("Add Expense")

col4,col5 = st.columns(2)

with col4:
    description = st.text_input("Expense description")
with col5:
    amount = st.number_input("Amount", min_value=0.01, step=0.01, value = 100.00)


col1, col2, col3 = st.columns(3)

with col1:
    payer = st.selectbox("Paid by", get_members())

with col2:
    split_type = st.selectbox("Split Type", ["Equal Split", "Payer Owes Full", "Payer Doesn't Owe Anything"])

with col3:
    split_with = st.multiselect("Split with", [m for m in get_members() if m != payer])


expense_date = datetime.now()


if st.button("Add Expense"):
    if description and amount > 0 and payer and (split_with or split_type == "Payer Owes Full"):
        add_expense(description, amount, payer, split_with, split_type, expense_date)
        st.success("Expense added successfully!")
    else:
        st.error("Please fill in all fields.")



# Calculate and display balances
balances = calculate_balances()
balance_data = [{"Member": member, "Balance": format_currency(balance)} 
                for member, balance in balances.items()]
balance_df = pd.DataFrame(balance_data)


# Settlement suggestions
st.subheader("Settlement Suggestions")
positive_balances = {k: v for k, v in balances.items() if v > 0}
negative_balances = {k: v for k, v in balances.items() if v < 0}

for debtor, debt in negative_balances.items():
    for creditor, credit in positive_balances.items():
        if debt == 0:
            break
        if credit == 0:
            continue
        amount = min(abs(debt), credit)
        
        #st.write(f"{debtor} pays {creditor}: {format_currency(amount)}")
        # Display settlement suggestion with custom style
        st.markdown(f"""
            <div class='settlement-suggestion'>
                {debtor} pays {creditor}: {format_currency(amount)}
            </div>
        """, unsafe_allow_html=True)
     
        
        
        
        debt += amount
        positive_balances[creditor] -= amount

st.subheader("Balances")
st.dataframe(balance_df,hide_index=True)


# Display expenses
st.subheader("Expenses")
expenses = get_expenses()
if expenses:
    expense_data = []
    for expense in expenses:
        splits = ", ".join([f"{m}: {format_currency(a)}" for m, a in expense['splits'].items()])
        expense_data.append({
            "Transaction ID": expense['transaction_id'],
            "Date": expense['date'],
            "Description": expense['description'],
            "Total Amount": format_currency(expense['amount']),
            "Payer": expense['payer'],
            "Split Type": expense['split_type'],
            "Splits": splits
        })
    expense_df = pd.DataFrame(expense_data)
    st.dataframe(expense_df, hide_index=True)
else:
    st.write("No expenses added yet.")


# Loop through each member and show their summary
# members = get_members()

# for member in members:
#     summary = get_member_summary(member)
#     st.write(f"### {member}'s Summary")
#     st.write(f"{member} paid: {format_currency(summary['total_paid'])}")
#     st.write(f"{member} owes: {format_currency(summary['total_owed'])}")
#     st.write("---")  # Separator between summaries

        
        
# Sidebar for deleting a transaction
st.sidebar.header("Delete Single Transaction")

transaction_id_to_delete = st.sidebar.text_input("Enter the Transaction ID to delete")

if st.sidebar.button("Delete Single Transaction"):
    if transaction_id_to_delete:
        delete_transaction_by_id(transaction_id_to_delete)
    else:
        st.sidebar.error("Please enter a valid Transaction ID.")
        


# Sidebar for deleting all transactions
st.sidebar.write("")
st.sidebar.write("")
st.sidebar.write("")
st.sidebar.write("")
st.sidebar.subheader("Delete All Transactions")
if st.sidebar.button("Delete All Transactions"):
    delete_all_transactions()
    st.sidebar.success("All transactions have been deleted. Member list is preserved.")
    st.experimental_rerun()
