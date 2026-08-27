# app/email_utils.py
import os
import io
from datetime import datetime
from flask import current_app
from docxtpl import DocxTemplate
from .extensions import db
from .models import Application, EstateDeals, EstateSells, EmailLog, ApplicationType
from .notification_client import notification_client
from .auth_utils import get_gateway_user_login
import logging

logger = logging.getLogger(__name__)

# Куда уходит письмо, если ответственного не удалось связать с учёткой портала.
# Терять заявку нельзя, а слать на локальный email в обход auth-service — значит
# годами не замечать, что справочник разъехался с порталом.
DEFAULT_INCIDENT_RECIPIENT = 'robot@gh.uz'


def _unlinked_reason(responsible):
    """
    Человекочитаемая причина, почему у ответственного нет логина портала.

    Returns:
        str: причина для письма-инцидента
    """
    if not responsible:
        return 'ответственный по заявке не назначен'
    if not responsible.gateway_user_id:
        return 'в справочнике ответственных не выбран пользователь портала'
    return (f'auth-service не вернул логин по gateway_user_id={responsible.gateway_user_id} '
            f'(учётка удалена или сервис недоступен)')


def _incident_body(app_obj, responsible, reason, original_body):
    """Тело письма-инцидента: данные для ручной досылки и для починки справочника."""
    return (
        '⚠ Письмо перенаправлено на служебный ящик.' + NL + NL +
        'Адрес доставки определить не удалось, поэтому заявка не ушла ответственному.' + NL + NL +
        f'Причина: {reason}' + NL + NL +
        f'Заявка: №{app_obj.id} ({app_obj.application_type})' + NL +
        f'Договор: {app_obj.agreement_number}' + NL +
        f'Ответственный в справочнике: {responsible.full_name if responsible else "не назначен"}' + NL +
        f'Email в справочнике: {(responsible.email if responsible else None) or "не указан"}' + NL +
        f'Gateway User ID: {(responsible.gateway_user_id if responsible else None) or "не заполнен"}' + NL + NL +
        'Что сделать: открыть раздел «Ответственные лица», выбрать для этого сотрудника '
        'пользователя портала, после чего переслать вложение адресату вручную.' + NL + NL +
        '--- Исходное письмо ---' + NL + NL +
        original_body
    )


