#!/usr/bin/env python3
"""
Ежедневный бэкап SQLite-базы с ротацией по схеме дед-отец-сын (GFS).

РАСКЛАДКА
  Снимок снимается раз в сутки и раскладывается по четырём уровням. Каждый
  уровень — отдельный файл, поэтому 31 декабря один снимок даёт четыре копии.

    backups/
      2025_0300_clbackup.sqlite          годовые лежат в корне
      2026_0300_clbackup.sqlite
      monthly/August_0300_clbackup.sqlite
      weekly/III_0300_clbackup.sqlite
      daily/Monday_0300_clbackup.sqlite

  Имя = {слот}_{время без секунд}_clbackup.sqlite
    годовой   слот — номер года:            2026
    месячный  слот — название месяца:       August
    недельный слот — римский номер недели:  III
    дневной   слот — название дня недели:   Monday

  ВНИМАНИЕ: в имени нет даты, только слот и время съёмки. Когда снят снимок,
  показывает mtime файла — по нему же ротация решает, какой файл в слоте
  свежее. Не копируйте бэкапы командами, которые сбрасывают mtime.

РОТАЦИЯ
  В каждом слоте живёт один файл — самый свежий. Слоты циклятся сами собой:
  следующий понедельник перезапишет daily/Monday, следующий август —
  monthly/August. Сверх этого держим ограниченное число слотов на уровень:

    daily    7 слотов   Monday..Sunday          (BACKUP_KEEP_DAILY)
    weekly   6 слотов   I..VI                   (BACKUP_KEEP_WEEKLY)
    monthly  12 слотов  January..December       (BACKUP_KEEP_MONTHLY)
    yearly   без предела                        (BACKUP_KEEP_YEARLY=0)

  «Последний в периоде» получается сам: файл в слоте переписывается каждый
  день, пока период не кончился, поэтому в weekly/III в итоге лежит снимок
  последнего дня третьей недели.

  Верхняя граница: X(лет) + 12 + 6 + 7 файлов.

НУМЕРАЦИЯ НЕДЕЛЬ
  Недели ISO (понедельник–воскресенье), номер — по порядку внутри месяца.
  Неделя, содержащая 1-е число, всегда I. В месяцах, где ISO-недели дают
  шесть кусков, появляется VI — поэтому слотов шесть, а не пять.

ЧТО НЕ ТРОГАЕТСЯ
  Ротация уровня разбирает только файлы, подходящие под шаблон этого уровня.
  Ручные бэкапы перед миграциями (db_before_*.sqlite) лежат в корне, под
  шаблон годовых не подходят и не удаляются никогда.

СОГЛАСОВАННОСТЬ СНИМКА
  Снимок снимается через online-backup API SQLite (Connection.backup), а не
  копированием файла: база работает в WAL под gunicorn, и обычный cp может
  дать порванный снимок. По уровням раскладывается уже готовый статичный
  файл — его копировать безопасно. Жёсткие ссылки намеренно не используются:
  открытие такого файла клиентом SQLite может изменить сразу все уровни.

ИСПОЛЬЗОВАНИЕ
  python backup_manager.py --now            # Снять бэкап и почистить старые
  python backup_manager.py --list           # Показать бэкапы по уровням
  python backup_manager.py --prune          # Только чистка
  python backup_manager.py --prune --dry-run

  В контейнере запускается автоматически фоновым потоком из run.py.

ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ
  BACKUP_ENABLED=true        Выключить фоновый поток: false
  BACKUP_DIR=/app/backups    Куда складывать (должен быть примонтирован томом!)
  BACKUP_TIME=03:00          Во сколько снимать, местное время (TZ=Asia/Tashkent)
  BACKUP_KEEP_DAILY=7
  BACKUP_KEEP_WEEKLY=6
  BACKUP_KEEP_MONTHLY=12
  BACKUP_KEEP_YEARLY=0       0 = хранить вечно
"""

import argparse
import datetime
import os
import re
import shutil
import sqlite3
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SUFFIX = '_clbackup.sqlite'
STAGING_NAME = '.staging_clbackup.sqlite'

# Явные списки, а не %A/%B: strftime зависит от локали контейнера.
DAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday',
             'Friday', 'Saturday', 'Sunday']
MONTH_NAMES = ['January', 'February', 'March', 'April', 'May', 'June',
               'July', 'August', 'September', 'October', 'November', 'December']

TIERS = ('yearly', 'monthly', 'weekly', 'daily')

