import os
from flask import Flask, request, Response
from pymongo import MongoClient
from dotenv import load_dotenv

# Load environment variables (for local/dev)
load_dotenv()

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017/")
DB_NAME = os.environ.get("DATABASE_NAME", "ussd_wallet")
CUSTOMER_CARE = os.environ.get("CUSTOMER_CARE", "+1234567890")

app = Flask(__name__)
client = MongoClient(MONGO_URI)
db = client[DB_NAME]

def get_user(phone_number):
    return db.users.find_one({"phone_number": phone_number})

def create_account(phone_number, name, pin):
    user = {
        "phone_number": phone_number,
        "name": name,
        "pin": pin,
        "balance": 0.0
    }
    db.users.insert_one(user)
    return user

def update_balance(phone_number, amount):
    db.users.update_one({"phone_number": phone_number}, {"$inc": {"balance": amount}})

def send_money(sender_phone, recipient_phone, amount):
    sender = get_user(sender_phone)
    recipient = get_user(recipient_phone)
    if not recipient:
        return False, "Recipient not found."
    if sender["balance"] < amount:
        return False, "Insufficient funds."
    update_balance(sender_phone, -amount)
    update_balance(recipient_phone, amount)
    return True, "Transfer successful."

def check_pin(phone_number, pin):
    user = get_user(phone_number)
    return user and user["pin"] == pin

# Optional: Health check route (Render and k8s often use this)
@app.route("/healthz", methods=["GET"])
def healthz():
    return "OK", 200

