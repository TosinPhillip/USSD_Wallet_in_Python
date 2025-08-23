import os
import random
import re
import datetime
from flask import Flask, request, Response
from pymongo import MongoClient
from dotenv import load_dotenv

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

def generate_account_number():
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

@app.route("/healthz", methods=["GET"])
def healthz():
    return "OK", 200

@app.route("/", methods=['GET', 'POST'])
def ussd():
    session_id = request.values.get("sessionId", "")
    service_code = request.values.get("serviceCode", "")
    phone_number = request.values.get("phoneNumber", "")
    text = request.values.get("text", "")

    menu = text.split("*") if text else []
    response = ""

    # Language selection page
    if not menu or menu[0] == "":
        response = "CON Select Language:\n1. English\n2. Ikwere"
        return Response(response, mimetype="text/plain")

    # Handle language selection
    if menu[0] == "1":
        # English selected, continue with existing workflow
        # Shift menu to remove language selection
        menu = menu[1:]

        # Main menu
        if not menu or menu[0] == "":
            response = "CON Welcome to Franciswallet\n"
            response += "1. Create Account\n2. Check Balance\n3. Send Money\n4. Enquiry Services\n5. Exit"
            return Response(response, mimetype="text/plain")

        # Create Account
        if menu[0] == "1":
            if len(menu) == 1:
                response = "CON Please enter your full name:"
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
                name = menu[1]
                dob = menu[2]
                bvn = menu[3]
                nin = menu[4]
                pin = menu[5]
                pin_confirm = menu[6]
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
                if errors:
                    response = "END Error: " + "; ".join(errors)
                else:
                    acct_num = generate_account_number()
                    users_db.insert_one({
                        "name": name,
                        "dob": dob,
                        "bvn": bvn,
                        "nin": nin,
                        "pin": pin,
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
                response = "CON Enter your account number:"
            elif len(menu) == 2:
                response = "CON Enter your password:"
            elif len(menu) == 3:
                acct_num = menu[1]
                pin = menu[2]
                if authenticate(acct_num, pin):
                    user = get_user_by_acct(acct_num)
                    response = f"END Your balance is NGN{user['balance']:.2f}."
                else:
                    response = "END Invalid account number or password."
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
                sender = users_db.find_one({"phone_number": phone_number})
                sender_acct = sender["acct_num"] if sender else None
                recipient_acct = menu[1]
                amount = float(menu[2])
                pin = menu[3]
                sender_user = get_user_by_acct(sender_acct)
                recipient_user = get_user_by_acct(recipient_acct)
                if not sender_user or not recipient_user:
                    response = "END Transaction failed. Invalid account number."
                elif not authenticate(sender_acct, pin):
                    response = "END Transaction failed. Invalid password."
                elif sender_user['balance'] < amount:
                    response = "END Transaction failed. Insufficient funds."
                else:
                    users_db.update_one({"acct_num": sender_acct}, {"$inc": {"balance": -amount}})
                    users_db.update_one({"acct_num": recipient_acct}, {"$inc": {"balance": amount}})
                    now = datetime.datetime.now().isoformat()
                    record_transaction(sender_acct, {
                        "type": "debit",
                        "amount": amount,
                        "to": recipient_acct,
                        "date": now
                    })
                    record_transaction(recipient_acct, {
                        "type": "credit",
                        "amount": amount,
                        "from": sender_acct,
                        "date": now
                    })
                    response = f"END Transaction successful! Sent NGN{amount:,.2f}."
                return Response(response, mimetype="text/plain")
            return Response(response, mimetype="text/plain")

        # Enquiry Services
        if menu[0] == "4":
            if len(menu) == 1:
                response = (
                    "CON Enquiry Services:\n"
                    "1. Customer Care\n"
                    "2. Transaction History\n"
                    "3. Account Details\n"
                    "4. Back to Main Menu"
                )
            elif len(menu) == 2:
                option = menu[1]
                if option == "1":
                    response = f"END Contact: support@wallet.com or call {CUSTOMER_CARE}."
                elif option == "2":
                    response = "CON Enter account number to view last 5 transactions:"
                elif option == "3":
                    response = "CON Enter account number to view details:"
                elif option == "4":
                    response = "END Thank you for using Franciswallet."
                else:
                    response = "END Invalid option."
            elif len(menu) == 3 and menu[1] == "2":
                acct_num = menu[2]
                txns_doc = transactions_db.find_one({"acct_num": acct_num})
                txns = txns_doc["txns"][-5:] if txns_doc and "txns" in txns_doc else []
                if not txns:
                    response = "END No recent transactions."
                else:
                    lines = [f"{t['date'][:10]}: {t['type'].capitalize()} NGN{t['amount']:.2f}" for t in txns]
                    response = "END " + "\n".join(lines)
            elif len(menu) == 3 and menu[1] == "3":
                acct_num = menu[2]
                user = get_user_by_acct(acct_num)
                if user:
                    response = (f"END Name: {user['name']}\n"
                                f"Account Number: {user['acct_num']}\n"
                                f"BVN Linked: {user['bvn']}")
                else:
                    response = "END Account not found."
            return Response(response, mimetype="text/plain")

        # Exit
        if menu[0] == "5":
            response = "END Thank you for using Franciswallet. Goodbye!"
            return Response(response, mimetype="text/plain")

        response = "END Invalid option."
        return Response(response, mimetype="text/plain")

    elif menu[0] == "2":
        # Ikwere selected
        response = "END Thank you"
        return Response(response, mimetype="text/plain")
    else:
        # Invalid language selection
        response = "END Invalid language selection."
        return Response(response, mimetype="text/plain")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)