SLOT_PATTERNS = {
    'yearly': re.compile(r'^(\d{4})_(\d{4})' + re.escape(SUFFIX) + r'$'),
    'monthly': re.compile(r'^(' + '|'.join(MONTH_NAMES) + r')_(\d{4})'
                          + re.escape(SUFFIX) + r'$'),
    'weekly': re.compile(r'^([IVX]+)_(\d{4})' + re.escape(SUFFIX) + r'$'),
    'daily': re.compile(r'^(' + '|'.join(DAY_NAMES) + r')_(\d{4})'
                        + re.escape(SUFFIX) + r'$'),
}


# ============================================================================
# КОНФИГУРАЦИЯ
# ============================================================================

def _env_int(name, default):
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        print(f"[backup] Некорректное значение {name}, взято {default}")
        return default


def get_config():
    return {
        'enabled': os.getenv('BACKUP_ENABLED', 'true').lower() == 'true',
        'dir': os.getenv('BACKUP_DIR', os.path.join(BASE_DIR, 'backups')),
        'time': os.getenv('BACKUP_TIME', '03:00'),
        'keep': {
            'daily': _env_int('BACKUP_KEEP_DAILY', 7),
            'weekly': _env_int('BACKUP_KEEP_WEEKLY', 6),
            'monthly': _env_int('BACKUP_KEEP_MONTHLY', 12),
            'yearly': _env_int('BACKUP_KEEP_YEARLY', 0),
        },
    }


def resolve_db_path(app=None):
    """Путь к файлу SQLite. Берётся из конфига Flask, либо из DATABASE_URL."""
    if app is not None:
        db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
    else:
        db_uri = os.getenv('DATABASE_URL', '')
        if not db_uri:
            db_uri = 'sqlite:///' + os.path.join(BASE_DIR, 'instance', 'app.db')

    if not db_uri.startswith('sqlite:'):
        return None

    path = re.sub(r'^sqlite:/{2,}', '', db_uri)
    if not os.path.isabs(path) and app is not None:
        path = os.path.join(app.instance_path, path)
    return path


# ============================================================================
# ИМЕНОВАНИЕ
# ============================================================================

def to_roman(n):
    """Римская запись для 1..3999. На практике нужны только I..VI."""
    table = ((1000, 'M'), (900, 'CM'), (500, 'D'), (400, 'CD'),
             (100, 'C'), (90, 'XC'), (50, 'L'), (40, 'XL'),
             (10, 'X'), (9, 'IX'), (5, 'V'), (4, 'IV'), (1, 'I'))
    out = []
    for value, symbol in table:
        count, n = divmod(n, value)
        out.append(symbol * count)
    return ''.join(out)


def week_ordinal_in_month(d):
    """Порядковый номер ISO-недели внутри месяца, начиная с 1.

    Недели считаются от понедельника. Неделя, содержащая 1-е число месяца,
    всегда первая — даже если сама начинается в прошлом месяце."""
    def monday_of(x):
        return x - datetime.timedelta(days=x.weekday())

    first_of_month = d.replace(day=1)
    delta_days = (monday_of(d.date() if isinstance(d, datetime.datetime) else d)
                  - monday_of(first_of_month.date()
                              if isinstance(first_of_month, datetime.datetime)
                              else first_of_month)).days
    return delta_days // 7 + 1


def slot_name(tier, dt):
    if tier == 'yearly':
        return str(dt.year)
    if tier == 'monthly':
        return MONTH_NAMES[dt.month - 1]
    if tier == 'weekly':
        return to_roman(week_ordinal_in_month(dt))
    return DAY_NAMES[dt.weekday()]


def file_name(tier, dt):
    return f"{slot_name(tier, dt)}_{dt.strftime('%H%M')}{SUFFIX}"


def tier_dir(backup_dir, tier):
    """Годовые лежат в корне, остальные уровни — в одноимённых подпапках."""
    return backup_dir if tier == 'yearly' else os.path.join(backup_dir, tier)


# ============================================================================
# СНЯТИЕ БЭКАПА
# ============================================================================

def _snapshot(db_path, staging_path):
    """Согласованный снимок базы в staging_path."""
    src = dst = None
    try:
        src = sqlite3.connect(db_path)
        dst = sqlite3.connect(staging_path)
        with dst:
            src.backup(dst)
    finally:
        for con in (dst, src):
            if con is not None:
                con.close()


