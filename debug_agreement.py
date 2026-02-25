#!/usr/bin/env python3
"""
Диагностика: почему договор не отображается в листинге клиентов.

Проверяет:
  1. Есть ли договор в удалённой MySQL (MacroCRM)
  2. Есть ли связанные записи (estate_sells, estate_deals_contacts)
  3. Проходит ли договор через JOIN-фильтр синхронизации
  4. Есть ли договор в локальной SQLite
  5. Проходит ли через WHERE-фильтр отображения (имя/телефон не пустые)

Использование:
  python debug_agreement.py 13037-GHP
  python debug_agreement.py 13037          # частичный поиск
  python debug_agreement.py "Иванов"       # поиск по имени клиента

Требует:
  - Переменные окружения SOURCE_MYSQL_* (через .env или напрямую)
  - pymysql
"""
import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Загружаем .env из текущей директории (client_service/.env)
from dotenv import load_dotenv
script_dir = os.path.dirname(os.path.abspath(__file__))
local_env = os.path.join(script_dir, '.env')
if os.path.exists(local_env):
    load_dotenv(local_env, override=True)

from config import Config
from sqlalchemy import create_engine, text


def section(title):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print('=' * 60)


def check_remote_mysql(search_term):
    """Проверяет договор в удалённой MySQL (MacroCRM)."""
    section("1. ПОИСК В УДАЛЁННОЙ MySQL (MacroCRM)")

    if not Config.SOURCE_DATABASE_URI:
        print("  ✗ SOURCE_DATABASE_URI не сконфигурирован!")
        print("    Установите переменные: SOURCE_MYSQL_USER, SOURCE_MYSQL_PASSWORD,")
        print("    SOURCE_MYSQL_HOST, SOURCE_MYSQL_DATABASE")
        return None

    engine = create_engine(Config.SOURCE_DATABASE_URI)
    with engine.connect() as conn:
        # Поиск по номеру договора
        print(f"\n  Поиск по agreement_number LIKE '%{search_term}%'...")
        deals = conn.execute(text(
            "SELECT d.id, d.agreement_number, d.contacts_buy_id, d.estate_sell_id, "
            "d.deal_status_name, d.deal_sum "
            "FROM estate_deals d "
            "WHERE d.agreement_number LIKE :search"
        ), {"search": f"%{search_term}%"}).mappings().all()

        if not deals:
            # Попробуем поиск по имени клиента
            print(f"  Не найдено по agreement_number. Поиск по имени клиента...")
            deals = conn.execute(text(
                "SELECT d.id, d.agreement_number, d.contacts_buy_id, d.estate_sell_id, "
                "d.deal_status_name, d.deal_sum "
                "FROM estate_deals d "
                "JOIN estate_deals_contacts c ON d.contacts_buy_id = c.id "
                "WHERE c.contacts_buy_name LIKE :search"
            ), {"search": f"%{search_term}%"}).mappings().all()

        if not deals:
            print(f"  ✗ Договор '{search_term}' НЕ НАЙДЕН в MySQL!")
            print("    Проверьте правильность номера договора.")
            return None

        print(f"  ✓ Найдено {len(deals)} сделок:")
        for d in deals:
            print(f"    id={d['id']}, agreement={d['agreement_number']!r}, "
                  f"contact_id={d['contacts_buy_id']}, sell_id={d['estate_sell_id']}, "
                  f"status={d.get('deal_status_name')!r}")

        # Проверяем каждую найденную сделку
        results = []
        for deal in deals:
            deal_info = dict(deal)
            deal_info['problems'] = []

            # Проверка estate_sells
            sell_id = deal['estate_sell_id']
            if sell_id is None:
                print(f"\n  ✗ Сделка {deal['agreement_number']}: estate_sell_id = NULL!")
                deal_info['problems'].append('estate_sell_id IS NULL')
                deal_info['sell'] = None
            else:
                sell = conn.execute(text(
                    "SELECT s.estate_sell_id, s.house_id, s.estate_floor, s.geo_flatnum "
                    "FROM estate_sells s WHERE s.estate_sell_id = :id"
                ), {"id": sell_id}).mappings().first()
                if sell:
                    deal_info['sell'] = dict(sell)
                    print(f"\n  ✓ Сделка {deal['agreement_number']}: estate_sells id={sell_id} найден "
                          f"(house_id={sell['house_id']}, этаж={sell.get('estate_floor')}, кв.={sell.get('geo_flatnum')})")

                    # Проверка house
                    if sell['house_id']:
                        house = conn.execute(text(
                            "SELECT h.house_id, h.complex_name, h.name "
                            "FROM estate_houses h WHERE h.house_id = :id"
                        ), {"id": sell['house_id']}).mappings().first()
                        if house:
                            print(f"    ✓ Дом: {house['complex_name']} / {house['name']}")
                        else:
                            print(f"    ✗ Дом house_id={sell['house_id']} НЕ НАЙДЕН!")
                            deal_info['problems'].append(f"house_id={sell['house_id']} not found")
                else:
                    print(f"\n  ✗ Сделка {deal['agreement_number']}: estate_sells id={sell_id} НЕ НАЙДЕН!")
                    deal_info['problems'].append(f'estate_sells {sell_id} not found')
                    deal_info['sell'] = None

            # Проверка contacts
            contact_id = deal['contacts_buy_id']
            if contact_id is None:
                print(f"  ✗ Сделка {deal['agreement_number']}: contacts_buy_id = NULL!")
                deal_info['problems'].append('contacts_buy_id IS NULL')
                deal_info['contact'] = None
            else:
                contact = conn.execute(text(
                    "SELECT c.id, c.contacts_buy_name, c.contacts_buy_phones "
                    "FROM estate_deals_contacts c WHERE c.id = :id"
                ), {"id": contact_id}).mappings().first()
                if contact:
                    name = contact['contacts_buy_name']
                    phones = contact['contacts_buy_phones']
                    deal_info['contact'] = dict(contact)
                    print(f"  ✓ Контакт id={contact_id}: name={name!r}, phones={phones!r}")

                    # Проверка фильтров отображения
                    if not name or name.strip() == '':
                        print(f"    ⚠ Имя пустое — будет скрыт в листинге!")
                        deal_info['problems'].append('contacts_buy_name is empty')
                    if not phones or phones.strip() == '':
                        print(f"    ⚠ Телефон пустой — будет скрыт в листинге!")
                        deal_info['problems'].append('contacts_buy_phones is empty')
                else:
                    print(f"  ✗ Контакт id={contact_id} НЕ НАЙДЕН!")
                    deal_info['problems'].append(f'contact {contact_id} not found')
                    deal_info['contact'] = None

            results.append(deal_info)

        # Проверка JOIN-запроса синхронизации
        section("2. ТЕСТ JOIN-ЗАПРОСА СИНХРОНИЗАЦИИ")
        print("  Запрос data_sync.py использует INNER JOIN с estate_sells и estate_deals_contacts.")
        print("  Если какая-то из связей отсутствует — договор не попадёт в локальную БД.\n")

        for deal in deals:
            agr = deal['agreement_number']
            sync_result = conn.execute(text(
                "SELECT d.id, d.agreement_number "
                "FROM estate_deals d "
                "JOIN estate_sells s ON d.estate_sell_id = s.estate_sell_id "
                "JOIN estate_deals_contacts c ON d.contacts_buy_id = c.id "
                "WHERE d.id = :deal_id"
            ), {"deal_id": deal['id']}).mappings().first()

            if sync_result:
                print(f"  ✓ {agr}: пройдёт через sync JOIN")
            else:
                print(f"  ✗ {agr}: ОТСЕИВАЕТСЯ sync JOIN!")
                # Определяем какой именно join ломает
                if deal['estate_sell_id'] is not None:
                    sells_ok = conn.execute(text(
                        "SELECT 1 FROM estate_deals d "
                        "JOIN estate_sells s ON d.estate_sell_id = s.estate_sell_id "
                        "WHERE d.id = :deal_id"
                    ), {"deal_id": deal['id']}).first()
                    if not sells_ok:
                        print(f"    → estate_sells JOIN не проходит (sell_id={deal['estate_sell_id']} не существует)")
                if deal['contacts_buy_id'] is not None:
                    contacts_ok = conn.execute(text(
                        "SELECT 1 FROM estate_deals d "
                        "JOIN estate_deals_contacts c ON d.contacts_buy_id = c.id "
                        "WHERE d.id = :deal_id"
                    ), {"deal_id": deal['id']}).first()
                    if not contacts_ok:
                        print(f"    → estate_deals_contacts JOIN не проходит (contact_id={deal['contacts_buy_id']} не существует)")

        return results


