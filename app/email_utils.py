# app/email_utils.py
import os
import io
from datetime import datetime
from flask import current_app
from flask_mail import Message
from docxtpl import DocxTemplate
from .extensions import db, mail
from .models import Application, EstateDeals, EstateSells, EmailLog, ApplicationType


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

        context = {
            'fio_otvetstvenni': responsible.full_name if responsible else 'Не назначен',
            'request_id': app_obj.id,
            'today_date': datetime.utcnow().strftime('%d.%m.%Y'),
            'agreement_number': app_obj.agreement_number,
            'client_fio': client.contacts_buy_name,
            'complex_name': sell.house.complex_name if sell and sell.house else 'N/A',
            'house_name': sell.house.name if sell and sell.house else 'N/A',
            'podiezd': sell.geo_house_entrance if sell else 'N/A',
            'flat_num': sell.geo_flatnum if sell else 'N/A',
            'comment': app_obj.comment,
            'client_phone_number': client.contacts_buy_phones,
            'defects': [{'defect_type': d.defect_type, 'comment': d.description} for d in app_obj.defects]
        }

        subject_str = f'Новая заявка: {app_obj.application_type} №{app_obj.id}'

        doc = DocxTemplate(template_path)
        doc.render(context)
        doc_io = io.BytesIO()
        doc.save(doc_io)
        doc_io.seek(0)

        # Используем стандартный способ создания сообщения
        msg = Message(subject=subject_str,
                      recipients=[responsible.email],
                      body=f"Поступила новая заявка №{app_obj.id} ({app_obj.application_type}). Подробности в прикрепленном файле.")

        # Используем имя файла на латинице, чтобы исключить любые проблемы
        msg.attach(f"Application_{app_obj.id}.docx",
                   "application/vnd.openxmlformats-officedocument.wordprocessingml.document", doc_io.read())

        log_entry.recipient = responsible.email
        log_entry.subject = subject_str

        mail.send(msg)

        log_entry.status = 'Success'
        log_entry.server_response = "250 OK: Message accepted for delivery."
        print(f"INFO: Email для заявки #{application_id} успешно отправлен на {responsible.email}")

    except Exception as e:
        log_entry.status = 'Failed'
        log_entry.server_response = str(e)
        print(f"CRITICAL ERROR: Не удалось отправить email для заявки #{application_id}. Ошибка: {e}")

    finally:
        # Эта операция выполняется в контексте приложения, который создается
        # в фоновом потоке в routes.py
        db.session.add(log_entry)
        db.session.commit()