def _place(staging_path, target_path):
    """Кладёт готовый снимок в слот. Через .tmp, чтобы обрыв копирования
    не оставил битый файл под рабочим именем."""
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    tmp = target_path + '.tmp'
    shutil.copyfile(staging_path, tmp)
    os.replace(tmp, target_path)


def create_backup(db_path, backup_dir, now=None):
    """Снимает снимок и раскладывает по всем четырём уровням.

    Возвращает {tier: path} или пустой dict при ошибке."""
    if not db_path or not os.path.exists(db_path):
        print(f"[backup] Файл БД не найден: {db_path}")
        return {}

    os.makedirs(backup_dir, exist_ok=True)
    now = now or datetime.datetime.now()
    staging_path = os.path.join(backup_dir, STAGING_NAME)

    try:
        _snapshot(db_path, staging_path)
    except (sqlite3.Error, OSError) as e:
        print(f"[backup] Ошибка снятия снимка: {e}")
        _cleanup(staging_path)
        return {}

    size_mb = os.path.getsize(staging_path) / (1024 * 1024)
    written = {}
    try:
        for tier in TIERS:
            target = os.path.join(tier_dir(backup_dir, tier), file_name(tier, now))
            _place(staging_path, target)
            written[tier] = target
            rel = os.path.relpath(target, backup_dir)
            print(f"[backup] + {rel}")
    except OSError as e:
        print(f"[backup] Ошибка раскладки по уровням: {e}")
    finally:
        _cleanup(staging_path)

    if written:
        print(f"[backup] Снимок {size_mb:.1f} МБ разложен по {len(written)} уровням.")
    return written


def _cleanup(path):
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


# ============================================================================
# РОТАЦИЯ
# ============================================================================

def list_tier(backup_dir, tier):
    """Файлы уровня: [(path, slot, mtime), ...] от нового к старому."""
    directory = tier_dir(backup_dir, tier)
    if not os.path.isdir(directory):
        return []

    pattern = SLOT_PATTERNS[tier]
    found = []
    for name in os.listdir(directory):
        m = pattern.match(name)
        if not m:
            continue
        path = os.path.join(directory, name)
        if not os.path.isfile(path):
            continue
        found.append((path, m.group(1), os.path.getmtime(path)))
    return sorted(found, key=lambda x: x[2], reverse=True)


def select_tier_keepers(entries, limit):
    """В каждом слоте оставляем самый свежий файл, затем держим не больше
    limit слотов по свежести (0 = без ограничения). entries — от нового
    к старому. Возвращает set путей."""
    keep = set()
    seen_slots = []
    for path, slot, _mtime in entries:
        if slot in seen_slots:
            continue  # в слоте уже отобран более свежий файл
        if limit and len(seen_slots) >= limit:
            break  # лимит слотов исчерпан, дальше только старее
        seen_slots.append(slot)
        keep.add(path)
    return keep


def prune(backup_dir, cfg, dry_run=False):
    """Чистит все уровни. Возвращает число удалённых файлов."""
    total_removed = 0
    total_kept = 0

    for tier in TIERS:
        entries = list_tier(backup_dir, tier)
        if not entries:
            continue
        keep = select_tier_keepers(entries, cfg['keep'][tier])
        total_kept += len(keep)

        for path, _slot, _mtime in entries:
            if path in keep:
                continue
            rel = os.path.relpath(path, backup_dir)
            if dry_run:
                print(f"[backup] - (dry-run) {rel}")
                total_removed += 1
                continue
            try:
                os.remove(path)
                print(f"[backup] - {rel}")
                total_removed += 1
            except OSError as e:
                print(f"[backup] Не удалось удалить {rel}: {e}")

    print(f"[backup] Осталось {total_kept} бэкапов, удалено {total_removed}.")
    return total_removed


