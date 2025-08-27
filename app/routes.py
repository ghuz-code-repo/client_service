# app/routes.py
import time
import math
import json
import io
import os
from datetime import datetime
from threading import Thread
from openpyxl import load_workbook, Workbook
from openpyxl.styles import Font, Alignment
from flask import (render_template, request, Blueprint, abort, flash, redirect,
                   url_for, jsonify, current_app, send_file)
from flask_login import login_required, current_user
from sqlalchemy.orm import selectinload, joinedload
from sqlalchemy import text
from flask_mail import Message
from werkzeug.utils import secure_filename
from .extensions import db
from .models import (User, EstateDealsContacts, EstateDeals, EstateSells, Client,
                     Application, Defect, ApplicationLog, ResponsiblePerson, EstateHouses, responsible_assignments,
                     DefectType, EmailLog, ApplicationType)
from .email_utils import generate_and_send_email
from .decorators import permission_required, admin_required
from sqlalchemy import or_

main = Blueprint('main', __name__)

def send_email_async(app, application_id):
    """
    Функция-обертка для запуска отправки email в отдельном потоке
    с собственным контекстом приложения.
    """
    with app.app_context():
        generate_and_send_email(application_id)


class SQLPagination:
    """Простой класс для имитации объекта пагинации Flask-SQLAlchemy."""

    def __init__(self, items, page, per_page, total):
        self.items = items
        self.page = page
        self.per_page = per_page
        self.total = total

    @property
    def pages(self):
        return math.ceil(self.total / self.per_page) if self.per_page > 0 else 0

    @property
    def has_prev(self):
        return self.page > 1

    @property
    def has_next(self):
        return self.page < self.pages

    @property
    def prev_num(self):
        return self.page - 1

    @property
    def next_num(self):
        return self.page + 1

    def iter_pages(self, left_edge=2, left_current=2, right_current=5, right_edge=2):
        last = 0
        for num in range(1, self.pages + 1):
            if num <= left_edge or \
                    (self.page - left_current - 1 < num < self.page + right_current) or \
                    num > self.pages - right_edge:
                if last + 1 != num:
                    yield None
                yield num
                last = num


@main.route('/client-service/')
@login_required
def index():
    page = request.args.get('page', 1, type=int)
    search_query = request.args.get('search', '')
    per_page = 100
    offset = (page - 1) * per_page
    params = {}
    from_clause = "FROM estate_deals_contacts c JOIN estate_deals d ON c.id=d.contacts_buy_id"
    where_clause = "WHERE c.contacts_buy_name IS NOT NULL AND c.contacts_buy_name!='' AND c.contacts_buy_phones IS NOT NULL AND c.contacts_buy_phones!='' AND d.agreement_number IS NOT NULL AND TRIM(d.agreement_number)!=''"
    if search_query:
        where_clause += " AND (c.contacts_buy_name LIKE :search OR d.agreement_number LIKE :search)"
        params['search'] = f'%{search_query}%'

    count_sql = f"SELECT COUNT(DISTINCT c.id) {from_clause} {where_clause}"
    total_clients = db.session.execute(text(count_sql), params).scalar() or 0
    data_sql = f"""
        SELECT c.id AS client_id,c.contacts_buy_name,c.contacts_buy_phones,d.agreement_number,d.deal_sum,d.finances_income_reserved,s.estate_floor,s.estate_riser,s.geo_flatnum,s.estate_rooms,h.complex_name,h.name as house_name
        FROM estate_deals_contacts c
        JOIN estate_deals d ON c.id=d.contacts_buy_id
        LEFT JOIN estate_sells s ON d.estate_sell_id=s.estate_sell_id
        LEFT JOIN estate_houses h ON s.house_id=h.house_id
        JOIN(SELECT DISTINCT c.id {from_clause} {where_clause} ORDER BY c.contacts_buy_name LIMIT :limit OFFSET :offset) AS page_ids ON c.id=page_ids.id
        WHERE d.agreement_number IS NOT NULL AND TRIM(d.agreement_number)!=''
    """
    params['limit'], params['offset'] = per_page, offset
    all_data = db.session.execute(text(data_sql), params).mappings().all()
    clients_data, ordered_client_ids = {}, []
    for row in all_data:
        client_id = row['client_id']
        if client_id not in clients_data:
            ordered_client_ids.append(client_id)
            contact_info = {'id': row.get('client_id'), 'contacts_buy_name': row.get('contacts_buy_name'),
                            'contacts_buy_phones': row.get('contacts_buy_phones')}
            clients_data[client_id] = {'contact': contact_info, 'deals': []}
        clients_data[client_id]['deals'].append(row)

    client_list = []
    for cid in ordered_client_ids:
        data = clients_data.get(cid)
        if data:
            structured_deals = []
            for deal_row in data['deals']:
                sell_obj = type('obj', (object,), {'estate_floor': deal_row.get('estate_floor'),
                                                   'estate_riser': deal_row.get('estate_riser'),
                                                   'geo_flatnum': deal_row.get('geo_flatnum'),
                                                   'estate_rooms': deal_row.get('estate_rooms'),
                                                   'house': type('obj', (object,),
                                                                 {'complex_name': deal_row.get('complex_name'),
                                                                  'name': deal_row.get('house_name')})})
                structured_deals.append(type('obj', (object,), {'agreement_number': deal_row.get('agreement_number'),
                                                                'deal_sum': deal_row.get('deal_sum'),
                                                                'finances_income_reserved': deal_row.get(
                                                                    'finances_income_reserved'), 'sell': sell_obj}))
            contact_obj = type('obj', (object,), data['contact'])
            client_list.append(Client(contact_obj, structured_deals))

    pagination = SQLPagination(client_list, page, per_page, total_clients)
    
    # Получаем данные для модального окна создания заявки без клиента
    application_types = ApplicationType.query.order_by(ApplicationType.name).all()
    defect_types_query = DefectType.query.order_by(DefectType.name).all()
    defect_types = [{'id': dt.id, 'name': dt.name} for dt in defect_types_query]
    responsible_persons = ResponsiblePerson.query.order_by(ResponsiblePerson.full_name).all()
    
    return render_template('index.html', 
                         clients=client_list, 
                         pagination=pagination, 
                         search_query=search_query,
                         application_types=application_types,
                         defect_types=defect_types,
                         responsible_persons=responsible_persons)