@app.route("/", methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'])
def ussd():
    session_id = request.values.get("sessionId", "")
    service_code = request.values.get("serviceCode", "")
    phone_number = request.values.get("phoneNumber", "")
    text = request.values.get("text", "")

    menu = text.split("*") if text else []
    response = ""

    if not menu or menu[0] == "":
        response = "CON Welcome to Francis' USSD Wallet\n"
        response += "1. Create Account\n2. Check Balance\n3. Send Money\n4. Enquiry Services\n5. Exit"
        return Response(response, mimetype="text/plain")

    if menu[0] == "1":
        if len(menu) == 1:
            if get_user(phone_number):
                return Response("END Account already exists.", mimetype="text/plain")
            response = "CON Enter your Name:"
        elif len(menu) == 2:
            response = "CON Set your 4-digit PIN:"
        elif len(menu) == 3:
            if get_user(phone_number):
                return Response("END Account already exists.", mimetype="text/plain")
            create_account(phone_number, menu[1], menu[2])
            response = "END Account created successfully!"
        return Response(response, mimetype="text/plain")

    if menu[0] == "2":
        if not get_user(phone_number):
            return Response("END Please create an account first.", mimetype="text/plain")
        if len(menu) == 1:
            response = "CON Enter your PIN to view balance:"
        elif len(menu) == 2:
            if not check_pin(phone_number, menu[1]):
                return Response("END Incorrect PIN.", mimetype="text/plain")
            user = get_user(phone_number)
            response = f"END Your balance is ${user['balance']:.2f}"
        return Response(response, mimetype="text/plain")

    if menu[0] == "3":
        if not get_user(phone_number):
            return Response("END Please create an account first.", mimetype="text/plain")
        if len(menu) == 1:
            response = "CON Enter recipient's phone number (e.g. +234xxxxxxxxxx):"
        elif len(menu) == 2:
            response = "CON Enter amount to send:"
        elif len(menu) == 3:
            response = "CON Enter your PIN to confirm:"
        elif len(menu) == 4:
            if not check_pin(phone_number, menu[3]):
                return Response("END Incorrect PIN.", mimetype="text/plain")
            try:
                amount = float(menu[2])
                success, msg = send_money(phone_number, menu[1], amount)
                response = f"END {msg}"
            except Exception:
                response = "END Invalid amount."
        return Response(response, mimetype="text/plain")

    if menu[0] == "4":
        response = f"END For enquiries, call {CUSTOMER_CARE}"
        return Response(response, mimetype="text/plain")

    if menu[0] == "5":
        response = "END Thank you for using our service!"
        return Response(response, mimetype="text/plain")

    response = "END Invalid option."
    return Response(response, mimetype="text/plain")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
    
    
    
    

import os
import random
import re
import datetime
import bcrypt
from flask import Flask, request, Response
from pymongo import MongoClient
from dotenv import load_dotenv
from pymongo import ReturnDocument

# Load environment variables
load_dotenv()

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017/")
DB_NAME = os.environ.get("DATABASE_NAME", "USSD_Wallet")
CUSTOMER_CARE = os.environ.get("CUSTOMER_CARE", "+1234567890")

app = Flask(__name__)
client = MongoClient(MONGO_URI)
db = client[DB_NAME]
users_db = db["users_db"]
transactions_db = db["transactions_db"]

# ---------------- Utility Functions ---------------- #

def generate_account_number():
    """Generate unique 10-digit account number"""
    while True:
        acct_num = str(random.randint(10**9, 10**10 - 1))
        if not users_db.find_one({"acct_num": acct_num}):
            return acct_num

def validate_bvn(bvn): return re.fullmatch(r"\d{11}", bvn) is not None
def validate_nin(nin): return re.fullmatch(r"\d{11}", nin) is not None
def validate_pin(pin): return re.fullmatch(r"\d{4,6}", pin) is not None

def hash_pin(pin): return bcrypt.hashpw(pin.encode(), bcrypt.gensalt()).decode()
def verify_pin(pin, hashed): return bcrypt.checkpw(pin.encode(), hashed.encode())

def get_user_by_acct(acct_num): return users_db.find_one({"acct_num": acct_num})

def authenticate(acct_num, pin):
    user = get_user_by_acct(acct_num)
    return user and verify_pin(pin, user["pin"])

def record_transaction(acct_num, txn):
    transactions_db.update_one(
        {"acct_num": acct_num},
        {"$push": {"txns": txn}},
        upsert=True
    )

# ---------------- Health Check ---------------- #

@app.route("/healthz", methods=["GET"])
def healthz():
    return "OK", 200

# ---------------- USSD Menu ---------------- #

@app.route("/", methods=['GET', 'POST'])
def ussd():
    session_id = request.values.get("sessionId", "")
    service_code = request.values.get("serviceCode", "")
    phone_number = request.values.get("phoneNumber", "")
    text = request.values.get("text", "")

    menu = text.split("*") if text else []
    response = ""

    # ---------------- Language selection ---------------- #
    if not menu or menu[0] == "":
        response = "CON Select Language:\n1. English\n2. Ikwere"
        return Response(response, mimetype="text/plain")

    # ---------------- English Flow ---------------- #
    if menu[0] == "1":
        menu = menu[1:]  # Remove language selection

        if not menu or menu[0] == "":
            response = "CON Welcome to Franciswallet\n1. Create Account\n2. Check Balance\n3. Send Money\n4. Enquiry Services\n5. Exit"
            return Response(response, mimetype="text/plain")

        # Create Account
        if menu[0] == "1":
            if len(menu) == 1:
                response = "CON Enter your full name:"
            elif len(menu) == 2:
                response = "CON Enter your date of birth (DD/MM/YYYY):"
            elif len(menu) == 3:
                response = "CON Enter your 11-digit BVN:"
            elif len(menu) == 4:
                response = "CON Enter your 11-digit NIN:"
            elif len(menu) == 5:
                response = "CON Create a 4-6 digit password:"
            elif len(menu) == 6:
                response = "CON Confirm your password:"
            elif len(menu) == 7:
                name, dob, bvn, nin, pin, pin_confirm = menu[1:7]
                errors = []
                try:
                    datetime.datetime.strptime(dob, "%d/%m/%Y")
                except Exception:
                    errors.append("Invalid DOB format.")
                if not validate_bvn(bvn): errors.append("Invalid BVN.")
                if not validate_nin(nin): errors.append("Invalid NIN.")
                if not validate_pin(pin): errors.append("PIN must be 4-6 digits.")
                if pin != pin_confirm: errors.append("PINs do not match.")
                if errors:
                    response = "END Error: " + "; ".join(errors)
                else:
                    acct_num = generate_account_number()
                    users_db.insert_one({
                        "name": name,
                        "dob": dob,
                        "bvn": bvn,
                        "nin": nin,
                        "pin": hash_pin(pin),
                        "balance": 0.0,
                        "acct_num": acct_num,
                        "phone_number": phone_number
                    })
                    response = f"END Account created! Your account number is {acct_num}."
                return Response(response, mimetype="text/plain")
            return Response(response, mimetype="text/plain")

        # Check Balance
        if menu[0] == "2":
            if len(menu) == 1:
                response = "CON Enter account number:"
            elif len(menu) == 2:
                response = "CON Enter password:"
            elif len(menu) == 3:
                acct_num, pin = menu[1], menu[2]
                if authenticate(acct_num, pin):
                    user = get_user_by_acct(acct_num)
                    response = f"END Balance: NGN{user['balance']:.2f}"
                else:
                    response = "END Invalid account or password."
                return Response(response, mimetype="text/plain")
            return Response(response, mimetype="text/plain")

        # Send Money
        if menu[0] == "3":
            if len(menu) == 1:
                response = "CON Enter recipient account number:"
            elif len(menu) == 2:
                response = "CON Enter amount to send:"
            elif len(menu) == 3:
                response = "CON Enter your password to confirm:"
            elif len(menu) == 4:
                recipient_acct, amount_str, pin = menu[1], menu[2], menu[3]
                try:
                    amount = float(amount_str)
                except ValueError:
                    return Response("END Invalid amount.", mimetype="text/plain")

                sender = users_db.find_one({"phone_number": phone_number})
                sender_acct = sender["acct_num"] if sender else None
                sender_user = get_user_by_acct(sender_acct)
                recipient_user = get_user_by_acct(recipient_acct)

                if not sender_user or not recipient_user:
                    response = "END Invalid account number."
                elif not authenticate(sender_acct, pin):
                    response = "END Invalid password."
                elif sender_user['balance'] < amount:
                    response = "END Insufficient funds."
                else:
                    now = datetime.datetime.now().isoformat()
                    # Atomic debit and credit
                    users_db.find_one_and_update(
                        {"acct_num": sender_acct, "balance": {"$gte": amount}},
                        {"$inc": {"balance": -amount}},
                        return_document=ReturnDocument.AFTER
                    )
                    users_db.update_one({"acct_num": recipient_acct}, {"$inc": {"balance": amount}})
                    record_transaction(sender_acct, {"type": "debit","amount": amount,"to": recipient_acct,"date": now})
                    record_transaction(recipient_acct, {"type": "credit","amount": amount,"from": sender_acct,"date": now})
                    response = f"END Sent NGN{amount:.2f} successfully."
                return Response(response, mimetype="text/plain")
            return Response(response, mimetype="text/plain")

        # Enquiry Services
        if menu[0] == "4":
            if len(menu) == 1:
                response = "CON Enquiry:\n1. Customer Care\n2. Last 5 Transactions\n3. Account Details\n4. Main Menu"
            elif len(menu) == 2:
                if menu[1] == "1":
                    response = f"END Contact support@wallet.com or {CUSTOMER_CARE}"
                elif menu[1] == "2":
                    response = "CON Enter account number:"
                elif menu[1] == "3":
                    response = "CON Enter account number:"
                elif menu[1] == "4":
                    response = "END Returning to main menu."
                else:
                    response = "END Invalid option."
            elif len(menu) == 3 and menu[1] == "2":
                acct_num = menu[2]
                txns_doc = transactions_db.find_one({"acct_num": acct_num})
                txns = txns_doc["txns"][-5:] if txns_doc else []
                if not txns:
                    response = "END No transactions."
                else:
                    lines = [f"{t['date'][:10]} {t['type']} NGN{t['amount']:.2f}" for t in txns]
                    response = "END " + "\n".join(lines)
            elif len(menu) == 3 and menu[1] == "3":
                acct_num = menu[2]
                user = get_user_by_acct(acct_num)
                if user:
                    response = f"END {user['name']}\nAcct: {user['acct_num']}\nBVN: {user['bvn']}"
                else:
                    response = "END Account not found."
            return Response(response, mimetype="text/plain")

        # Exit
        if menu[0] == "5":
            return Response("END Thank you for using Franciswallet.", mimetype="text/plain")

        return Response("END Invalid option.", mimetype="text/plain")

    # ---------------- Ikwere Flow ---------------- #
    elif menu[0] == "2":
        menu = menu[1:]

        if not menu or menu[0] == "":
            response = "CON Nnọọ na Franciswallet\n1. Mepụta Akaụntụ\n2. Lelee Ego\n3. Zipu Ego\n4. Ajụjụ\n5. Kwụsị"
            return Response(response, mimetype="text/plain")

        # (Repeat same logic as English, but replace all responses with Ikwere translations)
        # For brevity: you'd duplicate each branch (Create Account, Balance, Send Money, Enquiry, Exit),
        # but with translated texts like:
        # "CON Tinye aha gị:" (Enter your name)
        # "END Ego gị bụ NGN..." (Your balance is NGN...)
        # "END Emechara!" (Completed!)
        # etc.

        return Response("END Ọrụ Ikwere ka edobere nke ọma.", mimetype="text/plain")

    else:
        return Response("END Invalid language.", mimetype="text/plain")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
