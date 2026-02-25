# app/decorators.py
from functools import wraps
from flask import g, abort
from app.auth_utils import is_admin as gateway_is_admin, has_permission, has_any_permission


def auth_required(permission=None, any_of=None):
    """
    Декоратор: проверяет аутентификацию через Gateway.
    
    Args:
        permission (str, optional): Разрешение для проверки (например, 'client-service.admin.users')
        any_of (list, optional): Список разрешений, хотя бы одно из которых должно быть у пользователя
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not g.get('auth_user_id'):
                abort(401)
            
            # Проверяем разрешение если указано
            if permission and not has_permission(permission):
                abort(403)
            # Проверяем список разрешений (любое из)
            if any_of and not has_any_permission(*any_of):
                abort(403)
            
            return f(*args, **kwargs)
        
        return decorated_function
    
    # Поддержка вызова без скобок: @auth_required
    if callable(permission):
        f = permission
        permission = None
        return decorator(f)
    
    return decorator


def admin_required(f):
    """
    Декоратор: проверяет админские права через Gateway.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not g.get('auth_user_id'):
            abort(401)
        if not gateway_is_admin():
            abort(403)
        return f(*args, **kwargs)
    
    return decorated_function


def permission_required(*required_permissions):
    """
    Декоратор для проверки разрешений через Gateway.
    
    @permission_required('client-service.applications.view')
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not g.get('auth_user_id'):
                abort(401)
            
            # Админы проходят всегда
            if gateway_is_admin():
                return f(*args, **kwargs)
            
            # Проверяем хотя бы одно из указанных разрешений
            if not has_any_permission(*required_permissions):
                abort(403)
            
            return f(*args, **kwargs)
        
        return decorated_function
    return decorator
