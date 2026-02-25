#!/usr/bin/env python3
"""
Миграционный скрипт: исправление привязок заявок к пользователям.

Исправляет:
  1. ApplicationLog.author_id — строковые gateway ID (MongoDB ObjectID)
     хранятся в integer FK поле вместо локального user.id
  2. ResponsiblePerson.gateway_user_id — NULL у всех ответственных лиц,
     что ломает фильтрацию «мои заявки» для менеджеров ДКС

Не трогает:
  - 7 ранних заявок (id 2-8) без creator_id — создатель неизвестен
  - 793 ранних логов без author_id — автор неизвестен (до добавления поля)

Использование:
  python migrate_fix_bindings.py              # Dry-run (по умолчанию)
  python migrate_fix_bindings.py --apply      # Применить миграцию
  python migrate_fix_bindings.py --report     # Только отчёт, без изменений

Бэкап базы создаётся автоматически перед миграцией в папку backups/.
"""

import argparse
import datetime
import os
import shutil
import sys

# Добавляем корень проекта в PYTHONPATH
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from app.extensions import db
from app.models import User, Application, ApplicationLog, ResponsiblePerson
from sqlalchemy import text


# ============================================================================
# КОНФИГУРАЦИЯ МАППИНГА
# ============================================================================
#
# ResponsiblePerson.id → User.auth_user_id (gateway MongoDB ObjectID)
#
# ⚠️  ПРОВЕРЬ ЭТОТ МАППИНГ ПЕРЕД ЗАПУСКОМ С --apply!
#     Закомментируй или удали строки, в которых не уверен.
#     Скрипт пропустит записи без маппинга и выведет предупреждение.
#
# Формат: responsible_person_id → auth_user_id пользователя из Gateway
#
RESPONSIBLE_PERSON_TO_GATEWAY_USER = {
    # RP id=1  'Алина Хайруллина'                    → User id=11 'Alina'
    1: '683847e82e6536e622a19d7e',
    # RP id=2  'Карина Гумерова'                      → User id=10 'Karina'
    2: '683847e82e6536e622a19d86',
    # RP id=3  'Алия Анварова'                        → User id=6  'Aliya'
    3: '683847e82e6536e622a19d80',
    # RP id=4  'Андрей Токарев'                       → User id=8  'AndreyT'
    4: '683847e92e6536e622a19d9a',
    # RP id=5  'Дмитрий Мезенцев'                     → User id=7  'Dmitriy'
    5: '683847e92e6536e622a19d99',
    # RP id=6  'Даврон Уринов'                        → User id=9  'DavronU'
    6: '683847e92e6536e622a19d92',
    # RP id=7  'Санжар Пулатов'                       → User id=12 'Sanjar'
    7: '683847e22e6536e622a19d04',
    # RP id=8  'Luiza Kayumova'                       → User id=19 'L.kayumova'
    8: '68f9dfe135a5488684d82772',
    # RP id=9  'Мехрожиддин Исломбеков'               → User id=3  'Mehroj'
    9: '68f72e1baba349d342bc74d3',
    # RP id=10 'Dmitrii Plakhotnyi Pavlovich'         → ???  НЕТ СООТВЕТСТВИЯ
    # 10: None,
    # RP id=11 'Чарос Шафайзиева'                    → User id=4  'Charos'
    11: '68f72e47aba349d342bc74d4',
    # RP id=12 'Кунанбаев Русланбек Ахмедович'        → User id=17 'Ruslan Kunanbayev'
    12: '68ee1d7f4271cf7486950e8c',
    # RP id=13 'Мирокил Рузиев'                      → ???  НЕТ СООТВЕТСТВИЯ
    # 13: None,
}


# ============================================================================
# УТИЛИТЫ
# ============================================================================

class Colors:
    """ANSI цвета для терминала."""
    HEADER = '\033[95m'
    OK = '\033[92m'
    WARN = '\033[93m'
    FAIL = '\033[91m'
    BOLD = '\033[1m'
    END = '\033[0m'

    @staticmethod
    def supported():
        return hasattr(sys.stdout, 'isatty') and sys.stdout.isatty()


def cprint(msg, color=''):
    """Печать с цветом (если терминал поддерживает)."""
    if Colors.supported() and color:
        print(f"{color}{msg}{Colors.END}")
    else:
        print(msg)