def generate_and_send_email(application_id):
    """
    Умная версия: Генерирует Word-документ, находя шаблон в БД,
    отправляет его по email и детально ЛОГИРУЕТ результат.
    """
    log_entry = EmailLog(application_id=application_id)

    try:
        app_obj = Application.query.get(application_id)
        if not app_obj:
            raise ValueError(f"Заявка с ID {application_id} не найдена.")

        # --- НОВАЯ ЛОГИКА ПОИСКА ШАБЛОНА ---
        # Находим тип заявки в нашей новой таблице
        app_type_record = ApplicationType.query.filter_by(name=app_obj.application_type).first()

        # Проверяем, что для этого типа заявки вообще есть шаблон
        if not app_type_record or not app_type_record.template_filename:
            log_entry.status = 'Skipped'
            log_entry.server_response = f"Для типа заявки '{app_obj.application_type}' шаблон не настроен. Отправка пропущена."
            log_entry.recipient = app_obj.responsible_person.email if app_obj.responsible_person else 'N/A'
            log_entry.subject = f"Пропуск отправки для заявки #{app_obj.id}"
            db.session.add(log_entry)
            db.session.commit()
            print(
                f"INFO: Шаблон для типа '{app_obj.application_type}' не найден. Отправка email для заявки #{application_id} пропущена.")
            return

        template_filename = app_type_record.template_filename
        template_path = os.path.join(current_app.root_path, 'word_templates', template_filename)

        if not os.path.exists(template_path):
            raise FileNotFoundError(f"Файл шаблона '{template_filename}' не найден по пути {template_path}")

        # Сбор данных для шаблона
        client = app_obj.client
        responsible = app_obj.responsible_person
        deal = EstateDeals.query.filter_by(agreement_number=app_obj.agreement_number, contacts_buy_id=client.id).first()
        sell = deal.sell if deal else None

        # Подготовка списка дефектов
        defects_list = [{'defect_type': d.defect_type, 'comment': d.description} for d in app_obj.defects]
        
        # Для обратной совместимости со старыми шаблонами добавляем первый дефект как 'defect'
        # и флаг наличия дефектов
        first_defect = defects_list[0] if defects_list else {'defect_type': '', 'comment': ''}
        
        context = {
            'fio_otvetstvenni': responsible.full_name if responsible else 'Не назначен',
            'request_id': app_obj.id,
            'today_date': datetime.now().strftime('%d.%m.%Y'),
            'agreement_number': app_obj.agreement_number,
            'client_fio': client.contacts_buy_name,
            'complex_name': (sell.house.complex_name if sell and sell.house else None) or app_obj.housing_complex or 'N/A',
            'house_name': (sell.house.name if sell and sell.house else None) or app_obj.house_number or 'N/A',
            'podiezd': sell.geo_house_entrance if sell else 'N/A',
            'flat_num': sell.geo_flatnum if sell else 'N/A',
            'comment': app_obj.comment,
            'client_phone_number': client.contacts_buy_phones,
            'defects': defects_list,
            # Для обратной совместимости со старыми шаблонами:
            'defect': first_defect,  # Первый дефект (или пустой объект)
            'has_defects': len(defects_list) > 0,  # Флаг наличия дефектов
            'defects_count': len(defects_list)  # Количество дефектов
        }

        subject_str = f'Новая заявка: {app_obj.application_type} №{app_obj.id}'

        try:
            doc = DocxTemplate(template_path)
            print(f"DEBUG: Рендерим шаблон {template_filename} для заявки #{application_id}")
            print(f"DEBUG: Количество дефектов: {len(context['defects'])}")
            print(f"DEBUG: Контекст содержит ключи: {list(context.keys())}")
            if context['defects']:
                print(f"DEBUG: Первый дефект: {context['defect']}")
            doc.render(context)
            doc_io = io.BytesIO()
            doc.save(doc_io)
            doc_io.seek(0)
            print(f"SUCCESS: Шаблон {template_filename} успешно отрендерен")
        except Exception as render_error:
            error_msg = f"Ошибка при рендеринге шаблона {template_filename}: {render_error}"
            print(f"ERROR: {error_msg}")
            print(f"ERROR: Контекст на момент ошибки: {list(context.keys())}")
            raise ValueError(error_msg)

        # Формируем текст письма
        email_body = f"Поступила новая заявка №{app_obj.id} ({app_obj.application_type}).\n\n"
        email_body += f"Клиент: {client.contacts_buy_name}\n"
        email_body += f"Телефон: {client.contacts_buy_phones}\n"
        email_body += f"Договор: {app_obj.agreement_number}\n"
        email_body += f"Комментарий: {app_obj.comment}\n\n"
        email_body += "Подробности в прикрепленном файле."

        # Ответственный — сотрудник портала: адресуем логином, адрес доставки
        # подставит auth-service.
        responsible_login = get_gateway_user_login(responsible.gateway_user_id) if responsible else None

        if responsible_login:
            addressing = {'login': responsible_login}
            target = responsible_login
            success_status = 'Success'
        else:
            # Привязки нет — на локальный email не откатываемся: письмо ушло бы мимо
            # портала и молча, а справочник так и остался бы сломанным. Отправляем
            # на служебный ящик с данными инцидента, вложение сохраняем — по нему
            # заявку можно дослать руками.
            reason = _unlinked_reason(responsible)
            target = os.getenv('UNLINKED_RESPONSIBLE_EMAIL', DEFAULT_INCIDENT_RECIPIENT)
            addressing = {'external_recipient': target}
            subject_str = f'[НЕТ ПРИВЯЗКИ] {subject_str}'
            email_body = _incident_body(app_obj, responsible, reason, email_body)
            success_status = 'Redirected'
            logger.warning(
                f'Заявка #{application_id}: {reason}; письмо перенаправлено на {target}'
            )

        log_entry.recipient = target
        log_entry.subject = subject_str

        # Отправляем через notification-service
        try:
            result = notification_client.send_email(
                subject=subject_str,
                content=email_body,
                attachment_filename=f"Application_{app_obj.id}.docx",
                attachment_content=doc_io.read(),
                **addressing
            )
            
            log_entry.status = success_status
            log_entry.server_response = f"Notification ID: {result.get('id', 'N/A')}"
            logger.info(f"Email для заявки #{application_id} успешно отправлен на {target}")
            
        except Exception as send_error:
            raise Exception(f"Ошибка отправки через notification-service: {send_error}")

    except Exception as e:
        log_entry.status = 'Failed'
        log_entry.server_response = str(e)
        logger.error(f"Не удалось отправить email для заявки #{application_id}. Ошибка: {e}")

    finally:
        # Эта операция выполняется в контексте приложения, который создается
        # в фоновом потоке в routes.py
        db.session.add(log_entry)
        db.session.commit()

