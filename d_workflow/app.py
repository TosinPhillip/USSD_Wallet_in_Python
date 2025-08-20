from flask import Flask, request, jsonify
from flask_pymongo import PyMongo
from models import User, Transaction, Session, mongo
from services import AccountService, TransactionService, AirtimeService
from validators import Validators
from config import Config
from datetime import datetime, timedelta
import re
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config.from_object(Config)
mongo.init_app(app)

@app.route('/ussd', methods=['POST'])
def ussd_handler():
    # Get request data
    data = request.get_json()
    phone = data.get('phoneNumber')
    session_id = data.get('sessionId')
    text = data.get('text', '')
    
    # Clean the input text
    text = text.strip()
    inputs = text.split('*')
    current_input = inputs[-1] if inputs else ''
    
    # Check for new session
    if text == '':
        # New session - show main menu
        session = Session.create(phone)
        response = "CON Welcome to USSD Wallet\n1. Create Account\n2. Check Balance\n3. Transfer Money\n4. Airtime & Data\n5. Transaction History\n6. Change PIN\n7. Enquiry/Help"
        return format_response(response)
    
    # Get existing session
    session = Session.find(session_id)
    if not session or not session['isActive']:
        return format_response("END Session expired. Please dial " + Config.USSD_CODE + " to start again.")
    
    # Update session activity
    Session.update(session_id, {'lastActivity': datetime.utcnow()})
    
    # Route based on current step
    if session['currentStep'] == 'main_menu':
        return handle_main_menu(phone, session, current_input)
    elif session['currentStep'].startswith('account_creation'):
        return handle_account_creation(phone, session, current_input, inputs)
    elif session['currentStep'].startswith('balance_inquiry'):
        return handle_balance_inquiry(phone, session, current_input)
    elif session['currentStep'].startswith('money_transfer'):
        return handle_money_transfer(phone, session, current_input, inputs)
    elif session['currentStep'].startswith('airtime_purchase'):
        return handle_airtime_purchase(phone, session, current_input, inputs)
    elif session['currentStep'].startswith('transaction_history'):
        return handle_transaction_history(phone, session, current_input)
    elif session['currentStep'].startswith('change_pin'):
        return handle_change_pin(phone, session, current_input, inputs)
    elif session['currentStep'].startswith('enquiry_help'):
        return handle_enquiry_help(phone, session, current_input)
    else:
        return format_response("END Invalid option. Please dial " + Config.USSD_CODE + " to start again.")

def handle_main_menu(phone, session, current_input):
    try:
        option = int(current_input)
    except ValueError:
        Session.deactivate(session['sessionId'])
        return format_response("END Invalid option. Please dial " + Config.USSD_CODE + " to start again.")
    
    if option == 1:
        # Account creation
        Session.update(session['sessionId'], {
            'currentStep': 'account_creation_1',
            'stepData': {'step': 1}
        })
        return format_response("CON Enter First Name")
    elif option == 2:
        # Balance inquiry
        user = User.find_by_phone(phone)
        if not user:
            Session.deactivate(session['sessionId'])
            return format_response("END Account not found. Please create an account first.")
        
        Session.update(session['sessionId'], {
            'currentStep': 'balance_inquiry_pin',
            'stepData': {'attempts': 0}
        })
        return format_response("CON Enter your 4-digit PIN")
    elif option == 3:
        # Money transfer
        user = User.find_by_phone(phone)
        if not user:
            Session.deactivate(session['sessionId'])
            return format_response("END Account not found. Please create an account first.")
        
        Session.update(session['sessionId'], {
            'currentStep': 'money_transfer_type',
            'stepData': {}
        })
        return format_response("CON Select transfer type:\n1. To Bank Account\n2. To Phone Number\n3. To Same Bank")
    elif option == 4:
        # Airtime & Data
        Session.update(session['sessionId'], {
            'currentStep': 'airtime_purchase_menu',
            'stepData': {}
        })
        return format_response("CON Airtime & Data:\n1. Buy Airtime\n2. Buy Data")
    elif option == 5:
        # Transaction history
        user = User.find_by_phone(phone)
        if not user:
            Session.deactivate(session['sessionId'])
            return format_response("END Account not found. Please create an account first.")
        
        Session.update(session['sessionId'], {
            'currentStep': 'transaction_history_pin',
            'stepData': {'attempts': 0}
        })
        return format_response("CON Enter your 4-digit PIN")
    elif option == 6:
        # Change PIN
        user = User.find_by_phone(phone)
        if not user:
            Session.deactivate(session['sessionId'])
            return format_response("END Account not found. Please create an account first.")
        
        Session.update(session['sessionId'], {
            'currentStep': 'change_pin_current',
            'stepData': {'attempts': 0}
        })
        return format_response("CON Enter your current 4-digit PIN")
    elif option == 7:
        # Enquiry/Help
        Session.update(session['sessionId'], {
            'currentStep': 'enquiry_help_menu',
            'stepData': {}
        })
        return format_response("CON Enquiry/Help:\n1. Account Information\n2. Service Charges\n3. Branch Locator\n4. Contact Support\n5. FAQ\n6. Block Account")
    else:
        Session.deactivate(session['sessionId'])
        return format_response("END Invalid option. Please dial " + Config.USSD_CODE + " to start again.")

