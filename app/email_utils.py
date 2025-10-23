# app/email_utils.py
import os
import io
from datetime import datetime
from flask import current_app
from docxtpl import DocxTemplate
from .extensions import db
from .models import Application, EstateDeals, EstateSells, EmailLog, ApplicationType
from .notification_client import notification_client
import logging

logger = logging.getLogger(__name__)


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
            'complex_name': sell.house.complex_name if sell and sell.house else 'N/A',
            'house_name': sell.house.name if sell and sell.house else 'N/A',
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

        log_entry.recipient = responsible.email
        log_entry.subject = subject_str

        # Отправляем через notification-service
        try:
            result = notification_client.send_email(
                recipient=responsible.email,
                subject=subject_str,
                content=email_body,
                attachment_filename=f"Application_{app_obj.id}.docx",
                attachment_content=doc_io.read()
            )
            
            log_entry.status = 'Success'
            log_entry.server_response = f"Notification ID: {result.get('id', 'N/A')}"
            logger.info(f"Email для заявки #{application_id} успешно отправлен на {responsible.email}")
            
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

