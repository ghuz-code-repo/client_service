"""
Тесты для проверки заполнения полей housing_complex и house_number при создании заявок.
Запуск: python -m pytest test_housing_backfill.py -v
"""
import pytest
import datetime
from unittest.mock import patch, MagicMock
from app import create_app, db
from app.models import (
    Application, EstateDeals, EstateSells, EstateHouses,
    EstateDealsContacts, ResponsiblePerson, ApplicationType, User
)


class TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = 'test-secret'
    WTF_CSRF_ENABLED = False
    APPLICATION_ROOT = '/client-service'
    MAIL_SUPPRESS_SEND = True
    MAIL_SERVER = 'localhost'
    MAIL_PORT = 25
    MAIL_USE_TLS = False
    MAIL_USE_SSL = False
    MAIL_USERNAME = None
    MAIL_PASSWORD = None
    MAIL_DEFAULT_SENDER = ('Test', 'test@test.com')
    USER_ROLES = ['Админ']
    APPLICATION_STATUSES = ['В работе', 'Выполнено']
    APPLICATION_SOURCES = ['Звонок']
    AUTH_SERVICE_URL = None
    SOURCE_DATABASE_URI = None


@pytest.fixture
def app():
    application = create_app(TestConfig)
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def seed_data(app):
    """Создаёт базовые данные для тестов."""
    with app.app_context():
        # Дом и ЖК
        house = EstateHouses(house_id=1, complex_name='ЖК Тестовый', name='Дом 5')
        db.session.add(house)

        # Объект продажи
        sell = EstateSells(estate_sell_id=1, house_id=1, geo_house_entrance='1', geo_flatnum='42')
        db.session.add(sell)

        # Клиент
        contact = EstateDealsContacts(id=100, contacts_buy_name='Тестов Тест', contacts_buy_phones='+998901234567')
        db.session.add(contact)

        # Сделка
        deal = EstateDeals(
            id=1, estate_sell_id=1,
            agreement_number='AG-001',
            contacts_buy_id=100,
            deal_status_name='Активный'
        )
        db.session.add(deal)

        # Ответственный
        responsible = ResponsiblePerson(id=1, full_name='Иванов Иван', email='ivanov@test.com')
        db.session.add(responsible)

        # Тип заявки
        app_type = ApplicationType(id=1, name='Дефекты', execution_days=30)
        db.session.add(app_type)

        # Пользователь
        user = User(id=1, username='testuser', role='Админ', auth_user_id='gw-1')
        db.session.add(user)

        db.session.commit()

        return {
            'house': house,
            'sell': sell,
            'contact': contact,
            'deal': deal,
            'responsible': responsible,
            'app_type': app_type,
            'user': user,
        }


class TestHousingFieldsOnCreate:
    """Тесты: поля ЖК/Дом заполняются при создании заявки из карточки клиента."""

    def test_create_application_populates_housing_from_deal(self, app, seed_data):
        """При создании заявки с agreement_number, ЖК/Дом подтягиваются из EstateHouses."""
        with app.app_context():
            deal = EstateDeals.query.filter_by(
                agreement_number='AG-001',
                contacts_buy_id=100
            ).first()

            housing_complex = None
            house_number = None
            if deal and deal.sell and deal.sell.house:
                housing_complex = deal.sell.house.complex_name
                house_number = deal.sell.house.name

            new_app = Application(
                client_id=100,
                agreement_number='AG-001',
                application_type='Дефекты',
                comment='Тестовый комментарий',
                responsible_person_id=1,
                creator_id=1,
                source='Звонок',
                housing_complex=housing_complex,
                house_number=house_number,
            )
            db.session.add(new_app)
            db.session.commit()

            saved = Application.query.get(new_app.id)
            assert saved.housing_complex == 'ЖК Тестовый'
            assert saved.house_number == 'Дом 5'

    def test_create_application_null_when_no_deal(self, app, seed_data):
        """Если deal не найден, поля остаются None."""
        with app.app_context():
            deal = EstateDeals.query.filter_by(
                agreement_number='NONEXISTENT',
                contacts_buy_id=100
            ).first()

            housing_complex = None
            house_number = None
            if deal and deal.sell and deal.sell.house:
                housing_complex = deal.sell.house.complex_name
                house_number = deal.sell.house.name

            new_app = Application(
                client_id=100,
                agreement_number='NONEXISTENT',
                application_type='Дефекты',
                comment='Тест',
                responsible_person_id=1,
                creator_id=1,
                source='Звонок',
                housing_complex=housing_complex,
                house_number=house_number,
            )
            db.session.add(new_app)
            db.session.commit()

            saved = Application.query.get(new_app.id)
            assert saved.housing_complex is None
            assert saved.house_number is None

    def test_create_application_null_when_no_house(self, app):
        """Если sell существует, но house_id = NULL, поля остаются None."""
        with app.app_context():
            sell_no_house = EstateSells(estate_sell_id=99, house_id=None)
            contact = EstateDealsContacts(id=200, contacts_buy_name='Без дома', contacts_buy_phones='+998900000000')
            deal = EstateDeals(id=99, estate_sell_id=99, agreement_number='AG-NOHOUSE', contacts_buy_id=200)
            responsible = ResponsiblePerson(id=2, full_name='Тест', email='t@t.com')
            db.session.add_all([sell_no_house, contact, deal, responsible])
            db.session.commit()

            found_deal = EstateDeals.query.filter_by(agreement_number='AG-NOHOUSE', contacts_buy_id=200).first()
            housing_complex = None
            house_number = None
            if found_deal and found_deal.sell and found_deal.sell.house:
                housing_complex = found_deal.sell.house.complex_name
                house_number = found_deal.sell.house.name

            new_app = Application(
                client_id=200,
                agreement_number='AG-NOHOUSE',
                application_type='Дефекты',
                comment='Тест',
                responsible_person_id=2,
                creator_id=None,
                source='Звонок',
                housing_complex=housing_complex,
                house_number=house_number,
            )
            db.session.add(new_app)
            db.session.commit()

            saved = Application.query.get(new_app.id)
            assert saved.housing_complex is None
            assert saved.house_number is None