def handle_account_creation(phone, session, current_input, inputs):
    step = session['stepData']['step']
    
    if step == 1:
        # First name
        if not current_input:
            return format_response("CON First name cannot be empty. Enter First Name")
        
        Session.update(session['sessionId'], {
            'stepData': {
                'step': 2,
                'firstName': current_input
            }
        })
        return format_response("CON Enter Last Name")
    
    elif step == 2:
        # Last name
        if not current_input:
            return format_response("CON Last name cannot be empty. Enter Last Name")
        
        Session.update(session['sessionId'], {
            'stepData': {
                'step': 3,
                'lastName': current_input,
                **session['stepData']
            }
        })
        return format_response("CON Enter Phone Number")
    
    elif step == 3:
        # Phone number validation
        if not Validators.validate_phone(current_input):
            return format_response("CON Invalid phone number. Format: 08012345678. Enter Phone Number")
        
        if User.find_by_phone(current_input):
            return format_response("CON Phone number already registered. Enter a different Phone Number")
        
        Session.update(session['sessionId'], {
            'stepData': {
                'step': 4,
                'phoneNumber': current_input,
                **session['stepData']
            }
        })
        return format_response("CON Enter Date of Birth (DD/MM/YYYY)")
    
    elif step == 4:
        # Date of birth
        if not Validators.validate_date(current_input):
            return format_response("CON Invalid date format. Use DD/MM/YYYY. Enter Date of Birth")
        
        Session.update(session['sessionId'], {
            'stepData': {
                'step': 5,
                'dateOfBirth': current_input,
                **session['stepData']
            }
        })
        return format_response("CON Select Gender:\n1. Male\n2. Female")
    
    elif step == 5:
        # Gender
        try:
            gender_option = int(current_input)
            if gender_option not in [1, 2]:
                raise ValueError
        except ValueError:
            return format_response("CON Invalid option. Select Gender:\n1. Male\n2. Female")
        
        gender = 'male' if gender_option == 1 else 'female'
        Session.update(session['sessionId'], {
            'stepData': {
                'step': 6,
                'gender': gender,
                **session['stepData']
            }
        })
        return format_response("CON Enter BVN (Bank Verification Number)")
    
    elif step == 6:
        # BVN
        if not Validators.validate_bvn(current_input):
            return format_response("CON Invalid BVN. Must be 11 digits. Enter BVN")
        
        Session.update(session['sessionId'], {
            'stepData': {
                'step': 7,
                'bvn': current_input,
                **session['stepData']
            }
        })
        return format_response("CON Create 4-digit PIN")
    
    elif step == 7:
        # PIN creation
        if not Validators.validate_pin(current_input):
            return format_response("CON PIN must be 4 digits and not sequential or repetitive. Create 4-digit PIN")
        
        Session.update(session['sessionId'], {
            'stepData': {
                'step': 8,
                'pin': current_input,
                **session['stepData']
            }
        })
        return format_response("CON Confirm 4-digit PIN")
    
    elif step == 8:
        # PIN confirmation
        if current_input != session['stepData']['pin']:
            return format_response("CON PINs do not match. Create 4-digit PIN")
        
        Session.update(session['sessionId'], {
            'stepData': {
                'step': 9,
                **session['stepData']
            }
        })
        return format_response("CON Select Security Question:\n1. Mother's maiden name\n2. City of birth\n3. Favorite teacher's name")
    
    elif step == 9:
        # Security question
        try:
            question_option = int(current_input)
            if question_option not in [1, 2, 3]:
                raise ValueError
        except ValueError:
            return format_response("CON Invalid option. Select Security Question:\n1. Mother's maiden name\n2. City of birth\n3. Favorite teacher's name")
        
        questions = {
            1: "Mother's maiden name",
            2: "City of birth",
            3: "Favorite teacher's name"
        }
        
        Session.update(session['sessionId'], {
            'stepData': {
                'step': 10,
                'securityQuestion': questions[question_option],
                **session['stepData']
            }
        })
        return format_response("CON Enter Security Answer")
    
    elif step == 10:
        # Security answer
        if not current_input:
            return format_response("CON Security answer cannot be empty. Enter Security Answer")
        
        Session.update(session['sessionId'], {
            'stepData': {
                'step': 11,
                'securityAnswer': current_input,
                **session['stepData']
            }
        })
        return format_response("CON Enter Next of Kin Name")
    
    elif step == 11:
        # Next of kin name
        if not current_input:
            return format_response("CON Next of kin name cannot be empty. Enter Next of Kin Name")
        
        Session.update(session['sessionId'], {
            'stepData': {
                'step': 12,
                'nextOfKinName': current_input,
                **session['stepData']
            }
        })
        return format_response("CON Enter Next of Kin Phone Number")
    
    elif step == 12:
        # Next of kin phone
        if not Validators.validate_phone(current_input):
            return format_response("CON Invalid phone number. Format: 08012345678. Enter Next of Kin Phone Number")
        
        Session.update(session['sessionId'], {
            'stepData': {
                'step': 13,
                'nextOfKinPhone': current_input,
                **session['stepData']
            }
        })
        
        # Prepare summary
        data = session['stepData']
        summary = (
            f"First Name: {data['firstName']}\n"
            f"Last Name: {data['lastName']}\n"
            f"Phone: {data['phoneNumber']}\n"
            f"DOB: {data['dateOfBirth']}\n"
            f"Gender: {data['gender']}\n"
            f"BVN: {data['bvn']}\n"
            f"Next of Kin: {data['nextOfKinName']} ({data['nextOfKinPhone']})\n\n"
            "1. Confirm\n2. Cancel"
        )
        
        return format_response("CON Review details:\n" + summary)
    
    elif step == 13:
        # Confirmation
        try:
            confirm_option = int(current_input)
            if confirm_option not in [1, 2]:
                raise ValueError
        except ValueError:
            data = session['stepData']
            summary = (
                f"First Name: {data['firstName']}\n"
                f"Last Name: {data['lastName']}\n"
                f"Phone: {data['phoneNumber']}\n"
                f"DOB: {data['dateOfBirth']}\n"
                f"Gender: {data['gender']}\n"
                f"BVN: {data['bvn']}\n"
                f"Next of Kin: {data['nextOfKinName']} ({data['nextOfKinPhone']})\n\n"
                "1. Confirm\n2. Cancel"
            )
            return format_response("CON Invalid option. Review details:\n" + summary)
        
        if confirm_option == 2:
            Session.deactivate(session['sessionId'])
            return format_response("END Account creation cancelled")
        
        # Create the account
        data = session['stepData']
        account_data = {
            'firstName': data['firstName'],
            'lastName': data['lastName'],
            'phoneNumber': data['phoneNumber'],
            'dateOfBirth': data['dateOfBirth'],
            'gender': data['gender'],
            'bvn': data['bvn'],
            'pin': data['pin'],
            'securityQuestion': data['securityQuestion'],
            'securityAnswer': data['securityAnswer'],
            'nextOfKin': {
                'name': data['nextOfKinName'],
                'phoneNumber': data['nextOfKinPhone']
            }
        }
        
        account_id, message = AccountService.create_account(account_data)
        Session.deactivate(session['sessionId'])
        
        if account_id:
            user = User.find_by_phone(data['phoneNumber'])
            return format_response(f"END Account created successfully. Your account number is {user['accountNumber']}. {message}")
        else:
            return format_response(f"END Account creation failed. {message}")

