# app/__init__.py
import datetime
import os
from flask import Flask
from .extensions import db, mail, login_manager, migrate
from config import Config


# --- ГЛАВНАЯ ФАБРИКА ПРИЛОЖЕНИЯ ---

def create_app(config_class=Config):
    """
    Фабрика для создания экземпляра приложения Flask.
    Теперь она только настраивает приложение, не взаимодействуя с БД.
    """
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Инициализация расширений
    db.init_app(app)
    mail.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)  # Связываем Flask-Migrate с приложением и БД

    # Регистрация Blueprints (маршрутов)
    from .routes import main as main_blueprint
    app.register_blueprint(main_blueprint)

    from .auth import auth as auth_blueprint
    app.register_blueprint(auth_blueprint)

    # --- РЕГИСТРАЦИЯ CLI-КОМАНД ---
    # Эти команды заменяют старый код, который выполнялся при запуске.
    # Теперь вы управляете созданием данных из терминала.

    @app.cli.command("init-db")
    def init_db_command():
        """Заполняет справочники начальными данными."""
        _populate_initial_data(app)
        print("SUCCESS: Команда 'init-db' выполнена.")

    @app.cli.command("create-admin")
    def create_admin_command():
        """Создает пользователя admin по умолчанию."""
        _create_default_admin(app)

    # --- НАСТРОЙКА FLASK-LOGIN ---

    @login_manager.user_loader
    def load_user(user_id):
        from .models import User
        return User.query.get(int(user_id))

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


def _create_default_admin(app):
    """
    Проверяет наличие администратора по умолчанию и создает его, если он отсутствует.
    """
    with app.app_context():
        from .models import User
        admin_username = app.config.get('ADMIN_USERNAME')
        admin_password = app.config.get('ADMIN_PASSWORD')

        if not all([admin_username, admin_password]):
            print("WARNING: ADMIN_USERNAME или ADMIN_PASSWORD не установлены. Создание админа пропущено.")
            return

        if User.query.filter_by(username=admin_username).first():
            print(f"INFO: Пользователь '{admin_username}' уже существует.")
            return

        print(f"INFO: Пользователь '{admin_username}' не найден. Создание нового...")
        user = User(username=admin_username, role='Админ')
        user.set_password(admin_password)
        db.session.add(user)
        db.session.commit()
        print(f"SUCCESS: Пользователь '{admin_username}' успешно создан.")