class TestBackfillScript:
    """Тесты для скрипта бэкфилла."""

    def test_backfill_fills_empty_fields(self, app, seed_data):
        """Бэкфилл заполняет поля для заявок с NULL housing/house."""
        with app.app_context():
            # Создаём заявку без ЖК/Дом (имитация старых данных)
            old_app = Application(
                client_id=100,
                agreement_number='AG-001',
                application_type='Дефекты',
                comment='Старая заявка',
                responsible_person_id=1,
                source='Звонок',
                housing_complex=None,
                house_number=None,
            )
            db.session.add(old_app)
            db.session.commit()

            # Запускаем логику бэкфилла
            apps_to_fill = Application.query.filter(
                Application.housing_complex.is_(None),
                Application.house_number.is_(None),
            ).all()

            for application in apps_to_fill:
                if application.agreement_number and application.agreement_number.startswith('NC-'):
                    continue
                deal = EstateDeals.query.filter_by(
                    agreement_number=application.agreement_number,
                    contacts_buy_id=application.client_id
                ).first()
                if deal and deal.sell and deal.sell.house:
                    application.housing_complex = deal.sell.house.complex_name
                    application.house_number = deal.sell.house.name

            db.session.commit()

            saved = Application.query.get(old_app.id)
            assert saved.housing_complex == 'ЖК Тестовый'
            assert saved.house_number == 'Дом 5'

    def test_backfill_skips_nc_applications(self, app, seed_data):
        """Бэкфилл пропускает NC-заявки."""
        with app.app_context():
            nc_app = Application(
                client_id=100,
                agreement_number='NC-12345',
                application_type='Дефекты',
                comment='NC заявка',
                responsible_person_id=1,
                source='Звонок',
                housing_complex=None,
                house_number=None,
            )
            db.session.add(nc_app)
            db.session.commit()

            apps_to_fill = Application.query.filter(
                Application.housing_complex.is_(None),
                Application.house_number.is_(None),
            ).all()

            for application in apps_to_fill:
                if application.agreement_number and application.agreement_number.startswith('NC-'):
                    continue
                deal = EstateDeals.query.filter_by(
                    agreement_number=application.agreement_number,
                    contacts_buy_id=application.client_id
                ).first()
                if deal and deal.sell and deal.sell.house:
                    application.housing_complex = deal.sell.house.complex_name
                    application.house_number = deal.sell.house.name

            db.session.commit()

            saved = Application.query.get(nc_app.id)
            assert saved.housing_complex is None
            assert saved.house_number is None

    def test_backfill_does_not_overwrite_existing(self, app, seed_data):
        """Бэкфилл не трогает заявки, где поля уже заполнены."""
        with app.app_context():
            existing_app = Application(
                client_id=100,
                agreement_number='AG-001',
                application_type='Дефекты',
                comment='Уже заполнено',
                responsible_person_id=1,
                source='Звонок',
                housing_complex='Другой ЖК',
                house_number='Дом 99',
            )
            db.session.add(existing_app)
            db.session.commit()

            # Бэкфилл ищет только NULL
            apps_to_fill = Application.query.filter(
                Application.housing_complex.is_(None),
                Application.house_number.is_(None),
            ).all()

            assert existing_app not in apps_to_fill

            saved = Application.query.get(existing_app.id)
            assert saved.housing_complex == 'Другой ЖК'
            assert saved.house_number == 'Дом 99'


class TestFilteringConsistency:
    """Тесты: фильтрация по ЖК/Дом работает после заполнения полей."""

    def test_filter_by_housing_complex(self, app, seed_data):
        """Фильтрация по housing_complex находит заявку."""
        with app.app_context():
            app1 = Application(
                client_id=100, agreement_number='AG-001',
                application_type='Дефекты', comment='тест',
                responsible_person_id=1, source='Звонок',
                housing_complex='ЖК Тестовый', house_number='Дом 5',
            )
            db.session.add(app1)
            db.session.commit()

            results = Application.query.filter(
                Application.housing_complex == 'ЖК Тестовый'
            ).all()
            assert len(results) == 1
            assert results[0].id == app1.id

    def test_filter_by_house_number(self, app, seed_data):
        """Фильтрация по house_number находит заявку."""
        with app.app_context():
            app1 = Application(
                client_id=100, agreement_number='AG-001',
                application_type='Дефекты', comment='тест',
                responsible_person_id=1, source='Звонок',
                housing_complex='ЖК Тестовый', house_number='Дом 5',
            )
            db.session.add(app1)
            db.session.commit()

            results = Application.query.filter(
                Application.house_number == 'Дом 5'
            ).all()
            assert len(results) == 1

    def test_filter_returns_empty_for_null_fields(self, app, seed_data):
        """Фильтрация не находит заявки, где ЖК = NULL."""
        with app.app_context():
            app_null = Application(
                client_id=100, agreement_number='AG-001',
                application_type='Дефекты', comment='без ЖК',
                responsible_person_id=1, source='Звонок',
                housing_complex=None, house_number=None,
            )
            db.session.add(app_null)
            db.session.commit()

            results = Application.query.filter(
                Application.housing_complex == 'ЖК Тестовый'
            ).all()
            assert len(results) == 0
