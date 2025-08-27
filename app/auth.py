# app/auth.py
from flask import render_template, flash, redirect, url_for, Blueprint, current_app, request
from flask_login import login_user, logout_user, login_required, current_user
from .extensions import db
from .models import User
from .decorators import admin_required
from werkzeug.security import generate_password_hash

auth = Blueprint('auth', __name__)


@auth.route('/client-service/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        remember = True if request.form.get('remember') else False

        user = User.query.filter_by(username=username).first()

        if not user or not user.check_password(password):
            flash('Неправильный логин или пароль.', 'danger')
            return redirect(url_for('auth.login'))

        login_user(user, remember=remember)
        return redirect(url_for('main.index'))

    return render_template('login.html')


@auth.route('/client-service/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))


@auth.route('/client-service/users')
@login_required
@admin_required
def users():
    all_users = User.query.order_by(User.username).all()
    roles = current_app.config['USER_ROLES']
    return render_template('users.html', users=all_users, roles=roles)


@auth.route('/client-service/users/create', methods=['POST'])
@login_required
@admin_required
def create_user():
    username = request.form.get('username')
    password = request.form.get('password')
    role = request.form.get('role')

    if not all([username, password, role]):
        flash('Все поля обязательны для заполнения.', 'danger')
        return redirect(url_for('auth.users'))

    if User.query.filter_by(username=username).first():
        flash('Пользователь с таким логином уже существует.', 'danger')
        return redirect(url_for('auth.users'))

    user = User(username=username, role=role)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    flash(f'Пользователь {username} успешно создан.', 'success')
    return redirect(url_for('auth.users'))


@auth.route('/client-service/users/<int:user_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('Вы не можете удалить сами себя.', 'danger')
        return redirect(url_for('auth.users'))

    # Предотвращаем удаление последнего админа
    if user.role == 'Админ' and User.query.filter_by(role='Админ').count() == 1:
        flash('Нельзя удалить последнего администратора.', 'danger')
        return redirect(url_for('auth.users'))

    db.session.delete(user)
    db.session.commit()
    flash(f'Пользователь {user.username} удален.', 'success')
    return redirect(url_for('auth.users'))
