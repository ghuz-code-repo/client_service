"""
Утилиты для работы с централизованной авторизацией через gateway
"""

from flask import g
from app.models import User
from app.extensions import db
import logging

logger = logging.getLogger(__name__)


def get_current_user_from_gateway():
    """
    Получает текущего пользователя из заголовков gateway.
    Создает или обновляет локальную запись в БД.
    
    Returns:
        User: Объект пользователя или None
    """
    # Проверяем наличие данных от gateway
    if not g.get('auth_user_id') or not g.get('username'):
        logger.debug("No gateway headers found")
        return None
    
    try:
        # Поиск по auth_user_id (приоритет)
        user = User.query.filter_by(auth_user_id=g.auth_user_id).first()
        
        # Fallback на username
        if not user and g.username:
            user = User.query.filter_by(username=g.username).first()
        
        # Создание нового пользователя
        if not user:
            logger.info(f"Creating new user from gateway: {g.username}")
            user = User(
                auth_user_id=g.auth_user_id,
                username=g.username,
                role=_determine_role_from_permissions()
            )
            # НЕ устанавливаем password_hash для gateway пользователей
            db.session.add(user)
            db.session.commit()
            logger.info(f"User created: {user.username} (id={user.id})")
        
        # Обновление auth_user_id если его не было
        if user and not user.auth_user_id and g.auth_user_id:
            logger.info(f"Updating auth_user_id for user {user.username}")
            user.auth_user_id = g.auth_user_id
            db.session.commit()
        
        # Обновление роли на основе разрешений
        new_role = _determine_role_from_permissions()
        if user.role != new_role:
            logger.info(f"Updating role for user {user.username}: {user.role} → {new_role}")
            user.role = new_role
            db.session.commit()
        
        return user
        
    except Exception as e:
        logger.error(f"Error getting user from gateway: {e}", exc_info=True)
        db.session.rollback()
        return None


def _determine_role_from_permissions():
    """
    Определяет локальную роль на основе разрешений от gateway.
    Используется для обратной совместимости с бизнес-логикой.
    
    Returns:
        str: Название роли
    """
    permissions = g.get('service_permissions', [])
    roles = g.get('service_roles', [])
    
    # Системный админ или админ сервиса
    # Проверяем как полное имя роли 'client-service-admin', так и короткое 'admin'
    if g.get('is_admin') or 'client-service-admin' in roles or 'admin' in roles:
        return 'Админ'
    
    # Менеджер
    if 'client-service-manager' in roles or 'manager' in roles:
        return 'Менеджер ДКС'
    
    # По разрешениям
    if 'client-service.applications.assign' in permissions:
        return 'Менеджер ДКС'
    
    if 'client-service.applications.edit' in permissions:
        return 'Специалист КЦ'
    
    # По умолчанию
    return 'Специалист КЦ'


def has_permission(permission_name):
    """
    Проверяет наличие разрешения у текущего пользователя.
    
    Args:
        permission_name (str): Название разрешения
        
    Returns:
        bool: True если разрешение есть
    """
    permissions = g.get('service_permissions', [])
    return permission_name in permissions


def has_any_permission(*permission_names):
    """
    Проверяет наличие хотя бы одного из указанных разрешений у текущего пользователя.
    
    Args:
        *permission_names: Названия разрешений для проверки
        
    Returns:
        bool: True если есть хотя бы одно из разрешений
    """
    permissions = g.get('service_permissions', [])
    return any(perm in permissions for perm in permission_names)



def has_any_permission(permission_list):
    """
    Проверяет наличие хотя бы одного разрешения из списка.
    
    Args:
        permission_list (list): Список разрешений
        
    Returns:
        bool: True если есть хотя бы одно разрешение
    """
    permissions = g.get('service_permissions', [])
    return any(perm in permissions for perm in permission_list)


def is_admin():
    """
    Проверяет, является ли пользователь администратором.
    
    Returns:
        bool: True если администратор
    """
    return g.get('is_admin', False) or 'client-service-admin' in g.get('service_roles', [])


