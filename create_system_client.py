#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Скрипт для создания системного клиента и договора
"""
import os
import sys
from datetime import datetime

# Добавляем текущую директорию в путь Python
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from app.extensions import db
from app.models import EstateDealsContacts, EstateDeals

def create_system_client():
    """Создает системного клиента и договор если они еще не существуют"""
    app = create_app()
    
    with app.app_context():
        # Проверяем, существует ли системный клиент
        system_client = EstateDealsContacts.query.filter_by(
            contacts_buy_name="СИСТЕМНЫЙ КЛИЕНТ (для заявок без договора)"
        ).first()
        
        if not system_client:
            # Создаем системного клиента
            system_client = EstateDealsContacts(
                contacts_buy_name="СИСТЕМНЫЙ КЛИЕНТ (для заявок без договора)",
                contacts_buy_phones="000-00-00"
            )
            db.session.add(system_client)
            db.session.flush()  # Чтобы получить ID
            
            print(f"Создан системный клиент с ID: {system_client.id}")
        else:
            print(f"Системный клиент уже существует с ID: {system_client.id}")
        
        # Проверяем, существует ли системный договор
        system_deal = EstateDeals.query.filter_by(
            agreement_number="SYSTEM-001",
            contacts_buy_id=system_client.id
        ).first()
        
        if not system_deal:
            # Создаем системный договор
            system_deal = EstateDeals(
                agreement_number="SYSTEM-001",
                contacts_buy_id=system_client.id,
                deal_status_name="Системный",
                agreement_date=datetime.now().date(),
                deal_sum=0.0,
                finances_income_reserved=0.0
            )
            db.session.add(system_deal)
            print("Создан системный договор с номером: SYSTEM-001")
        else:
            print("Системный договор уже существует")
        
        # Сохраняем изменения
        db.session.commit()
        print("Все изменения сохранены в базу данных")
        
        return system_client.id

if __name__ == "__main__":
    system_client_id = create_system_client()
    print(f"\nСистемный клиент ID: {system_client_id}")
    print("Теперь можно создавать заявки без указания реального клиента и договора")
