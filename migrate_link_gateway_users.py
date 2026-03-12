#!/usr/bin/env python3
"""
Скрипт миграции: Связывание локальных пользователей с Gateway по username.

Этот скрипт:
1. Подключается к MongoDB Gateway напрямую
2. Находит пользователей Gateway по username (часть email до @)
3. Обновляет поле auth_user_id в локальной SQLite БД client-service через Flask/SQLAlchemy

Использование:
    python migrate_link_gateway_users.py --dry-run  # Проверка без изменений
    python migrate_link_gateway_users.py --execute  # Выполнить миграцию
"""

import os
import sys
from pymongo import MongoClient
from bson.objectid import ObjectId

# Flask imports
from app import create_app
from app.models import User
from app.extensions import db

# Маппинг локальных username на username в Gateway (часть email до @)
# Формат: 'локальный_username': 'gateway_username' (часть до @ в email)
USERNAME_GATEWAY_MAP = {
    'Mehroj': 'm.islombekov',
    'Charos': 'c.shafayziyeva',
    'Luiza': 'l.pulatova',  # Исправлено: было LuizaP
    'Aliya': 'a.anvarova',
    'Dmitriy': 'd.mezensev',
    'AndreyT': 'a.tokarev',
    'DavronU': 'd.urinov',
    'Alina': 'a.khayrullina',
    'Karina': 'k.gumerova',
    'Sanjar': 's.pulatov',
    'AndreyK': 'an.kogay',
    'Dilnoz Hasanova': 'd.xasanova',
    'Ruslan Kunanbayev': 'r.kunanbayev'
}

# MongoDB Gateway connection (доступ из контейнера client-service)
MONGO_HOST = os.getenv('GATEWAY_MONGO_HOST', 'gateway-mongo-1')
MONGO_PORT = int(os.getenv('GATEWAY_MONGO_PORT', '27017'))
MONGO_DB = os.getenv('GATEWAY_MONGO_DB', 'authdb')


def connect_to_gateway_mongo():
    """
    Подключается к MongoDB Gateway.
    
    Returns:
        pymongo.collection.Collection: Коллекция users или None при ошибке
    """
    try:
        client = MongoClient(MONGO_HOST, MONGO_PORT, serverSelectionTimeoutMS=5000)
        # Проверяем подключение
        client.server_info()
        
        db = client[MONGO_DB]
        users_collection = db['users']
        
        print(f"✅ Подключено к MongoDB: {MONGO_HOST}:{MONGO_PORT}/{MONGO_DB}")
        return users_collection
        
    except Exception as e:
        print(f"❌ Ошибка подключения к MongoDB Gateway: {e}")
        return None


def find_gateway_user_by_username(users_collection, gateway_username):
    """
    Находит пользователя Gateway по username в MongoDB.
    
    Args:
        users_collection: Коллекция users из MongoDB
        gateway_username (str): Username в Gateway (часть email до @)
        
    Returns:
        dict: Данные пользователя или None
    """
    try:
        user = users_collection.find_one({'username': gateway_username})
        return user
    except Exception as e:
        print(f"  ❌ Ошибка поиска в MongoDB: {e}")
        return None


