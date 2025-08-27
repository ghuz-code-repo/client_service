# run.py
import os
import threading
import time
from dotenv import load_dotenv
from flask import Flask, url_for
from flask_sqlalchemy import SQLAlchemy
from werkzeug.middleware.proxy_fix import ProxyFix
from prefix_middleware import PrefixMiddleware
# Загружаем переменные окружения из файла .env в самом начале
# Это нужно сделать до импорта app и config, чтобы они "увидели" эти переменные
load_dotenv()
from app import create_app
from data_sync import sync_data, create_database



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
        # --- ИЗМЕНЕНИЕ ЗДЕСЬ ---
        # Сначала ждем указанный интервал.
        print(f"\nСледующая фоновая синхронизация запланирована через {sync_interval_hours} часа(ов)...")
        time.sleep(sync_interval_seconds)

        # Затем выполняем синхронизацию.
        with app_context:
            sync_data()

# behind_proxy = os.getenv('BEHIND_PROXY', 'false').lower() == 'true'
# prefix = '/client-service' if behind_proxy else ''
# print(f"Using URL prefix: '{
#       }'")

# Configure app to work behind a proxy
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# Direct route handler for static files with the prefix
@app.route('/client-service/static/<path:filename>')
def custom_static(filename):
    print(f"Custom static file request for: {filename}")
    return app.send_static_file(filename)

# Apply PrefixMiddleware if running behind proxy
# if behind_proxy:
#     app.wsgi_app = PrefixMiddleware(app.wsgi_app, app=app, prefix=prefix)
#     print(f"Applied PrefixMiddleware with prefix: {prefix}")
    
    # Test URL generation to debug
    # with app.test_request_context():
    #     print(f"Test static URL: {url_for('static', filename='css/common.css')}")

# app.config.update(
#     SERVER_NAME=None,  # Set to None to avoid URL generation issues
#     APPLICATION_ROOT=prefix,
# )


if __name__ == '__main__':
    # 1. Создаем локальную базу данных и таблицы (если их нет)
    create_database(app)

    # 2. Выполняем ПЕРВУЮ и ЕДИНСТВЕННУЮ синхронизацию данных при запуске
    with app.app_context():
        sync_data()

    # 3. Запускаем периодическую синхронизацию в отдельном фоновом потоке
    print("\nЗапуск фонового процесса для периодической синхронизации данных...")
    sync_thread = threading.Thread(target=background_sync_task, args=(app.app_context(),))
    sync_thread.daemon = True  # Поток завершится при выходе из основного приложения
    sync_thread.start()

    # 4. Запускаем веб-приложение Flask
    print("\nЗапуск веб-приложения Flask...")
    # Для production используйте Gunicorn или другой WSGI-сервер
    # debug=True и use_reloader=True не должны использоваться в production
    app.run(host='0.0.0.0', port=80, debug=app.config.get('DEBUG', True), use_reloader=True)