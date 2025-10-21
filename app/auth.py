# app/auth.py
from flask import redirect, url_for, Blueprint
from flask_login import logout_user
from .decorators import auth_required

auth = Blueprint('auth', __name__)


@auth.route('/logout')
@auth_required
def logout():
    """
    Выход из системы.
    Примечание: Аутентификация теперь полностью управляется через Gateway.
    Управление пользователями происходит в Gateway auth-service.
    """
    logout_user()
    # Перенаправляем на главную страницу Gateway для полного выхода
    return redirect('/')
