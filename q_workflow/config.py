# config.py
import os
from urllib.parse import quote_plus

class Config:
    MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/ussd_wallet")
    SESSION_TIMEOUT_SECONDS = 90
    MAX_PIN_ATTEMPTS = 3
    BANK_NAME = "QuickBank"
    USSD_CODE = "*384*2025#"