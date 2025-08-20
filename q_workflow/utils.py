# utils.py
from datetime import datetime, timedelta
from config import Config
from models import sessions_collection, users_collection

def create_or_update_session(phone_number, session_id, current_step, step_data=None):
    if step_data is None:
        step_data = {}
    
    sessions_collection.update_one(
        {"phoneNumber": phone_number},
        {"$set": {
            "sessionId": session_id,
            "currentStep": current_step,
            "stepData": stepData,
            "lastActivity": datetime.now(),
            "isActive": True
        }},
        upsert=True
    )

def get_session(phone_number):
    return sessions_collection.find_one({
        "phoneNumber": phone_number,
        "isActive": True,
        "lastActivity": {"$gte": datetime.now() - timedelta(seconds=Config.SESSION_TIMEOUT_SECONDS)}
    })

def end_session(phone_number):
    sessions_collection.update_one(
        {"phoneNumber": phone_number},
        {"$set": {"isActive": False}}
    )

def validate_nigerian_phone(phone: str) -> bool:
    phone = phone.strip().replace('+', '')
    return phone.startswith(('080', '081', '070', '090', '081')) and len(phone) == 11

def format_amount(n):
    return f"{n:,.2f}"