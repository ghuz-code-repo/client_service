#!/usr/bin/env python3
"""
Миграция: перевод NC-контактов и NC-сделок на отрицательные ID.

Проблема:
  NC-контакты (клиенты без договора) создаются через SQLite autoincrement,
  и их ID пересекается с диапазоном MySQL (MacroCRM).
  При синхронизации data_sync.py не может вставить MySQL-контакты
  из-за конфликта PRIMARY KEY, теряя ~29k контактов и ~4.5k сделок.

  Дополнительная сложность: data_sync.py ранее уже негировал часть NC-deal ID,
  поэтому простая формула -id даёт коллизии. Решение — последовательные
  отрицательные ID (-1, -2, -3, ...) для всех NC-сущностей.

Таблицы, которые обновляются:
  1. estate_deals_contacts.id       → последовательный отрицательный ID
  2. estate_deals.id                → последовательный отрицательный ID
  3. estate_deals.contacts_buy_id   → обновлённый contact ID
  4. applications.client_id         → обновлённый contact ID

Использование:
  python migrate_nc_negative_ids.py              # Dry-run (по умолчанию)
  python migrate_nc_negative_ids.py --apply      # Применить

Бэкап создаётся автоматически перед миграцией.
ВАЖНО: после миграции нужно перезапустить контейнер для пересинхронизации!
"""
import argparse
import datetime
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
local_env = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
if os.path.exists(local_env):
    load_dotenv(local_env, override=True)

from app import create_app
from app.extensions import db
from sqlalchemy import text


def backup_database(app):
    """Создаёт бэкап SQLite базы данных."""
    db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if db_uri.startswith('sqlite:///'):
        db_path = db_uri.replace('sqlite:///', '')
    else:
        print("  ⚠ Не SQLite БД, бэкап пропущен")
        return None

    if not os.path.isabs(db_path):
        db_path = os.path.join(app.instance_path, db_path)

    if not os.path.exists(db_path):
        print(f"  ⚠ Файл БД не найден: {db_path}")
        return None

    backup_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backups')
    os.makedirs(backup_dir, exist_ok=True)

    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = os.path.join(backup_dir, f"db_before_nc_migration_{timestamp}.sqlite")
    shutil.copy2(db_path, backup_path)
    size_mb = os.path.getsize(backup_path) / (1024 * 1024)
    print(f"  ✓ Бэкап: {backup_path} ({size_mb:.1f} МБ)")
    return backup_path


