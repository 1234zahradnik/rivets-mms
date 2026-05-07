from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, abort, make_response, send_from_directory
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from models import db, Company, Machine, MachineHistory, WorkOrder, InventoryItem, InventoryTransaction, User, WOComment, Notification, PMSchedule
from datetime import datetime, date, timedelta
from werkzeug.utils import secure_filename
from utils import safe_date, safe_float, safe_int, build_csv, paginate
import json, os, re

ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.heic', '.webp'}

import config as _config

app = Flask(__name__)
env_name = os.environ.get('FLASK_ENV', 'default')
app.config.from_object(_config.config.get(env_name, _config.config['default']))
app.config.from_prefixed_env()

db.init_app(app)

UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to continue.'
login_manager.login_message_category = 'danger'

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


@app.context_processor
def inject_globals():
    unread = 0
    if current_user.is_authenticated:
        unread = Notification.query.filter_by(
            company_id=current_user.company_id,
            user_id=current_user.id,
            is_read=False
        ).count()
        # also count company-wide (user_id=None) notifications
        unread += Notification.query.filter_by(
            company_id=current_user.company_id,
            user_id=None,
            is_read=False
        ).count()
    return {'now': datetime.now(), 'today': date.today(), 'unread_notifications': unread}


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def cq(model):
    """Company-scoped query — always filters to current user's company."""
    return model.query.filter_by(company_id=current_user.company_id)


def cget(model, id):
    """Company-scoped get-or-404."""
    return cq(model).filter_by(id=id).first_or_404()


def require_manager():
    if not current_user.is_manager_or_above:
        abort(403)


def _slugify(text):
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')


def _next_wo_number():
    """Sequential WO per company: WO-2026-00001"""
    max_id = (db.session.query(db.func.max(WorkOrder.id))
              .filter_by(company_id=current_user.company_id).scalar()) or 0
    return f"WO-{datetime.now().year}-{max_id + 1:05d}"


def _notify(title, message='', link='', icon='🔔', user_id=None):
    """Create an in-app notification for the current user's company."""
    db.session.add(Notification(
        company_id=current_user.company_id,
        user_id=user_id,
        title=title,
        message=message,
        link=link,
        icon=icon
    ))


def _notify_managers(title, message='', link='', icon='🔔'):
    """Notify every admin/manager in the current company."""
    managers = cq(User).filter(User.role.in_(['admin', 'manager']), User.is_active == True).all()
    for m in managers:
        db.session.add(Notification(
            company_id=current_user.company_id,
            user_id=m.id,
            title=title,
            message=message,
            link=link,
            icon=icon
        ))


def _sync_machine_status(machine_id):
    if not machine_id:
        return
    machine = cget(Machine, machine_id)
    open_repair = cq(WorkOrder).filter(
        WorkOrder.machine_id == machine_id,
        WorkOrder.category.in_(['Corrective', 'Safety']),
        WorkOrder.status.in_(['In Progress', 'Assigned', 'Approved'])
    ).count()
    machine.status = 'Down' if open_repair > 0 else 'Active'


