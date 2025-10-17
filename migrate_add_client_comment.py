"""
Миграция: Добавление поля client_comment в таблицу estate_deals_contacts
Дата: 16.10.2025
Описание: Добавляет текстовое поле для комментариев о клиенте
"""
import sqlite3
import os

def migrate():
    db_path = os.path.join('instance', 'app.db')
    
    if not os.path.exists(db_path):
        print(f"❌ База данных не найдена: {db_path}")
        return False
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Проверяем, существует ли уже колонка
        cursor.execute("PRAGMA table_info(estate_deals_contacts)")
        columns = [column[1] for column in cursor.fetchall()]
        
        if 'client_comment' in columns:
            print("✔️ Колонка 'client_comment' уже существует в таблице estate_deals_contacts")
            conn.close()
            return True
        
        # Добавляем новую колонку
        print("➕ Добавление колонки 'client_comment' в таблицу estate_deals_contacts...")
        cursor.execute("""
            ALTER TABLE estate_deals_contacts 
            ADD COLUMN client_comment TEXT
        """)
        
        conn.commit()
        print("✅ Миграция успешно выполнена!")
        
        # Проверяем результат
        cursor.execute("PRAGMA table_info(estate_deals_contacts)")
        columns = [column[1] for column in cursor.fetchall()]
        print(f"📋 Колонки таблицы estate_deals_contacts: {columns}")
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ Ошибка при выполнении миграции: {e}")
        if conn:
            conn.rollback()
            conn.close()
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("МИГРАЦИЯ: Добавление поля client_comment")
    print("=" * 60)
    migrate()
