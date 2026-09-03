# data_sync.py
import sys
import time
from sqlalchemy import create_engine, inspect, literal_column
from app.extensions import db
from app.models import EstateSells, EstateDeals, EstateDealsContacts, EstateHouses
from config import Config
from sqlalchemy.orm import noload
from app.models import EstateSells, EstateDeals, EstateDealsContacts, EstateHouses

# Fix encoding for Docker logs
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

# --- НОВОЕ: Устанавливаем размер порции данных для обработки ---
# Это количество записей, которое будет загружаться в память за один раз.
# 1000 - это хороший баланс между скоростью и использованием памяти.
CHUNK_SIZE = 100000

# Часть договоров в MacroCRM оформлена как предварительные: agreement_number/agreement_date
# пустые, а номер и дата лежат в preliminary_number/preliminary_date. Локально такие сделки
# не различаются — при синхронизации подставляем предварительный номер в agreement_number,
# иначе договор не проходит фильтр "agreement_number != ''" и клиент не виден в листинге.
# Непустой agreement_number берётся как есть (без TRIM), чтобы не разъехаться с уже
# созданными заявками, которые хранят номер строкой.
_AGREEMENT_BLANK = "NULLIF(TRIM(estate_deals.agreement_number), '') IS NULL"
DEAL_NUMBER_SQL = (
    f"CASE WHEN {_AGREEMENT_BLANK} "
    "THEN COALESCE(estate_deals.preliminary_number, '') "
    "ELSE estate_deals.agreement_number END"
)
DEAL_DATE_SQL = (
    f"CASE WHEN {_AGREEMENT_BLANK} "
    "THEN estate_deals.preliminary_date "
    "ELSE estate_deals.agreement_date END"
)


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
                    
                    # ИСПРАВЛЕНИЕ: Для клиентов НЕ удаляем тех, кто создан локально для заявок без договора
                    if table_name == 'estate_deals_contacts':
                        print(f"   - Очистка таблицы {table_name} (сохраняя локальных клиентов)...")
                        
                        # Сначала негируем ID локальных NC-контактов (если ещё положительные)
                        local_contacts_pos = con.execute(db.text('''
                            SELECT DISTINCT c.id FROM estate_deals_contacts c
                            JOIN estate_deals d ON d.contacts_buy_id = c.id
                            WHERE (d.agreement_number LIKE 'NC-%' OR d.agreement_number = 'SYSTEM-001')
                              AND c.id > 0
                        ''')).fetchall()
                        
                        if local_contacts_pos:
                            min_contact_id = con.execute(db.text(
                                'SELECT MIN(id) FROM estate_deals_contacts WHERE id < 0'
                            )).scalar() or 0
                            next_neg_id = min(min_contact_id, 0) - 1
                            
                            for row in local_contacts_pos:
                                old_cid = row[0]
                                # Обновляем ID контакта
                                con.execute(db.text(
                                    'UPDATE estate_deals_contacts SET id = :new_id WHERE id = :old_id'
                                ), {'new_id': next_neg_id, 'old_id': old_cid})
                                # Обновляем FK в estate_deals
                                con.execute(db.text(
                                    'UPDATE estate_deals SET contacts_buy_id = :new_id WHERE contacts_buy_id = :old_id'
                                ), {'new_id': next_neg_id, 'old_id': old_cid})
                                # Обновляем FK в applications
                                con.execute(db.text(
                                    'UPDATE applications SET client_id = :new_id WHERE client_id = :old_id'
                                ), {'new_id': next_neg_id, 'old_id': old_cid})
                                next_neg_id -= 1
                            
                            print(f"   - Негировано {len(local_contacts_pos)} NC-контактов с положительными ID.")
                        
                        # Удаляем только НЕ-NC клиентов (с отрицательными ID контакты сохранятся).
                        # Клиентов, на которых ссылаются заявки, сохраняем тоже: estate_deals_contacts
                        # в источнике содержит только владельцев действующих сделок, поэтому при
                        # переуступке/переоформлении договора прежний владелец пропадает из источника,
                        # и все его заявки осиротели бы (Application.client -> None, «N/A» в списке).
                        # IS NOT NULL в подзапросах обязателен: NULL внутри NOT IN обнуляет всё условие.
                        con.execute(db.text('''
                            DELETE FROM estate_deals_contacts
                            WHERE id NOT IN (
                                SELECT DISTINCT contacts_buy_id
                                FROM estate_deals
                                WHERE (agreement_number LIKE 'NC-%'
                                    OR agreement_number = 'SYSTEM-001')
                                  AND contacts_buy_id IS NOT NULL
                            )
                            AND id NOT IN (
                                SELECT DISTINCT client_id
                                FROM applications
                                WHERE client_id IS NOT NULL
                            )
                        '''))
                        kept_contacts = con.execute(db.text(
                            'SELECT COUNT(*) FROM estate_deals_contacts'
                        )).scalar()
                        print(f"   - Сохранено {kept_contacts} клиентов "
                              f"(договоры NC-*/SYSTEM-001 + те, на кого ссылаются заявки).")
                    elif table_name == 'estate_deals':
                        print(f"   - Очистка таблицы {table_name} (сохраняя договоры без договора)...")
                        
                        # Получаем NC/SYSTEM сделки с положительными ID
                        local_deals = con.execute(db.text('''
                            SELECT id, contacts_buy_id FROM estate_deals 
                            WHERE (agreement_number LIKE 'NC-%' 
                               OR agreement_number = 'SYSTEM-001')
                              AND id > 0
                        ''')).fetchall()
                        
                        # Генерируем последовательные отрицательные ID для сделок
                        if local_deals:
                            # Находим минимальный существующий отрицательный ID
                            min_deal_id = con.execute(db.text(
                                'SELECT MIN(id) FROM estate_deals WHERE id < 0'
                            )).scalar() or 0
                            next_neg_id = min(min_deal_id, 0) - 1
                            
                            for deal in local_deals:
                                con.execute(db.text('''
                                    UPDATE estate_deals 
                                    SET id = :new_id 
                                    WHERE id = :old_id
                                '''), {'new_id': next_neg_id, 'old_id': deal[0]})
                                next_neg_id -= 1
                            
                            print(f"   - Изменено {len(local_deals)} локальных договоров на отрицательные ID.")
                        
                        # Удаляем только НЕ локальные договоры
                        con.execute(db.text('''
                            DELETE FROM estate_deals 
                            WHERE agreement_number NOT LIKE 'NC-%' 
                              AND agreement_number != 'SYSTEM-001'
                        '''))
                        print("   - Локальные договоры (NC-* и SYSTEM-001) сохранены.")
                    else:
                        print(f"   - Очистка таблицы {table_name} с помощью прямого SQL-запроса...")
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
            sell_orphans_nulled = 0
            contact_orphans_nulled = 0
            contacts_refreshed = 0

            # Контакты, пережившие очистку на ЭТАПЕ 1 (NC-клиенты + те, на кого ссылаются
            # заявки). Их нельзя вставлять повторно — PRIMARY KEY уже занят. Те из них,
            # что ещё есть в источнике, обновляем; остальные остаются как есть.
            preserved_contact_ids = set()
            if model == EstateDealsContacts:
                preserved_contact_ids = {
                    row[0] for row in local_session.execute(
                        db.text('SELECT id FROM estate_deals_contacts')
                    ).fetchall()
                }
                if preserved_contact_ids:
                    print(f"    - {len(preserved_contact_ids)} сохранённых клиентов: "
                          f"вставка заменена на обновление.")

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
                elif model == EstateDealsContacts:
                    # Для EstateDealsContacts исключаем поле client_comment, которого нет в удаленной БД
                    chunk_query = db.select(
                        model.id,
                        model.contacts_buy_name,
                        model.contacts_buy_phones
                    ).limit(CHUNK_SIZE).offset(offset)
                elif model == EstateDeals:
                    # LEFT JOIN вместо INNER: сделки без привязки к квартире/контакту
                    # (estate_sell_id / contacts_buy_id IS NULL) больше не отсеиваются молча.
                    # _sell_match/_contact_match ниже используются только чтобы отличить
                    # "битую" ссылку на несуществующую в источнике запись (её обнуляем,
                    # иначе упадёт FOREIGN KEY локальной БД) от изначально пустой.
                    # agreement_number/agreement_date подменяются на предварительные,
                    # если основные пустые — см. DEAL_NUMBER_SQL/DEAL_DATE_SQL.
                    chunk_query = (
                        db.select(
                            model.id, model.estate_sell_id, model.deal_status_name,
                            literal_column(DEAL_NUMBER_SQL).label('agreement_number'),
                            literal_column(DEAL_DATE_SQL).label('agreement_date'),
                            model.deal_sum,
                            model.deal_area, model.contacts_buy_id, model.finances_income_reserved,
                            EstateSells.estate_sell_id.label('_sell_match'),
                            EstateDealsContacts.id.label('_contact_match'),
                        )
                        .outerjoin(EstateSells, model.estate_sell_id == EstateSells.estate_sell_id)
                        .outerjoin(EstateDealsContacts, model.contacts_buy_id == EstateDealsContacts.id)
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

                # ИСПРАВЛЕНИЕ: Для клиентов и договоров фильтруем локальные данные
                if model == EstateDealsContacts:
                    # Сохранённые клиенты уже есть локально — обновляем их вместо вставки,
                    # чтобы имя/телефон не устаревали. NC-клиенты (id < 0) в источнике
                    # отсутствуют, поэтому под обновление не попадают.
                    if preserved_contact_ids:
                        to_update = [dict(record) for record in chunk
                                     if record['id'] in preserved_contact_ids]
                        if to_update:
                            local_session.bulk_update_mappings(model, to_update)
                            contacts_refreshed += len(to_update)
                        chunk = [record for record in chunk
                                 if record['id'] not in preserved_contact_ids]

                elif model == EstateDeals:
                    # Обнуляем "битые" FK (запись есть, а связанной estate_sells/contacts
                    # в источнике нет) перед вставкой — иначе нарушится FOREIGN KEY локальной БД.
                    fixed_chunk = []
                    for record in chunk:
                        record = dict(record)
                        sell_match = record.pop('_sell_match')
                        contact_match = record.pop('_contact_match')
                        if record['estate_sell_id'] is not None and sell_match is None:
                            sell_orphans_nulled += 1
                            record['estate_sell_id'] = None
                        if record['contacts_buy_id'] is not None and contact_match is None:
                            contact_orphans_nulled += 1
                            record['contacts_buy_id'] = None
                        fixed_chunk.append(record)
                    chunk = fixed_chunk

                    # Для договоров исключаем NC-* и SYSTEM-001 (они не должны приходить из MacroCRM)
                    # Но на всякий случай фильтруем
                    original_count = len(chunk)
                    chunk = [record for record in chunk
                            if not ((record.get('agreement_number') or '').startswith('NC-') or
                                   record.get('agreement_number') == 'SYSTEM-001')]
                    filtered_count = original_count - len(chunk)
                    if filtered_count > 0:
                        print(f"    - Исключено {filtered_count} локальных договоров из синхронизации.")

                # Сразу записываем полученную порцию в локальную БД
                if chunk:  # Проверяем, что chunk не пустой после фильтрации
                    local_session.bulk_insert_mappings(model, chunk)

                chunk_size = len(chunk)
                model_records_synced += chunk_size
                total_records_synced += chunk_size
                offset += CHUNK_SIZE

                print(f"    - Обработано и сохранено {chunk_size} записей (всего для таблицы: {model_records_synced}).")

            # Сохраняем изменения в локальной БД после каждой таблицы
            local_session.commit()
            if model == EstateDealsContacts and preserved_contact_ids:
                stale = len(preserved_contact_ids) - contacts_refreshed
                print(f"    ⚠ Сохранённых клиентов: {len(preserved_contact_ids)}, из них обновлено "
                      f"из источника {contacts_refreshed}, осталось только локально {stale} "
                      f"(NC-клиенты и прежние владельцы переуступленных договоров).")
            if model == EstateDeals and (sell_orphans_nulled or contact_orphans_nulled):
                print(f"    ⚠ Обнулено битых ссылок: estate_sell_id={sell_orphans_nulled}, "
                      f"contacts_buy_id={contact_orphans_nulled} (запись есть в estate_deals, "
                      f"связанной estate_sells/estate_deals_contacts нет в источнике).")
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