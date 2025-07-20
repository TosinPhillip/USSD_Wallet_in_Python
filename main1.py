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

# Root route for browser and Render health check
@app.route("/", methods=["GET"])
def index():
    return "USSD Wallet API running.", 200

# Optional: Health check route (Render and k8s often use this)
@app.route("/healthz", methods=["GET"])
def healthz():
    return "OK", 200

@app.route("/ussd", methods=["POST"])
def ussd():
    session_id = request.values.get("sessionId", "")
    service_code = request.values.get("serviceCode", "")
    phone_number = request.values.get("phoneNumber", "")
    text = request.values.get("text", "")

    menu = text.split("*") if text else []
    response = ""

    if not menu or menu[0] == "":
        response = "CON Welcome to USSD Wallet\n"
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
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))