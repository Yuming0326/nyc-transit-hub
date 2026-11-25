import os
from dotenv import load_dotenv
load_dotenv()
class Config:
    FRONTEND_ORIGIN = os.getenv('FRONTEND_ORIGIN', 'http://localhost:5173')
    TRANSIT_MODE = os.getenv('TRANSIT_MODE', 'demo')
    CACHE_TTL_SECONDS = int(os.getenv('CACHE_TTL_SECONDS', '30'))
    MTA_CONNECT_TIMEOUT_SECONDS = float(os.getenv('MTA_CONNECT_TIMEOUT_SECONDS', '3.05'))
    MTA_READ_TIMEOUT_SECONDS = float(os.getenv('MTA_READ_TIMEOUT_SECONDS', '10'))
    MTA_MAX_AGE_SECONDS = float(os.getenv('MTA_MAX_AGE_SECONDS', '120'))
    MTA_ALERTS_MAX_AGE_SECONDS = float(os.getenv('MTA_ALERTS_MAX_AGE_SECONDS', '600'))
    BUS_MAX_AGE_SECONDS = float(os.getenv('BUS_MAX_AGE_SECONDS', '120'))
    BUS_VEHICLE_MAX_AGE_SECONDS = float(os.getenv('BUS_VEHICLE_MAX_AGE_SECONDS', '120'))
    # Backend only; never returned to clients or logged.
    MTA_BUS_TIME_API_KEY = os.getenv('MTA_BUS_TIME_API_KEY', '')
    FIREBASE_PROJECT_ID = os.getenv('FIREBASE_PROJECT_ID')
