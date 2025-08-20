# app.py
from flask import Flask, request, jsonify
from models import *
from utils import *
from config import Config
import re

app = Flask(__name__)

@app.route("/ussd", methods=['POST'])
def ussd_handler():
    try:
        # Simulated payload from gateway
        session_id = request.form.get('sessionId')
        phone_number = request.form.get('phoneNumber')
        text = request.form.get('text', "")
        service_code = request.form.get('serviceCode')

        response = ""
        session = get_session(phone_number)

        # Start new session if none exists
        if not session and text == "":
            response = main_menu()
            create_or_update_session(phone_number, session_id, "main_menu")
            return send_response(response)

        elif session:
            current_step = session.get("currentStep")
            step_data = session.get("stepData", {})
        else:
            return send_response("END Session expired. Please restart.")

        # Route based on current step
        if current_step == "main_menu":
            response = handle_main_menu(text, phone_number, session_id)
        
        elif current_step.startswith("create_account"):
            response = handle_account_creation(text, phone_number, session_id, step_data)
        
        elif current_step == "pin_auth_balance":
            response = handle_balance_inquiry(text, phone_number)
        
        elif current_step.startswith("transfer"):
            response = handle_transfer_flow(text, phone_number, step_data)
        
        elif current_step.startswith("airtime"):
            response = handle_airtime_flow(text, phone_number, step_data)
        
        elif current_step == "pin_auth_history":
            response = handle_transaction_history(text, phone_number, step_data.get("history_period"))
        
        elif current_step == "change_pin_current":
            response = handle_change_pin(text, phone_number, step_data)
        
        elif current_step == "help_menu":
            response = handle_help_menu(text, phone_number)
        
        else:
            response = "END Unknown error. Please try again."

        return send_response(response)

    except Exception as e:
        print(f"Error: {e}")
        return send_response("END An error occurred. Please try again later.")


# ======================
# USSD Response Helpers
# ======================
def send_response(message):
    if message.startswith("END"):
        return message
    else:
        return "CON " + message

def main_menu():
    return (
        f"Welcome to {Config.BANK_NAME}\n"
        "1. Create Account\n"
        "2. Check Balance\n"
        "3. Transfer Money\n"
        "4. Airtime & Data\n"
        "5. Transaction History\n"
        "6. Change PIN\n"
        "7. Enquiry/Help\n"
        "8. Mini Statement\n"
        "9. Account Settings"
    )


# ===================================
# 1. Account Creation Workflow
# ===================================
def handle_main_menu(text, phone_number, session_id):
    choice = text.strip()
    
    if choice == "":
        return main_menu()

    options = {
        '1': start_account_creation,
        '2': lambda: request_pin_for_balance(phone_number),
        '3': lambda: transfer_main_menu(phone_number),
        '4': lambda: airtime_main_menu(phone_number),
        '5': lambda: request_pin_for_history(phone_number),
        '6': lambda: change_pin_start(phone_number),
        '7': lambda: help_menu(phone_number),
    }

    action = options.get(choice)
    if action:
        return action()
    else:
        return "END Invalid option selected."


def start_account_creation():
    create_or_update_session(phone_number, session_id, "create_account_fname")
    return "Enter First Name:"