@main.route('/client-service/client/<int:client_id>')
@login_required
def client_card(client_id):
    contact = EstateDealsContacts.query.get_or_404(client_id)
    deals_for_client = contact.deals.options(selectinload(EstateDeals.sell).selectinload(EstateSells.house)).all()
    applications = Application.query.filter_by(client_id=client_id).order_by(Application.created_at.desc()).all()
    client = Client(contact, deals_for_client)

    defect_types_query = DefectType.query.order_by(DefectType.name).all()
    defect_types = [{'id': dt.id, 'name': dt.name} for dt in defect_types_query]

    application_types = ApplicationType.query.order_by(ApplicationType.name).all()
    application_statuses = current_app.config['APPLICATION_STATUSES']

    warranty_info = {}
    for deal in deals_for_client:
        if deal.sell and deal.sell.house:
            house_key = deal.sell.house.name
            if house_key and house_key not in warranty_info:
                warranty_info[house_key] = {
                    'house_date': deal.sell.house.warranty_house_end_date,
                    'apartments_date': deal.sell.house.warranty_apartments_end_date
                }

    current_date = datetime.now().date()

    return render_template('client_card.html',
                           client=client,
                           applications=applications,
                           defect_types=defect_types,
                           application_types=application_types,
                           application_statuses=application_statuses,
                           warranty_info=warranty_info,
                           current_date=current_date)