def handle_balance_inquiry(phone, session, current_input):
    if session['currentStep'] == 'balance_inquiry_pin':
        user = User.find_by_phone(phone)
        attempts = session['stepData']['attempts']
        
        if not User.verify_pin(user, current_input):
            attempts += 1
            remaining = Config.MAX_PIN_ATTEMPTS - attempts
            
            if remaining > 0:
                Session.update(session['sessionId'], {
                    'stepData': {'attempts': attempts}
                })
                return format_response(f"CON Invalid PIN. {remaining} attempts remaining. Enter your 4-digit PIN")
            else:
                # Lock account
                User.update(user['_id'], {
                    'accountStatus': 'locked',
                    'failedLoginAttempts': attempts
                })
                Session.deactivate(session['sessionId'])
                return format_response("END Account locked due to too many failed attempts. Contact support.")
        
        # PIN is correct
        balance, error = TransactionService.check_balance(user['accountNumber'], current_input)
        if error:
            Session.deactivate(session['sessionId'])
            return format_response(f"END {error}")
        
        Session.deactivate(session['sessionId'])
        return format_response(f"END Your balance is N{balance:,.2f}. Thank you.")

def handle_money_transfer(phone, session, current_input, inputs):
    user = User.find_by_phone(phone)
    
    if session['currentStep'] == 'money_transfer_type':
        try:
            option = int(current_input)
            if option not in [1, 2, 3]:
                raise ValueError
        except ValueError:
            return format_response("CON Invalid option. Select transfer type:\n1. To Bank Account\n2. To Phone Number\n3. To Same Bank")
        
        Session.update(session['sessionId'], {
            'currentStep': f'money_transfer_recipient_{option}',
            'stepData': {'type': option}
        })
        
        if option == 1:
            return format_response("CON Enter recipient account number")
        elif option == 2:
            return format_response("CON Enter recipient phone number")
        else:
            return format_response("CON Enter recipient account number")
    
    elif session['currentStep'].startswith('money_transfer_recipient_'):
        transfer_type = session['stepData']['type']
        recipient = current_input
        
        # Validate recipient based on type
        if transfer_type == 1 or transfer_type == 3:
            # Bank account - simple validation for demo
            if not recipient.isdigit() or len(recipient) != 10:
                return format_response("CON Invalid account number. Must be 10 digits. Enter recipient account number")
            
            # For demo, we'll assume any 10-digit number is valid
            recipient_name = "Recipient Name"  # In real app, we'd look this up
            
        elif transfer_type == 2:
            # Phone number
            if not Validators.validate_phone(recipient):
                return format_response("CON Invalid phone number. Format: 08012345678. Enter recipient phone number")
            
            recipient_user = User.find_by_phone(recipient)
            if not recipient_user:
                return format_response("CON Recipient not registered. Enter a different phone number")
            
            recipient_name = f"{recipient_user['firstName']} {recipient_user['lastName']}"
            recipient = recipient_user['accountNumber']
        else:
            Session.deactivate(session['sessionId'])
            return format_response("END Invalid transfer type")
        
        Session.update(session['sessionId'], {
            'currentStep': 'money_transfer_amount',
            'stepData': {
                'type': transfer_type,
                'recipient': recipient,
                'recipientName': recipient_name
            }
        })
        return format_response("CON Enter amount to transfer")
    
    elif session['currentStep'] == 'money_transfer_amount':
        if not Validators.validate_amount(current_input):
            return format_response("CON Invalid amount. Enter amount to transfer")
        
        amount = float(current_input)
        
        Session.update(session['sessionId'], {
            'currentStep': 'money_transfer_confirm',
            'stepData': {
                **session['stepData'],
                'amount': amount
            }
        })
        
        summary = (
            f"Transfer to: {session['stepData']['recipientName']}\n"
            f"Account: {session['stepData']['recipient']}\n"
            f"Amount: N{amount:,.2f}\n\n"
            "1. Confirm\n2. Cancel"
        )
        return format_response("CON Confirm transfer:\n" + summary)
    
    elif session['currentStep'] == 'money_transfer_confirm':
        try:
            option = int(current_input)
            if option not in [1, 2]:
                raise ValueError
        except ValueError:
            summary = (
                f"Transfer to: {session['stepData']['recipientName']}\n"
                f"Account: {session['stepData']['recipient']}\n"
                f"Amount: N{session['stepData']['amount']:,.2f}\n\n"
                "1. Confirm\n2. Cancel"
            )
            return format_response("CON Invalid option. Confirm transfer:\n" + summary)
        
        if option == 2:
            Session.deactivate(session['sessionId'])
            return format_response("END Transfer cancelled")
        
        # Proceed with transfer
        data = session['stepData']
        success, message = TransactionService.transfer_funds(
            user['accountNumber'],
            data['recipient'],
            data['amount'],
            '',  # PIN will be collected next
            "USSD Transfer"
        )
        
        if not success:
            Session.deactivate(session['sessionId'])
            return format_response(f"END Transfer failed. {message}")
        
        Session.update(session['sessionId'], {
            'currentStep': 'money_transfer_pin',
            'stepData': {
                **session['stepData'],
                'reference': message.split(':')[-1].strip(),
                'attempts': 0
            }
        })
        return format_response("CON Enter your PIN to authorize transfer")
    
    elif session['currentStep'] == 'money_transfer_pin':
        attempts = session['stepData']['attempts']
        
        if not User.verify_pin(user, current_input):
            attempts += 1
            remaining = Config.MAX_PIN_ATTEMPTS - attempts
            
            if remaining > 0:
                Session.update(session['sessionId'], {
                    'stepData': {
                        **session['stepData'],
                        'attempts': attempts
                    }
                })
                return format_response(f"CON Invalid PIN. {remaining} attempts remaining. Enter your 4-digit PIN")
            else:
                # Lock account
                User.update(user['_id'], {
                    'accountStatus': 'locked',
                    'failedLoginAttempts': attempts
                })
                Session.deactivate(session['sessionId'])
                return format_response("END Account locked due to too many failed attempts. Contact support.")
        
        # PIN is correct - complete the transfer
        data = session['stepData']
        success, message = TransactionService.transfer_funds(
            user['accountNumber'],
            data['recipient'],
            data['amount'],
            current_input,
            "USSD Transfer"
        )
        
        Session.deactivate(session['sessionId'])
        
        if success:
            return format_response(f"END Transfer successful. {message}")
        else:
            return format_response(f"END Transfer failed. {message}")

