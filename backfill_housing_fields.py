"""
Скрипт бэкфилла: заполняет housing_complex и house_number
для существующих заявок, где эти поля пустые.

Логика: для каждой заявки без NC-договора подтягиваем ЖК/Дом
через цепочку EstateDeals -> EstateSells -> EstateHouses.

Запуск: python backfill_housing_fields.py [--dry-run]
"""
import sys
from app import create_app, db
from app.models import Application, EstateDeals


def backfill(dry_run=False):
    app = create_app()

    with app.app_context():
        apps = Application.query.filter(
            Application.housing_complex.is_(None),
            Application.house_number.is_(None),
        ).all()

        print(f"Найдено заявок с пустыми ЖК/Дом: {len(apps)}")

        updated = 0
        skipped_nc = 0
        skipped_no_deal = 0

        for application in apps:
            # NC-заявки пропускаем — у них нет реальных договоров
            if application.agreement_number and application.agreement_number.startswith('NC-'):
                skipped_nc += 1
                continue

            deal = EstateDeals.query.filter_by(
                agreement_number=application.agreement_number,
                contacts_buy_id=application.client_id
            ).first()

            if not deal or not deal.sell or not deal.sell.house:
                skipped_no_deal += 1
                continue

            house = deal.sell.house
            complex_name = house.complex_name
            house_name = house.name

            if not complex_name and not house_name:
                skipped_no_deal += 1
                continue

            application.housing_complex = complex_name
            application.house_number = house_name
            updated += 1

            if updated % 100 == 0:
                print(f"  Обработано: {updated}...")

        print(f"\nИтого:")
        print(f"  Обновлено: {updated}")
        print(f"  Пропущено NC-заявок: {skipped_nc}")
        print(f"  Пропущено (нет deal/house): {skipped_no_deal}")

        if dry_run:
            print("\n⚠️  DRY RUN — изменения НЕ сохранены в БД.")
            db.session.rollback()
        else:
            db.session.commit()
            print("\n✅ Изменения сохранены в БД.")


if __name__ == '__main__':
    dry_run = '--dry-run' in sys.argv
    if dry_run:
        print("Режим DRY RUN (без записи в БД)\n")
    backfill(dry_run=dry_run)
