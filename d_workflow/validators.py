import re
import phonenumbers
from datetime import datetime

class Validators:
    @staticmethod
    def validate_phone(phone):
        try:
            parsed = phonenumbers.parse(phone, "NG")
            return phonenumbers.is_valid_number(parsed)
        except:
            return False
    
    @staticmethod
    def validate_bvn(bvn):
        return len(bvn) == 11 and bvn.isdigit()
    
    @staticmethod
    def validate_pin(pin):
        if len(pin) != 4 or not pin.isdigit():
            return False
        # Check for sequential or repetitive patterns
        if (pin in ['1234', '4321', '0000', '1111', '2222', '3333', '4444', 
                   '5555', '6666', '7777', '8888', '9999']):
            return False
        return True
    
    @staticmethod
    def validate_amount(amount):
        try:
            amount = float(amount)
            return amount > 0
        except ValueError:
            return False
    
    @staticmethod
    def validate_date(date_str, format='%d/%m/%Y'):
        try:
            datetime.strptime(date_str, format)
            return True
        except ValueError:
            return False