#!/usr/bin/env python3
"""
Миграционный скрипт: восстановление удалённых клиентов, на которых ссылаются заявки.

ПРОБЛЕМА
  estate_deals_contacts в MacroCRM содержит только владельцев действующих сделок.
  После переуступки/переоформления договора прежний владелец пропадает из источника,
  а data_sync.sync_data() полностью перезаливал эту таблицу. В результате
  applications.client_id указывал на несуществующую строку:
    - Application.client -> None, в списке заявок клиент показывается как «N/A»;
    - на карточке заявки нет кнопки «К карточке клиента» и нет данных договора
      (deal_info ищет сделку по паре agreement_number + client_id).

РЕШЕНИЕ
  Восстановить строку клиента, а НЕ перепривязывать заявку к текущему владельцу
  договора. Заявку подавал прежний владелец: часть договоров реально сменила
  собственника (перепродажа), и перепривязка приписала бы чужую заявку.

  Источники восстановления, в порядке приоритета:
    1. --donor PATH — явно указанные копии app.db, где клиент ещё присутствует;
    2. backups/*.sqlite — бэкапы БД в этой папке, от свежего к старому;
    3. таблица contacts в MacroCRM — мастер-справочник, переживает удаление
       записи из estate_deals_contacts, но не переживает слияние дублей.

  ВНИМАНИЕ: backups/ исключена из git (.gitignore) и в Docker-образ не попадает.
  В контейнере источник (1) обычно единственный полноценный — скопируйте туда
  бэкап с рабочей машины:
    docker cp backups/db_before_nc_migration_20260225_174029.sqlite \\
              client-service-service:/tmp/donor.sqlite

  Рецидив закрыт в data_sync.py: клиенты, на которых ссылаются заявки, больше
  не удаляются при синхронизации.

ИСПОЛЬЗОВАНИЕ
  python fix_orphan_clients.py                          # Dry-run (по умолчанию)
  python fix_orphan_clients.py --donor /tmp/donor.sqlite
  python fix_orphan_clients.py --donor /tmp/donor.sqlite --apply
  python fix_orphan_clients.py --report                 # Только отчёт

Бэкап базы создаётся автоматически перед изменениями в папку backups/.
Скрипт идемпотентен: повторный запуск чинит только то, что осталось.
"""

import argparse
import datetime
import glob
import os
import sqlite3
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BACKUP_DIR = os.path.join(BASE_DIR, 'backups')

sys.path.insert(0, BASE_DIR)

# config.py ищет .env на уровень выше корня проекта — при запуске скрипта вручную
# (вне Docker, где переменные приходят через env_file) он не находится.
# Грузим явно ДО импорта config, иначе SOURCE_DATABASE_URI соберётся как None.
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE_DIR, '.env'))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from backup_manager import resolve_db_path  # noqa: E402
from config import Config  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402


# ============================================================================
# ВСПОМОГАТЕЛЬНОЕ
# ============================================================================

def backup_database(app):
    """Создаёт бэкап SQLite базы данных.

    Через online-backup API SQLite, а не копированием файла: база работает
    в режиме WAL, и часть закоммиченных транзакций может лежать в -wal,
    которого обычный copy не захватит."""
    db_path = resolve_db_path(app)
    if not db_path:
        print(f"  ! Не SQLite БД, бэкап пропущен")
        return None

    os.makedirs(BACKUP_DIR, exist_ok=True)
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = os.path.join(BACKUP_DIR, f"db_before_orphan_clients_{timestamp}.sqlite")
    tmp_path = backup_path + '.tmp'

    src = dst = None
    try:
        src = sqlite3.connect(db_path)
        dst = sqlite3.connect(tmp_path)
        with dst:
            src.backup(dst)
    except (sqlite3.Error, OSError) as e:
        print(f"  ! Бэкап не создан: {e}")
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        return None
    finally:
        for con in (dst, src):
            if con is not None:
                con.close()

    os.replace(tmp_path, backup_path)
    size_mb = os.path.getsize(backup_path) / (1024 * 1024)
    print(f"  + Бэкап: {backup_path} ({size_mb:.1f} МБ)")
    return backup_path


