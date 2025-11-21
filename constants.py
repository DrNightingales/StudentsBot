from dotenv import load_dotenv
from os import environ

load_dotenv()
API_KEY = environ['API_KEY']
ADMIN_ID = int(environ['ADMIN_ID'])
DB_PATH = environ['DB_PATH']
REGISTRATION_URL_BASE = environ['REGISTRATION_URL_BASE']