# ══════════════════════════════════════════════════════════════════════════════
# AUTH
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        email    = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user     = User.query.filter_by(email=email).first()
        if user and user.is_active and user.check_password(password):
            login_user(user, remember=request.form.get('remember') == 'on')
            return redirect(request.args.get('next') or url_for('dashboard'))
        flash('Invalid email or password.', 'danger')
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out.', 'success')
    return redirect(url_for('login'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        company_name = request.form.get('company_name', '').strip()
        email        = request.form.get('email', '').strip().lower()
        password     = request.form.get('password', '')
        username     = request.form.get('username', '').strip()

        if not all([company_name, email, password, username]):
            flash('All fields are required.', 'danger')
            return render_template('register.html')
        if len(password) < 6:
            flash('Password must be at least 6 characters.', 'danger')
            return render_template('register.html')

        slug = _slugify(company_name)
        if Company.query.filter_by(slug=slug).first():
            slug = f"{slug}-{Company.query.count() + 1}"

        company = Company(name=company_name, slug=slug)
        db.session.add(company)
        db.session.flush()

        user = User(
            company_id=company.id,
            username=username,
            display_name=username,
            email=email,
            role='admin'
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        login_user(user)
        flash(f"Welcome to Rivet's MMS, {username}! Your account is ready.", 'success')
        return redirect(url_for('dashboard'))
    return render_template('register.html')


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN — USER MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/admin/users')
@login_required
def admin_users():
    require_manager()
    users = cq(User).order_by(User.username).all()
    return render_template('admin_users.html', users=users)


@app.route('/admin/users/add', methods=['POST'])
@login_required
def admin_users_add():
    require_manager()
    email    = request.form.get('email', '').strip().lower()
    username = request.form.get('username', '').strip()
    role     = request.form.get('role', 'technician')
    password = request.form.get('password', '')

    if not all([email, username, password]):
        flash('Username, email, and password are required.', 'danger')
        return redirect(url_for('admin_users'))
    if User.query.filter_by(company_id=current_user.company_id, email=email).first():
        flash('A user with that email already exists.', 'danger')
        return redirect(url_for('admin_users'))

    user = User(
        company_id=current_user.company_id,
        username=username,
        display_name=username,
        email=email,
        role=role
    )
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    flash(f'User {username} added.', 'success')
    return redirect(url_for('admin_users'))


@app.route('/admin/users/<int:id>/toggle', methods=['POST'])
@login_required
def admin_users_toggle(id):
    require_manager()
    user = cget(User, id)
    if user.id == current_user.id:
        flash("Can't deactivate yourself.", 'danger')
    else:
        user.is_active = not user.is_active
        db.session.commit()
        flash(f'User {"activated" if user.is_active else "deactivated"}.', 'success')
    return redirect(url_for('admin_users'))


@app.route('/admin/users/<int:id>/reset-password', methods=['POST'])
@login_required
def admin_users_reset_password(id):
    require_manager()
    user   = cget(User, id)
    new_pw = request.form.get('password', '')
    if len(new_pw) < 6:
        flash('Password must be at least 6 characters.', 'danger')
    else:
        user.set_password(new_pw)
        db.session.commit()
        flash(f'Password reset for {user.username}.', 'success')
    return redirect(url_for('admin_users'))


# ══════════════════════════════════════════════════════════════════════════════
# DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/')
@login_required
def dashboard():
    _auto_generate_pm(current_user.company_id)
    active_statuses = ['Requested', 'Approved', 'Assigned', 'In Progress', 'On Hold']
    open_wos       = cq(WorkOrder).filter(WorkOrder.status.in_(active_statuses)).count()
    overdue        = cq(WorkOrder).filter(
        WorkOrder.due_date < date.today(),
        WorkOrder.status.notin_(['Completed', 'Cancelled'])
    ).count()
    low_stock      = cq(InventoryItem).filter(
        InventoryItem.quantity_on_hand <= InventoryItem.min_stock_level
    ).count()
    machines_down      = cq(Machine).filter_by(status='Down').count()
    machines_down_list = cq(Machine).filter_by(status='Down').order_by(Machine.name).all()

    emergency_wos = cq(WorkOrder).filter(
        WorkOrder.priority.in_(['Emergency', 'High']),
        WorkOrder.status.notin_(['Completed', 'Cancelled'])
    ).order_by(
        db.case((WorkOrder.priority == 'Emergency', 0), else_=1),
        WorkOrder.created_at
    ).limit(8).all()

    recent_wos = cq(WorkOrder).order_by(WorkOrder.created_at.desc()).limit(8).all()
    recent_history = (MachineHistory.query
                      .join(Machine, MachineHistory.machine_id == Machine.id)
                      .filter(Machine.company_id == current_user.company_id)
                      .order_by(MachineHistory.date.desc()).limit(6).all())

    upcoming_pm = cq(WorkOrder).filter(
        WorkOrder.category == 'Preventive',
        WorkOrder.status.notin_(['Completed', 'Cancelled']),
        WorkOrder.due_date.isnot(None),
        WorkOrder.due_date <= date.today() + timedelta(days=7)
    ).order_by(WorkOrder.due_date).limit(5).all()

    # "My Jobs" — WOs assigned to this user by name/username
    my_jobs = []
    if current_user.role == 'technician':
        name = current_user.display_name or current_user.username
        my_jobs = cq(WorkOrder).filter(
            WorkOrder.assigned_to.ilike(name),
            WorkOrder.status.in_(active_statuses)
        ).order_by(WorkOrder.created_at.desc()).limit(10).all()

    return render_template('dashboard.html',
                           open_wos=open_wos, overdue=overdue,
                           low_stock=low_stock, machines_down=machines_down,
                           machines_down_list=machines_down_list,
                           emergency_wos=emergency_wos,
                           recent_wos=recent_wos, recent_history=recent_history,
                           upcoming_pm=upcoming_pm, my_jobs=my_jobs)


# ══════════════════════════════════════════════════════════════════════════════
# MACHINES
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/machines')
@login_required
def machines_list():
    search = request.args.get('q', '').strip()
    status = request.args.get('status', '')
    page   = safe_int(request.args.get('page', 1), 1)

    query = cq(Machine)
    if search:
        like = f'%{search}%'
        query = query.filter(
            db.or_(Machine.name.ilike(like), Machine.asset_tag.ilike(like),
                   Machine.location.ilike(like), Machine.manufacturer.ilike(like))
        )
    if status:
        query = query.filter_by(status=status)

    machines, total, pages = paginate(query.order_by(Machine.name), page, app.config.get('PER_PAGE', 25))
    return render_template('machines.html', machines=machines, search=search, status=status,
                           page=page, pages=pages, total=total)


@app.route('/machines/add', methods=['GET', 'POST'])
@login_required
def machine_add():
    require_manager()
    if request.method == 'POST':
        m = Machine(
            company_id=current_user.company_id,
            name=request.form['name'],
            asset_tag=request.form['asset_tag'].strip().upper(),
            location=request.form.get('location', ''),
            manufacturer=request.form.get('manufacturer', ''),
            model_number=request.form.get('model_number', ''),
            serial_number=request.form.get('serial_number', ''),
            install_date=safe_date(request.form.get('install_date')),
            criticality=request.form.get('criticality', 'Medium'),
            notes=request.form.get('notes', '')
        )
        db.session.add(m)
        db.session.commit()
        flash(f'Machine {m.asset_tag} added.', 'success')
        return redirect(url_for('machine_detail', id=m.id))
    return render_template('machine_form.html', machine=None)


@app.route('/machines/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def machine_edit(id):
    require_manager()
    machine = cget(Machine, id)
    if request.method == 'POST':
        machine.name          = request.form['name']
        machine.asset_tag     = request.form['asset_tag'].strip().upper()
        machine.location      = request.form.get('location', '')
        machine.manufacturer  = request.form.get('manufacturer', '')
        machine.model_number  = request.form.get('model_number', '')
        machine.serial_number = request.form.get('serial_number', '')
        machine.install_date  = safe_date(request.form.get('install_date'))
        machine.criticality   = request.form.get('criticality', 'Medium')
        machine.notes         = request.form.get('notes', '')
        db.session.commit()
        flash('Machine updated.', 'success')
        return redirect(url_for('machine_detail', id=machine.id))
    return render_template('machine_form.html', machine=machine)


@app.route('/machines/<int:id>')
@login_required
def machine_detail(id):
    machine = cget(Machine, id)
    history = MachineHistory.query.filter_by(machine_id=id).order_by(MachineHistory.date.desc()).all()
    wos     = cq(WorkOrder).filter_by(machine_id=id).order_by(WorkOrder.created_at.desc()).all()
    return render_template('machine_detail.html', machine=machine, history=history, wos=wos)


@app.route('/machines/<int:id>/history/add', methods=['POST'])
@login_required
def machine_history_add(id):
    cget(Machine, id)
    h = MachineHistory(
        machine_id=id,
        event_type=request.form['event_type'],
        description=request.form['description'],
        technician=request.form.get('technician', '') or current_user.display_name,
        hours_spent=safe_float(request.form.get('hours_spent')),
        cost=safe_float(request.form.get('cost'))
    )
    db.session.add(h)
    db.session.commit()
    flash('History entry added.', 'success')
    return redirect(url_for('machine_detail', id=id))


@app.route('/machines/export')
@login_required
def machines_export():
    machines = cq(Machine).order_by(Machine.asset_tag).all()
    headers  = ['asset_tag', 'name', 'location', 'manufacturer', 'model_number',
                'serial_number', 'install_date', 'status', 'criticality', 'notes']
    rows = [{
        'asset_tag': m.asset_tag, 'name': m.name, 'location': m.location,
        'manufacturer': m.manufacturer, 'model_number': m.model_number,
        'serial_number': m.serial_number,
        'install_date': m.install_date.isoformat() if m.install_date else '',
        'status': m.status, 'criticality': m.criticality, 'notes': m.notes
    } for m in machines]
    resp = make_response(build_csv(rows, headers))
    resp.headers['Content-Type'] = 'text/csv'
    resp.headers['Content-Disposition'] = 'attachment; filename=machines.csv'
    return resp


# ══════════════════════════════════════════════════════════════════════════════
# WORK ORDERS
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/work-orders')
@login_required
def work_orders():
    status_filter   = request.args.get('status', '')
    priority_filter = request.args.get('priority', '')
    assigned_filter = request.args.get('assigned', '')
    search          = request.args.get('q', '').strip()
    page            = safe_int(request.args.get('page', 1), 1)

    query = cq(WorkOrder)
    if status_filter:
        query = query.filter_by(status=status_filter)
    if priority_filter:
        query = query.filter_by(priority=priority_filter)
    if assigned_filter:
        query = query.filter(WorkOrder.assigned_to.ilike(f'%{assigned_filter}%'))
    if search:
        like = f'%{search}%'
        query = query.filter(
            db.or_(WorkOrder.wo_number.ilike(like), WorkOrder.title.ilike(like),
                   WorkOrder.assigned_to.ilike(like))
        )

    wos, total, pages = paginate(query.order_by(WorkOrder.created_at.desc()), page, app.config.get('PER_PAGE', 25))
    return render_template('work_orders.html', wos=wos,
                           status_filter=status_filter, priority_filter=priority_filter,
                           assigned_filter=assigned_filter,
                           search=search, page=page, pages=pages, total=total)


@app.route('/work-orders/request', methods=['GET', 'POST'])
@login_required
def wo_request():
    if request.method == 'POST':
        wo = WorkOrder(
            company_id=current_user.company_id,
            wo_number='TMP',
            title=request.form['title'],
            description=request.form.get('description', ''),
            machine_id=safe_int(request.form.get('machine_id')) or None,
            requester_name=request.form.get('requester_name', '') or current_user.display_name,
            requester_email=request.form.get('requester_email', '') or current_user.email,
            priority=request.form.get('priority', 'Medium'),
            category=request.form.get('category', 'Corrective'),
            due_date=safe_date(request.form.get('due_date'))
        )
        db.session.add(wo)
        db.session.flush()
        wo.wo_number = _next_wo_number()
        f = request.files.get('photo')
        if f and f.filename:
            ext = os.path.splitext(f.filename)[1].lower()
            if ext in ALLOWED_EXTENSIONS:
                fname = secure_filename(f"{wo.wo_number}{ext}")
                f.save(os.path.join(app.config['UPLOAD_FOLDER'], fname))
                wo.attachment = fname
        # Emergency WO → immediately mark machine as Down
        if wo.priority == 'Emergency' and wo.machine_id:
            machine = cget(Machine, wo.machine_id)
            machine.status = 'Down'

        db.session.commit()

        # Notify managers about emergency or high-priority
        if wo.priority in ('Emergency', 'High'):
            _notify_managers(
                title=f"{'🚨 EMERGENCY' if wo.priority == 'Emergency' else '⚠️ High Priority'}: {wo.title}",
                message=f"Submitted by {wo.requester_name or current_user.display_name}",
                link=url_for('wo_detail', id=wo.id),
                icon='🚨' if wo.priority == 'Emergency' else '⚠️'
            )
            db.session.commit()

        flash(f'Work order {wo.wo_number} submitted.', 'success')
        return redirect(url_for('work_orders'))

    machines = cq(Machine).order_by(Machine.name).all()
    return render_template('wo_request.html', machines=machines)


@app.route('/work-orders/<int:id>')
@login_required
def wo_detail(id):
    wo        = cget(WorkOrder, id)
    inventory = cq(InventoryItem).filter_by(status='Active').order_by(InventoryItem.name).all()

    parts_used_detail = []
    if wo.parts_used:
        try:
            for part_id_str, qty in json.loads(wo.parts_used).items():
                item = db.session.get(InventoryItem, int(part_id_str))
                if item and item.company_id == current_user.company_id:
                    parts_used_detail.append({
                        'name': item.name, 'part_number': item.part_number,
                        'qty': qty, 'unit_cost': item.unit_cost,
                        'total': item.unit_cost * qty
                    })
        except (json.JSONDecodeError, ValueError):
            pass

    comments  = WOComment.query.filter_by(wo_id=id).order_by(WOComment.created_at).all()
    tech_users = cq(User).filter(User.is_active == True).order_by(User.display_name).all()
    return render_template('wo_detail.html', wo=wo,
                           inventory=inventory, parts_used_detail=parts_used_detail,
                           comments=comments, tech_users=tech_users)


@app.route('/work-orders/<int:id>/update', methods=['POST'])
@login_required
def wo_update(id):
    wo           = cget(WorkOrder, id)
    old_status   = wo.status
    old_assigned = wo.assigned_to

    wo.status          = request.form.get('status', wo.status)
    wo.assigned_to     = request.form.get('assigned_to', wo.assigned_to)
    wo.priority        = request.form.get('priority', wo.priority)
    wo.category        = request.form.get('category', wo.category)
    wo.estimated_hours = safe_float(request.form.get('estimated_hours'))
    wo.scheduled_date  = safe_date(request.form.get('scheduled_date'))

    if old_status != wo.status:
        if wo.status == 'In Progress' and not wo.started_at:
            wo.started_at = datetime.utcnow()
        if wo.status in ('Completed', 'Cancelled') and not wo.completed_at:
            wo.completed_at = datetime.utcnow()

    _sync_machine_status(wo.machine_id)
    db.session.commit()

    # Notify newly assigned technician if they have an account
    if wo.assigned_to and wo.assigned_to != old_assigned:
        tech = cq(User).filter(
            db.or_(User.display_name == wo.assigned_to, User.username == wo.assigned_to)
        ).first()
        if tech:
            _notify(
                title=f"You've been assigned: {wo.wo_number}",
                message=wo.title,
                link=url_for('wo_detail', id=wo.id),
                icon='📋',
                user_id=tech.id
            )
            db.session.commit()

    flash('Work order updated.', 'success')
    return redirect(url_for('wo_detail', id=id))


@app.route('/work-orders/<int:id>/close', methods=['POST'])
@login_required
def wo_close(id):
    wo = cget(WorkOrder, id)
    if wo.status == 'Completed':
        flash('Already closed.', 'warning')
        return redirect(url_for('wo_detail', id=id))

    wo.status           = 'Completed'
    wo.completed_at     = datetime.utcnow()
    wo.actual_hours     = safe_float(request.form.get('actual_hours'))
    wo.completion_notes = request.form.get('completion_notes', '')
    wo.resolution       = request.form.get('resolution', 'Fixed')
    wo.total_cost       = safe_float(request.form.get('total_cost'))

    if not wo.started_at:
        wo.started_at = wo.completed_at

    parts_data = {}
    for key, val in request.form.items():
        if key.startswith('part_qty_') and val:
            qty = safe_int(val)
            if qty > 0:
                part_id = int(key.replace('part_qty_', ''))
                item    = db.session.get(InventoryItem, part_id)
                if item and item.company_id == current_user.company_id and item.status == 'Active':
                    item.quantity_on_hand = max(0, item.quantity_on_hand - qty)
                    parts_data[str(part_id)] = qty
                    db.session.add(InventoryTransaction(
                        item_id=part_id,
                        transaction_type='Used',
                        quantity=-qty,
                        unit_cost=item.unit_cost,
                        reference_wo=wo.wo_number,
                        notes=f"Used on {wo.wo_number}",
                        performed_by=wo.assigned_to or current_user.display_name
                    ))

    wo.parts_used = json.dumps(parts_data) if parts_data else ''

    if wo.machine_id:
        db.session.add(MachineHistory(
            machine_id=wo.machine_id,
            event_type='Maintenance',
            description=f"WO {wo.wo_number}: {wo.title} — {wo.completion_notes}",
            technician=wo.assigned_to or current_user.display_name,
            hours_spent=wo.actual_hours,
            cost=wo.total_cost
        ))

    _sync_machine_status(wo.machine_id)
    db.session.commit()
    flash('Work order closed out.', 'success')
    return redirect(url_for('wo_detail', id=id))


@app.route('/work-orders/<int:id>/comment', methods=['POST'])
@login_required
def wo_comment(id):
    wo   = cget(WorkOrder, id)
    body = request.form.get('body', '').strip()
    if body:
        db.session.add(WOComment(
            wo_id=id,
            author=current_user.display_name or current_user.username,
            body=body
        ))
        db.session.commit()
        flash('Note added.', 'success')
    return redirect(url_for('wo_detail', id=id))


@app.route('/notifications')
@login_required
def notifications():
    notifs = Notification.query.filter(
        Notification.company_id == current_user.company_id,
        db.or_(Notification.user_id == current_user.id, Notification.user_id == None)
    ).order_by(Notification.created_at.desc()).limit(50).all()
    return render_template('notifications.html', notifs=notifs)


@app.route('/notifications/mark-read', methods=['POST'])
@login_required
def notifications_mark_read():
    Notification.query.filter(
        Notification.company_id == current_user.company_id,
        db.or_(Notification.user_id == current_user.id, Notification.user_id == None),
        Notification.is_read == False
    ).update({'is_read': True})
    db.session.commit()
    return redirect(request.referrer or url_for('notifications'))


@app.route('/work-orders/export')
@login_required
def work_orders_export():
    wos     = cq(WorkOrder).order_by(WorkOrder.created_at.desc()).all()
    headers = ['wo_number', 'title', 'machine', 'requester_name', 'priority',
               'status', 'category', 'assigned_to', 'created_at', 'due_date',
               'started_at', 'completed_at', 'actual_hours', 'total_cost', 'resolution']
    rows = [{
        'wo_number': w.wo_number, 'title': w.title,
        'machine': w.machine.name if w.machine else 'N/A',
        'requester_name': w.requester_name, 'priority': w.priority,
        'status': w.status, 'category': w.category, 'assigned_to': w.assigned_to,
        'created_at': w.created_at.isoformat() if w.created_at else '',
        'due_date': w.due_date.isoformat() if w.due_date else '',
        'started_at': w.started_at.isoformat() if w.started_at else '',
        'completed_at': w.completed_at.isoformat() if w.completed_at else '',
        'actual_hours': w.actual_hours, 'total_cost': w.total_cost, 'resolution': w.resolution
    } for w in wos]
    resp = make_response(build_csv(rows, headers))
    resp.headers['Content-Type'] = 'text/csv'
    resp.headers['Content-Disposition'] = 'attachment; filename=work_orders.csv'
    return resp


# ══════════════════════════════════════════════════════════════════════════════
# INVENTORY
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/inventory')
@login_required
def inventory_list():
    low_stock = request.args.get('low_stock') == '1'
    category  = request.args.get('category', '')
    search    = request.args.get('q', '').strip()
    page      = safe_int(request.args.get('page', 1), 1)

    query = cq(InventoryItem)
    if low_stock:
        query = query.filter(InventoryItem.quantity_on_hand <= InventoryItem.min_stock_level)
    if category:
        query = query.filter_by(category=category)
    if search:
        like = f'%{search}%'
        query = query.filter(
            db.or_(InventoryItem.name.ilike(like), InventoryItem.part_number.ilike(like),
                   InventoryItem.location.ilike(like))
        )

    items, total, pages = paginate(query.order_by(InventoryItem.name), page, app.config.get('PER_PAGE', 25))
    categories = cq(InventoryItem).with_entities(InventoryItem.category).distinct().all()
    return render_template('inventory.html', items=items,
                           categories=[c[0] for c in categories if c[0]],
                           low_stock=low_stock, category=category, search=search,
                           page=page, pages=pages, total=total)


@app.route('/inventory/add', methods=['GET', 'POST'])
@login_required
def inventory_add():
    require_manager()
    if request.method == 'POST':
        item = InventoryItem(
            company_id=current_user.company_id,
            part_number=request.form['part_number'].strip().upper(),
            name=request.form['name'],
            description=request.form.get('description', ''),
            category=request.form.get('category', ''),
            location=request.form.get('location', ''),
            quantity_on_hand=safe_int(request.form.get('quantity_on_hand')),
            min_stock_level=safe_int(request.form.get('min_stock_level')),
            reorder_point=safe_int(request.form.get('reorder_point')),
            unit_cost=safe_float(request.form.get('unit_cost')),
            supplier=request.form.get('supplier', ''),
            supplier_part_number=request.form.get('supplier_part_number', ''),
            unit_of_measure=request.form.get('unit_of_measure', 'EA'),
            notes=request.form.get('notes', ''),
            used_on=request.form.get('used_on', '')
        )
        db.session.add(item)
        db.session.flush()
        if item.quantity_on_hand > 0:
            db.session.add(InventoryTransaction(
                item_id=item.id,
                transaction_type='Received',
                quantity=item.quantity_on_hand,
                unit_cost=item.unit_cost,
                notes='Initial stock'
            ))
        db.session.commit()
        flash('Inventory item added.', 'success')
        return redirect(url_for('inventory_list'))
    return render_template('inventory_form.html', item=None)


@app.route('/inventory/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def inventory_edit(id):
    require_manager()
    item = cget(InventoryItem, id)
    if request.method == 'POST':
        old_qty               = item.quantity_on_hand
        item.part_number      = request.form['part_number'].strip().upper()
        item.name             = request.form['name']
        item.description      = request.form.get('description', '')
        item.category         = request.form.get('category', '')
        item.location         = request.form.get('location', '')
        item.min_stock_level  = safe_int(request.form.get('min_stock_level'))
        item.reorder_point    = safe_int(request.form.get('reorder_point'))
        item.unit_cost        = safe_float(request.form.get('unit_cost'))
        item.supplier         = request.form.get('supplier', '')
        item.supplier_part_number = request.form.get('supplier_part_number', '')
        item.unit_of_measure  = request.form.get('unit_of_measure', 'EA')
        item.status           = request.form.get('status', 'Active')
        item.notes            = request.form.get('notes', '')
        item.used_on          = request.form.get('used_on', '')

        new_qty = safe_int(request.form.get('quantity_on_hand'), old_qty)
        if new_qty != old_qty:
            item.quantity_on_hand = new_qty
            db.session.add(InventoryTransaction(
                item_id=item.id,
                transaction_type='Adjusted',
                quantity=new_qty - old_qty,
                unit_cost=item.unit_cost,
                notes='Adjusted via item edit'
            ))
        db.session.commit()
        flash('Inventory item updated.', 'success')
        return redirect(url_for('inventory_detail', id=item.id))
    return render_template('inventory_form.html', item=item)


@app.route('/inventory/<int:id>')
@login_required
def inventory_detail(id):
    item         = cget(InventoryItem, id)
    transactions = (InventoryTransaction.query.filter_by(item_id=id)
                    .order_by(InventoryTransaction.created_at.desc()).all())
    return render_template('inventory_detail.html', item=item, transactions=transactions)


@app.route('/inventory/<int:id>/adjust', methods=['POST'])
@login_required
def inventory_adjust(id):
    item    = cget(InventoryItem, id)
    new_qty = safe_int(request.form.get('quantity'))
    diff    = new_qty - item.quantity_on_hand
    item.quantity_on_hand = new_qty
    db.session.add(InventoryTransaction(
        item_id=id,
        transaction_type='Adjusted',
        quantity=diff,
        unit_cost=item.unit_cost,
        notes=request.form.get('notes', 'Manual adjustment'),
        performed_by=request.form.get('performed_by', '') or current_user.display_name
    ))
    db.session.commit()
    flash('Inventory adjusted.', 'success')
    return redirect(url_for('inventory_detail', id=id))


@app.route('/inventory/export')
@login_required
def inventory_export():
    items   = cq(InventoryItem).order_by(InventoryItem.part_number).all()
    headers = ['part_number', 'name', 'category', 'location', 'quantity_on_hand',
               'min_stock_level', 'reorder_point', 'unit_cost', 'supplier',
               'unit_of_measure', 'status', 'notes']
    rows = [{
        'part_number': i.part_number, 'name': i.name, 'category': i.category,
        'location': i.location, 'quantity_on_hand': i.quantity_on_hand,
        'min_stock_level': i.min_stock_level, 'reorder_point': i.reorder_point,
        'unit_cost': i.unit_cost, 'supplier': i.supplier,
        'unit_of_measure': i.unit_of_measure, 'status': i.status, 'notes': i.notes
    } for i in items]
    resp = make_response(build_csv(rows, headers))
    resp.headers['Content-Type'] = 'text/csv'
    resp.headers['Content-Disposition'] = 'attachment; filename=inventory.csv'
    return resp


# ══════════════════════════════════════════════════════════════════════════════
# PM SCHEDULES
# ══════════════════════════════════════════════════════════════════════════════

def _auto_generate_pm(company_id):
    """Generate due PM work orders for all active schedules. Call on dashboard load."""
    today = date.today()
    due = PMSchedule.query.filter_by(company_id=company_id, is_active=True).filter(
        db.or_(PMSchedule.next_due == None, PMSchedule.next_due <= today)
    ).all()
    for sched in due:
        # Check there isn't already an open PM WO for this schedule
        existing = WorkOrder.query.filter(
            WorkOrder.company_id == company_id,
            WorkOrder.category == 'Preventive',
            WorkOrder.title == sched.title,
            WorkOrder.status.notin_(['Completed', 'Cancelled'])
        ).first()
        if existing:
            continue
        # Create the WO
        max_id = (db.session.query(db.func.max(WorkOrder.id))
                  .filter_by(company_id=company_id).scalar()) or 0
        wo_num = f"WO-{today.year}-{max_id + 1:05d}"
        wo = WorkOrder(
            company_id=company_id,
            wo_number=wo_num,
            title=sched.title,
            description=sched.description,
            machine_id=sched.machine_id,
            category='Preventive',
            priority='Medium',
            estimated_hours=sched.estimated_hours,
            assigned_to=sched.assigned_to,
            due_date=sched.next_due or today
        )
        db.session.add(wo)
        # Advance next_due
        sched.last_generated_at = today
        sched.next_due = today + timedelta(days=sched.interval_days)
    if due:
        db.session.commit()


@app.route('/pm-schedules')
@login_required
def pm_list():
    require_manager()
    schedules = cq(PMSchedule).order_by(PMSchedule.next_due).all()
    return render_template('pm_schedules.html', schedules=schedules)


@app.route('/pm-schedules/add', methods=['GET', 'POST'])
@login_required
def pm_add():
    require_manager()
    if request.method == 'POST':
        interval = safe_int(request.form.get('interval_days'), 30)
        next_due = safe_date(request.form.get('next_due')) or date.today() + timedelta(days=interval)
        sched = PMSchedule(
            company_id=current_user.company_id,
            machine_id=safe_int(request.form.get('machine_id')) or None,
            title=request.form['title'],
            description=request.form.get('description', ''),
            interval_days=interval,
            estimated_hours=safe_float(request.form.get('estimated_hours')),
            assigned_to=request.form.get('assigned_to', ''),
            next_due=next_due
        )
        db.session.add(sched)
        db.session.commit()
        flash('PM schedule created.', 'success')
        return redirect(url_for('pm_list'))
    machines = cq(Machine).order_by(Machine.name).all()
    return render_template('pm_form.html', sched=None, machines=machines)


@app.route('/pm-schedules/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def pm_edit(id):
    require_manager()
    sched = cq(PMSchedule).filter_by(id=id).first_or_404()
    if request.method == 'POST':
        sched.machine_id      = safe_int(request.form.get('machine_id')) or None
        sched.title           = request.form['title']
        sched.description     = request.form.get('description', '')
        sched.interval_days   = safe_int(request.form.get('interval_days'), 30)
        sched.estimated_hours = safe_float(request.form.get('estimated_hours'))
        sched.assigned_to     = request.form.get('assigned_to', '')
        sched.next_due        = safe_date(request.form.get('next_due'))
        sched.is_active       = request.form.get('is_active') == 'on'
        db.session.commit()
        flash('PM schedule updated.', 'success')
        return redirect(url_for('pm_list'))
    machines = cq(Machine).order_by(Machine.name).all()
    return render_template('pm_form.html', sched=sched, machines=machines)


@app.route('/pm-schedules/<int:id>/delete', methods=['POST'])
@login_required
def pm_delete(id):
    require_manager()
    sched = cq(PMSchedule).filter_by(id=id).first_or_404()
    db.session.delete(sched)
    db.session.commit()
    flash('PM schedule deleted.', 'success')
    return redirect(url_for('pm_list'))


# ══════════════════════════════════════════════════════════════════════════════
# REPORTS
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/reports')
@login_required
def reports():
    cid = current_user.company_id

    wo_by_status = {}
    for row in (db.session.query(WorkOrder.status, db.func.count(WorkOrder.id))
                .filter_by(company_id=cid).group_by(WorkOrder.status).all()):
        wo_by_status[row[0]] = row[1]

    wo_by_category = {}
    for row in (db.session.query(WorkOrder.category, db.func.count(WorkOrder.id))
                .filter_by(company_id=cid).group_by(WorkOrder.category).all()):
        wo_by_category[row[0] or 'Uncategorized'] = row[1]

    mttr_data = []
    for m in cq(Machine).order_by(Machine.name).all():
        completed = cq(WorkOrder).filter(
            WorkOrder.machine_id == m.id,
            WorkOrder.status == 'Completed',
            WorkOrder.started_at.isnot(None),
            WorkOrder.completed_at.isnot(None),
            WorkOrder.category.in_(['Corrective', 'Safety'])
        ).all()
        if completed:
            total_hrs = sum((w.completed_at - w.started_at).total_seconds() / 3600 for w in completed)
            mttr_data.append({
                'machine': m.name, 'wo_count': len(completed),
                'avg_mttr_hrs': round(total_hrs / len(completed), 1),
                'total_hrs': round(total_hrs, 1)
            })
    mttr_data.sort(key=lambda x: x['avg_mttr_hrs'], reverse=True)

    top_machines = []
    for row in (db.session.query(Machine.name, db.func.count(WorkOrder.id).label('cnt'))
                .join(WorkOrder, WorkOrder.machine_id == Machine.id)
                .filter(Machine.company_id == cid)
                .group_by(Machine.id)
                .order_by(db.text('cnt DESC'))
                .limit(10).all()):
        top_machines.append({'machine': row[0], 'count': row[1]})

    inv_items         = cq(InventoryItem).filter_by(status='Active').all()
    inv_total_value   = sum(i.quantity_on_hand * i.unit_cost for i in inv_items)
    inv_low_stock_cnt = sum(1 for i in inv_items if i.quantity_on_hand <= i.min_stock_level)

    inv_by_category = {}
    for i in inv_items:
        cat = i.category or 'Uncategorized'
        inv_by_category.setdefault(cat, {'count': 0, 'value': 0.0})
        inv_by_category[cat]['count'] += 1
        inv_by_category[cat]['value'] += i.quantity_on_hand * i.unit_cost

    parts_spend = (db.session.query(
                       db.func.sum(InventoryTransaction.quantity * InventoryTransaction.unit_cost))
                   .join(InventoryItem, InventoryTransaction.item_id == InventoryItem.id)
                   .filter(InventoryItem.company_id == cid,
                           InventoryTransaction.transaction_type == 'Used').scalar()) or 0
    parts_spend = abs(parts_spend)

    pm_window = date.today() - timedelta(days=30)
    pm_total  = cq(WorkOrder).filter(
        WorkOrder.category == 'Preventive',
        WorkOrder.due_date >= pm_window,
        WorkOrder.due_date <= date.today()
    ).count()
    pm_done   = cq(WorkOrder).filter(
        WorkOrder.category == 'Preventive',
        WorkOrder.due_date >= pm_window,
        WorkOrder.due_date <= date.today(),
        WorkOrder.status == 'Completed'
    ).count()
    pm_compliance = round(pm_done / pm_total * 100) if pm_total else None

    open_wos_list = cq(WorkOrder).filter(WorkOrder.status.notin_(['Completed', 'Cancelled'])).all()
    age_buckets   = {'< 1 day': 0, '1–3 days': 0, '4–7 days': 0, '> 7 days': 0}
    for w in open_wos_list:
        if w.created_at:
            age = (datetime.utcnow() - w.created_at).days
            if age < 1:
                age_buckets['< 1 day'] += 1
            elif age <= 3:
                age_buckets['1–3 days'] += 1
            elif age <= 7:
                age_buckets['4–7 days'] += 1
            else:
                age_buckets['> 7 days'] += 1

    return render_template('reports.html',
                           wo_by_status=wo_by_status, wo_by_category=wo_by_category,
                           mttr_data=mttr_data, top_machines=top_machines,
                           inv_total_value=inv_total_value, inv_low_stock_cnt=inv_low_stock_cnt,
                           inv_by_category=inv_by_category, parts_spend=parts_spend,
                           pm_compliance=pm_compliance, pm_total=pm_total, pm_done=pm_done,
                           age_buckets=age_buckets,
                           total_wos=sum(wo_by_status.values()), total_inv_items=len(inv_items))


# ══════════════════════════════════════════════════════════════════════════════
# API (company-scoped)
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/api/machines')
@login_required
def api_machines():
    return jsonify([m.to_dict() for m in cq(Machine).all()])


@app.route('/api/work-orders')
@login_required
def api_work_orders():
    return jsonify([w.to_dict() for w in cq(WorkOrder).all()])


@app.route('/api/inventory')
@login_required
def api_inventory():
    return jsonify([i.to_dict() for i in cq(InventoryItem).all()])


# ══════════════════════════════════════════════════════════════════════════════
# ERROR HANDLERS
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/uploads/<path:filename>')
@login_required
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


@app.errorhandler(403)
def forbidden(e):
    return render_template('error.html', code=403, message="You don't have permission to do that."), 403


@app.errorhandler(404)
def not_found(e):
    return render_template('error.html', code=404, message="Page not found."), 404


@app.errorhandler(500)
def server_error(e):
    db.session.rollback()
    return render_template('error.html', code=500, message="Something went wrong."), 500


# ══════════════════════════════════════════════════════════════════════════════
# INIT
# ══════════════════════════════════════════════════════════════════════════════

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(
        debug=app.config.get('FLASK_DEBUG', False),
        host='0.0.0.0',
        port=int(os.environ.get('PORT', 5000))
    )
