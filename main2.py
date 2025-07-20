import os
import re
import logging
import hashlib
import secrets
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Dict, Optional, Tuple, Any
from functools import wraps
from dotenv import load_dotenv

from flask import Flask, request, jsonify, Response
from pymongo import MongoClient, DESCENDING
from pymongo.errors import PyMongoError, DuplicateKeyError
import africastalking

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('ussd_wallet.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', secrets.token_urlsafe(32))

# Configuration from environment variables
MONGODB_URI = os.environ.get('MONGO_URI', 'mongodb://localhost:27017/')
DATABASE_NAME = os.environ.get('DATABASE_NAME', 'ussd_wallet')
AFRICASTALKING_USERNAME = os.environ.get('AFRICASTALKING_USERNAME', 'sandbox')
AFRICASTALKING_API_KEY = os.environ.get('AFRICASTALKING_API_KEY', 'your_api_key_here')
AFRICASTALKING_SHORTCODE = os.environ.get('AFRICASTALKING_SHORTCODE', '428')

# Transaction limits
MIN_TRANSACTION_AMOUNT = Decimal('1.00')
MAX_TRANSACTION_AMOUNT = Decimal('100000.00')
DAILY_TRANSACTION_LIMIT = Decimal('200000.00')

# Session timeout (in minutes)
SESSION_TIMEOUT = 10

# Initialize Africa's Talking
try:
    africastalking.initialize(AFRICASTALKING_USERNAME, AFRICASTALKING_API_KEY)
    sms = africastalking.SMS
    logger.info("Africa's Talking initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize Africa's Talking: {e}")
    sms = None

# Initialize MongoDB
try:
    client = MongoClient(MONGODB_URI)
    db = client[DATABASE_NAME]
    
    # Create collections with indexes
    users_collection = db.users
    transactions_collection = db.transactions
    sessions_collection = db.sessions
    
    # Create indexes
    users_collection.create_index("phone_number", unique=True)
    users_collection.create_index("created_at")
    
    transactions_collection.create_index([("user_id", 1), ("created_at", -1)])
    transactions_collection.create_index("transaction_id", unique=True)
    transactions_collection.create_index("created_at")
    
    sessions_collection.create_index("session_id", unique=True)
    sessions_collection.create_index("expires_at", expireAfterSeconds=0)
    
    logger.info("MongoDB connected and indexes created successfully")
    
except PyMongoError as e:
    logger.error(f"MongoDB connection failed: {e}")
    raise

class USSDSession:
    """Manages USSD session state"""
    
    @staticmethod
    def create_session(session_id: str, phone_number: str, data: Dict = None) -> bool:
        """Create a new session"""
        try:
            session_data = {
                'session_id': session_id,
                'phone_number': phone_number,
                'data': data or {},
                'created_at': datetime.utcnow(),
                'expires_at': datetime.utcnow() + timedelta(minutes=SESSION_TIMEOUT),
                'step': 'main_menu'
            }
            sessions_collection.insert_one(session_data)
            return True
        except Exception as e:
            logger.error(f"Failed to create session: {e}")
            return False
    
    @staticmethod
    def get_session(session_id: str) -> Optional[Dict]:
        """Get session data"""
        try:
            return sessions_collection.find_one({'session_id': session_id})
        except Exception as e:
            logger.error(f"Failed to get session: {e}")
            return None
    
    @staticmethod
    def update_session(session_id: str, data: Dict, step: str = None) -> bool:
        """Update session data"""
        try:
            update_data = {
                'data': data,
                'expires_at': datetime.utcnow() + timedelta(minutes=SESSION_TIMEOUT)
            }
            if step:
                update_data['step'] = step
                
            result = sessions_collection.update_one(
                {'session_id': session_id},
                {'$set': update_data}
            )
            return result.modified_count > 0
        except Exception as e:
            logger.error(f"Failed to update session: {e}")
            return False
    
    @staticmethod
    def delete_session(session_id: str) -> bool:
        """Delete session"""
        try:
            result = sessions_collection.delete_one({'session_id': session_id})
            return result.deleted_count > 0
        except Exception as e:
            logger.error(f"Failed to delete session: {e}")
            return False

