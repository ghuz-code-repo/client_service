"""
Скрипт для добавления новых полей в базу данных:
1. due_date и completed_at в таблицу applications
2. execution_days в таблицу application_types
"""

import sqlite3
import sys
from datetime import datetime

def migrate_database(db_path='instance/app.db'):
    """Добавляет новые поля в существующую базу данных"""
    
    try:
        # Подключаемся к базе данных
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        print(f"Подключение к базе данных: {db_path}")
        
        # Проверяем, существуют ли уже эти поля
        cursor.execute("PRAGMA table_info(applications)")
        app_columns = [column[1] for column in cursor.fetchall()]
        
        cursor.execute("PRAGMA table_info(application_types)")
        type_columns = [column[1] for column in cursor.fetchall()]
        
        # Добавляем поля в таблицу applications
        if 'due_date' not in app_columns:
            print("Добавление поля due_date в таблицу applications...")
            cursor.execute("ALTER TABLE applications ADD COLUMN due_date DATETIME")
            print("✓ Поле due_date добавлено")
        else:
            print("- Поле due_date уже существует")
            
        if 'completed_at' not in app_columns:
            print("Добавление поля completed_at в таблицу applications...")
            cursor.execute("ALTER TABLE applications ADD COLUMN completed_at DATETIME")
            print("✓ Поле completed_at добавлено")
        else:
            print("- Поле completed_at уже существует")
            
        # Добавляем поле в таблицу application_types
        if 'execution_days' not in type_columns:
            print("Добавление поля execution_days в таблицу application_types...")
            cursor.execute("ALTER TABLE application_types ADD COLUMN execution_days INTEGER DEFAULT 3")
            
            # Устанавливаем значения по умолчанию для существующих записей
            cursor.execute("UPDATE application_types SET execution_days = 3 WHERE execution_days IS NULL")
            print("✓ Поле execution_days добавлено")
        else:
            print("- Поле execution_days уже существует")
            
        # Обновляем completed_at для завершенных заявок
        print("\nОбновление дат завершения для существующих заявок...")
        cursor.execute("""
            UPDATE applications 
            SET completed_at = datetime('now') 
            WHERE status IN ('Выполнено', 'Закрыто', 'Отклонено') 
            AND completed_at IS NULL
        """)
        
        updated_count = cursor.rowcount
        print(f"✓ Обновлено {updated_count} заявок")
        
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
