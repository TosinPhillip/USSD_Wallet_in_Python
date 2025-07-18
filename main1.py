import random
import re
import datetime
from flask import Flask, render_template, request, redirect
from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi

app = Flask(__name__)

# Replace the URI string with your MongoDB connection string
app.config["MONGO_URI"] = "mongodb+srv://oluyemitosin72:GcXd8IgFLmRNyFvF@behind-the-reef.kfdz17i.mongodb.net/?retryWrites=true&w=majority&appName=Behind-the-Reef"
uri = "mongodb+srv://oluyemitosin72:GcXd8IgFLmRNyFvF@behind-the-reef.kfdz17i.mongodb.net/?retryWrites=true&w=majority&appName=Behind-the-Reef"

# Create a new client and connect to the server
client = MongoClient(uri, server_api=ServerApi('1'))

db = client["USSD_Wallet"]  # Database name

# Access collections
users_db = db["users_db"]  # 'users_db' collection
transactions_db = db["transactions_db"]  # 'transactions_db' collection

def generate_account_number():
    # Generates a unique 10-digit account number
    while True:
        acct_num = str(random.randint(10**9, 10**10 - 1))
        if not users_db.find_one({"acct_num": acct_num}):
            return acct_num

def validate_bvn(bvn):
    return re.fullmatch(r"\d{11}", bvn) is not None

def validate_nin(nin):
    return re.fullmatch(r"\d{11}", nin) is not None

def validate_pin(pin):
    return re.fullmatch(r"\d{4,6}", pin) is not None

def get_user_by_acct(acct_num):
    return users_db.find_one({"acct_num": acct_num})

def authenticate(acct_num, pin):
    user = get_user_by_acct(acct_num)
    return user and user['pin'] == pin

def record_transaction(acct_num, txn):
    transactions_db.update_one(
        {"acct_num": acct_num},
        {"$push": {"txns": txn}},
        upsert=True
    )
    # Optionally, keep only last 5 transactions (not enforced here)

def main_menu():
    return (
        "Welcome to PyWallet\n"
        "1. Create Account\n"
        "2. Check Balance\n"
        "3. Send Money\n"
        "4. Enquiry Services\n"
        "5. Exit"
    )

def create_account_flow(session):
    # session: dict with keys for each step
    step = session.get('step', 0)
    prompts = [
        "Please enter your full name:",
        "Enter your date of birth (DD/MM/YYYY):",
        "Enter your 11-digit BVN:",
        "Enter your 11-digit NIN:",
        "Create a 4-6 digit password:",
        "Confirm your password:"
    ]
    if step < len(prompts):
        return prompts[step]
    # After all steps, validate and create account
    name = session['name']
    dob = session['dob']
    bvn = session['bvn']
    nin = session['nin']
    pin = session['pin']
    pin_confirm = session['pin_confirm']
    # Validate
    errors = []
    try:
        datetime.datetime.strptime(dob, "%d/%m/%Y")
    except Exception:
        errors.append("Invalid DOB format.")
    if not validate_bvn(bvn):
        errors.append("Invalid BVN format.")
    if not validate_nin(nin):
        errors.append("Invalid NIN format.")
    if not validate_pin(pin):
        errors.append("PIN must be 4-6 digits.")
    if pin != pin_confirm:
        errors.append("PINs do not match.")
    acct_num = generate_account_number()
    users_db.insert_one({
        "name": name,
        "dob": dob,
        "bvn": bvn,
        "nin": nin,
        "pin": pin,
        "balance": 0.0,
        "acct_num": acct_num
    })
    return f"Account created successfully! Your account number is {acct_num}. Keep it safe."

def check_balance_flow(session):
    step = session.get('step', 0)
    if step == 0:
        return "Enter your account number:"
    elif step == 1:
        return "Enter your password:"
    elif step == 2:
        acct_num = session['acct_num']
        pin = session['pin']
        if authenticate(acct_num, pin):
            user = get_user_by_acct(acct_num)
            return f"Your balance is ₦{user['balance']:.2f}."
        else:
            return "Invalid account number or password."
    return ""

def send_money_flow(session):
    step = session.get('step', 0)
    if step == 0:
        return "Enter recipient account number:"
    elif step == 1:
        return "Enter amount to send:"
    elif step == 2:
        return "Enter your password to confirm:"
    elif step == 3:
        sender_acct = session['sender_acct']
        recipient_acct = session['recipient_acct']
        amount = float(session['amount'])
        pin = session['pin']
        sender = get_user_by_acct(sender_acct)
        recipient = get_user_by_acct(recipient_acct)
        if not sender or not recipient:
            return "Transaction failed. Reason: Invalid account number."
        if not authenticate(sender_acct, pin):
            return "Transaction failed. Reason: Invalid password."
        if sender['balance'] < amount:
            return "Transaction failed. Reason: Insufficient funds."
        session['recipient_name'] = recipient['name']
        session['amount'] = amount
        return f"Send ₦{amount:,.2f} to {recipient['name']}? 1. Confirm 2. Cancel"
    elif step == 4:
        if session['confirm'] == '1':
            sender = get_user_by_acct(session['sender_acct'])
            recipient = get_user_by_acct(session['recipient_acct'])
            amount = session['amount']
            sender['balance'] -= amount
            recipient['balance'] += amount
            # Record transactions
            record_transaction(sender['acct_num'], {
                "type": "debit",
                "amount": amount,
                "to": recipient['acct_num'],
                "date": datetime.datetime.now().isoformat()
            })
            record_transaction(recipient['acct_num'], {
                "type": "credit",
                "amount": amount,
                "from": sender['acct_num'],
                "date": datetime.datetime.now().isoformat()
            })
            return f"Transaction successful! New balance: ₦{sender['balance']:.2f}."
        else:
            return "Transaction cancelled."
    return ""

