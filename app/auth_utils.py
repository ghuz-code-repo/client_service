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
    if g.get('is_admin') or 'client-service-admin' in roles:
        return 'Админ'
    
    # Менеджер
    if 'client-service-manager' in roles:
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
    Возвращает URL аватарки пользователя.
    
    Returns:
        str: URL аватарки или None
    """
    # Пытаемся получить из заголовков Gateway
    avatar = g.get('avatar_url', '')
    if avatar:
        return avatar
    
    # Fallback на Gravatar или дефолтную иконку
    email = g.get('email', '')
    if email:
        import hashlib
        hash_email = hashlib.md5(email.lower().encode('utf-8')).hexdigest()
        return f"https://www.gravatar.com/avatar/{hash_email}?d=identicon&s=40"
    
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