def handle_airtime_purchase(phone, session, current_input, inputs):
    user = User.find_by_phone(phone)
    
    if session['currentStep'] == 'airtime_purchase_menu':
        try:
            option = int(current_input)
            if option not in [1, 2]:
                raise ValueError
        except ValueError:
            return format_response("CON Invalid option. Airtime & Data:\n1. Buy Airtime\n2. Buy Data")
        
        # For this demo, we'll just implement airtime purchase
        if option == 2:
            Session.deactivate(session['sessionId'])
            return format_response("END Data purchase coming soon")
        
        Session.update(session['sessionId'], {
            'currentStep': 'airtime_purchase_type',
            'stepData': {'product': 'airtime'}
        })
        return format_response("CON Buy Airtime:\n1. For My Number\n2. For Another Number")
    
    elif session['currentStep'] == 'airtime_purchase_type':
        try:
            option = int(current_input)
            if option not in [1, 2]:
                raise ValueError
        except ValueError:
            return format_response("CON Invalid option. Buy Airtime:\n1. For My Number\n2. For Another Number")
        
        if option == 1:
            # For my number
            Session.update(session['sessionId'], {
                'currentStep': 'airtime_purchase_amount',
                'stepData': {
                    **session['stepData'],
                    'recipient': user['phoneNumber'],
                    'for_self': True
                }
            })
            return format_response("CON Enter amount")
        else:
            # For another number
            Session.update(session['sessionId'], {
                'currentStep': 'airtime_purchase_recipient',
                'stepData': {
                    **session['stepData'],
                    'for_self': False
                }
            })
            return format_response("CON Enter recipient phone number")
    
    elif session['currentStep'] == 'airtime_purchase_recipient':
        if not Validators.validate_phone(current_input):
            return format_response("CON Invalid phone number. Format: 08012345678. Enter recipient phone number")
        
        Session.update(session['sessionId'], {
            'currentStep': 'airtime_purchase_amount',
            'stepData': {
                **session['stepData'],
                'recipient': current_input
            }
        })
        return format_response("CON Enter amount")
    
    elif session['currentStep'] == 'airtime_purchase_amount':
        if not Validators.validate_amount(current_input):
            return format_response("CON Invalid amount. Enter amount")
        
        amount = float(current_input)
        
        Session.update(session['sessionId'], {
            'currentStep': 'airtime_purchase_confirm',
            'stepData': {
                **session['stepData'],
                'amount': amount
            }
        })
        
        summary = (
            f"Recipient: {session['stepData']['recipient']}\n"
            f"Amount: N{amount:,.2f}\n\n"
            "1. Confirm\n2. Cancel"
        )
        return format_response("CON Confirm airtime purchase:\n" + summary)
    
    elif session['currentStep'] == 'airtime_purchase_confirm':
        try:
            option = int(current_input)
            if option not in [1, 2]:
                raise ValueError
        except ValueError:
            summary = (
                f"Recipient: {session['stepData']['recipient']}\n"
                f"Amount: N{session['stepData']['amount']:,.2f}\n\n"
                "1. Confirm\n2. Cancel"
            )
            return format_response("CON Invalid option. Confirm airtime purchase:\n" + summary)
        
        if option == 2:
            Session.deactivate(session['sessionId'])
            return format_response("END Airtime purchase cancelled")
        
        # Proceed with purchase
        data = session['stepData']
        success, message = AirtimeService.buy_airtime(
            user['accountNumber'],
            data['recipient'],
            data['amount'],
            '',  # PIN will be collected next
            data['for_self']
        )
        
        if not success:
            Session.deactivate(session['sessionId'])
            return format_response(f"END Airtime purchase failed. {message}")
        
        Session.update(session['sessionId'], {
            'currentStep': 'airtime_purchase_pin',
            'stepData': {
                **session['stepData'],
                'reference': message.split(':')[-1].strip(),
                'attempts': 0
            }
        })
        return format_response("CON Enter your PIN to authorize purchase")
    
    elif session['currentStep'] == 'airtime_purchase_pin':
        attempts = session['stepData']['attempts']
        
        if not User.verify_pin(user, current_input):
            attempts += 1
            remaining = Config.MAX_PIN_ATTEMPTS - attempts
            
            if remaining > 0:
                Session.update(session['sessionId'], {
                    'stepData': {
                        **session['stepData'],
                        'attempts': attempts
                    }
                })
                return format_response(f"CON Invalid PIN. {remaining} attempts remaining. Enter your 4-digit PIN")
            else:
                # Lock account
                User.update(user['_id'], {
                    'accountStatus': 'locked',
                    'failedLoginAttempts': attempts
                })
                Session.deactivate(session['sessionId'])
                return format_response("END Account locked due to too many failed attempts. Contact support.")
        
        # PIN is correct - complete the purchase
        data = session['stepData']
        success, message = AirtimeService.buy_airtime(
            user['accountNumber'],
            data['recipient'],
            data['amount'],
            current_input,
            data['for_self']
        )
        
        Session.deactivate(session['sessionId'])
        
        if success:
            return format_response(f"END {message}")
        else:
            return format_response(f"END Airtime purchase failed. {message}")

