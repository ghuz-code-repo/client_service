#!/usr/bin/env python3
"""
Скрипт миграции пользователей client-service в gateway
Связывает локальных пользователей с пользователями gateway через auth_user_id
"""

import sys
import argparse
import requests
from app import create_app
from app.models import User
from app.extensions import db

# Fix encoding
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

# Gateway API configuration
AUTH_SERVICE_URL = "http://auth-service:80"


def search_gateway_user(username):
    """Поиск пользователя в gateway по username"""
    try:
        response = requests.get(
            f"{AUTH_SERVICE_URL}/api/users/search",
            params={"username": username},
            timeout=10
        )
        if response.status_code == 200:
            users = response.json().get('users', [])
            if users:
                return users[0]  # Возвращаем первого найденного
        return None
    except Exception as e:
        print(f"⚠️ Ошибка поиска пользователя '{username}': {e}")
        return None


def migrate_users(dry_run=True):
    """
    Миграция пользователей client-service в gateway
    
    Args:
        dry_run (bool): Если True, выполняется без изменений (только отчет)
    """
    app = create_app()
    
    with app.app_context():
        # Получаем всех локальных пользователей
        local_users = User.query.all()
        
        print("\n" + "="*70)
        print("🔄 МИГРАЦИЯ ПОЛЬЗОВАТЕЛЕЙ CLIENT-SERVICE → GATEWAY")
        print("="*70)
        print(f"Режим: {'🔍 DRY RUN (без изменений)' if dry_run else '✍️  РЕАЛЬНАЯ МИГРАЦИЯ'}")
        print(f"Всего локальных пользователей: {len(local_users)}")
        print("="*70 + "\n")
        
        stats = {
            'total': len(local_users),
            'already_linked': 0,
            'found_in_gateway': 0,
            'not_found': 0,
            'linked': 0,
            'errors': 0
        }
        
        for user in local_users:
            print(f"\n👤 Пользователь: {user.username} (роль: {user.role})")
            
            # Проверяем, уже связан ли
            if user.auth_user_id:
                print(f"   ✅ Уже связан с gateway (auth_user_id: {user.auth_user_id})")
                stats['already_linked'] += 1
                continue
            
            # Ищем в gateway
            print(f"   🔍 Поиск в gateway...")
            gateway_user = search_gateway_user(user.username)
            
            if gateway_user:
                gateway_id = gateway_user.get('_id')
                gateway_name = gateway_user.get('username')
                gateway_email = gateway_user.get('email', 'N/A')
                
                print(f"   ✅ Найден в gateway:")
                print(f"      - ID: {gateway_id}")
                print(f"      - Username: {gateway_name}")
                print(f"      - Email: {gateway_email}")
                
                stats['found_in_gateway'] += 1
                
                if not dry_run:
                    try:
                        user.auth_user_id = gateway_id
                        db.session.commit()
                        print(f"   ✅ Связан с gateway (auth_user_id установлен)")
                        stats['linked'] += 1
                    except Exception as e:
                        db.session.rollback()
                        print(f"   ❌ Ошибка при сохранении: {e}")
                        stats['errors'] += 1
                else:
                    print(f"   🔍 [DRY RUN] Будет связан с auth_user_id={gateway_id}")
            else:
                print(f"   ⚠️  НЕ найден в gateway")
                print(f"      Необходимо создать пользователя в gateway вручную")
                stats['not_found'] += 1
        
        # Финальный отчет
        print("\n" + "="*70)
        print("📊 ИТОГОВЫЙ ОТЧЕТ")
        print("="*70)
        print(f"Всего пользователей:           {stats['total']}")
        print(f"Уже связаны с gateway:         {stats['already_linked']}")
        print(f"Найдено в gateway:             {stats['found_in_gateway']}")
        print(f"Не найдено в gateway:          {stats['not_found']}")
        
        if not dry_run:
            print(f"✅ Успешно связано:            {stats['linked']}")
            print(f"❌ Ошибки при связывании:      {stats['errors']}")
        else:
            print(f"🔍 Будет связано:              {stats['found_in_gateway']}")
        
        print("="*70 + "\n")
        
        # Рекомендации
        if stats['not_found'] > 0:
            print("⚠️  ВНИМАНИЕ:")
            print(f"   {stats['not_found']} пользователей не найдено в gateway.")
            print("   Необходимо:")
            print("   1. Создать этих пользователей в gateway через UI")
            print("   2. Запустить скрипт повторно\n")
        
        if dry_run and stats['found_in_gateway'] > 0:
            print("✅ Для выполнения реальной миграции запустите:")
            print("   python migrate_users_to_gateway.py --execute\n")


def main():
    parser = argparse.ArgumentParser(
        description='Миграция пользователей client-service в gateway'
    )
    parser.add_argument(
        '--execute',
        action='store_true',
        help='Выполнить реальную миграцию (по умолчанию: dry run)'
    )
    
    args = parser.parse_args()
    
    migrate_users(dry_run=not args.execute)


if __name__ == '__main__':
    main()
