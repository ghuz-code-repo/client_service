# app/notification_client.py
"""
Клиент для работы с централизованным notification-service
"""

import os
import requests
import base64
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class NotificationServiceClient:
    """Клиент для отправки уведомлений через notification-service"""
    
    def __init__(self):
        self.base_url = os.getenv('NOTIFICATION_SERVICE_URL', 'http://notification-service:80')
        self.timeout = 10
    
    def send_email(self, recipient: str, subject: str, content: str, 
                   attachment_filename: Optional[str] = None,
                   attachment_content: Optional[bytes] = None) -> dict:
        """
        Отправляет email через notification-service
        
        Args:
            recipient: Email получателя
            subject: Тема письма
            content: Текст письма
            attachment_filename: Имя файла вложения (опционально)
            attachment_content: Содержимое файла в байтах (опционально)
            
        Returns:
            dict: Ответ от notification-service
            
        Raises:
            requests.RequestException: При ошибке отправки
        """
        try:
            # Формируем тело письма
            email_body = content
            
            # Формируем запрос
            payload = {
                "type": "email",
                "recipient": recipient,
                "subject": subject,
                "content": email_body
            }
            
            # Добавляем вложение если есть
            if attachment_filename and attachment_content:
                # Кодируем вложение в base64
                attachment_base64 = base64.b64encode(attachment_content).decode('utf-8')
                payload["attachment_filename"] = attachment_filename
                payload["attachment_content"] = attachment_base64
                logger.info(f"Добавлено вложение: {attachment_filename} ({len(attachment_content)} bytes)")
            
            logger.info(f"Отправка email через notification-service: {recipient}, тема: {subject}")
            
            # Отправляем запрос
            response = requests.post(
                f"{self.base_url}/api/v1/notifications",
                json=payload,
                timeout=self.timeout
            )
            
            response.raise_for_status()
            result = response.json()
            
            logger.info(f"Email успешно отправлен. ID уведомления: {result.get('id')}")
            return result
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Ошибка при отправке email через notification-service: {e}")
            raise
    
    def send_email_batch(self, notifications: list) -> dict:
        """
        Отправляет батч уведомлений
        
        Args:
            notifications: Список уведомлений в формате:
                [
                    {
                        "type": "email",
                        "recipient": "user@example.com",
                        "subject": "Тема",
                        "content": "Текст"
                    },
                    ...
                ]
                
        Returns:
            dict: Ответ от notification-service с информацией о батче
        """
        try:
            payload = {
                "notifications": notifications
            }
            
            logger.info(f"Отправка батча из {len(notifications)} уведомлений")
            
            response = requests.post(
                f"{self.base_url}/api/v1/notifications/batch",
                json=payload,
                timeout=self.timeout
            )
            
            response.raise_for_status()
            result = response.json()
            
            logger.info(f"Батч уведомлений отправлен. Batch ID: {result.get('batch_id')}")
            return result
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Ошибка при отправке батча уведомлений: {e}")
            raise
    
    def get_notification_status(self, notification_id: int) -> dict:
        """
        Получает статус уведомления
        
        Args:
            notification_id: ID уведомления
            
        Returns:
            dict: Информация о статусе уведомления
        """
        try:
            response = requests.get(
                f"{self.base_url}/api/v1/notifications/{notification_id}",
                timeout=self.timeout
            )
            
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Ошибка при получении статуса уведомления {notification_id}: {e}")
            raise


# Глобальный экземпляр клиента
notification_client = NotificationServiceClient()
