import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/ussd_wallet')
    SECRET_KEY = os.getenv('SECRET_KEY', 'your-secret-key-here')
    USSD_CODE = os.getenv('USSD_CODE', '*123#')
    SESSION_TIMEOUT = int(os.getenv('SESSION_TIMEOUT', 90))  # seconds
    MAX_PIN_ATTEMPTS = int(os.getenv('MAX_PIN_ATTEMPTS', 3))
    TRANSACTION_LIMITS = {
        'tier1': {'daily': 20000, 'monthly': 300000},
        'tier2': {'daily': 100000, 'monthly': 2000000},
        'tier3': {'daily': 500000, 'monthly': 5000000}
    }
    USSD_CHARGE = float(os.getenv('USSD_CHARGE', 6.98))