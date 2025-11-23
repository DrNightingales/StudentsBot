from dotenv import load_dotenv
from os import environ

load_dotenv()
API_KEY = environ['API_KEY']
ADMIN_ID = int(environ['ADMIN_ID'])
DB_PATH = environ['DB_PATH']
REGISTRATION_URL_BASE = environ['REGISTRATION_URL_BASE']
TEACHER_USERNAME = environ['TEACHER_USERNAME']
STUDENTS_GROUP = environ.get('STUDENTS_GROUP', 'students')
STUDENT_DEFAULT_SHELL = environ.get('STUDENT_DEFAULT_SHELL', '/bin/bash')
STUDENTS_HOME_BASE = environ.get('STUDENTS_HOME_BASE', '/home')
DEBUG = bool(environ.get('DEBUG', True))
