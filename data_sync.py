# data_sync.py
import time
from sqlalchemy import create_engine, inspect
from app.extensions import db
from app.models import EstateSells, EstateDeals, EstateDealsContacts, EstateHouses
from config import Config
from sqlalchemy.orm import noload
from app.models import EstateSells, EstateDeals, EstateDealsContacts, EstateHouses
# --- НОВОЕ: Устанавливаем размер порции данных для обработки ---
# Это количество записей, которое будет загружаться в память за один раз.
# 1000 - это хороший баланс между скоростью и использованием памяти.
CHUNK_SIZE = 100000


def sync_data():
    """
    Синхронизирует данные из удаленной БД MySQL в локальную БД SQLite.
    ОБНОВЛЕННАЯ ЛОГИКА: Обрабатывает данные порциями (чанками),
    чтобы избежать переполнения памяти при работе с большими таблицами.
    """
    print(f"\n[{time.ctime()}] ЗАПУСК ПРОЦЕССА СИНХРОНИЗАЦИИ ДАННЫХ")

    source_engine = None
    source_session = None

    try:
        # --- ЭТАП 1: Подключение к БД и очистка локальных таблиц ---
        print("\n--- ЭТАП 1: Подготовка ---")
        print("-> Подключение к удаленной базе данных MySQL...")
        source_engine = create_engine(Config.SOURCE_DATABASE_URI)
        source_session = source_engine.connect()
        print("✔️ Подключение к MySQL успешно.")

        local_session = db.session
        print("-> Очистка синхронизируемых таблиц в локальной БД...")
        # Определяем порядок удаления (от дочерних к родительским)
        models_to_clear = [EstateDeals, EstateSells, EstateDealsContacts, EstateHouses]

        print("-> Отключаем проверку внешних ключей и начинаем транзакцию...")
        with local_session.get_bind().connect() as con:
            trans = con.begin()
            try:
                con.execute(db.text('PRAGMA foreign_keys = OFF'))
                print("   - Проверка ключей отключена.")

                for model in models_to_clear:
                    table_name = model.__tablename__
                    print(f"   - Очистка таблицы {table_name} с помощью прямого SQL-запроса...")
                    # Заменяем ORM-метод на прямой SQL-запрос в той же транзакции
                    con.execute(db.text(f'DELETE FROM {table_name}'))

                print("   - Включаем проверку ключей обратно.")
                con.execute(db.text('PRAGMA foreign_keys = ON'))

                print("-> Фиксация транзакции...")
                trans.commit()
                print("✔️ Транзакция успешно зафиксирована.")

            except Exception as e:
                print(f"❌ Ошибка во время очистки таблиц: {e}. Откат транзакции...")
                trans.rollback()
                # Перевыбрасываем исключение, чтобы остановить выполнение всего скрипта
                raise e

        print("✔️ Локальные таблицы очищены.")

        # --- ЭТАП 2: Поочередная синхронизация таблиц порциями ---
        print("\n--- ЭТАП 2: Загрузка и сохранение данных ---")

        # Определяем порядок скачивания (сначала родительские таблицы)
        models_to_sync = [EstateHouses, EstateDealsContacts, EstateSells, EstateDeals]
        total_records_synced = 0

        for model in models_to_sync:
            table_name = model.__tablename__
            print(f"--> Синхронизация таблицы: {table_name}...")

            offset = 0
            model_records_synced = 0

            # Цикл для загрузки данных порциями
            while True:
                # --- ИЗМЕНЕНИЕ: Загружаем не все, а только порцию данных ---
                if model == EstateHouses:
                    # Особый запрос для EstateHouses...
                    chunk_query = db.select(model.house_id, model.complex_name, model.name).limit(CHUNK_SIZE).offset(
                        offset)

                # --- НАЧАЛО ИЗМЕНЕНИЯ ---
                elif model == EstateSells:
                    # Для EstateSells отключаем автоматическую загрузку связанных сделок,
                    # чтобы избежать дубликатов из-за lazy='joined' в модели.
                    chunk_query = db.select(model).options(noload(model.deals)).limit(CHUNK_SIZE).offset(offset)
                # --- КОНЕЦ ИЗМЕНЕНИЯ ---
                elif model == EstateDeals:
                    # Для EstateDeals принудительно соединяем с родительскими таблицами,
                    # чтобы отфильтровать "осиротевшие" записи в источнике и избежать ошибок FOREIGN KEY.
                    chunk_query = (
                        db.select(model)
                        .join(EstateSells, model.estate_sell_id == EstateSells.estate_sell_id)
                        .join(EstateDealsContacts, model.contacts_buy_id == EstateDealsContacts.id)
                        .limit(CHUNK_SIZE).offset(offset)
                    )
                # --- КОНЕЦ ИЗМЕНЕНИЯ ---

                else:
                    # Стандартный запрос для остальных моделей
                    chunk_query = db.select(model).limit(CHUNK_SIZE).offset(offset)


                # Выполняем запрос в исходной БД
                chunk = source_session.execute(chunk_query).mappings().all()

                # Если порция пуста, значит, мы обработали всю таблицу
                if not chunk:
                    break

                # Сразу записываем полученную порцию в локальную БД
                local_session.bulk_insert_mappings(model, chunk)

                chunk_size = len(chunk)
                model_records_synced += chunk_size
                total_records_synced += chunk_size
                offset += CHUNK_SIZE

                print(f"    - Обработано и сохранено {chunk_size} записей (всего для таблицы: {model_records_synced}).")

            # Сохраняем изменения в локальной БД после каждой таблицы
            local_session.commit()
            print(f"✔️ Синхронизация таблицы {table_name} завершена. Всего записей: {model_records_synced}.\n")

        print(f"\n✔️ ЭТАП 2 ЗАВЕРШЕН. Всего синхронизировано {total_records_synced} записей.")
        print(f"\n[{time.ctime()}] ✔️ СИНХРОНИЗАЦИЯ УСПЕШНО ЗАВЕРШЕНА.")

    except Exception as e:
        print(f"\n[{time.ctime()}] ❌ КРИТИЧЕСКАЯ ОШИБКА во время синхронизации: {e}")
        if 'local_session' in locals() and local_session.is_active:
            print("-> Попытка отката транзакции...")
            local_session.rollback()
            print("✔️ Транзакция отменена.")
    finally:
        if source_session:
            source_session.close()
            print("-> Соединение с MySQL закрыто.")


def create_database(app):
    """
    Создает таблицы в локальной базе данных и проверяет их наличие.
    """
    with app.app_context():
        print("\nПроверка и создание локальной базы данных...")

        db.create_all()
        print("✔️ Выполнена команда db.create_all(). Таблицы созданы или уже существуют.")

        try:
            inspector = inspect(db.engine)
            tables = inspector.get_table_names()
            print(f"✔️ Обнаружены таблицы в app.db: {tables}")

            required_tables = [
                'users', 'estate_houses', 'estate_deals_contacts', 'estate_sells', 'estate_deals',
                'applications', 'defects', 'application_logs',
                'responsible_persons', 'responsible_assignments'
            ]

            missing_tables = [t for t in required_tables if t not in tables]
            if not missing_tables:
                print("✔️ Все необходимые таблицы присутствуют в базе данных.")
            else:
                print(
                    f"❌ ВНИМАНИЕ: Не найдены следующие таблицы: {missing_tables}. Они будут созданы при запуске приложения.")
        except Exception as e:
            print(f"❌ КРИТИЧЕСКАЯ ОШИБКА при проверке таблиц: {e}")