def backup_database(app):
    """Создаёт бэкап SQLite базы данных."""
    db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')

    # Извлекаем путь к файлу БД
    if db_uri.startswith('sqlite:///'):
        db_path = db_uri.replace('sqlite:///', '')
    elif db_uri.startswith('sqlite:////'):
        db_path = db_uri.replace('sqlite:////', '')
    else:
        cprint(f"  ⚠ Не SQLite БД ({db_uri}), бэкап пропущен", Colors.WARN)
        return None

    if not os.path.isabs(db_path):
        db_path = os.path.join(app.instance_path, db_path)

    if not os.path.exists(db_path):
        cprint(f"  ⚠ Файл БД не найден: {db_path}", Colors.WARN)
        return None

    # Создаём папку для бэкапов
    backup_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backups')
    os.makedirs(backup_dir, exist_ok=True)

    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_name = f"db_backup_{timestamp}.sqlite"
    backup_path = os.path.join(backup_dir, backup_name)

    shutil.copy2(db_path, backup_path)
    size_mb = os.path.getsize(backup_path) / (1024 * 1024)
    cprint(f"  ✓ Бэкап: {backup_path} ({size_mb:.1f} МБ)", Colors.OK)
    return backup_path


# ============================================================================
# ШАГ 1: Исправление ApplicationLog.author_id
# ============================================================================

def fix_log_author_ids(dry_run=True):
    """
    Исправляет ApplicationLog.author_id: заменяет строковые gateway ID
    на целочисленные локальные user.id.

    Проблема: баг в update_application_status записывал
    get_current_user_id() (строковый MongoDB ObjectID из Gateway)
    в integer FK поле author_id.
    """
    cprint("\n" + "=" * 60, Colors.HEADER)
    cprint("ШАГ 1: Исправление ApplicationLog.author_id", Colors.BOLD)
    cprint("=" * 60, Colors.HEADER)

    # Находим все записи, где author_id не является валидным user.id
    # (строка в integer поле — SQLite это позволяет)
    result = db.session.execute(text(
        "SELECT DISTINCT al.author_id "
        "FROM application_logs al "
        "LEFT JOIN users u ON al.author_id = u.id "
        "WHERE al.author_id IS NOT NULL AND u.id IS NULL"
    ))
    broken_gateway_ids = [row[0] for row in result.fetchall()]

    if not broken_gateway_ids:
        cprint("  ✓ Нет записей с некорректным author_id", Colors.OK)
        return 0

    # Строим маппинг gateway_id → local_user_id
    total_fixed = 0
    total_unresolved = 0

    for gw_id in sorted(broken_gateway_ids):
        user = User.query.filter_by(auth_user_id=str(gw_id)).first()
        count_result = db.session.execute(
            text("SELECT COUNT(*) FROM application_logs WHERE author_id = :gid"),
            {"gid": gw_id}
        )
        count = count_result.scalar()

        if user:
            cprint(f"  {gw_id} → User(id={user.id}, '{user.username}') | {count} записей", Colors.OK)
            if not dry_run:
                db.session.execute(
                    text("UPDATE application_logs SET author_id = :uid WHERE author_id = :gid"),
                    {"uid": user.id, "gid": gw_id}
                )
            total_fixed += count
        else:
            cprint(f"  {gw_id} → НЕ НАЙДЕН пользователь | {count} записей", Colors.FAIL)
            total_unresolved += count

    # Итог
    mode = "DRY-RUN" if dry_run else "ПРИМЕНЕНО"
    cprint(f"\n  [{mode}] Исправлено: {total_fixed}, Не удалось: {total_unresolved}", Colors.BOLD)

    if total_unresolved > 0:
        cprint("  ⚠ Некоторые gateway ID не удалось сопоставить с пользователями!", Colors.WARN)

    return total_fixed


# ============================================================================
# ШАГ 2: Привязка ResponsiblePerson к Gateway-пользователям
# ============================================================================

def link_responsible_persons(dry_run=True):
    """
    Заполняет ResponsiblePerson.gateway_user_id из конфигурации маппинга.
    Это нужно для корректной работы фильтрации «мои заявки» у менеджеров ДКС.
    """
    cprint("\n" + "=" * 60, Colors.HEADER)
    cprint("ШАГ 2: Привязка ResponsiblePerson → Gateway User", Colors.BOLD)
    cprint("=" * 60, Colors.HEADER)

    responsible_persons = ResponsiblePerson.query.order_by(ResponsiblePerson.id).all()
    total_linked = 0
    total_skipped = 0
    total_already = 0

    for rp in responsible_persons:
        gateway_user_id = RESPONSIBLE_PERSON_TO_GATEWAY_USER.get(rp.id)
        app_count = Application.query.filter_by(responsible_person_id=rp.id).count()

        if rp.gateway_user_id:
            # Уже привязан
            cprint(f"  id={rp.id} '{rp.full_name}' ({app_count} заявок) — "
                   f"уже привязан: {rp.gateway_user_id}", Colors.OK)
            total_already += 1
            continue

        if gateway_user_id is None:
            # Нет маппинга в конфиге
            cprint(f"  id={rp.id} '{rp.full_name}' ({app_count} заявок) — "
                   f"НЕТ МАППИНГА в конфиге", Colors.WARN)
            total_skipped += 1
            continue

        # Проверяем, что пользователь с таким auth_user_id существует
        user = User.query.filter_by(auth_user_id=gateway_user_id).first()
        if not user:
            cprint(f"  id={rp.id} '{rp.full_name}' ({app_count} заявок) — "
                   f"User с auth_user_id={gateway_user_id} НЕ НАЙДЕН!", Colors.FAIL)
            total_skipped += 1
            continue

        cprint(f"  id={rp.id} '{rp.full_name}' ({app_count} заявок) → "
               f"User(id={user.id}, '{user.username}')", Colors.OK)

        if not dry_run:
            rp.gateway_user_id = gateway_user_id

        total_linked += 1

    # Итог
    mode = "DRY-RUN" if dry_run else "ПРИМЕНЕНО"
    cprint(f"\n  [{mode}] Привязано: {total_linked}, Пропущено: {total_skipped}, "
           f"Уже было: {total_already}", Colors.BOLD)

    return total_linked