def print_listing(backup_dir, cfg):
    if not os.path.isdir(backup_dir):
        print(f"Папка бэкапов не найдена: {backup_dir}")
        return

    known = set()
    for tier in TIERS:
        entries = list_tier(backup_dir, tier)
        known.update(p for p, _s, _m in entries)
        limit = cfg['keep'][tier]
        cap = limit if limit else 'без предела'
        print(f"=== {tier.upper()} ({len(entries)}, лимит слотов: {cap}) ===")
        if not entries:
            print("  пусто")
            print()
            continue

        keep = select_tier_keepers(entries, limit)
        for path, slot, mtime in entries:
            size_mb = os.path.getsize(path) / (1024 * 1024)
            stamp = datetime.datetime.fromtimestamp(mtime).strftime('%d.%m.%Y %H:%M')
            mark = f'+ слот {slot}' if path in keep else '- под удаление'
            print(f"  {os.path.basename(path):<34} {size_mb:6.1f} МБ  {stamp}  {mark}")
        print()

    # Всё, что не подошло ни под один шаблон: ручные бэкапы и посторонние файлы
    others = []
    for name in sorted(os.listdir(backup_dir)):
        path = os.path.join(backup_dir, name)
        if os.path.isfile(path) and path not in known and name.endswith('.sqlite'):
            others.append(path)
    if others:
        print(f"=== ПРОЧИЕ ({len(others)}), ротацией не трогаются ===")
        for path in others:
            size_mb = os.path.getsize(path) / (1024 * 1024)
            print(f"  {os.path.basename(path):<34} {size_mb:6.1f} МБ")


# ============================================================================
# ФОНОВЫЙ ПОТОК
# ============================================================================

def _seconds_until(target_time, now=None):
    """Секунд до ближайшего наступления HH:MM."""
    now = now or datetime.datetime.now()
    try:
        hour, minute = (int(x) for x in target_time.split(':'))
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    except (ValueError, TypeError):
        print(f"[backup] Некорректный BACKUP_TIME='{target_time}', взято 03:00")
        target = now.replace(hour=3, minute=0, second=0, microsecond=0)

    if target <= now:
        target += datetime.timedelta(days=1)
    return (target - now).total_seconds()


def run_once(app=None, cfg=None):
    """Снять бэкап и почистить старые. Возвращает {tier: path}."""
    cfg = cfg or get_config()
    db_path = resolve_db_path(app)
    written = create_backup(db_path, cfg['dir'])
    if written:
        prune(cfg['dir'], cfg)
    return written


def backup_scheduler_task(app):
    """Тело фонового потока: раз в сутки снимает бэкап и чистит старые."""
    cfg = get_config()
    while True:
        delay = _seconds_until(cfg['time'])
        next_run = datetime.datetime.now() + datetime.timedelta(seconds=delay)
        print(f"[backup] Следующий бэкап: {next_run.strftime('%d.%m.%Y %H:%M:%S')}")
        time.sleep(delay)
        try:
            run_once(app, cfg)
        except Exception as e:
            # Поток не должен умирать: пропущенный бэкап лучше, чем отсутствие
            # бэкапов до следующего рестарта контейнера.
            print(f"[backup] Сбой при снятии бэкапа: {e}")


def start_backup_scheduler(app):
    """Запускает фоновый поток бэкапов. Вызывается из run.py."""
    import threading

    cfg = get_config()
    if not cfg['enabled']:
        print("[backup] BACKUP_ENABLED=false, фоновые бэкапы выключены.")
        return None

    db_path = resolve_db_path(app)
    if not db_path:
        print("[backup] БД не SQLite, фоновые бэкапы выключены.")
        return None

    keep = cfg['keep']
    print(f"[backup] Бэкапы: {cfg['dir']}, ежедневно в {cfg['time']}, "
          f"слотов {keep['daily']}д/{keep['weekly']}н/"
          f"{keep['monthly']}м/{keep['yearly'] or 'все'}г")

    thread = threading.Thread(target=backup_scheduler_task, args=(app,), daemon=True)
    thread.start()
    return thread


# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description='Бэкап SQLite-базы с ротацией GFS.')
    parser.add_argument('--now', action='store_true', help='Снять бэкап и почистить старые')
    parser.add_argument('--prune', action='store_true', help='Только чистка')
    parser.add_argument('--list', action='store_true', help='Показать бэкапы по уровням')
    parser.add_argument('--dry-run', action='store_true', help='Не удалять, только показать')
    args = parser.parse_args()

    sys.path.insert(0, BASE_DIR)
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, '.env'))

    cfg = get_config()

    if args.list:
        print_listing(cfg['dir'], cfg)
        return 0

    if args.prune:
        prune(cfg['dir'], cfg, dry_run=args.dry_run)
        return 0

    if args.now:
        db_path = resolve_db_path()
        print(f"[backup] БД: {db_path}")
        if not create_backup(db_path, cfg['dir']):
            return 1
        prune(cfg['dir'], cfg, dry_run=args.dry_run)
        return 0

    parser.print_help()
    return 0


if __name__ == '__main__':
    sys.exit(main())
