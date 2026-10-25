import os
from dotenv import load_dotenv
load_dotenv()
class Config:
    FRONTEND_ORIGIN = os.getenv('FRONTEND_ORIGIN', 'http://localhost:5173')
    TRANSIT_MODE = os.getenv('TRANSIT_MODE', 'demo')
    CACHE_TTL_SECONDS = int(os.getenv('CACHE_TTL_SECONDS', '30'))
    FIREBASE_PROJECT_ID = os.getenv('FIREBASE_PROJECT_ID')