# ============================================================================
# ШАГ 3: Отчёт по невосстановимым записям
# ============================================================================

def report_unrecoverable():
    """Выводит отчёт по записям, которые невозможно восстановить автоматически."""
    cprint("\n" + "=" * 60, Colors.HEADER)
    cprint("ОТЧЁТ: Невосстановимые записи", Colors.BOLD)
    cprint("=" * 60, Colors.HEADER)

    # 1. Заявки без создателя
    apps_no_creator = Application.query.filter(Application.creator_id == None).all()
    cprint(f"\n  Заявки без создателя (creator_id IS NULL): {len(apps_no_creator)}")
    for a in apps_no_creator:
        rp = db.session.get(ResponsiblePerson, a.responsible_person_id) if a.responsible_person_id else None
        rp_name = rp.full_name if rp else "нет"
        cprint(f"    app_id={a.id}, тип='{a.application_type}', статус='{a.status}', "
               f"дата={a.created_at}, ответственный='{rp_name}'")

    # 2. Логи без автора
    from sqlalchemy import func
    logs_no_author = db.session.query(func.count(ApplicationLog.id)).filter(
        ApplicationLog.author_id == None
    ).scalar()
    cprint(f"\n  Логи без автора (author_id IS NULL): {logs_no_author}")
    cprint("    (ранние записи, до добавления поля author_id — невосстановимы)")

    # 3. Ответственные без маппинга
    rps_no_gateway = ResponsiblePerson.query.filter(
        ResponsiblePerson.gateway_user_id == None
    ).all()
    unmapped = [rp for rp in rps_no_gateway if rp.id not in RESPONSIBLE_PERSON_TO_GATEWAY_USER]
    if unmapped:
        cprint(f"\n  Ответственные без маппинга в конфиге: {len(unmapped)}")
        for rp in unmapped:
            app_count = Application.query.filter_by(responsible_person_id=rp.id).count()
            cprint(f"    id={rp.id} '{rp.full_name}' ({app_count} заявок)")
        cprint("    → Добавьте маппинг в RESPONSIBLE_PERSON_TO_GATEWAY_USER")


# ============================================================================
# ШАГ 4: Валидация после миграции
# ============================================================================