def handle_transaction_history(phone, session, current_input):
    user = User.find_by_phone(phone)
    
    if session['currentStep'] == 'transaction_history_pin':
        attempts = session['stepData']['attempts']
        
        if not User.verify_pin(user, current_input):
            attempts += 1
            remaining = Config.MAX_PIN_ATTEMPTS - attempts
            
            if remaining > 0:
                Session.update(session['sessionId'], {
                    'stepData': {'attempts': attempts}
                })
                return format_response(f"CON Invalid PIN. {remaining} attempts remaining. Enter your 4-digit PIN")
            else:
                # Lock account
                User.update(user['_id'], {
                    'accountStatus': 'locked',
                    'failedLoginAttempts': attempts
                })
                Session.deactivate(session['sessionId'])
                return format_response("END Account locked due to too many failed attempts. Contact support.")
        
        # PIN is correct
        Session.update(session['sessionId'], {
            'currentStep': 'transaction_history_period',
            'stepData': {}
        })
        return format_response("CON Select period:\n1. Last 5 transactions\n2. Last 10 transactions\n3. This week\n4. This month")
    
    elif session['currentStep'] == 'transaction_history_period':
        try:
            option = int(current_input)
            if option not in [1, 2, 3, 4]:
                raise ValueError
        except ValueError:
            return format_response("CON Invalid option. Select period:\n1. Last 5 transactions\n2. Last 10 transactions\n3. This week\n4. This month")
        
        limit = 5 if option == 1 else 10
        transactions = Transaction.get_transactions(user['accountNumber'], limit)
        
        if not transactions:
            Session.deactivate(session['sessionId'])
            return format_response("END No transactions found")
        
        response = "END Your transactions:\n"
        for tx in transactions:
            date = tx['createdAt'].strftime('%d/%m %H:%M')
            type_ = "CR" if tx['transactionType'] == 'credit' else "DR"
            response += f"{date} {type_} N{tx['amount']:,.2f} - {tx.get('description', '')}\n"
        
        Session.deactivate(session['sessionId'])
        return format_response(response)