class WalletManager:
    """Handles wallet operations"""
    
    @staticmethod
    def hash_pin(pin: str) -> str:
        """Hash PIN using SHA-256"""
        return hashlib.sha256(pin.encode()).hexdigest()
    
    @staticmethod
    def validate_phone_number(phone_number: str) -> bool:
        """Validate phone number format"""
        # Remove any non-digit characters
        clean_phone = re.sub(r'[^\d]', '', phone_number)
        
        # Check if it's a valid Kenyan/African number format
        if clean_phone.startswith('0') and len(clean_phone) == 10:
            return True
        elif clean_phone.startswith('254') and len(clean_phone) == 12:
            return True
        elif clean_phone.startswith('+254') and len(clean_phone) == 13:
            return True
        
        return False
    
    @staticmethod
    def normalize_phone_number(phone_number: str) -> str:
        """Normalize phone number to +254 format"""
        clean_phone = re.sub(r'[^\d]', '', phone_number)
        
        if clean_phone.startswith('0'):
            return '+254' + clean_phone[1:]
        elif clean_phone.startswith('254'):
            return '+' + clean_phone
        elif phone_number.startswith('+254'):
            return phone_number
        
        return phone_number
    
    @staticmethod
    def validate_pin(pin: str) -> bool:
        """Validate PIN format (4 digits)"""
        return bool(re.match(r'^\d{4}$', pin))
    
    @staticmethod
    def validate_amount(amount_str: str) -> Tuple[bool, Optional[Decimal]]:
        """Validate transaction amount"""
        try:
            amount = Decimal(amount_str)
            if amount <= 0:
                return False, None
            if amount < MIN_TRANSACTION_AMOUNT:
                return False, None
            if amount > MAX_TRANSACTION_AMOUNT:
                return False, None
            return True, amount
        except (InvalidOperation, ValueError):
            return False, None
    
    @staticmethod
    def create_user(phone_number: str, pin: str, name: str = None) -> Tuple[bool, str]:
        """Create a new user account"""
        try:
            if not WalletManager.validate_phone_number(phone_number):
                return False, "Invalid phone number format"
            
            if not WalletManager.validate_pin(pin):
                return False, "PIN must be 4 digits"
            
            normalized_phone = WalletManager.normalize_phone_number(phone_number)
            hashed_pin = WalletManager.hash_pin(pin)
            
            user_data = {
                'phone_number': normalized_phone,
                'pin_hash': hashed_pin,
                'name': name or f"User {normalized_phone[-4:]}",
                'balance': Decimal('0.00'),
                'is_active': True,
                'created_at': datetime.utcnow(),
                'last_login': datetime.utcnow(),
                'failed_pin_attempts': 0,
                'is_locked': False
            }
            
            # Convert Decimal to float for MongoDB
            user_data['balance'] = float(user_data['balance'])
            
            users_collection.insert_one(user_data)
            logger.info(f"User created successfully: {normalized_phone}")
            return True, "Account created successfully"
            
        except DuplicateKeyError:
            return False, "Phone number already registered"
        except Exception as e:
            logger.error(f"Failed to create user: {e}")
            return False, "Registration failed. Please try again"
    
    @staticmethod
    def authenticate_user(phone_number: str, pin: str) -> Tuple[bool, Optional[Dict]]:
        """Authenticate user with phone number and PIN"""
        try:
            normalized_phone = WalletManager.normalize_phone_number(phone_number)
            user = users_collection.find_one({'phone_number': normalized_phone})
            
            if not user:
                return False, None
            
            if user.get('is_locked', False):
                return False, user
            
            hashed_pin = WalletManager.hash_pin(pin)
            
            if user['pin_hash'] == hashed_pin:
                # Reset failed attempts and update last login
                users_collection.update_one(
                    {'_id': user['_id']},
                    {
                        '$set': {'last_login': datetime.utcnow(), 'failed_pin_attempts': 0}
                    }
                )
                return True, user
            else:
                # Increment failed attempts
                failed_attempts = user.get('failed_pin_attempts', 0) + 1
                update_data = {'failed_pin_attempts': failed_attempts}
                
                if failed_attempts >= 3:
                    update_data['is_locked'] = True
                    logger.warning(f"Account locked due to failed PIN attempts: {normalized_phone}")
                
                users_collection.update_one(
                    {'_id': user['_id']},
                    {'$set': update_data}
                )
                
                return False, user
                
        except Exception as e:
            logger.error(f"Authentication failed: {e}")
            return False, None
    
    @staticmethod
    def get_user_by_phone(phone_number: str) -> Optional[Dict]:
        """Get user by phone number"""
        try:
            normalized_phone = WalletManager.normalize_phone_number(phone_number)
            return users_collection.find_one({'phone_number': normalized_phone})
        except Exception as e:
            logger.error(f"Failed to get user: {e}")
            return None
    
    @staticmethod
    def update_balance(phone_number: str, amount: Decimal, transaction_type: str, 
                      description: str, reference: str = None) -> Tuple[bool, str]:
        """Update user balance and create transaction record"""
        try:
            normalized_phone = WalletManager.normalize_phone_number(phone_number)
            user = users_collection.find_one({'phone_number': normalized_phone})
            
            if not user:
                return False, "User not found"
            
            current_balance = Decimal(str(user['balance']))
            
            if transaction_type in ['withdraw', 'send'] and current_balance < amount:
                return False, "Insufficient balance"
            
            # Check daily transaction limit
            today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            daily_transactions = transactions_collection.aggregate([
                {
                    '$match': {
                        'user_phone': normalized_phone,
                        'created_at': {'$gte': today},
                        'type': {'$in': ['withdraw', 'send']},
                        'status': 'completed'
                    }
                },
                {
                    '$group': {
                        '_id': None,
                        'total': {'$sum': '$amount'}
                    }
                }
            ])
            
            daily_total = Decimal('0.00')
            for result in daily_transactions:
                daily_total = Decimal(str(result['total']))
            
            if transaction_type in ['withdraw', 'send'] and (daily_total + amount) > DAILY_TRANSACTION_LIMIT:
                return False, "Daily transaction limit exceeded"
            
            # Calculate new balance
            if transaction_type in ['deposit', 'receive']:
                new_balance = current_balance + amount
            else:
                new_balance = current_balance - amount
            
            # Generate transaction ID
            transaction_id = f"TXN{datetime.utcnow().strftime('%Y%m%d%H%M%S')}{secrets.token_hex(4)}"
            
            # Create transaction record
            transaction_data = {
                'transaction_id': transaction_id,
                'user_phone': normalized_phone,
                'type': transaction_type,
                'amount': float(amount),
                'description': description,
                'reference': reference,
                'balance_before': float(current_balance),
                'balance_after': float(new_balance),
                'status': 'completed',
                'created_at': datetime.utcnow()
            }
            
            # Update balance and create transaction atomically
            users_collection.update_one(
                {'phone_number': normalized_phone},
                {'$set': {'balance': float(new_balance)}}
            )
            
            transactions_collection.insert_one(transaction_data)
            
            logger.info(f"Transaction completed: {transaction_id} for {normalized_phone}")
            return True, transaction_id
            
        except Exception as e:
            logger.error(f"Balance update failed: {e}")
            return False, "Transaction failed"
    
    @staticmethod
    def transfer_money(sender_phone: str, recipient_phone: str, amount: Decimal, 
                      sender_pin: str) -> Tuple[bool, str]:
        """Transfer money between users"""
        try:
            # Authenticate sender
            auth_success, sender_user = WalletManager.authenticate_user(sender_phone, sender_pin)
            if not auth_success:
                return False, "Invalid PIN"
            
            # Check if recipient exists
            recipient_user = WalletManager.get_user_by_phone(recipient_phone)
            if not recipient_user:
                return False, "Recipient not found"
            
            # Deduct from sender
            success, ref = WalletManager.update_balance(
                sender_phone, amount, 'send',
                f"Transfer to {WalletManager.normalize_phone_number(recipient_phone)}"
            )
            
            if not success:
                return False, ref
            
            # Add to recipient
            WalletManager.update_balance(
                recipient_phone, amount, 'receive',
                f"Transfer from {WalletManager.normalize_phone_number(sender_phone)}",
                ref
            )
            
            # Send SMS notifications if available
            if sms:
                try:
                    sender_msg = f"Transfer successful. Sent KSH {amount} to {recipient_phone}. Ref: {ref}"
                    recipient_msg = f"Money received. KSH {amount} from {sender_phone}. Ref: {ref}"
                    
                    sms.send(sender_msg, [sender_phone])
                    sms.send(recipient_msg, [recipient_phone])
                except Exception as e:
                    logger.error(f"SMS notification failed: {e}")
            
            return True, ref
            
        except Exception as e:
            logger.error(f"Money transfer failed: {e}")
            return False, "Transfer failed"
    
    @staticmethod
    def get_transaction_history(phone_number: str, limit: int = 10) -> list:
        """Get user transaction history"""
        try:
            normalized_phone = WalletManager.normalize_phone_number(phone_number)
            transactions = list(
                transactions_collection.find(
                    {'user_phone': normalized_phone},
                    {'_id': 0}
                ).sort('created_at', DESCENDING).limit(limit)
            )
            return transactions
        except Exception as e:
            logger.error(f"Failed to get transaction history: {e}")
            return []