def is_authenticated():
    """
    Проверяет, аутентифицирован ли пользователь через Gateway.
    Используется в шаблонах вместо current_user.is_authenticated.
    
    Returns:
        bool: True если пользователь аутентифицирован через Gateway
    """
    return bool(g.get('auth_user_id') and g.get('username'))


def get_current_username():
    """
    Возвращает имя текущего пользователя из Gateway.
    
    Returns:
        str: Имя пользователя или None
    """
    return g.get('username')


def get_current_user_id():
    """
    Возвращает ID текущего пользователя (работает с Gateway и Flask-Login).
    Используйте эту функцию вместо current_user.id для совместимости.
    
    Returns:
        str: Gateway user ID (MongoDB ObjectID) или None
    """
    # Приоритет: Gateway authentication
    if g.get('auth_user_id'):
        return g.auth_user_id
    
    # Fallback: Flask-Login (для старых сессий)
    from flask_login import current_user
    if current_user.is_authenticated:
        return current_user.auth_user_id or str(current_user.id)
    
    return None


def get_current_full_name():
    """
    Возвращает полное имя текущего пользователя из Gateway.
    
    Returns:
        str: Полное имя пользователя или username если не установлено
    """
    full_name = g.get('full_name', '')
    if full_name:
        return full_name
    return g.get('username', '')


def get_user_avatar_url():
    """
    Возвращает URL аватарки пользователя из Gateway.
    
    Returns:
        str: URL аватарки или None (если нет аватара, показываем иконку)
    """
    # Получаем URL аватара из заголовка Gateway
    avatar = g.get('avatar_url', '')
    if avatar:
        return avatar
    
    # Если аватара нет, возвращаем None - шаблон покажет иконку
    return None


def has_role(*role_names):
    """
    Проверяет наличие одной из указанных ролей у текущего пользователя.
    Для обратной совместимости с current_user.has_role().
    
    Args:
        *role_names: Названия ролей для проверки
        
    Returns:
        bool: True если пользователь имеет хотя бы одну из указанных ролей
    """
    # Проверяем системного админа
    if g.get('is_admin', False):
        return True
    
    # Определяем роль пользователя на основе разрешений
    current_role = _determine_role_from_permissions()
    
    # Проверяем совпадение с любой из переданных ролей
    return current_role in role_names


def get_gateway_users():
    """
    Получает список пользователей client-service из Gateway API.
    Возвращает только пользователей, у которых есть роли в этом сервисе.
    
    Returns:
        list: Список пользователей в формате [{'id': '...', 'username': '...', 'full_name': '...', 'email': '...'}]
    """
    import requests
    import os
    
    try:
        # URL Gateway API для получения пользователей конкретного сервиса
        gateway_url = os.getenv('AUTH_SERVICE_URL', 'http://auth-service:80')
        service_key = 'client-service'
        api_url = f"{gateway_url}/api/services/{service_key}/users"
        
        logger.debug(f"Fetching users for service '{service_key}' from Gateway: {api_url}")
        
        response = requests.get(api_url, timeout=5)
        
        if response.status_code == 200:
            users_data = response.json()
            
            # Преобразуем в удобный формат
            users = []
            for user in users_data:
                # Gateway возвращает поле 'id' (не '_id')
                user_id = user.get('id', user.get('_id', ''))
                
                # Полное имя уже есть в ответе Gateway
                full_name = user.get('full_name', '')
                if not full_name:
                    # Fallback: собираем из частей
                    parts = []
                    if user.get('last_name'):
                        parts.append(user['last_name'])
                    if user.get('first_name'):
                        parts.append(user['first_name'])
                    if user.get('middle_name'):
                        parts.append(user['middle_name'])
                    full_name = ' '.join(parts) if parts else user.get('username', '')
                
                users.append({
                    'id': user_id,
                    'username': user.get('username', ''),
                    'full_name': full_name,
                    'email': user.get('email', ''),
                    'role': user.get('role', 'user')
                })
            
            logger.info(f"Retrieved {len(users)} users for service '{service_key}' from Gateway")
            return users
        else:
            logger.error(f"Failed to get users from Gateway: {response.status_code}")
            return []
            
    except Exception as e:
        logger.error(f"Error getting users from Gateway: {e}")
        return []
