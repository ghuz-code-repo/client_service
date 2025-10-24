# app/decorators.py
from functools import wraps
from flask import g, redirect, url_for, flash, abort
from flask_login import current_user
from app.auth_utils import is_admin as gateway_is_admin, has_permission, has_any_permission


def auth_required(permission=None, any_of=None):
    """
    Гибридный декоратор: проверяет Flask-Login ИЛИ Gateway auth.
    Используется вместо @login_required
    
    Args:
        permission (str, optional): Разрешение для проверки (например, 'client-service.admin.users')
        any_of (list, optional): Список разрешений, хотя бы одно из которых должно быть у пользователя
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Способ 1: Gateway authentication (приоритет)
            if g.get('auth_user_id'):
                # Проверяем разрешение если указано
                if permission and not has_permission(permission):
                    abort(403)
                # Проверяем список разрешений (любое из)
                if any_of and not has_any_permission(*any_of):
                    abort(403)
                return f(*args, **kwargs)
            
            # Способ 2: Flask-Login (fallback)
            if current_user.is_authenticated:
                # Для Flask-Login проверяем роль админа если нужно разрешение
                if (permission or any_of) and current_user.role != 'Админ':
                    abort(403)
                return f(*args, **kwargs)
            
            # Не авторизован никак
            flash('Требуется авторизация', 'warning')
            return redirect(url_for('auth.login'))
        
        return decorated_function
    
    # Поддержка вызова без скобок: @auth_required
    if callable(permission):
        f = permission
        permission = None
        return decorator(f)
    
    return decorator


def admin_required(f):
    """
    Гибридный декоратор: проверяет админские права через Gateway ИЛИ Flask-Login.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Способ 1: Gateway authentication (приоритет)
        if g.get('auth_user_id'):
            if not gateway_is_admin():
                abort(403)
            return f(*args, **kwargs)
        
        # Способ 2: Flask-Login (fallback)
        if current_user.is_authenticated:
            if current_user.role != 'Админ':
                abort(403)
            return f(*args, **kwargs)
        
        # Не авторизован
        flash('Требуется авторизация', 'warning')
        return redirect(url_for('auth.login'))
    
    return decorated_function


def permission_required(*required_roles_or_permission):
    """
    Гибридный декоратор для проверки разрешений/ролей.
    
    Поддерживает два режима:
    1. Старый API (Flask-Login): @permission_required('Админ', 'Менеджер ДКС')
       Проверяет, что user.role входит в список ролей
    
    2. Новый API (Gateway): @permission_required('client-service.applications.view')
       Проверяет наличие разрешения через Gateway
    
    Логика:
    - Если Gateway auth активна (g.auth_user_id): проверяет permission через has_permission()
    - Если Flask-Login (current_user): проверяет роль через user.role in required_roles
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Gateway authentication (приоритет)
            if g.get('auth_user_id'):
                # Для Gateway используем первый аргумент как permission
                # Если передано несколько - это старый код, проверяем админа
                if len(required_roles_or_permission) == 1:
                    permission = required_roles_or_permission[0]
                    if not has_permission(permission):
                        abort(403)
                else:
                    # Множественные роли - backward compatibility
                    # Проверяем, что пользователь админ или имеет одну из ролей
                    if not gateway_is_admin():
                        abort(403)
                return f(*args, **kwargs)
            
            # Flask-Login fallback
            if current_user.is_authenticated:
                # Админы проходят всегда
                if current_user.role == 'Админ':
                    return f(*args, **kwargs)
                
                # Проверка роли в списке разрешенных
                if current_user.role in required_roles_or_permission:
                    return f(*args, **kwargs)
                
                abort(403)
            
            # Не авторизован
            flash('Требуется авторизация', 'warning')
            return redirect(url_for('auth.login'))
        
        return decorated_function
    return decorator
