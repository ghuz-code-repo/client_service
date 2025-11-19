# run.py
import os
import sys
import threading
import time
from dotenv import load_dotenv
from flask import Flask, url_for
from flask_sqlalchemy import SQLAlchemy
from werkzeug.middleware.proxy_fix import ProxyFix
from prefix_middleware import PrefixMiddleware

# Fix encoding for Docker logs
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

# Загружаем переменные окружения из файла .env в самом начале
# Это нужно сделать до импорта app и config, чтобы они "увидели" эти переменные
load_dotenv()
from app import create_app
from data_sync import sync_data, create_database

# Import service discovery and auth-connector
try:
    from auth_connector.service_discovery import init_service_discovery_flask
    from auth_connector import AuthClient, PermissionRegistry
    auth_connector_available = True
except ImportError:
    init_service_discovery_flask = None
    auth_connector_available = False
    print("⚠️ auth-connector not installed, service discovery disabled")



# Создаем экземпляр приложения с помощью нашей фабрики
app = create_app()

# --- ФОНОВАЯ СИНХРОНИЗАЦИЯ ---
def background_sync_task(app_context):
    """
    Задача, которая выполняется в фоновом потоке для периодической синхронизации.
    """
    # Устанавливаем интервал в часах
    sync_interval_hours = 4
    sync_interval_seconds = sync_interval_hours * 3600

    while True:
        # Сначала ждем указанный интервал
        from datetime import datetime, timedelta
        next_sync_time = datetime.now() + timedelta(hours=sync_interval_hours)
        print(f"\n{'='*70}")
        print(f"📅 СЛЕДУЮЩАЯ ФОНОВАЯ СИНХРОНИЗАЦИЯ ЗАПЛАНИРОВАНА:")
        print(f"   Через: {sync_interval_hours} часа(ов)")
        print(f"   Время: {next_sync_time.strftime('%d.%m.%Y %H:%M:%S')}")
        print(f"{'='*70}\n")
        
        time.sleep(sync_interval_seconds)

        # Затем выполняем синхронизацию
        print(f"\n{'='*70}")
        print(f"🔄 ЗАПУСК ФОНОВОЙ СИНХРОНИЗАЦИИ")
        print(f"   Время: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}")
        print(f"{'='*70}\n")
        
        with app_context:
            sync_data()
        
        print(f"\n{'='*70}")
        print(f"✅ ФОНОВАЯ СИНХРОНИЗАЦИЯ ЗАВЕРШЕНА")
        print(f"   Время: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}")
        print(f"{'='*70}\n")

# behind_proxy = os.getenv('BEHIND_PROXY', 'false').lower() == 'true'
# prefix = '/client-service' if behind_proxy else ''
# print(f"Using URL prefix: '{
#       }'")

# Configure app to work behind a proxy
# НЕ используем x_prefix=1, т.к. nginx делает rewrite и убирает префикс
# Префикс нужен только для генерации внешних URL, но не для внутренней маршрутизации
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=0)