def handle_account_creation(text, phone_number, session_id, step_data):
    steps = [
        ("fname", "Enter First Name:", None),
        ("lname", "Enter Last Name:", None),
        ("phone", "Enter Phone Number (e.g., 080...):", validate_nigerian_phone),
        ("dob", "Enter DOB (DD/MM/YYYY):", lambda x: re.match(r'\d{2}/\d{2}/\d{4}', x)),
        ("gender", "Select Gender:\n1. Male\n2. Female", lambda x: x in ['1','2']),
        ("bvn", "Enter BVN (11 digits):", validate_bvn),
        ("pin", "Create 4-digit PIN:", lambda x: x.isdigit() and len(x)==4),
        ("pin_confirm", "Confirm PIN:", None),
        ("security_q", "Security Q:\n1. Pet Name\n2. Birth Town", lambda x: x in ['1','2']),
        ("security_a", "Enter Answer:", None),
        ("nok_name", "Next of Kin Name:", None),
        ("nok_phone", "Next of Kin Phone:", validate_nigerian_phone),
        ("confirm", "Review details? 1. Yes 2. No", lambda x: x in ['1','2']),
    ]

    current_index = int(session.get("currentStep").split("_")[-1]) if "_" in session["currentStep"] else 0
    field, prompt, validator = steps[current_index]

    # Store input
    if field != "pin_confirm" and field != "confirm":
        step_data[field] = text.strip()

    # Validation
    if validator and not validator(text.strip()):
        return prompt  # Re-prompt

    next_index = current_index + 1
    if next_index >= len(steps):
        # Finalize creation
        acc_num = generate_account_number()
        hashed_pin = hash_pin(step_data["pin"])

        user_doc = {
            "accountNumber": acc_num,
            "firstName": step_data["fname"],
            "lastName": step_data["lname"],
            "phoneNumber": step_data["phone"],
            "dateOfBirth": datetime.strptime(step_data["dob"], "%d/%m/%Y"),
            "gender": "Male" if step_data["gender"] == "1" else "Female",
            "bvn": step_data["bvn"],
            "address": {"street": "", "city": "", "state": "", "country": "NG"},
            "nextOfKin": {
                "name": step_data["nok_name"],
                "phoneNumber": step_data["nok_phone"],
                "relationship": "Relative"
            },
            "accountStatus": "active",
            "accountTier": 1,
            "balance": 0.0,
            "pin": hashed_pin,
            "securityQuestion": step_data["security_q"],
            "securityAnswer": hash_pin(step_data["security_a"]),  # Simplified
            "failedLoginAttempts": 0,
            "createdAt": datetime.now(),
            "updatedAt": datetime.now()
        }

        users_collection.insert_one(user_doc)
        end_session(phone_number)
        log_transaction(acc_num, "credit", "deposit", 0, "Account created")
        return f"END Account created successfully!\nAcc: {acc_num}\nWelcome to {Config.BANK_NAME}!"

    # Move to next step
    next_field, next_prompt, _ = steps[next_index]
    new_step_key = f"create_account_{next_index}"
    create_or_update_session(phone_number, session_id, new_step_key, step_data)
    return next_prompt


# ===================================
# 2. Balance Inquiry
# ===================================
def request_pin_for_balance(phone_number):
    user = users_collection.find_one({"phoneNumber": phone_number})
    if not user:
        return "END No account found. Please create one first."
    if user["accountStatus"] != "active":
        return "END Account inactive. Contact support."

    create_or_update_session(phone_number, None, "pin_auth_balance")
    return "Enter your 4-digit PIN:"


def handle_balance_inquiry(text, phone_number):
    pin = text.strip()
    user = users_collection.find_one({"phoneNumber": phone_number})
    if not user:
        return "END User not found."

    attempts = user.get("failedLoginAttempts", 0)
    if attempts >= Config.MAX_PIN_ATTEMPTS:
        return "END Account locked. Contact support."

    if hash_pin(pin) == user["pin"]:
        users_collection.update_one(
            {"phoneNumber": phone_number},
            {"$set": {"failedLoginAttempts": 0, "lastLoginAt": datetime.now()}}
        )
        balance = get_balance(user["accountNumber"])
        end_session(phone_number)
        return f"END Your balance is ₦{format_amount(balance)}. Thank you for using {Config.BANK_NAME}."
    else:
        new_attempts = attempts + 1
        users_collection.update_one(
            {"phoneNumber": phone_number},
            {"$set": {"failedLoginAttempts": new_attempts}}
        )
        remaining = Config.MAX_PIN_ATTEMPTS - new_attempts
        if remaining > 0:
            return f"Invalid PIN. {remaining} attempt(s) remaining."
        else:
            return "END Account temporarily locked. Contact support."