def handle_change_pin(phone, session, current_input, inputs):
    user = User.find_by_phone(phone)
    
    if session['currentStep'] == 'change_pin_current':
        attempts = session['stepData']['attempts']
        
        if not User.verify_pin(user, current_input):
            attempts += 1
            remaining = Config.MAX_PIN_ATTEMPTS - attempts
            
            if remaining > 0:
                Session.update(session['sessionId'], {
                    'stepData': {'attempts': attempts}
                })
                return format_response(f"CON Invalid PIN. {remaining} attempts remaining. Enter your current 4-digit PIN")
            else:
                # Lock account
                User.update(user['_id'], {
                    'accountStatus': 'locked',
                    'failedLoginAttempts': attempts
                })
                Session.deactivate(session['sessionId'])
                return format_response("END Account locked due to too many failed attempts. Contact support.")
        
        # Current PIN is correct
        Session.update(session['sessionId'], {
            'currentStep': 'change_pin_new',
            'stepData': {'currentPin': current_input}
        })
        return format_response("CON Enter new 4-digit PIN")
    
    elif session['currentStep'] == 'change_pin_new':
        if not Validators.validate_pin(current_input):
            return format_response("CON PIN must be 4 digits and not sequential or repetitive. Enter new 4-digit PIN")
        
        if current_input == session['stepData']['currentPin']:
            return format_response("CON New PIN cannot be same as current PIN. Enter new 4-digit PIN")
        
        Session.update(session['sessionId'], {
            'currentStep': 'change_pin_confirm',
            'stepData': {
                **session['stepData'],
                'newPin': current_input
            }
        })
        return format_response("CON Confirm new 4-digit PIN")
    
    elif session['currentStep'] == 'change_pin_confirm':
        if current_input != session['stepData']['newPin']:
            Session.update(session['sessionId'], {
                'currentStep': 'change_pin_new',
                'stepData': {
                    'currentPin': session['stepData']['currentPin']
                }
            })
            return format_response("CON PINs do not match. Enter new 4-digit PIN")
        
        # Update PIN
        User.update(user['_id'], {
            'pin': generate_password_hash(current_input),
            'updatedAt': datetime.utcnow()
        })
        
        Session.deactivate(session['sessionId'])
        return format_response("END PIN changed successfully")

