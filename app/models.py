# app/models.py
import datetime
import json
from .extensions import db
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), index=True, unique=True, nullable=False)
    password_hash = db.Column(db.String(256))
    role = db.Column(db.String(64), nullable=False)
    # НОВАЯ СВЯЗЬ: профиль ответственного, привязанный к этому пользователю
    responsible_person_profile = db.relationship('ResponsiblePerson', backref='user_account', uselist=False, lazy='joined')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def has_role(self, *roles):
        return self.role in roles

responsible_assignments = db.Table('responsible_assignments',
                                   db.Column('responsible_person_id', db.Integer,
                                             db.ForeignKey('responsible_persons.id', ondelete='CASCADE'),
                                             primary_key=True),
                                   db.Column('house_id', db.Integer,
                                             db.ForeignKey('estate_houses.house_id', ondelete='CASCADE'),
                                             primary_key=True)
                                   )

class ResponsiblePerson(db.Model):
    __tablename__ = 'responsible_persons'
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(255), nullable=False, unique=True)
    # НОВОЕ ПОЛЕ: ID пользователя, к которому привязан этот ответственный
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, unique=True)
    application_types_json = db.Column(db.Text, default='[]')
    assigned_complexes = db.relationship('EstateHouses', secondary=responsible_assignments,
                                         lazy='subquery',
                                         backref=db.backref('responsible_persons', lazy=True))
    applications = db.relationship('Application', backref='responsible_person', lazy=True)

    @property
    def application_types(self):
        try:
            return json.loads(self.application_types_json)
        except (json.JSONDecodeError, TypeError):
            return []

    @application_types.setter
    def application_types(self, value):
        if isinstance(value, list):
            self.application_types_json = json.dumps(value)
        else:
            self.application_types_json = '[]'

