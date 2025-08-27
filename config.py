import os
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
basedir = os.path.abspath(os.path.dirname(__file__))
# Путь к .env файлу в корневой папке проекта (на один уровень выше, чем папка app, где лежит config.py)
dotenv_path = os.path.join(basedir, '..', '.env')
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path)


class Config:
    # --- Ключевые настройки безопасности ---
    SECRET_KEY = os.environ.get('SECRET_KEY')
    ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD')

    # --- Настройки приложения (не секретные) ---
    USER_ROLES = ['Специалист КЦ', 'Менеджер ДКС', 'Менеджер отдела оформления', 'Менеджер ОГР', 'Админ']
    APPLICATION_STATUSES = ['В работе', 'Выполнено', 'Частично выполнено', 'Отклонено', 'Закрыто']
    APPLICATION_SOURCES = ['Звонок', 'Телеграм', 'Офис', 'Другое']

    # --- Настройки почтового сервера (ВОЗВРАЩЕНЫ К ИСХОДНЫМ) ---
    MAIL_SERVER = os.environ.get('MAIL_SERVER', 'mail.gh.uz')

    # --- НАЧАЛО ИЗМЕНЕНИЯ ---
    # Возвращаем правильные настройки для работы через STARTTLS
    MAIL_USE_SSL = False
    MAIL_USE_TLS = True
    # Стандартный порт для TLS - 587
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
    # --- КОНЕЦ ИЗМЕНЕНИЯ ---

    MAIL_ASCII_ATTACHMENTS = False

    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = ('Golden House CRM', os.environ.get('MAIL_DEFAULT_SENDER', os.environ.get('MAIL_USERNAME')))

    # --- Настройки удаленной БД MySQL ---
    SOURCE_MYSQL_USER = os.environ.get('SOURCE_MYSQL_USER')
    SOURCE_MYSQL_PASSWORD = os.environ.get('SOURCE_MYSQL_PASSWORD')
    SOURCE_MYSQL_HOST = os.environ.get('SOURCE_MYSQL_HOST', 'localhost')
    SOURCE_MYSQL_PORT = int(os.environ.get('SOURCE_MYSQL_PORT', 3306))
    SOURCE_MYSQL_DATABASE = os.environ.get('SOURCE_MYSQL_DATABASE')

    if all([SOURCE_MYSQL_USER, SOURCE_MYSQL_PASSWORD, SOURCE_MYSQL_HOST, SOURCE_MYSQL_DATABASE]):
        SOURCE_DATABASE_URI = f'mysql+pymysql://{SOURCE_MYSQL_USER}:{SOURCE_MYSQL_PASSWORD}@{SOURCE_MYSQL_HOST}:{SOURCE_MYSQL_PORT}/{SOURCE_MYSQL_DATABASE}'
    else:
        SOURCE_DATABASE_URI = None

    # --- Настройки локальной БД ---
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///' + os.path.join(basedir+'/instance/', 'app.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False