@main.route('/client-service/export-applications')
@login_required
def export_applications():
    """Экспорт заявок в Excel с учетом всех фильтров"""
    # Базовый запрос с предзагрузкой связанных данных
    query = Application.query.options(
        joinedload(Application.client),
        joinedload(Application.responsible_person),
        joinedload(Application.creator),
        joinedload(Application.defects)
    )

    # Фильтрация заявок в зависимости от роли
    if not current_user.has_role('Админ'):
        created_by_me = Application.creator_id == current_user.id
        responsible_for = Application.responsible_person_id == (
            current_user.responsible_person_profile.id if current_user.responsible_person_profile else -1
        )
        query = query.filter(or_(created_by_me, responsible_for))
    
    # Применяем те же фильтры, что и в основном маршруте
    status = request.args.get('status', '')
    if status:
        query = query.filter(Application.status == status)
    
    app_type = request.args.get('type', '')
    if app_type:
        query = query.filter(Application.application_type == app_type)
    
    date_from = request.args.get('date_from', '')
    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d')
            query = query.filter(Application.created_at >= date_from_obj)
        except ValueError:
            pass
    
    date_to = request.args.get('date_to', '')
    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            query = query.filter(Application.created_at <= date_to_obj)
        except ValueError:
            pass
    
    search = request.args.get('search', '')
    if search:
        query = query.join(Application.client).filter(
            or_(
                EstateDealsContacts.contacts_buy_name.contains(search),
                Application.agreement_number.contains(search)
            )
        )
    
    overdue = request.args.get('overdue', '')
    if overdue == 'yes':
        query = query.filter(
            Application.due_date.isnot(None),
            Application.due_date < datetime.utcnow(),
            Application.completed_at.is_(None)
        )
    elif overdue == 'no':
        query = query.filter(
            or_(
                Application.due_date.is_(None),
                Application.due_date >= datetime.utcnow(),
                Application.completed_at.isnot(None)
            )
        )
    
    # Сортировка
    sort = request.args.get('sort', 'created_desc')
    if sort == 'created_desc':
        query = query.order_by(Application.created_at.desc())
    elif sort == 'created_asc':
        query = query.order_by(Application.created_at.asc())
    elif sort == 'due_desc':
        query = query.order_by(Application.due_date.desc().nullslast())
    elif sort == 'due_asc':
        query = query.order_by(Application.due_date.asc().nullsfirst())
    elif sort == 'id_desc':
        query = query.order_by(Application.id.desc())
    elif sort == 'id_asc':
        query = query.order_by(Application.id.asc())
    else:
        query = query.order_by(Application.created_at.desc())

    # Получаем все заявки без пагинации для экспорта
    apps = query.all()
    
    if not apps:
        flash('Не найдено заявок для экспорта с указанными фильтрами.', 'info')
        return redirect(url_for('main.applications'))

    # Создаем Excel файл
    wb = Workbook()
    ws = wb.active
    ws.title = "Заявки"
    
    # Создаем заголовок с информацией о фильтрах
    filter_info = []
    if status:
        filter_info.append(f"Статус: {status}")
    if app_type:
        filter_info.append(f"Тип: {app_type}")
    if date_from:
        filter_info.append(f"С даты: {date_from}")
    if date_to:
        filter_info.append(f"По дату: {date_to}")
    if search:
        filter_info.append(f"Поиск: {search}")
    if overdue == 'yes':
        filter_info.append("Только просроченные")
    elif overdue == 'no':
        filter_info.append("Не просроченные")
    
    if filter_info:
        ws.append([f"Отчет по заявкам. Фильтры: {', '.join(filter_info)}"])
        ws.merge_cells('A1:N1')
        ws['A1'].font = Font(bold=True, size=12)
        ws['A1'].alignment = Alignment(horizontal="left", vertical="center")
        ws.append([])  # Пустая строка
    
    # Заголовки колонок
    headers = ["ID Заявки", "Дата создания", "Статус", "Тип заявки", "№ Договора", 
               "ФИО Клиента", "Телефон клиента", "ЖК", "Дом", "Подъезд", "Номер квартиры",
               "Ответственный", "Email ответственного", "Создатель заявки", "Источник", 
               "Срок выполнения", "Дата завершения", "Просрочено", "Дата последнего изменения", 
               "Последний комментарий", "Комментарий к заявке", "Дефекты (Тип: Комментарий)"]
    ws.append(headers)
    
    # Стилизация заголовков
    for cell in ws[ws.max_row]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center")

    # Заполнение данными
    for app in apps:
        # Получаем данные о недвижимости
        complex_name = "N/A"
        house_name = "N/A"
        entrance = "N/A"
        flat_num = "N/A"
        
        if app.client and app.agreement_number:
            deal = EstateDeals.query.filter_by(
                agreement_number=app.agreement_number,
                contacts_buy_id=app.client.id
            ).first()
            
            if deal and deal.sell:
                sell = deal.sell
                entrance = sell.geo_house_entrance if sell.geo_house_entrance else "N/A"
                flat_num = sell.geo_flatnum if sell.geo_flatnum else "N/A"
                
                if sell.house:
                    complex_name = sell.house.complex_name if sell.house.complex_name else "N/A"
                    house_name = sell.house.name if sell.house.name else "N/A"
        
        defects_str = "; ".join([f"{d.defect_type}: {d.description}" for d in app.defects])
        is_overdue = "Да" if app.is_overdue else "Нет"
        
        # Получаем последний комментарий из логов
        last_log = ApplicationLog.query.filter_by(application_id=app.id).order_by(ApplicationLog.timestamp.desc()).first()
        last_comment = last_log.comment if last_log else "N/A"
        
        row_data = [
            app.id, 
            app.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            app.status, 
            app.application_type,
            app.agreement_number, 
            app.client.contacts_buy_name if app.client else "N/A",
            app.client.contacts_buy_phones if app.client else "N/A",
            complex_name, 
            house_name, 
            entrance, 
            flat_num,
            app.responsible_person.full_name if app.responsible_person else "Не назначен",
            app.responsible_person.email if app.responsible_person else "N/A",
            app.creator.username if app.creator else "Система",
            app.source if app.source else "Не указан",
            app.due_date.strftime('%Y-%m-%d') if app.due_date else "N/A",
            app.completed_at.strftime('%Y-%m-%d %H:%M:%S') if app.completed_at else "N/A",
            is_overdue,
            app.last_status_change.strftime('%Y-%m-%d %H:%M:%S') if app.last_status_change else "N/A",
            last_comment,
            app.comment, 
            defects_str
        ]
        ws.append(row_data)

    # Автоматическая настройка ширины колонок
    for col in ws.columns:
        max_length = 0
        column = col[0].column_letter
        for cell in col:
            try:
                if len(str(cell.value)) > max_length:
                    max_length = len(str(cell.value))
            except:
                pass
        adjusted_width = min(max_length + 2, 50)
        ws.column_dimensions[column].width = adjusted_width

    # Сохранение в буфер
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    
    # Формирование имени файла
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"applications_export_{timestamp}.xlsx"
    
    return send_file(buffer, as_attachment=True, download_name=filename,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@main.route('/client-service/applications')
@login_required
def applications():
    page = request.args.get('page', 1, type=int)

    # Базовый запрос с предзагрузкой связанных данных для оптимизации
    query = Application.query.options(
        joinedload(Application.client),
        joinedload(Application.responsible_person),
        joinedload(Application.creator)
    )

    # Фильтрация заявок в зависимости от роли
    if not current_user.has_role('Админ'):
        # Пользователь видит заявки, которые он создал
        created_by_me = Application.creator_id == current_user.id

        # Пользователь видит заявки, где он - ответственный
        # (через связь User -> ResponsiblePerson)
        responsible_for = Application.responsible_person_id == (
            current_user.responsible_person_profile.id if current_user.responsible_person_profile else -1
        )

        query = query.filter(or_(created_by_me, responsible_for))
    
    # Применяем фильтры
    # Фильтр по статусу
    status = request.args.get('status', '')
    if status:
        query = query.filter(Application.status == status)
    
    # Фильтр по типу заявки
    app_type = request.args.get('type', '')
    if app_type:
        query = query.filter(Application.application_type == app_type)
    
    # Фильтр по датам создания
    date_from = request.args.get('date_from', '')
    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d')
            query = query.filter(Application.created_at >= date_from_obj)
        except ValueError:
            pass
    
    date_to = request.args.get('date_to', '')
    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            query = query.filter(Application.created_at <= date_to_obj)
        except ValueError:
            pass
    
    # Поиск по клиенту или номеру договора
    search = request.args.get('search', '')
    if search:
        query = query.join(Application.client).filter(
            or_(
                EstateDealsContacts.contacts_buy_name.contains(search),
                Application.agreement_number.contains(search)
            )
        )
    
    # Фильтр по просроченным
    overdue = request.args.get('overdue', '')
    if overdue == 'yes':
        # Только просроченные
        query = query.filter(
            Application.due_date.isnot(None),
            Application.due_date < datetime.utcnow(),
            Application.completed_at.is_(None)
        )
    elif overdue == 'no':
        # Не просроченные
        query = query.filter(
            or_(
                Application.due_date.is_(None),
                Application.due_date >= datetime.utcnow(),
                Application.completed_at.isnot(None)
            )
        )
    
    # Сортировка
    sort = request.args.get('sort', 'created_desc')
    if sort == 'created_desc':
        query = query.order_by(Application.created_at.desc())
    elif sort == 'created_asc':
        query = query.order_by(Application.created_at.asc())
    elif sort == 'due_desc':
        query = query.order_by(Application.due_date.desc().nullslast())
    elif sort == 'due_asc':
        query = query.order_by(Application.due_date.asc().nullsfirst())
    elif sort == 'id_desc':
        query = query.order_by(Application.id.desc())
    elif sort == 'id_asc':
        query = query.order_by(Application.id.asc())
    else:
        query = query.order_by(Application.created_at.desc())

    # Пагинация
    apps_paginated = query.paginate(page=page, per_page=20)
    
    # Получаем уникальные типы заявок для фильтра
    application_types = db.session.query(Application.application_type).distinct().order_by(Application.application_type).all()
    application_types = [t[0] for t in application_types if t[0]]

    return render_template('applications.html', 
                         applications=apps_paginated,
                         application_types=application_types)

@main.route('/client-service/client/<int:client_id>/application/create', methods=['POST'])
@login_required
def create_application(client_id):
    contact = EstateDealsContacts.query.get_or_404(client_id)
    form_data = request.form
    application_type_name = form_data.get('application_type')
    agreement_number, comment, responsible_person_id = form_data.get(
        'agreement_number'), form_data.get('comment'), form_data.get(
        'responsible_person_id')
    
    # Получаем источник заявки
    source = form_data.get('source', 'Звонок')
    if source == 'Другое':
        custom_source = form_data.get('custom_source', '').strip()
        if custom_source:
            source = custom_source

    if not all([agreement_number, application_type_name, comment, responsible_person_id]):
        flash('Все поля, включая ответственного, обязательны для заполнения.', 'danger')
        return redirect(url_for('main.client_card', client_id=client_id))

    # Получаем тип заявки для определения срока выполнения
    app_type = ApplicationType.query.filter_by(name=application_type_name).first()
    
    # Рассчитываем срок выполнения
    due_date = None
    if app_type and app_type.execution_days:
        from datetime import timedelta
        due_date = datetime.utcnow() + timedelta(days=app_type.execution_days)

    new_app = Application(client_id=client_id, agreement_number=agreement_number,
                          application_type=application_type_name,
                          comment=comment, responsible_person_id=responsible_person_id,
                          creator_id=current_user.id, due_date=due_date, source=source)
    db.session.add(new_app)

    defects_data = {}
    for key, value in request.form.items():
        if key.startswith('defects-'):
            parts = key.split('-')
            if len(parts) == 3:
                index, field = int(parts[1]), parts[2]
                defects_data.setdefault(index, {})[field] = value

    if application_type_name == 'Дефекты' and not defects_data:
        db.session.rollback()
        flash('Для заявок типа "Дефекты" необходимо добавить хотя бы один дефект.', 'danger')
        return redirect(url_for('main.client_card', client_id=client_id))

    for index, data in sorted(defects_data.items()):
        defect_type, description = data.get('type'), data.get('description')
        if defect_type and description:
            db.session.add(Defect(application=new_app, defect_type=defect_type, description=description))
        else:
            flash(f'В дефекте №{index + 1} не заполнены все поля. Он не будет сохранен.', 'warning')

    db.session.add(ApplicationLog(application=new_app, action="Заявка создана",
                                  comment=f"Назначен ответственный: {ResponsiblePerson.query.get(responsible_person_id).full_name}",
                                  author_id=current_user.id))

    try:
        db.session.commit()
        app_instance = current_app._get_current_object()
        thr = Thread(target=send_email_async, args=[app_instance, new_app.id])
        thr.start()
        flash('Заявка успешно создана! Уведомление ответственному лицу отправляется.', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'Произошла ошибка при сохранении заявки в базу данных: {e}', 'danger')

    return redirect(url_for('main.client_card', client_id=client_id))


@main.route('/client-service/application/create-general', methods=['POST'])
@login_required
def create_general_application():
    """Создание заявки без привязки к клиенту (через системного клиента)"""
    form_data = request.form
    
    # Получаем системного клиента
    system_client = EstateDealsContacts.query.filter_by(
        contacts_buy_name="СИСТЕМНЫЙ КЛИЕНТ (для заявок без договора)"
    ).first()
    
    if not system_client:
        flash('Системный клиент не найден. Обратитесь к администратору.', 'danger')
        return redirect(url_for('main.index'))
    
    # Получаем данные из формы
    application_type_name = form_data.get('application_type')
    comment = form_data.get('comment')
    responsible_person_id = form_data.get('responsible_person_id')
    contact_name = form_data.get('contact_name', '').strip()
    contact_phone = form_data.get('contact_phone', '').strip()
    
    # Получаем источник заявки
    source = form_data.get('source', 'Звонок')
    if source == 'Другое':
        custom_source = form_data.get('custom_source', '').strip()
        if custom_source:
            source = custom_source

    # Проверяем обязательные поля
    if not all([application_type_name, comment, responsible_person_id]):
        flash('Тип заявки, комментарий и ответственный являются обязательными полями.', 'danger')
        return redirect(url_for('main.index'))

    # Добавляем информацию о контакте в комментарий, если она указана
    enhanced_comment = comment
    if contact_name or contact_phone:
        enhanced_comment = f"Контактные данные: "
        if contact_name:
            enhanced_comment += f"ФИО: {contact_name}"
        if contact_phone:
            if contact_name:
                enhanced_comment += ", "
            enhanced_comment += f"Телефон: {contact_phone}"
        enhanced_comment += f"\n\n{comment}"

    # Получаем тип заявки для определения срока выполнения
    app_type = ApplicationType.query.filter_by(name=application_type_name).first()
    
    # Рассчитываем срок выполнения
    due_date = None
    if app_type and app_type.execution_days:
        from datetime import timedelta
        due_date = datetime.utcnow() + timedelta(days=app_type.execution_days)

    # Создаем заявку с системным клиентом и договором
    new_app = Application(
        client_id=system_client.id, 
        agreement_number="SYSTEM-001",  # Системный договор
        application_type=application_type_name,
        comment=enhanced_comment, 
        responsible_person_id=responsible_person_id,
        creator_id=current_user.id, 
        due_date=due_date, 
        source=source
    )
    db.session.add(new_app)

    # Обработка дефектов
    defects_data = {}
    for key, value in request.form.items():
        if key.startswith('defects-'):
            parts = key.split('-')
            if len(parts) == 3:
                index, field = int(parts[1]), parts[2]
                defects_data.setdefault(index, {})[field] = value

    if app_type and app_type.has_defect_list and not defects_data:
        db.session.rollback()
        flash('Для заявок данного типа необходимо добавить хотя бы один дефект.', 'danger')
        return redirect(url_for('main.index'))

    for index, data in sorted(defects_data.items()):
        defect_type, description = data.get('type'), data.get('description')
        if defect_type and description:
            db.session.add(Defect(application=new_app, defect_type=defect_type, description=description))
        else:
            flash(f'В дефекте №{index + 1} не заполнены все поля. Он не будет сохранен.', 'warning')

    # Добавляем лог
    db.session.add(ApplicationLog(
        application=new_app, 
        action="Заявка создана (без привязки к клиенту)",
        comment=f"Назначен ответственный: {ResponsiblePerson.query.get(responsible_person_id).full_name}",
        author_id=current_user.id
    ))

    try:
        db.session.commit()
        app_instance = current_app._get_current_object()
        thr = Thread(target=send_email_async, args=[app_instance, new_app.id])
        thr.start()
        flash(f'Заявка №{new_app.id} успешно создана! Уведомление ответственному лицу отправляется.', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'Произошла ошибка при сохранении заявки в базу данных: {e}', 'danger')

    return redirect(url_for('main.applications'))


@main.route('/client-service/responsible')
@login_required
@permission_required('Админ')
def responsible_persons():
    persons = ResponsiblePerson.query.order_by(ResponsiblePerson.full_name).all()
    all_complex_names_tuples = db.session.query(EstateHouses.complex_name).filter(EstateHouses.complex_name.isnot(None),
                                                                                  EstateHouses.complex_name != '').distinct().order_by(
        EstateHouses.complex_name).all()
    all_complex_names = [name[0] for name in all_complex_names_tuples]

    all_application_types = ApplicationType.query.order_by(ApplicationType.name).all()
    all_users = User.query.order_by(User.username).all()
    return render_template('responsible.html',
                           persons=persons,
                           all_complex_names=all_complex_names,
                           all_application_types=all_application_types,all_users=all_users)


@main.route('/client-service/responsible', methods=['POST'])
@login_required
@permission_required('Админ')
def create_responsible_person():
    form_data = request.form
    new_person = ResponsiblePerson(full_name=form_data.get('full_name'), email=form_data.get('email'),
        user_id=form_data.get('user_id'))

    selected_app_type_names = form_data.getlist('application_types')
    new_person.application_types = selected_app_type_names

    assigned_complex_names = form_data.getlist('assigned_complexes')
    if assigned_complex_names:
        new_person.assigned_complexes = EstateHouses.query.filter(
            EstateHouses.complex_name.in_(assigned_complex_names)).all()
    else:
        new_person.assigned_complexes = []
    db.session.add(new_person)
    try:
        db.session.commit()
        flash(f'Ответственное лицо "{new_person.full_name}" успешно создано.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка при создании: {e}', 'danger')
    return redirect(url_for('main.responsible_persons'))


@main.route('/client-service/responsible/<int:person_id>/update', methods=['POST'])
@login_required
@permission_required('Админ')
def update_responsible_person(person_id):
    person = ResponsiblePerson.query.get_or_404(person_id)
    form_data = request.form
    person.full_name = form_data.get('full_name')
    person.email = form_data.get('email')
    person.user_id = form_data.get('user_id') or None

    selected_app_type_names = form_data.getlist('application_types')
    person.application_types = selected_app_type_names

    assigned_complex_names = form_data.getlist('assigned_complexes')
    if assigned_complex_names:
        person.assigned_complexes = EstateHouses.query.filter(
            EstateHouses.complex_name.in_(assigned_complex_names)).all()
    else:
        person.assigned_complexes = []
    try:
        db.session.commit()
        flash(f'Данные "{person.full_name}" успешно обновлены.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка при обновлении: {e}', 'danger')
    return redirect(url_for('main.responsible_persons'))


@main.route('/client-service/responsible/<int:person_id>/delete', methods=['POST'])
@login_required
@permission_required('Админ')
def delete_responsible_person(person_id):
    person = ResponsiblePerson.query.get_or_404(person_id)
    name = person.full_name
    db.session.delete(person)
    try:
        db.session.commit()
        flash(f'Ответственное лицо "{name}" было удалено.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка при удалении: {e}', 'danger')
    return redirect(url_for('main.responsible_persons'))


@main.route('/client-service/api/responsible')
@login_required
def get_responsible_persons():
    complex_name, app_type = request.args.get('complex_name'), request.args.get('application_type')
    if not complex_name or not app_type:
        return jsonify([])
    sql_query_complex = text(
        """SELECT DISTINCT p.id,p.full_name,p.email,p.application_types_json FROM responsible_persons p JOIN responsible_assignments ra ON p.id=ra.responsible_person_id JOIN estate_houses eh ON eh.house_id=ra.house_id WHERE eh.complex_name LIKE :complex_name""")
    params_complex = {'complex_name': complex_name}
    result = db.session.execute(sql_query_complex, params_complex)
    persons_for_complex = result.mappings().all()
    final_persons = []
    if persons_for_complex:
        for person in persons_for_complex:
            try:
                person_app_types = json.loads(person['application_types_json'])
                if app_type in person_app_types:
                    final_persons.append(person)
            except json.JSONDecodeError:
                continue
    return jsonify([{'id': p['id'], 'name': p['full_name'], 'email': p['email']} for p in final_persons])


@main.route('/client-service/application/<int:app_id>/update_status', methods=['POST'])
@login_required
@permission_required('Специалист КЦ', 'Менеджер ДКС', 'Менеджер отдела оформления', 'Менеджер ОГР', 'Админ')
def update_application_status(app_id):
    app = Application.query.get_or_404(app_id)
    is_admin = current_user.has_role('Админ')
    # Проверяем, привязан ли текущий пользователь к ответственному по этой заявке
    is_responsible = (current_user.responsible_person_profile and
                      current_user.responsible_person_profile.id == app.responsible_person_id)

    if not (is_admin or is_responsible):
        abort(403)  # Forbidden

    new_status, comment = request.form.get('status'), request.form.get('comment')
    if not new_status or not comment:
        flash('Для смены статуса необходимо выбрать новый статус и оставить комментарий.', 'danger')
        return redirect(url_for('main.client_card', client_id=app.client_id))
    if app.status == new_status:
        flash('Новый статус совпадает с текущим. Изменений не внесено.', 'info')
        return redirect(url_for('main.client_card', client_id=app.client_id))
    old_status = app.status
    app.status = new_status
    # Обновляем временной штамп последнего изменения статуса
    app.last_status_change = datetime.utcnow()
    
    # Устанавливаем дату завершения, если статус финальный
    if new_status in ['Выполнено', 'Закрыто', 'Отклонено']:
        if not app.completed_at:
            app.completed_at = datetime.utcnow()
    elif old_status in ['Выполнено', 'Закрыто', 'Отклонено'] and new_status not in ['Выполнено', 'Закрыто', 'Отклонено']:
        # Если возвращаем в работу, убираем дату завершения
        app.completed_at = None
    
    log_entry = ApplicationLog(application=app, action=f"Статус изменен: {old_status} -> {new_status}", 
                               comment=comment, author_id=current_user.id)
    db.session.add(log_entry)
    try:
        db.session.commit()
        flash(f'Статус заявки #{app.id} успешно изменен на "{new_status}".', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка при изменении статуса: {e}', 'danger')
    return redirect(url_for('main.client_card', client_id=app.client_id))


@main.route('/client-service/api/application/<int:app_id>/logs')
@login_required
def get_application_logs(app_id):
    Application.query.get_or_404(app_id)
    logs = ApplicationLog.query.filter_by(application_id=app_id).options(
        joinedload(ApplicationLog.author)
    ).order_by(ApplicationLog.timestamp.desc()).all()
    return jsonify(
        [{'timestamp': log.timestamp.strftime('%d.%m.%Y %H:%M:%S'), 
          'action': log.action, 
          'comment': log.comment,
          'author': log.author.username if log.author else 'Система'} for log in logs])


@main.route('/client-service/reports')
@login_required
@permission_required('Админ')
def reports():
    return render_template('reports.html')


@main.route('/client-service/reports/download', methods=['POST'])
@login_required
@permission_required('Специалист КЦ', 'Менеджер ДКС', 'Админ')
def download_report():
    start_date_str, end_date_str = request.form.get('start_date'), request.form.get('end_date')
    if not start_date_str or not end_date_str:
        flash('Необходимо указать и начальную, и конечную дату.', 'danger')
        return redirect(url_for('main.reports'))
    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
    except ValueError:
        flash('Неверный формат даты.', 'danger')
        return redirect(url_for('main.reports'))

    apps = Application.query.options(joinedload(Application.client), joinedload(Application.responsible_person),
                                     joinedload(Application.defects)).filter(Application.created_at >= start_date,
                                                                             Application.created_at <= end_date).order_by(
        Application.created_at.desc()).all()
    if not apps:
        flash('За указанный период не найдено ни одной заявки.', 'info')
        return redirect(url_for('main.reports'))

    wb = Workbook()
    ws = wb.active
    ws.title = "Отчет по заявкам"
    headers = ["ID Заявки", "Дата создания", "Статус", "Тип заявки", "№ Договора", "ФИО Клиента", "Телефон клиента",
               "ЖК", "Дом", "Подъезд", "Номер квартиры",
               "Ответственный", "Email ответственного", "Источник", "Срок выполнения", "Дата завершения", "Просрочено",
               "Дата последнего изменения", "Последний комментарий", "Комментарий к заявке", "Дефекты (Тип: Комментарий)"]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for app in apps:
        # Получаем данные о недвижимости через связи
        complex_name = "N/A"
        house_name = "N/A"
        entrance = "N/A"
        flat_num = "N/A"
        
        # Ищем сделку по номеру договора
        if app.client and app.agreement_number:
            deal = EstateDeals.query.filter_by(
                agreement_number=app.agreement_number,
                contacts_buy_id=app.client.id
            ).first()
            
            if deal and deal.sell:
                sell = deal.sell
                entrance = sell.geo_house_entrance if sell.geo_house_entrance else "N/A"
                flat_num = sell.geo_flatnum if sell.geo_flatnum else "N/A"
                
                if sell.house:
                    complex_name = sell.house.complex_name if sell.house.complex_name else "N/A"
                    house_name = sell.house.name if sell.house.name else "N/A"
        
        defects_str = "; ".join([f"{d.defect_type}: {d.description}" for d in app.defects])
        
        # Проверяем просроченность
        is_overdue = "Да" if app.is_overdue else "Нет"
        
        # Получаем последний комментарий из логов
        last_log = ApplicationLog.query.filter_by(application_id=app.id).order_by(ApplicationLog.timestamp.desc()).first()
        last_comment = last_log.comment if last_log else "N/A"
        
        row_data = [app.id, app.created_at.strftime('%Y-%m-%d %H:%M:%S'), app.status, app.application_type,
                    app.agreement_number, app.client.contacts_buy_name if app.client else "N/A",
                    app.client.contacts_buy_phones if app.client else "N/A",
                    complex_name, house_name, entrance, flat_num,
                    app.responsible_person.full_name if app.responsible_person else "Не назначен",
                    app.responsible_person.email if app.responsible_person else "N/A",
                    app.source if app.source else "Не указан",
                    app.due_date.strftime('%Y-%m-%d') if app.due_date else "N/A",
                    app.completed_at.strftime('%Y-%m-%d %H:%M:%S') if app.completed_at else "N/A",
                    is_overdue,
                    app.last_status_change.strftime('%Y-%m-%d %H:%M:%S') if app.last_status_change else "N/A",
                    last_comment,
                    app.comment, defects_str]
        ws.append(row_data)

    for col in ws.columns:
        max_length = 0
        column = col[0].column_letter
        for cell in col:
            try:
                if len(str(cell.value)) > max_length:
                    max_length = len(cell.value)
            except:
                pass
        adjusted_width = (max_length + 2)
        ws.column_dimensions[column].width = adjusted_width

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    filename = f"report_{start_date_str}_to_{end_date_str}.xlsx"
    return send_file(buffer, as_attachment=True, download_name=filename,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@main.route('/client-service/reports/download-completed', methods=['POST'])
@login_required
@permission_required('Специалист КЦ', 'Менеджер ДКС', 'Админ')
def download_completed_report():
    """Генерирует отчет по завершенным заявкам за указанный период"""
    start_date_str, end_date_str = request.form.get('start_date'), request.form.get('end_date')
    if not start_date_str or not end_date_str:
        flash('Необходимо указать и начальную, и конечную дату.', 'danger')
        return redirect(url_for('main.reports'))
    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
    except ValueError:
        flash('Неверный формат даты.', 'danger')
        return redirect(url_for('main.reports'))

    # Фильтруем только завершенные заявки по дате завершения
    apps = Application.query.options(
        joinedload(Application.client), 
        joinedload(Application.responsible_person),
        joinedload(Application.defects),
        joinedload(Application.creator)
    ).filter(
        Application.completed_at >= start_date,
        Application.completed_at <= end_date,
        Application.status.in_(['Выполнено', 'Закрыто', 'Отклонено'])
    ).order_by(Application.completed_at.desc()).all()
    
    if not apps:
        flash('За указанный период не найдено ни одной завершенной заявки.', 'info')
        return redirect(url_for('main.reports'))

    wb = Workbook()
    ws = wb.active
    ws.title = "Завершенные заявки"
    headers = ["ID Заявки", "Дата создания", "Дата завершения", "Время выполнения (дней)", 
               "Статус", "Тип заявки", "№ Договора", "ФИО Клиента", "Телефон клиента",
               "ЖК", "Дом", "Подъезд", "Номер квартиры",
               "Ответственный", "Email ответственного", "Создатель заявки", "Источник", 
               "Была просрочена", "Дата последнего изменения", "Последний комментарий", 
               "Комментарий к заявке", "Дефекты (Тип: Комментарий)"]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for app in apps:
        # Получаем данные о недвижимости через связи
        complex_name = "N/A"
        house_name = "N/A"
        entrance = "N/A"
        flat_num = "N/A"
        
        # Ищем сделку по номеру договора
        if app.client and app.agreement_number:
            deal = EstateDeals.query.filter_by(
                agreement_number=app.agreement_number,
                contacts_buy_id=app.client.id
            ).first()
            
            if deal and deal.sell:
                sell = deal.sell
                entrance = sell.geo_house_entrance if sell.geo_house_entrance else "N/A"
                flat_num = sell.geo_flatnum if sell.geo_flatnum else "N/A"
                
                if sell.house:
                    complex_name = sell.house.complex_name if sell.house.complex_name else "N/A"
                    house_name = sell.house.name if sell.house.name else "N/A"
        
        defects_str = "; ".join([f"{d.defect_type}: {d.description}" for d in app.defects])
        
        # Рассчитываем время выполнения в днях
        execution_time = "N/A"
        if app.completed_at and app.created_at:
            time_diff = app.completed_at - app.created_at
            execution_time = time_diff.days
        
        # Проверяем, была ли заявка просрочена
        was_overdue = "Нет"
        if app.due_date and app.completed_at:
            if app.completed_at > app.due_date:
                was_overdue = "Да"
        
        # Получаем последний комментарий из логов
        last_log = ApplicationLog.query.filter_by(application_id=app.id).order_by(ApplicationLog.timestamp.desc()).first()
        last_comment = last_log.comment if last_log else "N/A"
        
        row_data = [
            app.id, 
            app.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            app.completed_at.strftime('%Y-%m-%d %H:%M:%S') if app.completed_at else "N/A",
            execution_time,
            app.status, 
            app.application_type,
            app.agreement_number, 
            app.client.contacts_buy_name if app.client else "N/A",
            app.client.contacts_buy_phones if app.client else "N/A",
            complex_name, house_name, entrance, flat_num,
            app.responsible_person.full_name if app.responsible_person else "Не назначен",
            app.responsible_person.email if app.responsible_person else "N/A",
            app.creator.username if app.creator else "Система",
            app.source if app.source else "Не указан",
            was_overdue,
            app.last_status_change.strftime('%Y-%m-%d %H:%M:%S') if app.last_status_change else "N/A",
            last_comment,
            app.comment, 
            defects_str
        ]
        ws.append(row_data)

    # Автоматическая настройка ширины колонок
    for col in ws.columns:
        max_length = 0
        column = col[0].column_letter
        for cell in col:
            try:
                if len(str(cell.value)) > max_length:
                    max_length = len(str(cell.value))
            except:
                pass
        adjusted_width = min(max_length + 2, 50)  # Ограничиваем максимальную ширину
        ws.column_dimensions[column].width = adjusted_width

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    filename = f"completed_applications_{start_date_str}_to_{end_date_str}.xlsx"
    return send_file(buffer, as_attachment=True, download_name=filename,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@main.route('/client-service/deadlines/upload', methods=['GET', 'POST'])
@login_required
@admin_required
def upload_deadlines():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('Файл не был выбран.', 'danger')
            return redirect(request.url)
        file = request.files['file']
        if file.filename == '':
            flash('Файл не был выбран.', 'danger')
            return redirect(request.url)
        if file and file.filename.endswith('.xlsx'):
            try:
                workbook = load_workbook(file)
                sheet = workbook.active

                updated_count = 0
                not_found_count = 0
                error_count = 0

                for row_idx, row in enumerate(sheet.iter_rows(min_row=2, values_only=True), start=2):
                    if not any(row): continue

                    house_name = row[0]
                    house_date_raw = row[1]
                    apartments_date_raw = row[2]

                    if not house_name:
                        flash(f'Ошибка в строке {row_idx}: Название Дома не указано. Строка пропущена.', 'warning')
                        error_count += 1
                        continue

                    house = EstateHouses.query.filter_by(name=house_name).first()

                    if not house:
                        flash(f'Дом с названием "{house_name}" из строки {row_idx} не найден в базе данных.', 'warning')
                        not_found_count += 1
                        continue

                    try:
                        if house_date_raw:
                            parsed_house_date = house_date_raw.date() if isinstance(house_date_raw,
                                                                                    datetime) else datetime.strptime(
                                str(house_date_raw), '%d.%m.%Y').date()
                            house.warranty_house_end_date = parsed_house_date

                        if apartments_date_raw:
                            parsed_apartments_date = apartments_date_raw.date() if isinstance(apartments_date_raw,
                                                                                              datetime) else datetime.strptime(
                                str(apartments_date_raw), '%d.%m.%Y').date()
                            house.warranty_apartments_end_date = parsed_apartments_date

                        updated_count += 1

                    except (ValueError, TypeError):
                        flash(
                            f'Ошибка в строке {row_idx} для дома "{house_name}": Неверный формат даты. Ожидается ДД.ММ.ГГГГ. Строка пропущена.',
                            'warning')
                        error_count += 1
                        continue

                db.session.commit()

                success_message = f'Обработка файла завершена. '
                if updated_count > 0:
                    success_message += f'Обработано {updated_count} строк. Данные сохранены. '
                if not_found_count > 0:
                    success_message += f'Не найдено {not_found_count} домов. '
                if error_count > 0:
                    success_message += f'Ошибок в данных: {error_count}.'

                flash(success_message, 'success' if error_count == 0 and not_found_count == 0 else 'info')

            except Exception as e:
                db.session.rollback()
                flash(f'Произошла критическая ошибка при обработке файла: {e}', 'danger')

            return redirect(url_for('main.upload_deadlines'))

        else:
            flash('Неверный формат файла. Пожалуйста, загрузите файл .xlsx', 'danger')
            return redirect(request.url)

    return render_template('upload_deadlines.html')


@main.route('/client-service/deadlines/template')
@login_required
@admin_required
def download_deadlines_template():
    try:
        buffer = io.BytesIO()
        wb = Workbook()
        ws = wb.active
        ws.title = "Шаблон сроков гарантии"

        headers = ["Название Дома", "Срок гарантии по Дому (формат ДД.ММ.ГГГГ)",
                   "Срок гарантии по Квартирам (формат ДД.ММ.ГГГГ)"]
        ws.append(headers)

        header_font = Font(bold=True)
        for cell in ws[1]:
            cell.font = header_font
            cell.alignment = Alignment(wrap_text=True)

        ws.column_dimensions['A'].width = 40
        ws.column_dimensions['B'].width = 30
        ws.column_dimensions['C'].width = 30

        unique_house_names_tuples = db.session.query(EstateHouses.name).filter(EstateHouses.name.isnot(None),
                                                                               EstateHouses.name != '').distinct().order_by(
            EstateHouses.name).all()

        for name_tuple in unique_house_names_tuples:
            house_name = name_tuple[0]
            house = EstateHouses.query.filter_by(name=house_name).first()
            if house:
                house_date_str = house.warranty_house_end_date.strftime(
                    '%d.%m.%Y') if house.warranty_house_end_date else ''
                apartments_date_str = house.warranty_apartments_end_date.strftime(
                    '%d.%m.%Y') if house.warranty_apartments_end_date else ''
                ws.append([house.name, house_date_str, apartments_date_str])

        wb.save(buffer)
        buffer.seek(0)

        return send_file(
            buffer,
            as_attachment=True,
            download_name='shablon_srokov_garantii_po_domam.xlsx',
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
    except Exception as e:
        flash(f'Не удалось сгенерировать шаблон. Ошибка: {e}', 'danger')
        return redirect(url_for('main.upload_deadlines'))


@main.route('/client-service/admin/email-logs')
@login_required
@admin_required
def email_logs():
    page = request.args.get('page', 1, type=int)
    logs = EmailLog.query.order_by(EmailLog.timestamp.desc()).paginate(page=page, per_page=20)
    return render_template('email_logs.html', logs=logs)


@main.route('/client-service/admin/defect-types', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_defect_types():
    if request.method == 'POST':
        new_type_name = request.form.get('name')
        if new_type_name:
            existing_type = DefectType.query.filter_by(name=new_type_name).first()
            if not existing_type:
                new_type = DefectType(name=new_type_name)
                db.session.add(new_type)
                db.session.commit()
                flash(f'Тип дефекта "{new_type_name}" успешно добавлен.', 'success')
            else:
                flash(f'Тип дефекта "{new_type_name}" уже существует.', 'warning')
        else:
            flash('Название типа дефекта не может быть пустым.', 'danger')
        return redirect(url_for('main.manage_defect_types'))

    defect_types = DefectType.query.order_by(DefectType.name).all()
    return render_template('manage_defect_types.html', defect_types=defect_types)


@main.route('/client-service/admin/defect-types/<int:type_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_defect_type(type_id):
    type_to_delete = DefectType.query.get_or_404(type_id)
    try:
        db.session.delete(type_to_delete)
        db.session.commit()
        flash(f'Тип дефекта "{type_to_delete.name}" удален.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Не удалось удалить тип дефекта. Возможно, он где-то используется. Ошибка: {e}', 'danger')
    return redirect(url_for('main.manage_defect_types'))


@main.route('/client-service/admin/application-types', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_application_types():
    if request.method == 'POST':
        name = request.form.get('name')
        # --- ИЗМЕНЕНИЕ: Получаем значение чекбокса ---
        has_defect_list = 'has_defect_list' in request.form
        
        # Получаем срок выполнения
        execution_days = request.form.get('execution_days', type=int, default=3)
        if execution_days < 1:
            execution_days = 3  # Минимальный срок - 1 день

        if not name:
            flash('Название типа заявки не может быть пустым.', 'danger')
            return redirect(url_for('main.manage_application_types'))

        if 'template' not in request.files:
            flash('Файл шаблона не был выбран.', 'danger')
            return redirect(url_for('main.manage_application_types'))

        file = request.files['template']

        if file.filename == '':
            flash('Файл шаблона не был выбран.', 'danger')
            return redirect(url_for('main.manage_application_types'))

        if file and file.filename.endswith('.docx'):
            filename = secure_filename(file.filename)
            upload_folder = os.path.join(current_app.root_path, 'word_templates')
            os.makedirs(upload_folder, exist_ok=True)

            file.save(os.path.join(upload_folder, filename))

            # --- ИЗМЕНЕНИЕ: Сохраняем новый флаг в БД ---
            new_app_type = ApplicationType(name=name, template_filename=filename, has_defect_list=has_defect_list, execution_days=execution_days)
            db.session.add(new_app_type)
            db.session.commit()
            flash(f'Тип заявки "{name}" с шаблоном "{filename}" и сроком выполнения {execution_days} дн.(-я) успешно создан.', 'success')
        else:
            flash('Разрешены только файлы формата .docx', 'danger')

        return redirect(url_for('main.manage_application_types'))
    template_tags = [
        {'tag': '{{ fio_otvetstvenni }}', 'desc': 'ФИО ответственного сотрудника'},
        {'tag': '{{ request_id }}', 'desc': 'ID созданной заявки'},
        {'tag': '{{ today_date }}', 'desc': 'Текущая дата в формате ДД.ММ.ГГГГ'},
        {'tag': '{{ agreement_number }}', 'desc': 'Номер договора, к которому привязана заявка'},
        {'tag': '{{ client_fio }}', 'desc': 'ФИО клиента'},
        {'tag': '{{ complex_name }}', 'desc': 'Название ЖК (жилого комплекса)'},
        {'tag': '{{ house_name }}', 'desc': 'Название/номер дома'},
        {'tag': '{{ podiezd }}', 'desc': 'Номер подъезда'},
        {'tag': '{{ flat_num }}', 'desc': 'Номер квартиры'},
        {'tag': '{{ comment }}', 'desc': 'Общий комментарий к заявке'},
        {'tag': '{{ client_phone_number }}', 'desc': 'Контактный телефон клиента'},
        {'tag': '{% for defect in defects %}...{% endfor %}', 'desc': 'Цикл для перечисления дефектов'},
        {'tag': '{{ defect.defect_type }}', 'desc': 'Тип дефекта (внутри цикла)'},
        {'tag': '{{ defect.comment }}', 'desc': 'Комментарий к конкретному дефекту (внутри цикла)'},
    ]

    app_types = ApplicationType.query.order_by(ApplicationType.name).all()
    return render_template('manage_application_types.html', app_types=app_types, template_tags=template_tags)


@main.route('/client-service/admin/application-types/<int:type_id>/download')
@login_required
@admin_required
def download_application_template(type_id):
    """Скачивание шаблона Word для типа заявки"""
    app_type = ApplicationType.query.get_or_404(type_id)
    
    if not app_type.template_filename:
        flash('У данного типа заявки нет шаблона.', 'warning')
        return redirect(url_for('main.manage_application_types'))
    
    template_path = os.path.join(current_app.root_path, 'word_templates', app_type.template_filename)
    
    if not os.path.exists(template_path):
        flash('Файл шаблона не найден на сервере.', 'danger')
        return redirect(url_for('main.manage_application_types'))
    
    # Формируем имя файла для скачивания
    download_name = f"template_{app_type.name}_{app_type.template_filename}"
    # Заменяем пробелы на подчеркивания для корректного имени файла
    download_name = download_name.replace(' ', '_')
    
    return send_file(
        template_path,
        as_attachment=True,
        download_name=download_name,
        mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    )


@main.route('/client-service/admin/application-types/<int:type_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_application_type(type_id):
    app_type_to_delete = ApplicationType.query.get_or_404(type_id)

    if app_type_to_delete.template_filename:
        try:
            template_path = os.path.join(current_app.root_path, 'word_templates', app_type_to_delete.template_filename)
            if os.path.exists(template_path):
                os.remove(template_path)
        except OSError as e:
            flash(f'Не удалось удалить файл шаблона {app_type_to_delete.template_filename}. Ошибка: {e}', 'warning')

    db.session.delete(app_type_to_delete)
    db.session.commit()
    flash(f'Тип заявки "{app_type_to_delete.name}" удален.', 'success')
    return redirect(url_for('main.manage_application_types'))


@main.route('/client-service/application/<int:app_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_application(app_id):
    """
    Удаляет заявку и все связанные с ней данные (дефекты, логи).
    Доступно только администраторам.
    """
    app_to_delete = Application.query.get_or_404(app_id)

    try:
        # База данных настроена с каскадным удалением (cascade="all, delete-orphan"),
        # поэтому связанные дефекты и логи удалятся автоматически.
        db.session.delete(app_to_delete)
        db.session.commit()
        flash(f'Заявка #{app_id} была успешно удалена.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Произошла ошибка при удалении заявки #{app_id}: {e}', 'danger')

    # Перенаправляем пользователя обратно на страницу со списком заявок
    return redirect(url_for('main.applications'))