class Application(db.Model):
    __tablename__ = 'applications'
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('estate_deals_contacts.id'), nullable=False)
    # НОВОЕ ПОЛЕ: ID пользователя, создавшего заявку
    creator_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    agreement_number = db.Column(db.String(255), nullable=False)
    application_type = db.Column(db.String(50), nullable=False)
    comment = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(50), nullable=False, default='В работе')
    responsible_person_id = db.Column(db.Integer, db.ForeignKey('responsible_persons.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    # НОВЫЕ ПОЛЯ: даты для отслеживания сроков
    due_date = db.Column(db.DateTime, nullable=True)  # Срок выполнения заявки
    completed_at = db.Column(db.DateTime, nullable=True)  # Дата фактического завершения
    # НОВОЕ ПОЛЕ: источник заявки
    source = db.Column(db.String(100), nullable=True, default='Звонок')  # Источник заявки
    # НОВОЕ ПОЛЕ: временной штамп последнего изменения статуса
    last_status_change = db.Column(db.DateTime, nullable=True, default=datetime.datetime.utcnow)
    defects = db.relationship('Defect', backref='application', lazy=True, cascade="all, delete-orphan")
    logs = db.relationship('ApplicationLog', backref='application', lazy=True, cascade="all, delete-orphan")
    # НОВАЯ СВЯЗЬ: объект создателя заявки
    creator = db.relationship('User', backref=db.backref('created_applications', lazy='dynamic'), foreign_keys=[creator_id])
    
    @property
    def is_overdue(self):
        """Проверка, просрочена ли заявка"""
        if self.due_date and not self.completed_at:
            return datetime.datetime.utcnow() > self.due_date
        return False

class EstateSells(db.Model):
    __tablename__ = 'estate_sells'
    estate_sell_id = db.Column(db.Integer, primary_key=True)
    estate_sell_category = db.Column(db.String(255))
    house_id = db.Column(db.Integer, db.ForeignKey('estate_houses.house_id'))
    estate_rooms = db.Column(db.Integer)
    geo_house_entrance = db.Column(db.String(50))
    estate_floor = db.Column(db.Integer)
    estate_riser = db.Column(db.String(50))
    geo_flatnum = db.Column(db.String(50))
    deals = db.relationship('EstateDeals', backref='sell', lazy='joined')

class EstateDeals(db.Model):
    __tablename__ = 'estate_deals'
    id = db.Column(db.Integer, primary_key=True)
    estate_sell_id = db.Column(db.Integer, db.ForeignKey('estate_sells.estate_sell_id'))
    deal_status_name = db.Column(db.String(255))
    agreement_number = db.Column(db.String(255))
    agreement_date = db.Column(db.Date)
    deal_sum = db.Column(db.Float)
    deal_area = db.Column(db.Float)
    contacts_buy_id = db.Column(db.Integer, db.ForeignKey('estate_deals_contacts.id'))
    finances_income_reserved = db.Column(db.Float)

class EstateDealsContacts(db.Model):
    __tablename__ = 'estate_deals_contacts'
    id = db.Column(db.Integer, primary_key=True)
    contacts_buy_name = db.Column(db.String(255))
    contacts_buy_phones = db.Column(db.String(255))
    deals = db.relationship('EstateDeals', backref='contact', lazy='dynamic')
    applications = db.relationship('Application', backref='client', lazy='dynamic')

class EstateHouses(db.Model):
    __tablename__ = 'estate_houses'
    house_id = db.Column(db.Integer, primary_key=True)
    complex_name = db.Column(db.String(255))
    name = db.Column(db.String(255))
    sells = db.relationship('EstateSells', backref='house', lazy='dynamic')
    warranty_house_end_date = db.Column(db.Date, nullable=True)
    warranty_apartments_end_date = db.Column(db.Date, nullable=True)

class Defect(db.Model):
    __tablename__ = 'defects'
    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(db.Integer, db.ForeignKey('applications.id'), nullable=False)
    defect_type = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=False)

class ApplicationLog(db.Model):
    __tablename__ = 'application_logs'
    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(db.Integer, db.ForeignKey('applications.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    action = db.Column(db.String(255), nullable=False)
    comment = db.Column(db.Text)
    # НОВОЕ ПОЛЕ: автор изменения
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    author = db.relationship('User', backref=db.backref('application_logs', lazy='dynamic'))

class Client:
    def __init__(self, contact, deals):
        self.id = contact.id
        self.fio = contact.contacts_buy_name
        self.phone = contact.contacts_buy_phones
        self.agreement_numbers = sorted(list(set(d.agreement_number for d in deals if d.agreement_number and d.agreement_number.strip())))
        self.deals_map = {}
        self.deals = []
        for deal in deals:
            if not deal.agreement_number or not deal.agreement_number.strip():
                continue
            sell = deal.sell
            house = sell.house if sell else None
            deal_info = {
                'complex_name': house.complex_name if house else 'N/A',
                'house_name': house.name if house else 'N/A',
                'floor': sell.estate_floor if sell else 'N/A',
                'riser': sell.estate_riser if sell else 'N/A',
                'flat_num': sell.geo_flatnum if sell else 'N/A',
                'rooms': sell.estate_rooms if sell else 'N/A',
                'deal_sum': deal.deal_sum,
                'to_pay': deal.finances_income_reserved,
                'agreement_number': deal.agreement_number
            }
            self.deals.append(type('obj', (), deal_info)())
            if house:
                self.deals_map[deal.agreement_number] = house.complex_name

class EmailLog(db.Model):
    __tablename__ = 'email_logs'
    id = db.Column(db.Integer, primary_key=True)
    application_id = db.Column(db.Integer, db.ForeignKey('applications.id'), nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    recipient = db.Column(db.String(255))
    subject = db.Column(db.String(255))
    status = db.Column(db.String(50))
    server_response = db.Column(db.Text)
    application = db.relationship('Application', backref=db.backref('email_logs', lazy='dynamic'))

class DefectType(db.Model):
    __tablename__ = 'defect_types'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)

    def __repr__(self):
        return f'<DefectType {self.name}>'

# --- ИСПРАВЛЕНИЕ: Объединенное и единственное определение класса ---
class ApplicationType(db.Model):
    __tablename__ = 'application_types'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    template_filename = db.Column(db.String(255), nullable=True)
    has_defect_list = db.Column(db.Boolean, default=False, nullable=False)
    # НОВОЕ ПОЛЕ: срок выполнения в днях
    execution_days = db.Column(db.Integer, default=3, nullable=False)

    def __repr__(self):
        return f'<ApplicationType {self.name}>'
