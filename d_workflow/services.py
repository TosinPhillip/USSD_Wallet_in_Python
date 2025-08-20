from datetime import datetime, timedelta
from bson.objectid import ObjectId
from models import User, Transaction, Session
from validators import Validators
from config import Config
import random
import string

class AccountService:
    @staticmethod
    def create_account(data):
        # Validate required fields
        required_fields = ['firstName', 'lastName', 'phoneNumber', 'dateOfBirth', 
                          'gender', 'bvn', 'pin', 'securityQuestion', 'securityAnswer']
        if not all(field in data for field in required_fields):
            return None, "Missing required fields"
        
        # Validate phone number
        if not Validators.validate_phone(data['phoneNumber']):
            return None, "Invalid phone number"
        
        # Validate BVN
        if not Validators.validate_bvn(data['bvn']):
            return None, "Invalid BVN"
        
        # Validate PIN
        if not Validators.validate_pin(data['pin']):
            return None, "PIN must be 4 digits and not sequential or repetitive"
        
        # Check if phone number already exists
        if User.find_by_phone(data['phoneNumber']):
            return None, "Phone number already registered"
        
        # Create the user
        result = User.create(data)
        if result.inserted_id:
            return str(result.inserted_id), "Account created successfully"
        return None, "Failed to create account"

class TransactionService:
    @staticmethod
    def check_balance(account_number, pin):
        user = mongo.db.users.find_one({'accountNumber': account_number})
        if not user:
            return None, "Account not found"
        
        if not User.verify_pin(user, pin):
            return None, "Invalid PIN"
        
        return user['balance'], None
    
    @staticmethod
    def transfer_funds(sender_account, recipient_account, amount, pin, description=""):
        # Validate amount
        if not Validators.validate_amount(amount):
            return False, "Invalid amount"
        
        amount = float(amount)
        
        # Get sender and recipient
        sender = mongo.db.users.find_one({'accountNumber': sender_account})
        if not sender:
            return False, "Sender account not found"
        
        recipient = mongo.db.users.find_one({'accountNumber': recipient_account})
        if not recipient:
            return False, "Recipient account not found"
        
        # Verify PIN
        if not User.verify_pin(sender, pin):
            return False, "Invalid PIN"
        
        # Check balance
        if sender['balance'] < amount:
            return False, "Insufficient funds"
        
        # Check transaction limits
        tier_limit = Config.TRANSACTION_LIMITS[f'tier{sender["accountTier"]}']
        
        # Calculate daily transactions
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        daily_transactions = mongo.db.transactions.aggregate([
            {'$match': {
                'accountNumber': sender_account,
                'transactionType': 'debit',
                'createdAt': {'$gte': today_start}
            }},
            {'$group': {'_id': None, 'total': {'$sum': '$amount'}}}
        ])
        
        daily_total = next(daily_transactions, {}).get('total', 0)
        if daily_total + amount > tier_limit['daily']:
            return False, "Daily transaction limit exceeded"
        
        # Perform the transfer
        reference = ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))
        
        # Start transaction
        try:
            # Deduct from sender
            mongo.db.users.update_one(
                {'accountNumber': sender_account},
                {'$inc': {'balance': -amount}}
            )
            
            # Add to recipient
            mongo.db.users.update_one(
                {'accountNumber': recipient_account},
                {'$inc': {'balance': amount}}
            )
            
            # Record transactions
            debit_tx = {
                'accountNumber': sender_account,
                'transactionType': 'debit',
                'category': 'transfer',
                'amount': amount,
                'recipientAccountNumber': recipient_account,
                'recipientName': f"{recipient['firstName']} {recipient['lastName']}",
                'description': description,
                'referenceNumber': reference,
                'status': 'successful',
                'charges': Config.USSD_CHARGE,
                'balanceAfter': sender['balance'] - amount
            }
            
            credit_tx = {
                'accountNumber': recipient_account,
                'transactionType': 'credit',
                'category': 'transfer',
                'amount': amount,
                'senderAccountNumber': sender_account,
                'senderName': f"{sender['firstName']} {sender['lastName']}",
                'description': description,
                'referenceNumber': reference,
                'status': 'successful',
                'balanceAfter': recipient['balance'] + amount
            }
            
            Transaction.create(debit_tx)
            Transaction.create(credit_tx)
            
            return True, f"Transfer successful. Reference: {reference}"
        except Exception as e:
            return False, f"Transfer failed: {str(e)}"

class AirtimeService:
    @staticmethod
    def buy_airtime(account_number, phone_number, amount, pin, for_self=True):
        # Validate amount
        if not Validators.validate_amount(amount):
            return False, "Invalid amount"
        
        amount = float(amount)
        
        # Get user
        user = mongo.db.users.find_one({'accountNumber': account_number})
        if not user:
            return False, "Account not found"
        
        # Verify PIN
        if not User.verify_pin(user, pin):
            return False, "Invalid PIN"
        
        # Check balance
        if user['balance'] < amount:
            return False, "Insufficient funds"
        
        # Validate phone number
        if not Validators.validate_phone(phone_number):
            return False, "Invalid recipient phone number"
        
        # Check transaction limits
        tier_limit = Config.TRANSACTION_LIMITS[f'tier{user["accountTier"]}']
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        
        daily_transactions = mongo.db.transactions.aggregate([
            {'$match': {
                'accountNumber': account_number,
                'transactionType': 'debit',
                'createdAt': {'$gte': today_start}
            }},
            {'$group': {'_id': None, 'total': {'$sum': '$amount'}}}
        ])
        
        daily_total = next(daily_transactions, {}).get('total', 0)
        if daily_total + amount > tier_limit['daily']:
            return False, "Daily transaction limit exceeded"
        
        # Process airtime purchase (simulated)
        reference = ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))
        
        try:
            # Deduct from account
            mongo.db.users.update_one(
                {'accountNumber': account_number},
                {'$inc': {'balance': -amount}}
            )
            
            # Record transaction
            tx_data = {
                'accountNumber': account_number,
                'transactionType': 'debit',
                'category': 'airtime',
                'amount': amount,
                'recipientPhoneNumber': phone_number,
                'description': f"Airtime purchase {'for self' if for_self else 'for others'}",
                'referenceNumber': reference,
                'status': 'successful',
                'charges': Config.USSD_CHARGE,
                'balanceAfter': user['balance'] - amount
            }
            
            Transaction.create(tx_data)
            
            # In a real system, we would integrate with a telco API here
            return True, f"Airtime purchase successful. {amount} Naira airtime sent to {phone_number}. Reference: {reference}"
        except Exception as e:
            return False, f"Airtime purchase failed: {str(e)}"