def migrate_users(dry_run=True):
    """
    Основная функция миграции.
    
    Args:
        dry_run (bool): Если True, не вносит изменения в БД
    """
    print("=" * 80)
    print("МИГРАЦИЯ: Связывание локальных пользователей с Gateway по username")
    print("=" * 80)
    print(f"Режим: {'DRY RUN (без изменений)' if dry_run else 'EXECUTE (с изменениями)'}")
    print(f"MongoDB Gateway: {MONGO_HOST}:{MONGO_PORT}/{MONGO_DB}")
    print(f"БД client-service: SQLite через Flask/SQLAlchemy")
    print()
    
    # Подключаемся к MongoDB Gateway
    print("📥 Подключение к MongoDB Gateway...")
    users_collection = connect_to_gateway_mongo()
    
    if users_collection is None:
        print("❌ Не удалось подключиться к MongoDB Gateway.")
        return False
    
    print()
    
    total_users = len(USERNAME_GATEWAY_MAP)
    linked_users = 0
    not_found_local = []
    not_found_gateway = []
    already_linked = []
    
    for local_username, gateway_username in USERNAME_GATEWAY_MAP.items():
        print(f"[{linked_users + len(already_linked) + len(not_found_local) + len(not_found_gateway) + 1}/{total_users}] Обработка: {local_username} → {gateway_username}")
        
        # 1. Проверяем существование локального пользователя
        local_user = User.query.filter_by(username=local_username).first()
        
        if not local_user:
            print(f"  ❌ Локальный пользователь '{local_username}' не найден в БД")
            not_found_local.append(local_username)
            continue
        
        # 2. Проверяем, не связан ли уже
        if local_user.auth_user_id:
            print(f"  ℹ️  Уже связан: auth_user_id={local_user.auth_user_id}")
            already_linked.append(local_username)
            continue
        
        # 3. Ищем пользователя в Gateway MongoDB по username
        print(f"  🔍 Поиск в Gateway MongoDB: username={gateway_username}")
        gateway_user = find_gateway_user_by_username(users_collection, gateway_username)
        
        if not gateway_user:
            print(f"  ❌ Пользователь '{gateway_username}' не найден в Gateway")
            not_found_gateway.append(local_username)
            continue
        
        gateway_user_id = str(gateway_user.get('_id'))  # ObjectId -> string
        gateway_found_username = gateway_user.get('username')
        
        if not gateway_user_id:
            print(f"  ❌ Gateway вернул пользователя без _id")
            not_found_gateway.append(local_username)
            continue
        
        # 4. Связываем пользователей
        print(f"  ✅ Найден в Gateway: username={gateway_found_username}, id={gateway_user_id}")
        
        if not dry_run:
            local_user.auth_user_id = gateway_user_id
            db.session.add(local_user)
            print(f"  💾 Обновлен auth_user_id: {local_username} -> {gateway_user_id}")
        else:
            print(f"  🔸 [DRY RUN] Будет установлено: {local_username}.auth_user_id = {gateway_user_id}")
        
        linked_users += 1
        print()
    
    # Коммит изменений
    if not dry_run and linked_users > 0:
        try:
            db.session.commit()
            print("✅ Все изменения успешно сохранены в БД")
        except Exception as e:
            db.session.rollback()
            print(f"❌ Ошибка при сохранении: {e}")
            return False
    
    # Итоговый отчёт
    print()
    print("=" * 80)
    print("ИТОГИ МИГРАЦИИ")
    print("=" * 80)
    print(f"Всего пользователей для миграции: {total_users}")
    print(f"✅ Успешно связано: {linked_users}")
    print(f"ℹ️  Уже было связано: {len(already_linked)}")
    print(f"❌ Не найдено локально: {len(not_found_local)}")
    print(f"❌ Не найдено в Gateway: {len(not_found_gateway)}")
    
    if not_found_local:
        print(f"\n⚠️  Локальные пользователи не найдены: {', '.join(not_found_local)}")
    
    if not_found_gateway:
        print(f"\n⚠️  Gateway пользователи не найдены: {', '.join(not_found_gateway)}")
    
    if already_linked:
        print(f"\nℹ️  Уже связанные: {', '.join(already_linked)}")
    
    print()
    
    if dry_run:
        print("🔸 Это был DRY RUN. Для выполнения миграции запустите с --execute")
    else:
        print("✅ Миграция завершена!")
    
    return True


def main():
    """Точка входа."""
    app = create_app()
    
    with app.app_context():
        # Проверяем аргументы
        dry_run = True
        
        if len(sys.argv) > 1:
            if '--execute' in sys.argv:
                dry_run = False
                print("⚠️  РЕЖИМ ВЫПОЛНЕНИЯ: Изменения будут внесены в БД!")
                auto_confirm = os.environ.get('AUTO_CONFIRM', '').lower() == 'yes'
                if not auto_confirm:
                    confirm = input("Продолжить? (yes/no): ")
                    if confirm.lower() not in ['yes', 'y']:
                        print("Отменено пользователем")
                        return
                else:
                    print("✅ Автоматическое подтверждение (AUTO_CONFIRM=yes)")
            elif '--dry-run' in sys.argv:
                dry_run = True
            else:
                print("Использование:")
                print("  python migrate_link_gateway_users.py --dry-run   # Проверка")
                print("  python migrate_link_gateway_users.py --execute   # Выполнение")
                return
        
        # Запускаем миграцию
        success = migrate_users(dry_run=dry_run)
        sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
