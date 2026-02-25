# app/__init__.py
import datetime
import os
import base64
from flask import Flask, g, request
from .extensions import db, mail, migrate
from config import Config


# --- ГЛАВНАЯ ФАБРИКА ПРИЛОЖЕНИЯ ---

def create_app(config_class=Config):
    """
    Фабрика для создания экземпляра приложения Flask.
    Теперь она только настраивает приложение, не взаимодействуя с БД.
    """
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Применяем PrefixMiddleware для корректной работы url_for() с префиксом
    from prefix_middleware import PrefixMiddleware
    app.wsgi_app = PrefixMiddleware(app.wsgi_app, prefix='/client-service')

    # Инициализация расширений
    db.init_app(app)
    mail.init_app(app)
    migrate.init_app(app, db)  # Связываем Flask-Migrate с приложением и БД

    # ========== AUTH-CONNECTOR INTEGRATION ==========
    
    @app.before_request
    def process_gateway_headers():
        """
        Обработка заголовков от gateway перед каждым запросом.
        Аутентификация полностью через Gateway.
        """
        # Извлечение данных пользователя из заголовков
        g.auth_user_id = request.headers.get('X-User-ID')
        g.username = request.headers.get('X-User-Name')
        g.email = request.headers.get('X-User-Email', '')
        g.phone = request.headers.get('X-User-Phone', '')
        
        # Аватар пользователя
        avatar_path = request.headers.get('X-User-Avatar', '')
        if avatar_path:
            # Если путь начинается с /avatar/, это эндпоинт Gateway
            g.avatar_url = f"http://localhost{avatar_path}"
        else:
            g.avatar_url = ''
        
        # Декодирование полного имени из base64
        encoded_name = request.headers.get('X-User-Full-Name', '')
        encoding = request.headers.get('X-User-Full-Name-Encoding', '')
        if encoding == 'base64' and encoded_name:
            try:
                g.full_name = base64.b64decode(encoded_name).decode('utf-8')
            except Exception as e:
                app.logger.warning(f"Failed to decode full name: {e}")
                g.full_name = ''
        else:
            g.full_name = encoded_name
        
        # Флаг администратора
        g.is_admin = request.headers.get('X-User-Admin', 'false').lower() == 'true'
        
        # Роли и разрешения для сервиса
        service_roles = request.headers.get('X-User-Service-Roles', '')
        g.service_roles = [r.strip() for r in service_roles.split(',') if r.strip()]
        
        service_perms = request.headers.get('X-User-Service-Permissions', '')
        g.service_permissions = [p.strip() for p in service_perms.split(',') if p.strip()]
        
        # Debug logging
        if g.auth_user_id:
            app.logger.debug(f"Gateway auth: user={g.username}, roles={g.service_roles}, permissions={len(g.service_permissions)}")
    
    # ================================================

    # Регистрация Blueprints (маршрутов)
    from .routes import main as main_blueprint
    app.register_blueprint(main_blueprint)

    from .auth import auth as auth_blueprint
    app.register_blueprint(auth_blueprint)
    
    # Добавляем функции для шаблонов (после регистрации blueprints)
    @app.context_processor
    def inject_gateway_auth():
        """Добавляет функции Gateway auth в контекст всех шаблонов"""
        from .auth_utils import (
            is_authenticated, 
            get_current_username,
            get_current_full_name,
            get_user_avatar_url,
            is_admin as gateway_is_admin_func, 
            has_permission,
            has_role,
        )
        
        return {
            'gateway_is_authenticated': is_authenticated,
            'gateway_username': get_current_username,
            'gateway_full_name': get_current_full_name,
            'gateway_avatar_url': get_user_avatar_url,
            'gateway_is_admin': gateway_is_admin_func,
            'gateway_has_permission': has_permission,
            'gateway_has_role': has_role,
        }

    # --- РЕГИСТРАЦИЯ CLI-КОМАНД ---
    # Эти команды заменяют старый код, который выполнялся при запуске.
    # Теперь вы управляете созданием данных из терминала.

    @app.cli.command("init-db")
    def init_db_command():
        """Заполняет справочники начальными данными."""
        _populate_initial_data(app)
        print("SUCCESS: Команда 'init-db' выполнена.")

    # --- КОНТЕКСТНЫЙ ПРОЦЕССОР ---

    @app.context_processor
    def inject_user_and_year():
        return {'current_year': datetime.date.today().year}
    
    return app


# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (остаются без изменений, но вызываются по-другому) ---

def _populate_initial_data(app):
    """
    Заполняет справочники начальными данными, если они пусты.
    """
    with app.app_context():
        from .models import ApplicationType
        if ApplicationType.query.count() == 0:
            print("INFO: Таблица 'application_types' пуста. Заполнение начальными данными...")
            initial_types = [
                {'name': 'Дефекты', 'template_filename': 'defects_template.docx', 'has_defect_list': True, 'execution_days': 3},
                {'name': 'Претензия', 'template_filename': 'claim_template.docx', 'has_defect_list': False, 'execution_days': 5},
                {'name': 'Переоформление', 'template_filename': 'reissue_template.docx', 'has_defect_list': False, 'execution_days': 7}
            ]
            for app_type_data in initial_types:
                new_type = ApplicationType(**app_type_data)
                db.session.add(new_type)

            db.session.commit()
            print("SUCCESS: Начальные типы заявок добавлены.")
        else:
            print("INFO: Таблица 'application_types' уже содержит данные. Заполнение пропущено.")