def check_local_sqlite(search_term):
    """Проверяет договор в локальной SQLite."""
    section("3. ПОИСК В ЛОКАЛЬНОЙ SQLite")

    from app import create_app
    from app.extensions import db

    app = create_app()
    with app.app_context():
        # Поиск в estate_deals
        local_deals = db.session.execute(text(
            "SELECT d.id, d.agreement_number, d.contacts_buy_id, d.estate_sell_id "
            "FROM estate_deals d WHERE d.agreement_number LIKE :search"
        ), {"search": f"%{search_term}%"}).mappings().all()

        if local_deals:
            print(f"  ✓ Найдено {len(local_deals)} сделок в локальной БД:")
            for d in local_deals:
                print(f"    id={d['id']}, agreement={d['agreement_number']!r}")
        else:
            print(f"  ✗ Договор '{search_term}' НЕ НАЙДЕН в локальной SQLite!")
            print("    → Не попал при синхронизации (data_sync.py)")

        # Проверка через полный запрос отображения (как в routes.py index)
        section("4. ТЕСТ ЗАПРОСА ОТОБРАЖЕНИЯ (routes.py)")
        display_result = db.session.execute(text(
            "SELECT c.id, c.contacts_buy_name, c.contacts_buy_phones, d.agreement_number "
            "FROM estate_deals_contacts c "
            "JOIN estate_deals d ON c.id = d.contacts_buy_id "
            "WHERE c.contacts_buy_name IS NOT NULL AND c.contacts_buy_name != '' "
            "AND c.contacts_buy_phones IS NOT NULL AND c.contacts_buy_phones != '' "
            "AND d.agreement_number IS NOT NULL AND TRIM(d.agreement_number) != '' "
            "AND d.agreement_number LIKE :search"
        ), {"search": f"%{search_term}%"}).mappings().all()

        if display_result:
            print(f"  ✓ Найдено {len(display_result)} результатов в листинге:")
            for r in display_result:
                print(f"    name={r['contacts_buy_name']!r}, phones={r['contacts_buy_phones']!r}, "
                      f"agreement={r['agreement_number']!r}")
        else:
            print(f"  ✗ Договор НЕ ОТОБРАЖАЕТСЯ в листинге!")
            if local_deals:
                print("    → Есть в БД, но фильтруется WHERE (пустое имя или телефон)")
            else:
                print("    → Отсутствует в БД (не прошёл sync)")