def enquiry_services_flow(session):
    step = session.get('step', 0)
    if step == 0:
        return (
            "Enquiry Services:\n"
            "1. Customer Care\n"
            "2. Transaction History\n"
            "3. Account Details\n"
            "4. Back to Main Menu"
        )
    elif step == 1:
        option = session['enquiry_option']
        if option == '1':
            return "Contact: support@wallet.com or call 0123456789."
        elif option == '2':
            session['txn_history_step'] = 1
            return "Enter password to view last 5 transactions:"
        elif option == '3':
            session['acct_details_step'] = 1
            return "Enter password:"
        elif option == '4':
            return main_menu()
    elif step == 2 and session.get('txn_history_step') == 1:
        acct_num = session['acct_num']
        pin = session['pin']
        if authenticate(acct_num, pin):
            txns = transactions_db.get(acct_num, [])
            if not txns:
                return "No recent transactions."
            lines = [f"{t['date'][:10]}: {t['type'].capitalize()} ₦{t['amount']:.2f}" for t in txns]
            return "\n".join(lines)
        else:
            return "Invalid password."
    elif step == 2 and session.get('acct_details_step') == 1:
        acct_num = session['acct_num']
        pin = session['pin']
        if authenticate(acct_num, pin):
            user = get_user_by_acct(acct_num)
            return (f"Name: {user['name']}\n"
                    f"Account Number: {user['acct_num']}\n"
                    f"BVN Linked: {user['bvn']}")
        else:
            return "Invalid password."
    return ""

def exit_flow():
    return "Thank you for using PyWallet. Goodbye!"

# Example USSD session handler
def ussd_handler(session, user_input):
    # session: dict holding state, e.g. {'menu': 'main', ...}
    if session.get('menu') == 'main':
        if user_input == '1':
            session['menu'] = 'create_account'
            session['step'] = 0
            return create_account_flow(session)
        elif user_input == '2':
            session['menu'] = 'check_balance'
            session['step'] = 0
            return check_balance_flow(session)
        elif user_input == '3':
            session['menu'] = 'send_money'
            session['step'] = 0
            return send_money_flow(session)
        elif user_input == '4':
            session['menu'] = 'enquiry_services'
            session['step'] = 0
            return enquiry_services_flow(session)
        elif user_input == '5':
            return exit_flow()
        else:
            return main_menu()
    elif session.get('menu') == 'create_account':
        prompts = ["name", "dob", "bvn", "nin", "pin", "pin_confirm"]
        key = prompts[session['step']]
        session[key] = user_input
        session['step'] += 1
        result = create_account_flow(session)
        if "successfully" in result or "Error:" in result:
            session.clear()
            session['menu'] = 'main'
            return result + "\n\n" + main_menu()
        return result
    elif session.get('menu') == 'check_balance':
        if session['step'] == 0:
            session['acct_num'] = user_input
            session['step'] += 1
            return check_balance_flow(session)
        elif session['step'] == 1:
            session['pin'] = user_input
            session['step'] += 1
            result = check_balance_flow(session)
            session.clear()
            session['menu'] = 'main'
            return result + "\n\n" + main_menu()
    elif session.get('menu') == 'send_money':
        if session['step'] == 0:
            session['recipient_acct'] = user_input
            session['step'] += 1
            return send_money_flow(session)
        elif session['step'] == 1:
            session['amount'] = user_input
            session['step'] += 1
            return send_money_flow(session)
        elif session['step'] == 2:
            session['pin'] = user_input
            session['sender_acct'] = session.get('sender_acct', session.get('acct_num'))
            session['step'] += 1
            return send_money_flow(session)
        elif session['step'] == 3:
            session['confirm'] = user_input
            session['step'] += 1
            result = send_money_flow(session)
            session.clear()
            session['menu'] = 'main'
            return result + "\n\n" + main_menu()
    elif session.get('menu') == 'enquiry_services':
        if session['step'] == 0:
            session['enquiry_option'] = user_input
            session['step'] += 1
            return enquiry_services_flow(session)
        elif session.get('step') == 1:
            option = session['enquiry_option']
            if option == '2':  # Transaction History
                session['acct_num'] = session.get('acct_num', user_input)
                session['step'] += 1
                return enquiry_services_flow(session)
            elif option == '3':  # Account Details
                session['acct_num'] = session.get('acct_num', user_input)
                session['step'] += 1
                return enquiry_services_flow(session)
            else:
                session.clear()
                session['menu'] = 'main'
                return enquiry_services_flow(session)
        elif session['step'] == 2:
            option = session['enquiry_option']
            if option == '2' or option == '3':
                session['pin'] = user_input
                result = enquiry_services_flow(session)
                session.clear()
                session['menu'] = 'main'
                return result + "\n\n" + main_menu()
    else:
        session.clear()
        session['menu'] = 'main'
        return main_menu()

# To start a session:
session = {'menu': 'main'}
print(main_menu())
while True:
    user_input = input("> ")
    response = ussd_handler(session, user_input)
    print(response)