# ===================================
# 3. Transfer Money
# ===================================
def transfer_main_menu(phone_number):
    user = users_collection.find_one({"phoneNumber": phone_number})
    if not user:
        return "END Please create an account first."
    create_or_update_session(phone_number, None, "transfer_type")
    return (
        "Transfer Money:\n"
        "1. To Bank Account\n"
        "2. To Phone Number\n"
        "3. To This Bank"
    )


def handle_transfer_flow(text, phone_number, step_data):
    user = users_collection.find_one({"phoneNumber": phone_number})
    if not user:
        return "END Error: User not found."

    step_map = {
        "transfer_type": ("transfer_recipient", transfer_recipient_prompt),
        "transfer_recipient": ("transfer_amount", "Enter amount:"),
        "transfer_amount": ("transfer_pin", "Enter PIN to confirm:"),
    }

    current = step_data.get("current", "transfer_type")
    target, next_step, func = step_map.get(current, (None, None, None))

    if current == "transfer_type":
        if text not in ["1","2","3"]:
            return "Invalid selection. Enter 1, 2, or 3."
        step_data["type"] = text
        step_data["current"] = "transfer_recipient"
        create_or_update_session(phone_number, None, target, step_data)
        return func(text)

    elif current == "transfer_recipient":
        recipient = text.strip()
        step_data["recipient"] = recipient
        step_data["current"] = "transfer_amount"
        create_or_update_session(phone_number, None, next_step, step_data)
        return "Enter amount (max ₦100,000):"

    elif current == "transfer_amount":
        try:
            amount = float(text)
            if amount <= 0 or amount > 100000:
                return "Invalid amount. Try between ₦1 and ₦100,000."
            if amount > get_balance(user["accountNumber"]):
                return "Insufficient funds."
            step_data["amount"] = amount
            step_data["current"] = "transfer_pin"
            create_or_update_session(phone_number, None, next_step, step_data)
            return f"Send ₦{format_amount(amount)}?\nEnter PIN:"
        except ValueError:
            return "Enter valid amount."

    elif current == "transfer_pin":
        entered_pin = text.strip()
        if hash_pin(entered_pin) == user["pin"]:
            # Process transfer
            new_balance = get_balance(user["accountNumber"]) - step_data["amount"]
            users_collection.update_one(
                {"phoneNumber": phone_number},
                {"$set": {"balance": new_balance}}
            )
            log_transaction(
                user["accountNumber"],
                "debit",
                "transfer",
                step_data["amount"],
                f"To {step_data['recipient']}",
                charges=10.00
            )
            end_session(phone_number)
            return f"END Transfer of ₦{format_amount(step_data['amount'])} successful.\nBal: ₦{format_amount(new_balance)}"
        else:
            return "Invalid PIN. Transfer failed."


def transfer_recipient_prompt(choice):
    mapping = {
        "1": "Enter recipient account number:",
        "2": "Enter recipient phone number:",
        "3": "Enter internal account number:"
    }
    return mapping.get(choice, "Enter recipient:")


# ===================================
# 4. Airtime & Data
# ===================================
def airtime_main_menu(phone_number):
    create_or_update_session(phone_number, None, "airtime_service")
    return "Buy:\n1. Airtime\n2. Data"


