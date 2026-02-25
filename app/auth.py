# app/auth.py
from flask import redirect, Blueprint
from .decorators import auth_required

auth = Blueprint('auth', __name__)


@auth.route('/logout')
@auth_required
def logout():
    """
    Выход из системы.
    Перенаправляем на главную страницу Gateway для полного выхода.
    """
    return redirect('/')