# Initialization function (called both from Gunicorn and direct run)
def initialize_app():
    """Initialize database, run migrations, and setup auth connector"""
    # 1. Создаем локальную базу данных и таблицы (если их нет)
    create_database(app)
    
    # 1.5 Выполняем все Alembic миграции автоматически
    print("\n🔄 Применение миграций базы данных...")
    try:
        from flask_migrate import upgrade as flask_migrate_upgrade
        with app.app_context():
            flask_migrate_upgrade()
        print("✅ Миграции успешно применены")
    except Exception as e:
        print(f"⚠️  Ошибка применения миграций: {e}")
        print("Продолжаем запуск...")
    
    # 1.6 Автоматическая миграция для добавления новых полей (fallback)
    with app.app_context():
        from app import db
        try:
            print("\n🔧 Проверка и добавление полей housing_complex и house_number...")
            db.session.execute(db.text('ALTER TABLE applications ADD COLUMN housing_complex VARCHAR(255)'))
            db.session.commit()
            print("✅ Поле housing_complex добавлено")
        except Exception as e:
            if 'duplicate column name' in str(e).lower() or 'already exists' in str(e).lower():
                pass  # Поле уже существует
            else:
                db.session.rollback()
        
        try:
            db.session.execute(db.text('ALTER TABLE applications ADD COLUMN house_number VARCHAR(255)'))
            db.session.commit()
            print("✅ Поле house_number добавлено")
        except Exception as e:
            if 'duplicate column name' in str(e).lower() or 'already exists' in str(e).lower():
                pass  # Поле уже существует
            else:
                db.session.rollback()

    # 2. Выполняем ПЕРВУЮ и ЕДИНСТВЕННУЮ синхронизацию данных при запуске
    with app.app_context():
        sync_data()

    # ========== AUTH-CONNECTOR INTEGRATION ==========
    
    if auth_connector_available:
        try:
            # 3A. Permission Registry (декларирование разрешений)
            print("\n" + "="*70)
            print("📋 Initializing Permission Registry")
            print("="*70)
            
            registry = PermissionRegistry("client-service")
            
            # Заявки (Applications)
            registry.register(
                "client-service.applications.view",
                "Просмотр заявок",
                "Разрешение на просмотр всех заявок",
                "applications"
            )
            registry.register(
                "client-service.applications.create",
                "Создание заявок",
                "Разрешение на создание новых заявок",
                "applications"
            )
            registry.register(
                "client-service.applications.edit",
                "Редактирование заявок",
                "Разрешение на редактирование заявок",
                "applications"
            )
            registry.register(
                "client-service.applications.delete",
                "Удаление заявок",
                "Разрешение на удаление заявок",
                "applications"
            )
            registry.register(
                "client-service.applications.assign",
                "Назначение ответственных",
                "Разрешение на назначение ответственных",
                "applications"
            )
            registry.register(
                "client-service.applications.status.change",
                "Изменение статуса",
                "Разрешение на изменение статуса заявок",
                "applications"
            )
            registry.register(
                "client-service.applications.export",
                "Экспорт заявок",
                "Разрешение на экспорт заявок в Excel",
                "applications"
            )
            
            # Ответственные лица (Responsible)
            registry.register(
                "client-service.responsible.view",
                "Просмотр ответственных",
                "Разрешение на просмотр ответственных лиц",
                "responsible"
            )
            registry.register(
                "client-service.responsible.create",
                "Создание ответственных",
                "Разрешение на создание ответственных лиц",
                "responsible"
            )
            registry.register(
                "client-service.responsible.edit",
                "Редактирование ответственных",
                "Разрешение на редактирование ответственных лиц",
                "responsible"
            )
            registry.register(
                "client-service.responsible.delete",
                "Удаление ответственных",
                "Разрешение на удаление ответственных лиц",
                "responsible"
            )
            
            # Администрирование
            registry.register(
                "client-service.admin.panel",
                "Панель администратора",
                "Доступ к панели администратора",
                "admin"
            )
            registry.register(
                "client-service.admin.users",
                "Управление пользователями",
                "Управление пользователями системы",
                "admin"
            )
            registry.register(
                "client-service.admin.settings",
                "Настройки системы",
                "Управление настройками системы",
                "admin"
            )
            registry.register(
                "client-service.admin.logs",
                "Просмотр логов",
                "Доступ к системным логам",
                "admin"
            )
            
            print(f"✅ Registered {len(registry.get_all_permissions())} permissions")
            
            # 3B. Auth Client (для синхронизации)
            auth_client = AuthClient(
                auth_service_url=os.getenv('AUTH_SERVICE_URL', 'http://auth-service:80'),
                service_key="client-service",
                timeout=10
            )
            
            # Синхронизация разрешений с auth-service
            try:
                permissions_data = registry.to_dict()['permissions']
                if auth_client.sync_permissions(permissions_data):
                    print(f"✅ Permissions synced with auth-service")
                else:
                    print(f"⚠️ Failed to sync permissions with auth-service")
            except Exception as e:
                print(f"⚠️ Permission sync error: {e}")
            
            # 3C. Service Discovery (автоматическая регистрация)
            print("\n" + "="*70)
            print("🚀 Initializing Service Discovery")
            print("="*70)
            
            service_discovery_client = init_service_discovery_flask(
                app,
                service_key="client-service",
                internal_url="http://client-service-service:80",
                registry_url=os.getenv('AUTH_SERVICE_URL', 'http://auth-service:80') + '/api/registry',
                heartbeat_interval=30
            )
            print("✅ Service discovery initialized")
            
        except Exception as e:
            print(f"⚠️ Auth-connector initialization failed: {e}")
            import traceback
            traceback.print_exc()
    
    # ================================================

    # 4. Запускаем периодическую синхронизацию в отдельном фоновом потоке
    print("\nЗапуск фонового процесса для периодической синхронизации данных...")
    sync_thread = threading.Thread(target=background_sync_task, args=(app.app_context(),))
    sync_thread.daemon = True  # Поток завершится при выходе из основного приложения
    sync_thread.start()

# Initialize app when module is loaded (for Gunicorn)
initialize_app()

if __name__ == '__main__':
    # 5. Запускаем веб-приложение Flask (только при прямом запуске)
    print("\nЗапуск веб-приложения Flask...")
    # Для production используйте Gunicorn или другой WSGI-сервер
    # use_reloader=False чтобы избежать двойного запуска синхронизации
    app.run(host='0.0.0.0', port=80, debug=False, use_reloader=False)