#!/usr/bin/env python3
"""
Скрипт для исправления версии миграции в БД.
"""
from app import create_app
from app.extensions import db

app = create_app()

with app.app_context():
    # Обновляем версию миграции на существующую
    db.session.execute(db.text("UPDATE alembic_version SET version_num = '5877edff2f1b'"))
    db.session.commit()
    
    # Проверяем
    result = db.session.execute(db.text("SELECT version_num FROM alembic_version"))
    version = result.fetchone()[0]
    print(f"✅ Migration version updated to: {version}")
