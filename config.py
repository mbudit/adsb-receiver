import os
from dotenv import load_dotenv

# Path to the current file's directory
base_dir = os.path.dirname(os.path.abspath(__file__))

# Try loading from the local directory first, then fallback to parent directory
local_env = os.path.join(base_dir, ".env")
parent_env = os.path.join(os.path.dirname(base_dir), ".env")

if os.path.exists(local_env):
    load_dotenv(local_env)
elif os.path.exists(parent_env):
    load_dotenv(parent_env)
else:
    load_dotenv()  # Default behavior

# Database Configurations
DB_HOST = os.getenv("DATABASE_HOST", "localhost")
DB_PORT = int(os.getenv("DATABASE_PORT", 5432))
DB_NAME = os.getenv("DATABASE_NAME", "hidrometeorology")
DB_USER = os.getenv("DATABASE_USER", "hidro_user")
DB_PASSWORD = os.getenv("DATABASE_PASSWORD", "your_secure_password")

# ADS-B SDR Connection Configurations
SDR_HOST = os.getenv("ADSB_HOST", "localhost")
SDR_PORT = int(os.getenv("ADSB_PORT", 30002))

# Application Settings
BATCH_INTERVAL_SEC = int(os.getenv("BATCH_INTERVAL_SEC", 60))
UPLOAD_API_URL = os.getenv("UPLOAD_API_URL", "https://bytenusa.cloud/api/v1/adsb/bulk")

def get_connection_string():
    return f"host={DB_HOST} port={DB_PORT} dbname={DB_NAME} user={DB_USER} password={DB_PASSWORD}"

def get_status_summary():
    return {
        "sdr": f"{SDR_HOST}:{SDR_PORT}",
        "db": f"{DB_HOST}:{DB_PORT}/{DB_NAME}",
        "batch_interval": f"{BATCH_INTERVAL_SEC}s"
    }