def find_orphans():
    """Заявки, чей client_id не имеет строки в estate_deals_contacts.

    Возвращает (orphan_ids: list[int], rows: list[dict])."""
    rows = db.session.execute(text('''
        SELECT a.id AS app_id, a.client_id, a.agreement_number, a.created_at
        FROM applications a
        LEFT JOIN estate_deals_contacts c ON c.id = a.client_id
        WHERE c.id IS NULL
        ORDER BY a.client_id, a.id
    ''')).mappings().all()
    rows = [dict(r) for r in rows]
    orphan_ids = sorted({r['client_id'] for r in rows})
    return orphan_ids, rows


# ============================================================================
# ПОИСК ДАННЫХ КЛИЕНТА
# ============================================================================

def recover_from_donors(missing_ids, donors):
    """Ищет клиентов в донорских БД: сначала явно указанные через --donor,
    затем бэкапы из backups/ от самого свежего к старому.

    Донор — любая копия app.db, где нужный клиент ещё присутствует
    (бэкап до синхронизации, копия БД с другого стенда)."""
    found = {}
    explicit = []
    for path in donors or []:
        if os.path.exists(path):
            explicit.append(path)
        else:
            print(f"  ! Донор не найден: {path}")

    # recursive: автоматические бэкапы разложены по подпапкам daily/weekly/monthly
    auto = sorted(glob.glob(os.path.join(BACKUP_DIR, '**', '*.sqlite'), recursive=True),
                  key=lambda p: os.path.getmtime(p), reverse=True)
    backups = explicit + auto
    if not backups:
        print("  - Донорских БД не задано, бэкапов в backups/ нет.")
        print("    Папка backups/ в git не хранится (см. .gitignore) и в образ не попадает —")
        print("    скопируйте бэкап в контейнер и укажите его через --donor.")
        return found

    for path in backups:
        remaining = [i for i in missing_ids if i not in found]
        if not remaining:
            break
        try:
            con = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
            con.row_factory = sqlite3.Row
            placeholders = ','.join('?' * len(remaining))
            rows = con.execute(
                f'SELECT id, contacts_buy_name, contacts_buy_phones '
                f'FROM estate_deals_contacts WHERE id IN ({placeholders})',
                remaining
            ).fetchall()
            con.close()
        except sqlite3.Error as e:
            print(f"  ! Бэкап {os.path.basename(path)} прочитать не удалось: {e}")
            continue

        for r in rows:
            found[r['id']] = {
                'id': r['id'],
                'contacts_buy_name': r['contacts_buy_name'],
                'contacts_buy_phones': r['contacts_buy_phones'],
                'source': os.path.basename(path),
            }
        if rows:
            print(f"  + {os.path.basename(path)}: найдено {len(rows)} клиентов.")

    return found


def recover_from_source(missing_ids):
    """Ищет клиентов в мастер-справочнике contacts MacroCRM (только чтение)."""
    found = {}
    if not missing_ids:
        return found
    if not Config.SOURCE_DATABASE_URI:
        print("  - SOURCE_DATABASE_URI не настроен, источник пропущен.")
        return found

    try:
        engine = create_engine(Config.SOURCE_DATABASE_URI, pool_pre_ping=True)
        with engine.connect() as con:
            rows = con.execute(text(
                'SELECT id, contacts_buy_name, contacts_buy_phones '
                'FROM contacts WHERE id IN :ids'
            ), {'ids': tuple(missing_ids)}).mappings().all()
    except Exception as e:
        print(f"  ! Источник MySQL недоступен: {e}")
        return found

    for r in rows:
        found[r['id']] = {
            'id': r['id'],
            'contacts_buy_name': r['contacts_buy_name'],
            'contacts_buy_phones': r['contacts_buy_phones'],
            'source': 'MacroCRM.contacts',
        }
    if rows:
        print(f"  + MacroCRM.contacts: найдено {len(rows)} клиентов.")
    return found


# ============================================================================
# ОТЧЁТ И ПРИМЕНЕНИЕ
# ============================================================================

