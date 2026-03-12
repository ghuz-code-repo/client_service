#!/usr/bin/env python3
"""
Скрипт автоматического создания пользователей в gateway
Создает пользователей через auth-service API
"""

import sys
import requests
import time

# Fix encoding
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

# Gateway API configuration
AUTH_SERVICE_URL = "http://auth-service:80"

# Данные пользователей из таблицы
USERS = [
    {"username": "Mehroj", "password": "User1", "full_name": "Мехрож", "phone": "+998901234569"},
    {"username": "Charos", "password": "User5", "full_name": "Чарос", "phone": "+998901234570"},
    {"username": "LuizaP", "password": "User1986", "full_name": "Луиза", "phone": "+998901234568"},
    {"username": "Aliya", "password": "UserLera", "full_name": "Алия", "phone": "+998901234571"},
    {"username": "Dmitriy", "password": "UserMahal1", "full_name": "Дмитрий", "phone": "+998901234572"},
    {"username": "AndreyT", "password": "UserLiana", "full_name": "Андрей Т", "phone": "+998901234573"},
    {"username": "DavronU", "password": "User3534", "full_name": "Даврон У", "phone": "+998901234574"},
    {"username": "Alina", "password": "User2", "full_name": "Алина", "phone": "+998901234576"},
    {"username": "Karina", "password": "UserKarina", "full_name": "Карина", "phone": "+998901234575"},
    {"username": "Sanjar", "password": "UserDoc", "full_name": "Санжар", "phone": "+998901234577"},
    {"username": "AndreyK", "password": "UserKogay", "full_name": "Андрей К", "phone": "+998901234578"},
    {"username": "Dilnoz Hasanova", "password": "UserAndrea", "full_name": "Дильноз Хасанова", "phone": "+998901234579"},
    {"username": "Ruslan Kunanbayev", "password": "User7020", "full_name": "Руслан Кунанбаев", "phone": "+998901234582"},
]

# Дополнительные пользователи (admin, test, AnvarN - не в таблице, но были в DRY RUN)
ADDITIONAL_USERS = [
    {"username": "admin", "password": "admin123", "full_name": "Администратор", "phone": "+998901234567"},
    {"username": "test", "password": "test123", "full_name": "Тестовый пользователь", "phone": "+998901234580"},
    {"username": "AnvarN", "password": "anvar123", "full_name": "Анвар", "phone": "+998901234581"},
]

def generate_email(username):
    """Генерирует email из username"""
    # Убираем пробелы и делаем lowercase
    clean_username = username.replace(" ", "").lower()
    return f"{clean_username}@newcity.uz"


def create_user_in_gateway(user_data, admin_token=None):
    """
    Создает пользователя в gateway через API
    
    Args:
        user_data (dict): Данные пользователя (username, password, full_name, phone)
        admin_token (str): JWT токен администратора (если требуется)
    
    Returns:
        dict: Созданный пользователь или None при ошибке
    """
    username = user_data['username']
    password = user_data['password']
    full_name = user_data['full_name']
    phone = user_data['phone']
    email = generate_email(username)
    
    # Разделим full_name на части (last_name first_name)
    name_parts = full_name.split(maxsplit=1)
    last_name = name_parts[0] if name_parts else full_name
    first_name = name_parts[1] if len(name_parts) > 1 else ""
    
    # Form data для POST /api/users/
    payload = {
        "username": username,
        "password": password,
        "email": email,
        "last_name": last_name,
        "first_name": first_name,
        "phone": phone,
        "system_admin": "false"  # Не делаем системными админами
    }
    
    headers = {}
    if admin_token:
        headers['Authorization'] = f'Bearer {admin_token}'
    
    try:
        print(f"\n👤 Создание пользователя: {username}")
        print(f"   📧 Email: {email}")
        print(f"   📱 Phone: {phone}")
        print(f"   👤 Full name: {full_name}")
        
        # Попытка создать пользователя через form data
        response = requests.post(
            f"{AUTH_SERVICE_URL}/api/users/",
            data=payload,  # form data вместо json
            headers=headers,
            timeout=10
        )
        
        if response.status_code == 200:
            result = response.json()
            if result.get('success'):
                print(f"   ✅ Успешно создан")
                return {"username": username, "_id": "created"}
            else:
                error = result.get('error', 'Unknown error')
                print(f"   ❌ Ошибка: {error}")
                return None
        else:
            print(f"   ❌ Ошибка: {response.status_code}")
            print(f"   {response.text[:200]}")
            return None
            
    except Exception as e:
        print(f"   ❌ Исключение: {e}")
        return None


def create_all_users():
    """Создает всех пользователей из списка"""
    print("\n" + "="*70)
    print("🚀 СОЗДАНИЕ ПОЛЬЗОВАТЕЛЕЙ В GATEWAY")
    print("="*70)
    
    all_users = USERS + ADDITIONAL_USERS
    print(f"Всего пользователей для создания: {len(all_users)}")
    print("="*70)
    
    stats = {
        'total': len(all_users),
        'created': 0,
        'already_exists': 0,
        'errors': 0
    }
    
    created_users = []
    
    for user_data in all_users:
        result = create_user_in_gateway(user_data)
        if result:
            if result.get('_id'):
                stats['created'] += 1
                created_users.append(result)
            else:
                stats['already_exists'] += 1
        else:
            stats['errors'] += 1
        
        # Небольшая задержка между запросами
        time.sleep(0.2)
    
    # Финальный отчет
    print("\n" + "="*70)
    print("📊 ИТОГОВЫЙ ОТЧЕТ")
    print("="*70)
    print(f"Всего пользователей:           {stats['total']}")
    print(f"✅ Успешно создано:            {stats['created']}")
    print(f"ℹ️  Уже существовало:          {stats['already_exists']}")
    print(f"❌ Ошибок:                     {stats['errors']}")
    print("="*70)
    
    if stats['created'] > 0 or stats['already_exists'] > 0:
        print("\n✅ Пользователи готовы!")
        print("Следующий шаг: Запустить миграцию связывания")
        print("   docker compose run --rm client-service-service python migrate_users_to_gateway.py --execute\n")
    
    return created_users


if __name__ == '__main__':
    create_all_users()
