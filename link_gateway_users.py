#!/usr/bin/env python3
"""
Скрипт миграции: Связывание локальных пользователей с Gateway.

Маппинг: username в client-service -> username в Gateway (часть email до @)
Пример: локальный 'Mehroj' -> Gateway username 'm.islombekov' (из m.islombekov@gh.uz)

Использование:
    python link_gateway_users.py --dry-run   # Проверка без изменений
    python link_gateway_users.py --execute   # Выполнить миграцию
"""

import sys
from pymongo import MongoClient
from bson import ObjectId

# Подключение к MongoDB Gateway
# Пробуем несколько вариантов подключения
MONGO_HOSTS = [
    "172.20.0.2:27017",  # Прямой IP MongoDB Gateway (получен через docker inspect)
    "gateway-mongo-1:27017",  # Если в той же Docker сети
    "host.docker.internal:27017",  # Через хост
]
MONGO_DB = "auth_service"

# Маппинг: локальный username -> Gateway username (часть email до @)
USERNAME_MAP = {
    'Mehroj': 'm.islombekov',
    'Charos': 'c.shafayziyeva',
    'LuizaP': 'l.pulatova',
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


def get_gateway_user_id(mongo_client, gateway_username):
    """
    Получает ID пользователя из MongoDB Gateway по username.
    
    Args:
        mongo_client: MongoClient подключение
        gateway_username: Username в Gateway (например, 'm.islombekov')
        
    Returns:
        str: ObjectId пользователя или None
    """
    try:
        db = mongo_client[MONGO_DB]
        users_collection = db['users']
        
        user = users_collection.find_one({'username': gateway_username})
        
        if user and '_id' in user:
            return str(user['_id'])
        
        return None
        
    except Exception as e:
        print(f"  ❌ Ошибка при поиске в MongoDB: {e}")
        return None


def migrate_users(dry_run=True):
    """
    Основная функция миграции.
    
    Args:
        dry_run: Если True, не вносит изменения в БД
    """
    from app import create_app
    from app.models import User
    from app.extensions import db
    
    print("=" * 80)
    print("МИГРАЦИЯ: Связывание локальных пользователей с Gateway")
    print("=" * 80)
    print(f"Режим: {'DRY RUN (без изменений)' if dry_run else 'EXECUTE (с изменениями)'}")
    print(f"MongoDB Database: {MONGO_DB}")
    print()
    
    # Подключаемся к MongoDB Gateway (пробуем разные хосты)
    mongo_client = None
    connected_uri = None
    
    for mongo_host in MONGO_HOSTS:
        try:
            print(f"📥 Попытка подключения к MongoDB: {mongo_host}...")
            test_client = MongoClient(f"mongodb://{mongo_host}/", serverSelectionTimeoutMS=3000)
            test_client.admin.command('ping')
            mongo_client = test_client
            connected_uri = mongo_host
            print(f"✅ Успешное подключение к MongoDB: {mongo_host}")
            print()
            break
        except Exception as e:
            print(f"  ⚠️  Не удалось подключиться к {mongo_host}: {e}")
            continue
    
    if not mongo_client:
        print("❌ Не удалось подключиться ни к одному MongoDB хосту")
        return False
    
    # Создаем контекст Flask приложения
    app = create_app()
    
    with app.app_context():
        total_users = len(USERNAME_MAP)
        linked_users = 0
        not_found_local = []
        not_found_gateway = []
        already_linked = []
        
        for local_username, gateway_username in USERNAME_MAP.items():
            counter = len([linked_users, *already_linked, *not_found_local, *not_found_gateway])
            print(f"[{counter + 1}/{total_users}] Обработка: {local_username} -> {gateway_username}")
            
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
            
            # 3. Получаем ID пользователя из Gateway
            print(f"  🔍 Поиск в Gateway: username={gateway_username}")
            gateway_user_id = get_gateway_user_id(mongo_client, gateway_username)
            
            if not gateway_user_id:
                print(f"  ❌ Пользователь '{gateway_username}' не найден в Gateway")
                not_found_gateway.append(local_username)
                continue
            
            # 4. Связываем пользователей
            print(f"  ✅ Найден в Gateway: user_id={gateway_user_id}")
            
            if not dry_run:
                local_user.auth_user_id = gateway_user_id
                db.session.add(local_user)
                print(f"  💾 Обновлен auth_user_id: {local_user.username} -> {gateway_user_id}")
            else:
                print(f"  🔸 [DRY RUN] Будет установлено: {local_user.username}.auth_user_id = {gateway_user_id}")
            
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
        
        # Закрываем MongoDB подключение
        mongo_client.close()
        
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
    # Проверяем аргументы
    dry_run = True
    
    if len(sys.argv) > 1:
        if '--execute' in sys.argv:
            dry_run = False
            print("⚠️  РЕЖИМ ВЫПОЛНЕНИЯ: Изменения будут внесены в БД!")
        elif '--dry-run' in sys.argv:
            dry_run = True
        else:
            print("Использование:")
            print("  python link_gateway_users.py --dry-run   # Проверка")
            print("  python link_gateway_users.py --execute   # Выполнение")
            return
    
    # Запускаем миграцию
    success = migrate_users(dry_run=dry_run)
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
