"""Check ResponsiblePerson <-> User bindings v2"""
from app import create_app, db
from app.models import ResponsiblePerson, User, Application

app = create_app()
with app.app_context():
    print('=== RESPONSIBLE PERSONS ===')
    rps = ResponsiblePerson.query.order_by(ResponsiblePerson.id).all()
    for rp in rps:
        app_count = Application.query.filter_by(responsible_person_id=rp.id).count()
        print(f'  id={rp.id}, name="{rp.full_name}", email={rp.email}, gw_id={rp.gateway_user_id!r}, apps={app_count}')

    print()
    print('=== LOCAL USERS ===')
    users = User.query.order_by(User.id).all()
    for u in users:
        created_apps = Application.query.filter_by(creator_id=u.id).count()
        print(f'  id={u.id}, name="{u.username}", auth_user_id={u.auth_user_id!r}, role={u.role}, created_apps={created_apps}')

    print()
    print('=== BINDING CHECK: RP -> User (via gateway_user_id == auth_user_id) ===')
    bound = 0
    unbound = 0
    for rp in rps:
        if rp.gateway_user_id:
            matching_user = User.query.filter_by(auth_user_id=rp.gateway_user_id).first()
            if matching_user:
                print(f'  OK: RP "{rp.full_name}" (gw={rp.gateway_user_id}) -> User "{matching_user.username}"')
                bound += 1
            else:
                print(f'  WARN: RP "{rp.full_name}" (gw={rp.gateway_user_id}) -> NO matching User!')
                unbound += 1
        else:
            print(f'  MISSING: RP "{rp.full_name}" has gateway_user_id=NULL')
            unbound += 1
    print(f'\n  Summary: {bound} bound, {unbound} unbound (out of {len(rps)})')

    print()
    print('=== APPS WITHOUT RESPONSIBLE ===')
    no_rp = Application.query.filter(Application.responsible_person_id.is_(None)).count()
    total = Application.query.count()
    print(f'  {no_rp} / {total} apps have no responsible person')