def report(orphan_ids, orphan_rows, recovered):
    print()
    print("=== ОСИРОТЕВШИЕ ЗАЯВКИ ===")
    by_client = {}
    for r in orphan_rows:
        by_client.setdefault(r['client_id'], []).append(r)

    for cid in orphan_ids:
        apps = by_client[cid]
        data = recovered.get(cid)
        app_ids = ', '.join(str(a['app_id']) for a in apps)
        agreements = ', '.join(sorted({a['agreement_number'] for a in apps}))
        if data:
            print(f"  client_id={cid} <- «{data['contacts_buy_name']}» "
                  f"({data['contacts_buy_phones'] or 'нет телефона'}) [{data['source']}]")
        else:
            print(f"  client_id={cid} <- НЕ ВОССТАНОВЛЕН")
        print(f"      заявки: {app_ids}")
        print(f"      договоры: {agreements}")

    ok = sum(1 for cid in orphan_ids if cid in recovered)
    apps_ok = sum(len(by_client[cid]) for cid in orphan_ids if cid in recovered)
    print()
    print(f"  Итого: клиентов {ok}/{len(orphan_ids)}, "
          f"заявок {apps_ok}/{len(orphan_rows)} будет починено.")


def apply_fix(recovered):
    """Вставляет восстановленные строки клиентов."""
    inserted = 0
    for cid, data in sorted(recovered.items()):
        db.session.execute(text('''
            INSERT INTO estate_deals_contacts (id, contacts_buy_name, contacts_buy_phones)
            VALUES (:id, :name, :phones)
        '''), {
            'id': data['id'],
            'name': data['contacts_buy_name'],
            'phones': data['contacts_buy_phones'],
        })
        inserted += 1
    db.session.commit()
    print(f"  + Вставлено клиентов: {inserted}")
    return inserted


def validate():
    """Проверяет, что осиротевших заявок не осталось."""
    remaining = db.session.execute(text('''
        SELECT COUNT(*) FROM applications a
        LEFT JOIN estate_deals_contacts c ON c.id = a.client_id
        WHERE c.id IS NULL
    ''')).scalar()
    if remaining:
        print(f"  ! Осталось осиротевших заявок: {remaining}")
    else:
        print("  + Осиротевших заявок не осталось.")
    return remaining


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Восстановление удалённых клиентов, на которых ссылаются заявки.'
    )
    parser.add_argument('--apply', action='store_true',
                        help='Применить изменения (по умолчанию dry-run)')
    parser.add_argument('--report', action='store_true',
                        help='Только отчёт, без поиска в источнике и без изменений')
    parser.add_argument('--donor', action='append', metavar='PATH',
                        help='Путь к донорской SQLite-БД, где клиент ещё есть '
                             '(можно указать несколько раз). Проверяются раньше backups/.')
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        orphan_ids, orphan_rows = find_orphans()

        print(f"Осиротевших заявок: {len(orphan_rows)}, "
              f"уникальных клиентов: {len(orphan_ids)}")

        if not orphan_ids:
            print("Чинить нечего.")
            return 0

        if args.report:
            report(orphan_ids, orphan_rows, {})
            return 0

        print()
        print("=== ПОИСК ДАННЫХ КЛИЕНТОВ ===")
        recovered = recover_from_donors(orphan_ids, args.donor)
        still_missing = [i for i in orphan_ids if i not in recovered]
        recovered.update(recover_from_source(still_missing))

        report(orphan_ids, orphan_rows, recovered)

        unrecovered = [i for i in orphan_ids if i not in recovered]
        if unrecovered:
            print()
            print(f"  ! Без данных остались client_id: {unrecovered}")
            print("    Их заявки продолжат показывать «N/A»: данных нет ни в донорских БД,")
            print("    ни в мастер-справочнике MacroCRM (клиент слит с дублем и удалён).")
            print("    Найдите более старую копию app.db и передайте её через --donor.")

        if not args.apply:
            print()
            print("DRY-RUN. Изменения не внесены. Повторите с --apply.")
            return 0

        print()
        print("=== ПРИМЕНЕНИЕ ===")
        backup_database(app)
        apply_fix(recovered)
        validate()
        return 0


if __name__ == '__main__':
    sys.exit(main())