class USSDMenus:
    """USSD menu responses and navigation"""
    
    @staticmethod
    def main_menu() -> str:
        """Main menu"""
        return ("CON Welcome to Mobile Wallet\n"
                "1. Check Balance\n"
                "2. Send Money\n"
                "3. Deposit Money\n"
                "4. Transaction History\n"
                "5. Change PIN\n"
                "6. My Account\n"
                "0. Exit")
    
    @staticmethod
    def registration_menu() -> str:
        """Registration menu"""
        return "CON Welcome! Enter your name:"
    
    @staticmethod
    def pin_setup_menu() -> str:
        """PIN setup menu"""
        return "CON Set your 4-digit PIN:"
    
    @staticmethod
    def pin_confirm_menu() -> str:
        """PIN confirmation menu"""
        return "CON Confirm your 4-digit PIN:"
    
    @staticmethod
    def login_menu() -> str:
        """Login menu"""
        return "CON Enter your 4-digit PIN:"
    
    @staticmethod
    def balance_menu(balance: Decimal, name: str) -> str:
        """Balance display"""
        return f"END Hello {name}\nYour balance is KSH {balance:.2f}"
    
    @staticmethod
    def send_money_phone_menu() -> str:
        """Send money - phone number input"""
        return "CON Enter recipient phone number:"
    
    @staticmethod
    def send_money_amount_menu() -> str:
        """Send money - amount input"""
        return "CON Enter amount to send (KSH):"
    
    @staticmethod
    def send_money_pin_menu(phone: str, amount: Decimal) -> str:
        """Send money - PIN confirmation"""
        return f"CON Send KSH {amount:.2f} to {phone}?\nEnter your PIN to confirm:"
    
    @staticmethod
    def deposit_amount_menu() -> str:
        """Deposit amount input"""
        return "CON Enter deposit amount (KSH):"
    
    @staticmethod
    def deposit_confirm_menu(amount: Decimal) -> str:
        """Deposit confirmation"""
        return f"CON Deposit KSH {amount:.2f}?\nEnter your PIN to confirm:"
    
    @staticmethod
    def change_pin_current_menu() -> str:
        """Change PIN - current PIN"""
        return "CON Enter your current PIN:"
    
    @staticmethod
    def change_pin_new_menu() -> str:
        """Change PIN - new PIN"""
        return "CON Enter your new 4-digit PIN:"
    
    @staticmethod
    def change_pin_confirm_menu() -> str:
        """Change PIN - confirm new PIN"""
        return "CON Confirm your new PIN:"
    
    @staticmethod
    def account_info_menu(user: Dict) -> str:
        """Account information"""
        created_date = user['created_at'].strftime('%Y-%m-%d')
        return (f"END Account Information\n"
                f"Name: {user['name']}\n"
                f"Phone: {user['phone_number']}\n"
                f"Balance: KSH {user['balance']:.2f}\n"
                f"Joined: {created_date}")
    
    @staticmethod
    def transaction_history_menu(transactions: list) -> str:
        """Transaction history"""
        if not transactions:
            return "END No transactions found"
        
        response = "END Recent Transactions:\n"
        for i, txn in enumerate(transactions[:5], 1):
            date = txn['created_at'].strftime('%m/%d')
            amount = txn['amount']
            txn_type = txn['type'].capitalize()
            response += f"{i}. {date} {txn_type} KSH {amount:.2f}\n"
        
        return response
    
    @staticmethod
    def error_menu(message: str) -> str:
        """Error message"""
        return f"END Error: {message}"
    
    @staticmethod
    def success_menu(message: str) -> str:
        """Success message"""
        return f"END {message}"

