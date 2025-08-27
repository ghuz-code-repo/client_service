"""
Скрипт для добавления поля author_id в таблицу application_logs
"""

import sqlite3
import sys
from datetime import datetime

def migrate_database(db_path='instance/app.db'):
    """Добавляет поле author_id в таблицу application_logs"""
    
    try:
        # Подключаемся к базе данных
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        print(f"Подключение к базе данных: {db_path}")
        
        # Проверяем, существует ли уже это поле
        cursor.execute("PRAGMA table_info(application_logs)")
        log_columns = [column[1] for column in cursor.fetchall()]
        
        # Добавляем поле author_id в таблицу application_logs
        if 'author_id' not in log_columns:
            print("Добавление поля author_id в таблицу application_logs...")
            cursor.execute("ALTER TABLE application_logs ADD COLUMN author_id INTEGER REFERENCES users(id)")
            print("✓ Поле author_id добавлено")
        else:
            print("- Поле author_id уже существует")
        
        # Сохраняем изменения
        conn.commit()
        print("\n✅ Миграция успешно завершена!")
        
    except Exception as e:
        print(f"\n❌ Ошибка при выполнении миграции: {e}")
        if conn:
            conn.rollback()
        sys.exit(1)
        
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    # Можно передать путь к БД как аргумент
    db_path = sys.argv[1] if len(sys.argv) > 1 else 'instance/app.db'
    migrate_database(db_path)