def handle_enquiry_help(phone, session, current_input):
    if session['currentStep'] == 'enquiry_help_menu':
        try:
            option = int(current_input)
            if option not in range(1, 7):
                raise ValueError
        except ValueError:
            return format_response("CON Invalid option. Enquiry/Help:\n1. Account Information\n2. Service Charges\n3. Branch Locator\n4. Contact Support\n5. FAQ\n6. Block Account")
        
        if option == 1:
            user = User.find_by_phone(phone)
            if not user:
                Session.deactivate(session['sessionId'])
                return format_response("END Account not found")
            
            response = (
                f"Account Number: {user['accountNumber']}\n"
                f"Name: {user['firstName']} {user['lastName']}\n"
                f"Tier: {user['accountTier']}\n"
                f"Status: {user['accountStatus']}\n"
                f"Balance: N{user['balance']:,.2f}"
            )
            Session.deactivate(session['sessionId'])
            return format_response(f"END {response}")
        
        elif option == 2:
            charges = (
                "Service Charges:\n"
                "USSD Fee: N6.98 per transaction\n"
                "Transfer Fees:\n"
                " - Same Bank: Free\n"
                " - Other Banks: N50\n"
                "Airtime Purchase: 1% (min N10)"
            )
            Session.deactivate(session['sessionId'])
            return format_response(f"END {charges}")
        
        elif option == 6:
            user = User.find_by_phone(phone)
            if not user:
                Session.deactivate(session['sessionId'])
                return format_response("END Account not found")
            
            Session.update(session['sessionId'], {
                'currentStep': 'block_account_confirm',
                'stepData': {}
            })
            return format_response("CON Are you sure you want to block your account?\n1. Yes\n2. No")
    
    elif session['currentStep'] == 'block_account_confirm':
        try:
            option = int(current_input)
            if option not in [1, 2]:
                raise ValueError
        except ValueError:
            return format_response("CON Invalid option. Are you sure you want to block your account?\n1. Yes\n2. No")
        
        if option == 2:
            Session.deactivate(session['sessionId'])
            return format_response("END Account block cancelled")
        
        # Block the account
        user = User.find_by_phone(phone)
        User.update(user['_id'], {
            'accountStatus': 'blocked',
            'updatedAt': datetime.utcnow()
        })
        
        Session.deactivate(session['sessionId'])
        return format_response("END Your account has been blocked. Contact support to unblock.")

def format_response(message):
    return jsonify({
        'response': message
    })

if __name__ == '__main__':
    app.run(debug=True)