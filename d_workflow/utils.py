from datetime import datetime
from models import Session
from config import Config

def cleanup_expired_sessions():
    """Deactivate sessions that have timed out"""
    timeout = datetime.utcnow() - timedelta(seconds=Config.SESSION_TIMEOUT)
    mongo.db.sessions.update_many(
        {
            'lastActivity': {'$lt': timeout},
            'isActive': True
        },
        {'$set': {'isActive': False}}
    )