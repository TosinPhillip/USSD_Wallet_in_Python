# models.py
from pymongo import MongoClient
from datetime import datetime, timedelta
from config import Config
import hashlib

client = MongoClient(Config.MONGO_URI)
db = client['ussd_wallet']

users_collection = db['users']
transactions_collection = db['transactions']
sessions_collection = db['sessions']


def hash_pin(pin: str) -> str:
    return hashlib.sha256(pin.encode()).hexdigest()

def generate_account_number():
    # Simple 10-digit NUBAN-like number
    import random
    return str(random.randint(1000000000, 9999999999))

def log_transaction(account_number, txn_type, category, amount, desc="", status="successful", charges=0):
    ref = f"REF{datetime.now().strftime('%Y%m%d%H%M%S')}{random.randint(1000, 9999)}"
    transaction = {
        "accountNumber": account_number,
        "transactionType": "credit" if category == "deposit" else "debit",
        "category": category,
        "amount": float(amount),
        "description": desc,
        "referenceNumber": ref,
        "sessionId": get_current_session_id(),
        "status": status,
        "narration": desc,
        "charges": float(charges),
        "balanceAfter": get_balance(account_number),
        "createdAt": datetime.now(),
        "processedAt": datetime.now() if status == "successful" else None
    }
    transactions_collection.insert_one(transaction)
    return ref

def get_balance(account_number):
    user = users_collection.find_one({"accountNumber": account_number})
    return round(user["balance"], 2) if user else 0.0

def get_current_session_id():
    # Placeholder – should come from session context
    return "temp_session_123"

def validate_bvn(bvn: str) -> bool:
    return len(bvn) == 11 and bvn.isdigit()