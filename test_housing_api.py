#!/usr/bin/env python3
"""
Тестовый скрипт для проверки API ЖК и домов
"""
import sys
sys.path.insert(0, '/app')

from app import create_app, db

app = create_app()

with app.app_context():
    # Тест 1: Получение списка ЖК
    print("=" * 60)
    print("ТЕСТ 1: Получение списка всех ЖК")
    print("=" * 60)
    
    result = db.session.execute(
        db.text('SELECT DISTINCT complex_name FROM estate_houses WHERE complex_name IS NOT NULL ORDER BY complex_name')
    ).fetchall()
    
    complexes = [row[0] for row in result]
    print(f"Найдено ЖК: {len(complexes)}")
    print("\nПервые 10 ЖК:")
    for i, complex_name in enumerate(complexes[:10], 1):
        print(f"  {i}. {complex_name}")
    
    # Тест 2: Получение списка домов для первого ЖК
    if complexes:
        print("\n" + "=" * 60)
        print(f"ТЕСТ 2: Получение списка домов для ЖК '{complexes[0]}'")
        print("=" * 60)
        
        result = db.session.execute(
            db.text('SELECT DISTINCT name FROM estate_houses WHERE complex_name = :complex ORDER BY name'),
            {'complex': complexes[0]}
        ).fetchall()
        
        houses = [row[0] for row in result]
        print(f"Найдено домов: {len(houses)}")
        print("\nСписок домов:")
        for i, house in enumerate(houses, 1):
            print(f"  {i}. {house}")
    
    # Тест 3: Проверка данных для нескольких ЖК
    print("\n" + "=" * 60)
    print("ТЕСТ 3: Количество домов в разных ЖК")
    print("=" * 60)
    
    for complex_name in complexes[:5]:
        result = db.session.execute(
            db.text('SELECT COUNT(DISTINCT name) FROM estate_houses WHERE complex_name = :complex'),
            {'complex': complex_name}
        ).scalar()
        print(f"  {complex_name}: {result} домов")
    
    print("\n" + "=" * 60)
    print("✅ ВСЕ ТЕСТЫ ЗАВЕРШЕНЫ")
    print("=" * 60)
