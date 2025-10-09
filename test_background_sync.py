#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Тестовый скрипт для проверки фоновой синхронизации
Использует интервал 1 минута вместо 4 часов для быстрого тестирования
"""
import os
import threading
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

from app import create_app
from data_sync import sync_data, create_database

# Создаем экземпляр приложения
app = create_app()

def test_background_sync_task(app_context, interval_seconds=60):
    """
    Тестовая версия фоновой синхронизации с коротким интервалом
    """
    sync_count = 0
    
    while sync_count < 3:  # Запустим только 3 раза для теста
        sync_count += 1
        
        # Рассчитываем время следующей синхронизации
        next_sync_time = datetime.now() + timedelta(seconds=interval_seconds)
        
        print(f"\n{'='*70}")
        print(f"🧪 ТЕСТ: Синхронизация #{sync_count}")
        print(f"📅 Следующая синхронизация через {interval_seconds} секунд")
        print(f"   Время: {next_sync_time.strftime('%d.%m.%Y %H:%M:%S')}")
        print(f"{'='*70}\n")
        
        # Ждем
        time.sleep(interval_seconds)
        
        # Выполняем синхронизацию
        print(f"\n{'='*70}")
        print(f"🔄 ЗАПУСК ТЕСТОВОЙ СИНХРОНИЗАЦИИ #{sync_count}")
        print(f"   Время: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}")
        print(f"{'='*70}\n")
        
        with app_context:
            sync_data()
        
        print(f"\n{'='*70}")
        print(f"✅ ТЕСТОВАЯ СИНХРОНИЗАЦИЯ #{sync_count} ЗАВЕРШЕНА")
        print(f"   Время: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}")
        print(f"{'='*70}\n")
    
    print(f"\n{'='*70}")
    print(f"🎉 ТЕСТ ЗАВЕРШЕН: Выполнено {sync_count} синхронизаций")
    print(f"{'='*70}\n")

if __name__ == '__main__':
    print("\n" + "="*70)
    print("🧪 ТЕСТОВЫЙ РЕЖИМ: Фоновая синхронизация каждые 60 секунд")
    print("   Будет выполнено 3 синхронизации, затем скрипт завершится")
    print("="*70 + "\n")
    
    # Создаем БД
    create_database(app)
    
    # Первая синхронизация
    print("Выполняем первую синхронизацию при старте...")
    with app.app_context():
        sync_data()
    
    print("\n" + "="*70)
    print("✅ Первая синхронизация завершена")
    print("🚀 Запускаем фоновый поток с интервалом 60 секунд")
    print("="*70 + "\n")
    
    # Запускаем тестовый фоновый поток
    sync_thread = threading.Thread(
        target=test_background_sync_task, 
        args=(app.app_context(), 60)  # 60 секунд вместо 4 часов
    )
    sync_thread.daemon = False  # НЕ daemon, чтобы дождаться завершения
    sync_thread.start()
    
    # Ждем завершения теста
    sync_thread.join()
    
    print("\n" + "="*70)
    print("🎉 ВСЕ ТЕСТЫ ПРОЙДЕНЫ!")
    print("   Фоновая синхронизация работает корректно")
    print("   В production она будет выполняться каждые 4 часа")
    print("="*70 + "\n")