def print_summary(results):
    """Итоговый диагноз."""
    section("ИТОГ: ДИАГНОЗ")

    if not results:
        print("  Договор не найден ни в одной базе данных.")
        print("  Проверьте правильность номера.")
        return

    for deal in results:
        agr = deal.get('agreement_number', '?')
        problems = deal.get('problems', [])

        if not problems:
            print(f"  ✓ {agr}: все связи в порядке. Возможно нужна пересинхронизация.")
            print(f"    → Запустите data_sync или перезапустите контейнер client-service")
        else:
            print(f"  ✗ {agr}: найдены проблемы:")
            for p in problems:
                print(f"    - {p}")

            # Рекомендации
            sync_blocking = any(x in p for p in problems for x in
                                ['IS NULL', 'not found', 'estate_sells', 'contact'])
            display_blocking = any('empty' in p for p in problems)

            if sync_blocking:
                print(f"\n    ПРИЧИНА: Договор не проходит INNER JOIN при синхронизации.")
                print(f"    РЕШЕНИЕ: Заменить JOIN на LEFT JOIN в data_sync.py для EstateDeals,")
                print(f"    или исправить данные в MacroCRM (заполнить связи).")

            if display_blocking:
                print(f"\n    ПРИЧИНА: Контакт с пустым именем/телефоном скрывается в листинге.")
                print(f"    РЕШЕНИЕ: Заполнить имя/телефон в MacroCRM, или ослабить WHERE в routes.py.")


def main():
    parser = argparse.ArgumentParser(
        description="Диагностика: почему договор не отображается в листинге"
    )
    parser.add_argument(
        'search_term',
        help="Номер договора или имя клиента для поиска (например: 13037-GHP)"
    )
    args = parser.parse_args()

    print(f"\n  Поиск: '{args.search_term}'")

    results = check_remote_mysql(args.search_term)
    check_local_sqlite(args.search_term)
    print_summary(results)


if __name__ == '__main__':
    main()
