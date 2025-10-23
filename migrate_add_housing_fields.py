"""
Скрипт миграции для добавления полей ЖК и номера дома в таблицу applications
"""
from app import create_app, db

def migrate():
    app = create_app()
    
    with app.app_context():
        print("🔧 Добавление полей housing_complex и house_number в таблицу applications...")
        
        try:
            # Добавляем поле housing_complex
            db.session.execute(db.text('''
                ALTER TABLE applications 
                ADD COLUMN housing_complex VARCHAR(255)
            '''))
            print("✅ Поле housing_complex добавлено")
        except Exception as e:
            if 'duplicate column name' in str(e).lower() or 'already exists' in str(e).lower():
                print("⚠️  Поле housing_complex уже существует")
            else:
                print(f"❌ Ошибка при добавлении housing_complex: {e}")
                raise
        
        try:
            # Добавляем поле house_number
            db.session.execute(db.text('''
                ALTER TABLE applications 
                ADD COLUMN house_number VARCHAR(255)
            '''))
            print("✅ Поле house_number добавлено")
        except Exception as e:
            if 'duplicate column name' in str(e).lower() or 'already exists' in str(e).lower():
                print("⚠️  Поле house_number уже существует")
            else:
                print(f"❌ Ошибка при добавлении house_number: {e}")
                raise
        
        db.session.commit()
        print("\n✅ Миграция успешно завершена!")
        print("📋 Добавлены поля:")
        print("   - housing_complex (VARCHAR(255)) - Название ЖК")
        print("   - house_number (VARCHAR(255)) - Номер дома")

if __name__ == '__main__':
    migrate()