def migrate_nc_to_negative_ids(dry_run=True):
    """Переводит NC-контакты и NC-сделки на последовательные отрицательные ID."""
    app = create_app()

    with app.app_context():
        mode = "DRY-RUN" if dry_run else "APPLY"
        print(f"\n{'=' * 60}")
        print(f"  МИГРАЦИЯ NC-КОНТАКТОВ → ОТРИЦАТЕЛЬНЫЕ ID [{mode}]")
        print(f"{'=' * 60}")

        # Бэкап
        if not dry_run:
            print("\nСоздание бэкапа...")
            backup_database(app)

        # ============================================================
        # ШАГ 1: Собрать все NC- и SYSTEM-001 сделки
        # ============================================================
        print(f"\n--- ШАГ 1: Поиск NC-сделок и NC-контактов ---")
        nc_deals = db.session.execute(text(
            "SELECT d.id, d.agreement_number, d.contacts_buy_id "
            "FROM estate_deals d "
            "WHERE d.agreement_number LIKE :nc OR d.agreement_number = :sys "
            "ORDER BY d.id"
        ), {"nc": "NC-%", "sys": "SYSTEM-001"}).fetchall()

        print(f"  NC-сделок всего: {len(nc_deals)}")

        # Разделяем на положительные и уже отрицательные
        pos_deals = [(d[0], d[1], d[2]) for d in nc_deals if d[0] > 0]
        neg_deals = [(d[0], d[1], d[2]) for d in nc_deals if d[0] < 0]
        print(f"    С положительным ID: {len(pos_deals)}")
        print(f"    С отрицательным ID (уже негированы data_sync): {len(neg_deals)}")

        # Собираем уникальные NC-контакты (все положительные, т.к. контакты не негировались)
        nc_contact_ids = set()
        for d in nc_deals:
            if d[2] and d[2] > 0:
                nc_contact_ids.add(d[2])
        nc_contact_ids = sorted(nc_contact_ids)
        print(f"  NC-контактов с положительным ID: {len(nc_contact_ids)}")

        if not nc_contact_ids and not pos_deals:
            print("\n  ✓ Нечего мигрировать — все NC-записи уже мигрированы.")
            return

        # ============================================================
        # ШАГ 2: Построить маппинг старый ID → новый ID
        # ============================================================
        print(f"\n--- ШАГ 2: Построение маппинга ID ---")

        # Контакты: -1, -2, -3, ...
        contact_id_map = {}  # old_positive_id → new_negative_id
        for i, old_id in enumerate(nc_contact_ids, start=1):
            contact_id_map[old_id] = -i
        print(f"  Контакты: {len(contact_id_map)} записей")
        if contact_id_map:
            sample = list(contact_id_map.items())[:3]
            for old, new in sample:
                print(f"    {old} → {new}")

        # Сделки с положительным ID: -1, -2, -3, ...
        deal_id_map = {}  # old_positive_id → new_negative_id
        pos_deals_sorted = sorted(pos_deals, key=lambda x: x[0])
        for i, (old_id, agr, cid) in enumerate(pos_deals_sorted, start=1):
            deal_id_map[old_id] = -i
        print(f"  Сделки (положительные → отрицательные): {len(deal_id_map)} записей")
        if deal_id_map:
            sample = list(deal_id_map.items())[:3]
            for old, new in sample:
                print(f"    {old} → {new}")

        # ============================================================
        # ШАГ 3: Проверка коллизий в целевом пространстве
        # ============================================================
        print(f"\n--- ШАГ 3: Проверка коллизий ---")

        # Проверяем контакты
        new_contact_ids = set(contact_id_map.values())
        if new_contact_ids:
            min_new = min(new_contact_ids)
            max_new = max(new_contact_ids)
            existing = db.session.execute(text(
                "SELECT COUNT(*) FROM estate_deals_contacts "
                "WHERE id BETWEEN :min_id AND :max_id"
            ), {"min_id": min_new, "max_id": max_new}).scalar()
            if existing > 0:
                print(f"  ✗ КОЛЛИЗИЯ: {existing} контактов с ID в диапазоне [{min_new}, {max_new}]!")
                return
            print(f"  ✓ Контакты: диапазон [{min_new}, {max_new}] свободен")

        # Проверяем сделки
        new_deal_ids = set(deal_id_map.values())
        if new_deal_ids:
            min_new = min(new_deal_ids)
            max_new = max(new_deal_ids)
            existing = db.session.execute(text(
                "SELECT COUNT(*) FROM estate_deals "
                "WHERE id BETWEEN :min_id AND :max_id"
            ), {"min_id": min_new, "max_id": max_new}).scalar()
            if existing > 0:
                print(f"  ✗ КОЛЛИЗИЯ: {existing} сделок с ID в диапазоне [{min_new}, {max_new}]!")
                return
            print(f"  ✓ Сделки: диапазон [{min_new}, {max_new}] свободен")

        # ============================================================
        # ШАГ 4: Найти зависимые заявки
        # ============================================================
        print(f"\n--- ШАГ 4: Поиск зависимых заявок ---")
        affected_apps = []
        if nc_contact_ids:
            placeholders = ','.join(str(i) for i in nc_contact_ids)
            affected_apps = db.session.execute(text(
                f"SELECT id, client_id, agreement_number "
                f"FROM applications "
                f"WHERE client_id IN ({placeholders})"
            )).fetchall()
        print(f"  Заявок, ссылающихся на NC-контакты: {len(affected_apps)}")

        # ============================================================
        # ШАГ 5: Выполнение миграции
        # ============================================================
        print(f"\n--- ШАГ 5: Миграция [{mode}] ---")

        if dry_run:
            print(f"\n  Что будет сделано:")
            print(f"    1. {len(contact_id_map)} контактов → последовательные отрицательные ID")
            print(f"    2. {len(deal_id_map)} положительных сделок → последовательные отрицательные ID")
            print(f"    3. {len(neg_deals)} уже отрицательных сделок: обновление contacts_buy_id")
            print(f"    4. {len(affected_apps)} заявок: обновление client_id")
            print(f"\n  Примеры маппинга контактов:")
            for old, new in list(contact_id_map.items())[:5]:
                print(f"    contact {old} → {new}")
            print(f"\n  Примеры маппинга сделок:")
            for old, new in list(deal_id_map.items())[:5]:
                print(f"    deal {old} → {new}")
        else:
            conn = db.session.connection()
            conn.execute(text("PRAGMA foreign_keys = OFF"))

            try:
                # 5a. Обновляем контакты
                migrated_contacts = 0
                for old_id, new_id in contact_id_map.items():
                    conn.execute(text(
                        "UPDATE estate_deals_contacts SET id = :new_id WHERE id = :old_id"
                    ), {"new_id": new_id, "old_id": old_id})
                    migrated_contacts += 1
                print(f"  ✓ Контакты: {migrated_contacts} записей")

                # 5b. Обновляем положительные сделки (id + contacts_buy_id)
                migrated_pos_deals = 0
                for old_id, agr, old_cid in pos_deals_sorted:
                    new_deal_id = deal_id_map[old_id]
                    new_cid = contact_id_map.get(old_cid, old_cid) if old_cid else old_cid
                    conn.execute(text(
                        "UPDATE estate_deals SET id = :new_id, contacts_buy_id = :new_cid "
                        "WHERE id = :old_id"
                    ), {"new_id": new_deal_id, "old_id": old_id, "new_cid": new_cid})
                    migrated_pos_deals += 1
                print(f"  ✓ Сделки (положительные): {migrated_pos_deals} записей")

                # 5c. Обновляем уже отрицательные сделки — только contacts_buy_id
                migrated_neg_deals = 0
                for deal_id, agr, old_cid in neg_deals:
                    if old_cid and old_cid > 0 and old_cid in contact_id_map:
                        new_cid = contact_id_map[old_cid]
                        conn.execute(text(
                            "UPDATE estate_deals SET contacts_buy_id = :new_cid "
                            "WHERE id = :deal_id"
                        ), {"new_cid": new_cid, "deal_id": deal_id})
                        migrated_neg_deals += 1
                print(f"  ✓ Сделки (уже отрицательные, обновлён FK): {migrated_neg_deals} записей")

                # 5d. Обновляем заявки — client_id
                migrated_apps = 0
                for app_row in affected_apps:
                    app_id, old_cid, _ = app_row
                    if old_cid in contact_id_map:
                        conn.execute(text(
                            "UPDATE applications SET client_id = :new_cid WHERE id = :app_id"
                        ), {"new_cid": contact_id_map[old_cid], "app_id": app_id})
                        migrated_apps += 1
                print(f"  ✓ Заявки: {migrated_apps} записей")

                # Включаем FK
                conn.execute(text("PRAGMA foreign_keys = ON"))

                db.session.commit()
                print(f"\n  ✓ Миграция успешно завершена!")

            except Exception as e:
                db.session.rollback()
                print(f"\n  ✗ Ошибка: {e}")
                print("  Все изменения откачены.")
                raise

        # ============================================================
        # ШАГ 6: Валидация
        # ============================================================
        print(f"\n--- ШАГ 6: Валидация ---")

        remaining = db.session.execute(text(
            "SELECT COUNT(*) FROM estate_deals d "
            "JOIN estate_deals_contacts c ON d.contacts_buy_id = c.id "
            "WHERE (d.agreement_number LIKE :nc OR d.agreement_number = :sys) "
            "AND c.id > 0"
        ), {"nc": "NC-%", "sys": "SYSTEM-001"}).scalar()

        if remaining > 0:
            print(f"  ⚠ Осталось {remaining} NC-контактов с положительным ID")
        else:
            if not dry_run:
                print(f"  ✓ Все NC-контакты имеют отрицательные ID")
            else:
                print(f"  (будут мигрированы при --apply)")

        total_contacts = db.session.execute(text("SELECT COUNT(*) FROM estate_deals_contacts")).scalar()
        total_deals = db.session.execute(text("SELECT COUNT(*) FROM estate_deals")).scalar()
        neg_contacts = db.session.execute(text("SELECT COUNT(*) FROM estate_deals_contacts WHERE id < 0")).scalar()
        neg_deals = db.session.execute(text("SELECT COUNT(*) FROM estate_deals WHERE id < 0")).scalar()

        print(f"\n  Статистика:")
        print(f"    Контакты: {total_contacts} всего, {neg_contacts} с отрицательным ID")
        print(f"    Сделки: {total_deals} всего, {neg_deals} с отрицательным ID")

        if not dry_run:
            print(f"\n{'=' * 60}")
            print(f"  СЛЕДУЮЩИЙ ШАГ: перезапустите контейнер client-service")
            print(f"  для пересинхронизации данных из MySQL!")
            print(f"  docker compose restart client-service-service")
            print(f"{'=' * 60}")


def main():
    parser = argparse.ArgumentParser(
        description="Миграция NC-контактов на отрицательные ID"
    )
    parser.add_argument('--apply', action='store_true',
                        help='Применить миграцию (по умолчанию — dry-run)')
    args = parser.parse_args()
    migrate_nc_to_negative_ids(dry_run=not args.apply)


if __name__ == '__main__':
    main()