def validate_migration():
    """Проверяет целостность данных после миграции."""
    cprint("\n" + "=" * 60, Colors.HEADER)
    cprint("ВАЛИДАЦИЯ: Проверка целостности", Colors.BOLD)
    cprint("=" * 60, Colors.HEADER)

    errors = 0

    # 1. Проверяем, что нет строковых author_id
    result = db.session.execute(text(
        "SELECT COUNT(*) FROM application_logs al "
        "LEFT JOIN users u ON al.author_id = u.id "
        "WHERE al.author_id IS NOT NULL AND u.id IS NULL"
    ))
    broken_logs = result.scalar()
    if broken_logs > 0:
        cprint(f"  ✗ Осталось {broken_logs} логов с невалидным author_id", Colors.FAIL)
        errors += 1
    else:
        cprint("  ✓ Все author_id в логах валидны (NULL или ссылаются на users.id)", Colors.OK)

    # 2. Проверяем, что все creator_id валидны
    result = db.session.execute(text(
        "SELECT COUNT(*) FROM applications a "
        "LEFT JOIN users u ON a.creator_id = u.id "
        "WHERE a.creator_id IS NOT NULL AND u.id IS NULL"
    ))
    broken_creators = result.scalar()
    if broken_creators > 0:
        cprint(f"  ✗ {broken_creators} заявок с невалидным creator_id", Colors.FAIL)
        errors += 1
    else:
        cprint("  ✓ Все creator_id в заявках валидны", Colors.OK)

    # 3. Проверяем ResponsiblePerson.gateway_user_id
    from sqlalchemy import func
    rps_with_gateway = db.session.query(func.count(ResponsiblePerson.id)).filter(
        ResponsiblePerson.gateway_user_id != None
    ).scalar()
    rps_total = db.session.query(func.count(ResponsiblePerson.id)).scalar()
    if rps_with_gateway == rps_total:
        cprint(f"  ✓ Все ответственные ({rps_total}) привязаны к gateway", Colors.OK)
    else:
        cprint(f"  ⚠ Привязано {rps_with_gateway}/{rps_total} ответственных", Colors.WARN)

    # 4. Общая статистика
    from sqlalchemy import func as fn
    total_apps = db.session.query(fn.count(Application.id)).scalar()
    apps_with_creator = db.session.query(fn.count(Application.id)).filter(
        Application.creator_id != None
    ).scalar()
    total_logs = db.session.query(fn.count(ApplicationLog.id)).scalar()
    logs_with_author = db.session.query(fn.count(ApplicationLog.id)).filter(
        ApplicationLog.author_id != None
    ).scalar()

    cprint(f"\n  Статистика:")
    cprint(f"    Заявки с создателем: {apps_with_creator}/{total_apps}")
    cprint(f"    Логи с автором:     {logs_with_author}/{total_logs}")
    cprint(f"    Ответственные:      {rps_with_gateway}/{rps_total} привязаны")

    if errors > 0:
        cprint(f"\n  ✗ Найдено {errors} проблем!", Colors.FAIL)
    else:
        cprint(f"\n  ✓ Валидация пройдена", Colors.OK)

    return errors


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Миграция: исправление привязок заявок к пользователям",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        '--apply', action='store_true',
        help='Применить миграцию (по умолчанию — dry-run)'
    )
    parser.add_argument(
        '--report', action='store_true',
        help='Только отчёт, без изменений'
    )
    parser.add_argument(
        '--no-backup', action='store_true',
        help='Не создавать бэкап (опасно!)'
    )
    args = parser.parse_args()

    dry_run = not args.apply

    app = create_app()

    with app.app_context():
        # Заголовок
        cprint("\n" + "=" * 60, Colors.HEADER)
        if args.report:
            cprint("  РЕЖИМ: ТОЛЬКО ОТЧЁТ", Colors.BOLD)
        elif dry_run:
            cprint("  РЕЖИМ: DRY-RUN (без изменений в БД)", Colors.WARN)
            cprint("  Для применения запустите с флагом --apply", Colors.WARN)
        else:
            cprint("  РЕЖИМ: APPLY — ИЗМЕНЕНИЯ БУДУТ ЗАПИСАНЫ В БД!", Colors.FAIL)
        cprint("=" * 60, Colors.HEADER)

        # Бэкап
        if args.apply and not args.no_backup:
            cprint("\nСоздание бэкапа...", Colors.BOLD)
            backup_path = backup_database(app)
            if backup_path:
                cprint(f"  Для восстановления: скопируйте {backup_path} обратно", Colors.OK)
            else:
                cprint("  ⚠ Бэкап не создан! Используйте --no-backup чтобы продолжить", Colors.WARN)
                answer = input("  Продолжить без бэкапа? (yes/no): ").strip().lower()
                if answer != 'yes':
                    cprint("  Отменено.", Colors.FAIL)
                    sys.exit(1)

        if args.report:
            # Только отчёт
            report_unrecoverable()
            validate_migration()
            return

        # Шаг 1: Исправление author_id в логах
        fixed_logs = fix_log_author_ids(dry_run=dry_run)

        # Шаг 2: Привязка ответственных лиц
        linked_rps = link_responsible_persons(dry_run=dry_run)

        # Шаг 3: Отчёт по невосстановимым
        report_unrecoverable()

        # Коммит или откат
        if not dry_run:
            if fixed_logs > 0 or linked_rps > 0:
                cprint("\nСохранение изменений...", Colors.BOLD)
                try:
                    db.session.commit()
                    cprint("  ✓ Изменения сохранены!", Colors.OK)
                except Exception as e:
                    db.session.rollback()
                    cprint(f"  ✗ Ошибка при сохранении: {e}", Colors.FAIL)
                    cprint("  Все изменения откачены.", Colors.FAIL)
                    sys.exit(1)
            else:
                cprint("\n  Нечего сохранять — все данные уже корректны.", Colors.OK)

        # Шаг 4: Валидация
        errors = validate_migration()

        # Итог
        cprint("\n" + "=" * 60, Colors.HEADER)
        if dry_run:
            cprint("  DRY-RUN завершён. Для применения: python migrate_fix_bindings.py --apply", Colors.WARN)
        elif errors == 0:
            cprint("  ✓ Миграция успешно завершена!", Colors.OK)
        else:
            cprint("  ⚠ Миграция завершена с предупреждениями", Colors.WARN)
        cprint("=" * 60, Colors.HEADER)


if __name__ == '__main__':
    main()