def handle_airtime_flow(text, phone_number, step_data):
    # Simplified version
    if step_data.get("current") == "airtime_service":
        if text == "1":
            step_data["service"] = "airtime"
            step_data["current"] = "airtime_number"
            create_or_update_session(phone_number, None, "airtime_number", step_data)
            return "Enter number (or 1 for self):"
        else:
            return "END Data purchase not implemented yet."
    elif step_data.get("current") == "airtime_number":
        number = phone_number if text == "1" else text
        if not validate_nigerian_phone(number):
            return "Invalid number. Try again."
        step_data["number"] = number
        step_data["current"] = "airtime_amount"
        create_or_update_session(phone_number, None, "airtime_amount", step_data)
        return "Enter amount (₦100–₦5000):"
    elif step_data.get("current") == "airtime_amount":
        try:
            amt = float(text)
            if not 100 <= amt <= 5000:
                return "Amount must be between ₦100 and ₦5000."
            user = users_collection.find_one({"phoneNumber": phone_number})
            if amt > get_balance(user["accountNumber"]):
                return "Insufficient funds."
            # Simulate success
            new_bal = get_balance(user["accountNumber"]) - amt - 10  # incl fee
            users_collection.update_one(
                {"phoneNumber": phone_number},
                {"$set": {"balance": new_bal}}
            )
            log_transaction(user["accountNumber"], "debit", "airtime", amt, f"To {step_data['number']}", charges=10)
            end_session(phone_number)
            return f"END ₦{int(amt)} airtime sent to {step_data['number']}. New bal: ₦{format_amount(new_bal)}"
        except:
            return "Invalid amount."
    return "END Operation failed."


# ===================================
# 5. Transaction History
# ===================================
def request_pin_for_history(phone_number):
    user = users_collection.find_one({"phoneNumber": phone_number})
    if not user:
        return "END Account not found."
    create_or_update_session(phone_number, None, "pin_auth_history")
    return "Enter PIN to view history:\n1. Last 5 txns\n2. Last 10 txns"

def handle_transaction_history(text, phone_number, period_hint=None):
    user = users_collection.find_one({"phoneNumber": phone_number})
    if hash_pin(text.strip()) != user["pin"]:
        return "Invalid PIN."
    
    # Fetch last 5 for demo
    txns = list(transactions_collection.find(
        {"accountNumber": user["accountNumber"]}
    ).sort("createdAt", -1).limit(5))

    if not txns:
        msg = "No transactions yet."
    else:
        msg = "\n".join([
            f"{t['createdAt'].strftime('%d/%m %H:%M')} ₦{format_amount(t['amount'])} {t['category'].title()}"
            for t in txns
        ])
    
    end_session(phone_number)
    return f"END Recent Transactions:\n{msg}"


# ===================================
# 6. Change PIN
# ===================================
def change_pin_start(phone_number):
    create_or_update_session(phone_number, None, "change_pin_current")
    return "Enter current PIN:"

def handle_change_pin(text, phone_number, step_data):
    user = users_collection.find_one({"phoneNumber": phone_number})
    if "current_pin" not in step_data:
        if hash_pin(text) != user["pin"]:
            return "Wrong PIN. Try again."
        step_data["current_pin"] = text
        create_or_update_session(phone_number, None, "change_pin_new", step_data)
        return "Enter new 4-digit PIN:"
    elif "new_pin" not in step_data:
        if not (text.isdigit() and len(text) == 4):
            return "PIN must be 4 digits."
        step_data["new_pin"] = text
        create_or_update_session(phone_number, None, "change_pin_confirm", step_data)
        return "Confirm new PIN:"
    else:
        if text == step_data["new_pin"]:
            users_collection.update_one(
                {"phoneNumber": phone_number},
                {"$set": {"pin": hash_pin(text), "updatedAt": datetime.now()}}
            )
            end_session(phone_number)
            return "END PIN changed successfully!"
        else:
            return "PINs do not match. Try again."


# ===================================
# 7. Help Menu
# ===================================
def help_menu(phone_number):
    create_or_update_session(phone_number, None, "help_menu")
    return (
        "Help:\n"
        "1. Account Info\n"
        "2. Charges\n"
        "3. Branch Locator\n"
        "4. Contact Support\n"
        "5. FAQ\n"
        "6. Block Account"
    )

def handle_help_menu(text, phone_number):
    options = {
        '1': "END Full name, phone, balance.",
        '4': "END Call 0700-CALL-BANK or email help@quickbank.ng",
        '6': "END To block account, visit branch or call support."
    }
    return options.get(text, "END Feature under development.")


# ================================
# Run Server
# ================================
if __name__ == '__main__':
    app.run(debug=True, port=5000)