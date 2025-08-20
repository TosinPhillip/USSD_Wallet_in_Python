from datetime import datetime
from flask_pymongo import PyMongo
from bson.objectid import ObjectId
from werkzeug.security import generate_password_hash, check_password_hash
from config import Config

mongo = PyMongo()

class User:
    @staticmethod
    def create(data):
        data['pin'] = generate_password_hash(data['pin'])
        data['securityAnswer'] = generate_password_hash(data['securityAnswer'])
        data['accountNumber'] = User.generate_account_number()
        data['accountStatus'] = 'active'
        data['accountTier'] = 1
        data['balance'] = 0.0
        data['failedLoginAttempts'] = 0
        data['createdAt'] = datetime.utcnow()
        data['updatedAt'] = datetime.utcnow()
        
        return mongo.db.users.insert_one(data)
    
    @staticmethod
    def generate_account_number():
        # Generate 10-digit NUBAN account number
        last_user = mongo.db.users.find_one(sort=[("accountNumber", -1)])
        if last_user:
            last_num = int(last_user['accountNumber'])
            return f"{last_num + 1:010d}"
        return "0000000001"
    
    @staticmethod
    def find_by_phone(phone):
        return mongo.db.users.find_one({'phoneNumber': phone})
    
    @staticmethod
    def verify_pin(user, pin):
        return check_password_hash(user['pin'], pin)
    
    @staticmethod
    def update(user_id, data):
        data['updatedAt'] = datetime.utcnow()
        return mongo.db.users.update_one(
            {'_id': ObjectId(user_id)},
            {'$set': data}
        )

class Transaction:
    @staticmethod
    def create(data):
        data['createdAt'] = datetime.utcnow()
        data['processedAt'] = datetime.utcnow()
        return mongo.db.transactions.insert_one(data)
    
    @staticmethod
    def get_transactions(account_number, limit=5):
        return list(mongo.db.transactions.find(
            {'accountNumber': account_number},
            sort=[('createdAt', -1)],
            limit=limit
        ))

class Session:
    @staticmethod
    def create(phone, step='main_menu', step_data=None):
        session_id = ObjectId()
        session_data = {
            'sessionId': str(session_id),
            'phoneNumber': phone,
            'currentStep': step,
            'stepData': step_data or {},
            'startTime': datetime.utcnow(),
            'lastActivity': datetime.utcnow(),
            'isActive': True
        }
        mongo.db.sessions.insert_one(session_data)
        return session_data
    
    @staticmethod
    def find(session_id):
        return mongo.db.sessions.find_one({'sessionId': session_id})
    
    @staticmethod
    def update(session_id, data):
        data['lastActivity'] = datetime.utcnow()
        return mongo.db.sessions.update_one(
            {'sessionId': session_id},
            {'$set': data}
        )
    
    @staticmethod
    def deactivate(session_id):
        return mongo.db.sessions.update_one(
            {'sessionId': session_id},
            {'$set': {'isActive': False}}
        )