def require_session(f):
    """Decorator to ensure valid session exists"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        session_id = request.form.get('sessionId', '')
        if not session_id:
            return USSDMenus.error_menu("Session error")
        
        session = USSDSession.get_session(session_id)
        if not session:
            return USSDMenus.error_menu("Session expired")
        
        return f(session, *args, **kwargs)
    return decorated_function

@app.route('/ussd', methods=['POST'])
def ussd_callback():
    """Main USSD callback handler"""
    try:
        # Get USSD parameters
        session_id = request.form.get('sessionId', '')
        service_code = request.form.get('serviceCode', '')
        phone_number = request.form.get('phoneNumber', '')
        text = request.form.get('text', '')
        
        logger.info(f"USSD Request: {session_id}, {phone_number}, {text}")
        
        if not all([session_id, service_code, phone_number]):
            return USSDMenus.error_menu("Invalid request parameters")
        
        # Normalize phone number
        normalized_phone = WalletManager.normalize_phone_number(phone_number)
        
        # Check if user exists
        user = WalletManager.get_user_by_phone(normalized_phone)
        
        # Handle empty text (first request)
        if not text:
            if user:
                # Existing user - create session and ask for PIN
                USSDSession.create_session(session_id, normalized_phone)
                return USSDMenus.login_menu()
            else:
                # New user - start registration
                USSDSession.create_session(session_id, normalized_phone, {'step': 'registration'})
                return USSDMenus.registration_menu()
        
        # Get session
        session = USSDSession.get_session(session_id)
        if not session:
            return USSDMenus.error_menu("Session expired")
        
        # Parse user input
        input_parts = text.split('*')
        current_input = input_parts[-1] if input_parts else ''
        
        # Handle registration flow
        if session.get('data', {}).get('step') == 'registration':
            return handle_registration_flow(session, current_input, input_parts, normalized_phone)
        
        # Handle authenticated user flow
        if user and not session.get('data', {}).get('authenticated'):
            return handle_authentication_flow(session, current_input, normalized_phone, user)
        
        # Handle main menu navigation
        if session.get('data', {}).get('authenticated'):
            return handle_main_menu_flow(session, current_input, input_parts, normalized_phone, user)
        
        return USSDMenus.error_menu("Invalid session state")
        
    except Exception as e:
        logger.error(f"USSD callback error: {e}")
        return USSDMenus.error_menu("Service temporarily unavailable")

def handle_registration_flow(session: Dict, current_input: str, input_parts: list, phone_number: str) -> str:
    """Handle user registration flow"""
    try:
        session_data = session.get('data', {})
        step = session_data.get('step')
        
        if step == 'registration':
            # Get user name
            if not current_input.strip():
                return USSDMenus.error_menu("Name cannot be empty")
            
            session_data['name'] = current_input.strip()
            session_data['step'] = 'pin_setup'
            USSDSession.update_session(session['session_id'], session_data)
            return USSDMenus.pin_setup_menu()
        
        elif step == 'pin_setup':
            # Set PIN
            if not WalletManager.validate_pin(current_input):
                return USSDMenus.error_menu("PIN must be 4 digits")
            
            session_data['pin'] = current_input
            session_data['step'] = 'pin_confirm'
            USSDSession.update_session(session['session_id'], session_data)
            return USSDMenus.pin_confirm_menu()
        
        elif step == 'pin_confirm':
            # Confirm PIN
            if current_input != session_data.get('pin'):
                session_data['step'] = 'pin_setup'
                USSDSession.update_session(session['session_id'], session_data)
                return USSDMenus.error_menu("PINs don't match. Enter new PIN:")
            
            # Create user account
            success, message = WalletManager.create_user(
                phone_number, 
                session_data['pin'], 
                session_data['name']
            )
            
            USSDSession.delete_session(session['session_id'])
            
            if success:
                return USSDMenus.success_menu(f"Account created successfully!\nWelcome {session_data['name']}")
            else:
                return USSDMenus.error_menu(message)
        
        return USSDMenus.error_menu("Invalid registration step")
        
    except Exception as e:
        logger.error(f"Registration flow error: {e}")
        return USSDMenus.error_menu("Registration failed")

def handle_authentication_flow(session: Dict, current_input: str, phone_number: str, user: Dict) -> str:
    """Handle user authentication"""
    try:
        if user.get('is_locked'):
            USSDSession.delete_session(session['session_id'])
            return USSDMenus.error_menu("Account locked. Contact support.")
        
        # Authenticate with PIN
        auth_success, auth_user = WalletManager.authenticate_user(phone_number, current_input)
        
        if auth_success:
            session_data = session.get('data', {})
            session_data['authenticated'] = True
            session_data['user_id'] = str(auth_user['_id'])
            USSDSession.update_session(session['session_id'], session_data, 'main_menu')
            return USSDMenus.main_menu()
        else:
            USSDSession.delete_session(session['session_id'])
            failed_attempts = user.get('failed_pin_attempts', 0) + 1
            
            if failed_attempts >= 3:
                return USSDMenus.error_menu("Account locked due to multiple failed attempts")
            else:
                return USSDMenus.error_menu(f"Invalid PIN. {3 - failed_attempts} attempts remaining")
    
    except Exception as e:
        logger.error(f"Authentication error: {e}")
        return USSDMenus.error_menu("Authentication failed")

def handle_main_menu_flow(session: Dict, current_input: str, input_parts: list, phone_number: str, user: Dict) -> str:
    """Handle main menu navigation and operations"""
    try:
        session_data = session.get('data', {})
        current_step = session.get('step', 'main_menu')
        
        # Main menu selection
        if current_step == 'main_menu':
            if current_input == '1':
                # Check Balance
                balance = Decimal(str(user['balance']))
                return USSDMenus.balance_menu(balance, user['name'])
            
            elif current_input == '2':
                # Send Money
                session_data['operation'] = 'send_money'
                USSDSession.update_session(session['session_id'], session_data, 'send_money_phone')
                return USSDMenus.send_money_phone_menu()
            
            elif current_input == '3':
                # Deposit Money
                session_data['operation'] = 'deposit'
                USSDSession.update_session(session['session_id'], session_data, 'deposit_amount')
                return USSDMenus.deposit_amount_menu()
            
            elif current_input == '4':
                # Transaction History
                transactions = WalletManager.get_transaction_history(phone_number)
                return USSDMenus.transaction_history_menu(transactions)
            
            elif current_input == '5':
                # Change PIN
                session_data['operation'] = 'change_pin'
                USSDSession.update_session(session['session_id'], session_data, 'change_pin_current')
                return USSDMenus.change_pin_current_menu()
            
            elif current_input == '6':
                # My Account
                return USSDMenus.account_info_menu(user)
            
            elif current_input == '0':
                # Exit
                USSDSession.delete_session(session['session_id'])
                return "END Thank you for using Mobile Wallet"
            
            else:
                return USSDMenus.error_menu("Invalid option. Please try again.")
        
        # Send Money Flow
        elif current_step == 'send_money_phone':
            if not WalletManager.validate_phone_number(current_input):
                return USSDMenus.error_menu("Invalid phone number format")
            
            recipient_phone = WalletManager.normalize_phone_number(current_input)
            
            if recipient_phone == phone_number:
                return USSDMenus.error_menu("Cannot send money to yourself")
            
            recipient = WalletManager.get_user_by_phone(recipient_phone)
            if not recipient:
                return USSDMenus.error_menu("Recipient not registered")
            
            session_data['recipient_phone'] = recipient_phone
            USSDSession.update_session(session['session_id'], session_data, 'send_money_amount')
            return USSDMenus.send_money_amount_menu()
        
        elif current_step == 'send_money_amount':
            valid, amount = WalletManager.validate_amount(current_input)
            if not valid:
                return USSDMenus.error_menu(f"Invalid amount. Min: {MIN_TRANSACTION_AMOUNT}, Max: {MAX_TRANSACTION_AMOUNT}")
            
            session_data['amount'] = str(amount)
            USSDSession.update_session(session['session_id'], session_data, 'send_money_pin')
            return USSDMenus.send_money_pin_menu(session_data['recipient_phone'], amount)
        
        elif current_step == 'send_money_pin':
            recipient_phone = session_data['recipient_phone']
            amount = Decimal(session_data['amount'])
            
            success, reference = WalletManager.transfer_money(
                phone_number, recipient_phone, amount, current_input
            )
            
            USSDSession.delete_session(session['session_id'])
            
            if success:
                return USSDMenus.success_menu(f"Transfer successful!\nSent KSH {amount:.2f} to {recipient_phone}\nReference: {reference}")
            else:
                return USSDMenus.error_menu(f"Transfer failed: {reference}")
        
        # Deposit Money Flow
        elif current_step == 'deposit_amount':
            valid, amount = WalletManager.validate_amount(current_input)
            if not valid:
                return USSDMenus.error_menu(f"Invalid amount. Min: {MIN_TRANSACTION_AMOUNT}, Max: {MAX_TRANSACTION_AMOUNT}")
            
            session_data['amount'] = str(amount)
            USSDSession.update_session(session['session_id'], session_data, 'deposit_confirm')
            return USSDMenus.deposit_confirm_menu(amount)
        
        elif current_step == 'deposit_confirm':
            # Verify PIN and process deposit
            auth_success, auth_user = WalletManager.authenticate_user(phone_number, current_input)
            
            if not auth_success:
                USSDSession.delete_session(session['session_id'])
                return USSDMenus.error_menu("Invalid PIN")
            
            amount = Decimal(session_data['amount'])
            success, reference = WalletManager.update_balance(
                phone_number, amount, 'deposit', 'Mobile money deposit'
            )
            
            USSDSession.delete_session(session['session_id'])
            
            if success:
                new_balance = Decimal(str(user['balance'])) + amount
                return USSDMenus.success_menu(f"Deposit successful!\nKSH {amount:.2f} deposited\nNew balance: KSH {new_balance:.2f}\nReference: {reference}")
            else:
                return USSDMenus.error_menu(f"Deposit failed: {reference}")
        
        # Change PIN Flow
        elif current_step == 'change_pin_current':
            # Verify current PIN
            auth_success, auth_user = WalletManager.authenticate_user(phone_number, current_input)
            
            if not auth_success:
                USSDSession.delete_session(session['session_id'])
                return USSDMenus.error_menu("Invalid current PIN")
            
            USSDSession.update_session(session['session_id'], session_data, 'change_pin_new')
            return USSDMenus.change_pin_new_menu()
        
        elif current_step == 'change_pin_new':
            if not WalletManager.validate_pin(current_input):
                return USSDMenus.error_menu("PIN must be 4 digits")
            
            session_data['new_pin'] = current_input
            USSDSession.update_session(session['session_id'], session_data, 'change_pin_confirm')
            return USSDMenus.change_pin_confirm_menu()
        
        elif current_step == 'change_pin_confirm':
            if current_input != session_data.get('new_pin'):
                session_data.pop('new_pin', None)
                USSDSession.update_session(session['session_id'], session_data, 'change_pin_new')
                return USSDMenus.error_menu("PINs don't match. Enter new PIN:")
            
            # Update PIN in database
            new_pin_hash = WalletManager.hash_pin(session_data['new_pin'])
            
            try:
                users_collection.update_one(
                    {'phone_number': phone_number},
                    {'$set': {'pin_hash': new_pin_hash, 'failed_pin_attempts': 0, 'is_locked': False}}
                )
                
                USSDSession.delete_session(session['session_id'])
                return USSDMenus.success_menu("PIN changed successfully!")
                
            except Exception as e:
                logger.error(f"PIN change failed: {e}")
                USSDSession.delete_session(session['session_id'])
                return USSDMenus.error_menu("PIN change failed. Please try again.")
        
        else:
            return USSDMenus.error_menu("Invalid operation")
    
    except Exception as e:
        logger.error(f"Main menu flow error: {e}")
        return USSDMenus.error_menu("Service error. Please try again.")

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    try:
        # Test database connection
        db.command('ping')
        return jsonify({
            'status': 'healthy',
            'timestamp': datetime.utcnow().isoformat(),
            'database': 'connected',
            'africastalking': 'initialized' if sms else 'not_initialized'
        }), 200
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'timestamp': datetime.utcnow().isoformat(),
            'error': str(e)
        }), 500

@app.route('/stats', methods=['GET'])
def get_stats():
    """Get wallet statistics - for admin/monitoring"""
    try:
        # Basic authentication (you should implement proper auth)
        api_key = request.headers.get('X-API-Key')
        if api_key != os.environ.get('ADMIN_API_KEY', 'admin_key_123'):
            return jsonify({'error': 'Unauthorized'}), 401
        
        # Get statistics
        total_users = users_collection.count_documents({'is_active': True})
        total_transactions = transactions_collection.count_documents({'status': 'completed'})
        
        # Get total balance
        pipeline = [
            {'$match': {'is_active': True}},
            {'$group': {'_id': None, 'total_balance': {'$sum': '$balance'}}}
        ]
        balance_result = list(users_collection.aggregate(pipeline))
        total_balance = balance_result[0]['total_balance'] if balance_result else 0
        
        # Get today's transactions
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_transactions = transactions_collection.count_documents({
            'created_at': {'$gte': today},
            'status': 'completed'
        })
        
        # Get today's transaction volume
        volume_pipeline = [
            {'$match': {
                'created_at': {'$gte': today},
                'status': 'completed'
            }},
            {'$group': {'_id': None, 'volume': {'$sum': '$amount'}}}
        ]
        volume_result = list(transactions_collection.aggregate(volume_pipeline))
        today_volume = volume_result[0]['volume'] if volume_result else 0
        
        return jsonify({
            'total_users': total_users,
            'total_transactions': total_transactions,
            'total_balance': float(total_balance),
            'today_transactions': today_transactions,
            'today_volume': float(today_volume),
            'timestamp': datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Stats endpoint error: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/webhook/sms', methods=['POST'])
def sms_webhook():
    """SMS delivery status webhook"""
    try:
        data = request.get_json()
        logger.info(f"SMS webhook received: {data}")
        
        # Process SMS delivery status
        # You can update transaction records or user notifications here
        
        return jsonify({'status': 'received'}), 200
        
    except Exception as e:
        logger.error(f"SMS webhook error: {e}")
        return jsonify({'error': 'Webhook processing failed'}), 500

@app.route('/api/user/<phone_number>/balance', methods=['GET'])
def get_user_balance_api(phone_number: str):
    """API endpoint to get user balance - for integration purposes"""
    try:
        # Basic API authentication
        api_key = request.headers.get('X-API-Key')
        if api_key != os.environ.get('API_KEY', 'your_api_key_here'):
            return jsonify({'error': 'Unauthorized'}), 401
        
        user = WalletManager.get_user_by_phone(phone_number)
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        return jsonify({
            'phone_number': user['phone_number'],
            'balance': float(user['balance']),
            'name': user['name'],
            'is_active': user['is_active']
        })
        
    except Exception as e:
        logger.error(f"Balance API error: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/transaction', methods=['POST'])
def create_transaction_api():
    """API endpoint to create transactions - for integration purposes"""
    try:
        # Basic API authentication
        api_key = request.headers.get('X-API-Key')
        if api_key != os.environ.get('API_KEY', 'your_api_key_here'):
            return jsonify({'error': 'Unauthorized'}), 401
        
        data = request.get_json()
        required_fields = ['phone_number', 'amount', 'type', 'description']
        
        if not all(field in data for field in required_fields):
            return jsonify({'error': 'Missing required fields'}), 400
        
        phone_number = data['phone_number']
        amount_str = str(data['amount'])
        transaction_type = data['type']
        description = data['description']
        
        # Validate inputs
        if transaction_type not in ['deposit', 'withdraw']:
            return jsonify({'error': 'Invalid transaction type'}), 400
        
        valid, amount = WalletManager.validate_amount(amount_str)
        if not valid:
            return jsonify({'error': 'Invalid amount'}), 400
        
        user = WalletManager.get_user_by_phone(phone_number)
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        # Process transaction
        success, reference = WalletManager.update_balance(
            phone_number, amount, transaction_type, description
        )
        
        if success:
            return jsonify({
                'success': True,
                'reference': reference,
                'message': f'{transaction_type.capitalize()} successful'
            })
        else:
            return jsonify({'error': reference}), 400
            
    except Exception as e:
        logger.error(f"Transaction API error: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/user/<phone_number>/transactions', methods=['GET'])
def get_user_transactions_api(phone_number: str):
    """API endpoint to get user transactions"""
    try:
        # Basic API authentication
        api_key = request.headers.get('X-API-Key')
        if api_key != os.environ.get('API_KEY', 'your_api_key_here'):
            return jsonify({'error': 'Unauthorized'}), 401
        
        limit = int(request.args.get('limit', 20))
        limit = min(limit, 100)  # Cap at 100 transactions
        
        user = WalletManager.get_user_by_phone(phone_number)
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        transactions = WalletManager.get_transaction_history(phone_number, limit)
        
        # Convert datetime objects to ISO format
        for txn in transactions:
            if 'created_at' in txn:
                txn['created_at'] = txn['created_at'].isoformat()
        
        return jsonify({
            'phone_number': phone_number,
            'transactions': transactions,
            'count': len(transactions)
        })
        
    except Exception as e:
        logger.error(f"Transactions API error: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.errorhandler(404)
def not_found(error):
    """404 error handler"""
    return jsonify({'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    """500 error handler"""
    logger.error(f"Internal server error: {error}")
    return jsonify({'error': 'Internal server error'}), 500

@app.errorhandler(Exception)
def handle_exception(error):
    """Global exception handler"""
    logger.error(f"Unhandled exception: {error}")
    return jsonify({'error': 'Service temporarily unavailable'}), 500

# Cleanup function to remove expired sessions
def cleanup_expired_sessions():
    """Remove expired sessions from database"""
    try:
        result = sessions_collection.delete_many({
            'expires_at': {'$lt': datetime.utcnow()}
        })
        if result.deleted_count > 0:
            logger.info(f"Cleaned up {result.deleted_count} expired sessions")
    except Exception as e:
        logger.error(f"Session cleanup error: {e}")

# Initialize database constraints and cleanup
def initialize_app():
    """Initialize application with database constraints"""
    try:
        # Ensure database constraints
        users_collection.create_index("phone_number", unique=True)
        transactions_collection.create_index("transaction_id", unique=True)
        sessions_collection.create_index("session_id", unique=True)
        
        # Set up TTL index for sessions
        sessions_collection.create_index("expires_at", expireAfterSeconds=0)
        
        # Clean up any existing expired sessions
        cleanup_expired_sessions()
        
        logger.info("Application initialized successfully")
        
    except Exception as e:
        logger.error(f"Application initialization failed: {e}")
        raise

if __name__ == '__main__':
    # Initialize the application
    initialize_app()
    
    # Get configuration from environment
    PORT = int(os.environ.get('PORT', 5000))
    DEBUG = os.environ.get('FLASK_ENV') == 'development'
    
    logger.info(f"Starting USSD Wallet application on port {PORT}")
    
    # Run the Flask application
    app.run(
        host='0.0.0.0',
        port=PORT,
        debug=DEBUG,
        threaded=True
    )