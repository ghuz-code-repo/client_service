

import sqlite3
import sys
from datetime import datetime

def migrate_database(db_path='instance/app.db'):
    """Добавляет поле source в таблицу applications"""
    
    try:
        # Подключаемся к базе данных
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        print(f"Подключение к базе данных: {db_path}")
        
        # Проверяем, существует ли уже это поле
        cursor.execute("PRAGMA table_info(applications)")
        app_columns = [column[1] for column in cursor.fetchall()]
        
        # Добавляем поле source в таблицу applications
        if 'source' not in app_columns:
            print("Добавление поля source в таблицу applications...")
            cursor.execute("ALTER TABLE applications ADD COLUMN source VARCHAR(100)")
            
            # Устанавливаем значение по умолчанию для существующих записей
            cursor.execute("UPDATE applications SET source = 'Звонок' WHERE source IS NULL")
            print("✓ Поле source добавлено и заполнено значениями по умолчанию")
        else:
            print("- Поле source уже существует")
        
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
