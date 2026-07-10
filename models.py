from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

db = SQLAlchemy()


class Company(db.Model):
    __tablename__ = 'companies'
    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(100), nullable=False)
    slug       = db.Column(db.String(50), unique=True, nullable=False)
    is_active  = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    users = db.relationship('User', backref='company', lazy=True)


class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id            = db.Column(db.Integer, primary_key=True)
    company_id    = db.Column(db.Integer, db.ForeignKey('companies.id'), nullable=False)
    username      = db.Column(db.String(50), nullable=False)
    display_name  = db.Column(db.String(100), default='')
    email         = db.Column(db.String(100), nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role          = db.Column(db.String(20), default='technician')  # admin, manager, technician, requester
    is_active     = db.Column(db.Boolean, default=True)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('company_id', 'email', name='uq_user_email_company'),
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_manager_or_above(self):
        return self.role in ('admin', 'manager')

    def to_dict(self):
        return {
            'id': self.id, 'username': self.username,
            'display_name': self.display_name, 'email': self.email,
            'role': self.role, 'is_active': self.is_active,
            'created_at': self.created_at.isoformat()
        }


class Machine(db.Model):
    __tablename__ = 'machines'
    id            = db.Column(db.Integer, primary_key=True)
    company_id    = db.Column(db.Integer, db.ForeignKey('companies.id'), nullable=False)
    name          = db.Column(db.String(100), nullable=False)
    asset_tag     = db.Column(db.String(50), nullable=False)
    location      = db.Column(db.String(100), default='')
    manufacturer  = db.Column(db.String(100), default='')
    model_number  = db.Column(db.String(100), default='')
    serial_number = db.Column(db.String(100), default='')
    install_date  = db.Column(db.Date)
    status        = db.Column(db.String(20), default='Active')
    criticality   = db.Column(db.String(20), default='Medium')
    notes         = db.Column(db.Text, default='')
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('company_id', 'asset_tag', name='uq_machine_tag_company'),
    )

    work_orders = db.relationship('WorkOrder', backref='machine', lazy=True)
    history     = db.relationship('MachineHistory', backref='machine', lazy=True,
                                  order_by='MachineHistory.date.desc()')

    def to_dict(self):
        return {
            'id': self.id, 'name': self.name, 'asset_tag': self.asset_tag,
            'location': self.location, 'manufacturer': self.manufacturer,
            'model_number': self.model_number, 'serial_number': self.serial_number,
            'install_date': self.install_date.isoformat() if self.install_date else None,
            'status': self.status, 'criticality': self.criticality,
            'notes': self.notes, 'created_at': self.created_at.isoformat()
        }


class MachineHistory(db.Model):
    __tablename__ = 'machine_history'
    id          = db.Column(db.Integer, primary_key=True)
    machine_id  = db.Column(db.Integer, db.ForeignKey('machines.id'), nullable=False)
    date        = db.Column(db.DateTime, default=datetime.utcnow)
    event_type  = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text, nullable=False)
    technician  = db.Column(db.String(100), default='')
    hours_spent = db.Column(db.Float, default=0)
    parts_used  = db.Column(db.Text, default='')
    cost        = db.Column(db.Float, default=0)

    def to_dict(self):
        return {
            'id': self.id, 'machine_id': self.machine_id,
            'date': self.date.isoformat(), 'event_type': self.event_type,
            'description': self.description, 'technician': self.technician,
            'hours_spent': self.hours_spent, 'cost': self.cost
        }


class WorkOrder(db.Model):
    __tablename__ = 'work_orders'
    id               = db.Column(db.Integer, primary_key=True)
    company_id       = db.Column(db.Integer, db.ForeignKey('companies.id'), nullable=False)
    wo_number        = db.Column(db.String(20), nullable=False)
    title            = db.Column(db.String(200), nullable=False)
    description      = db.Column(db.Text, default='')
    machine_id       = db.Column(db.Integer, db.ForeignKey('machines.id'))
    requester_name   = db.Column(db.String(100), default='')
    requester_email  = db.Column(db.String(100), default='')
    priority         = db.Column(db.String(20), default='Medium')
    status           = db.Column(db.String(20), default='Requested')
    category         = db.Column(db.String(50), default='Corrective')
    assigned_to      = db.Column(db.String(100), default='')
    created_at       = db.Column(db.DateTime, default=datetime.utcnow)
    scheduled_date   = db.Column(db.Date)
    started_at       = db.Column(db.DateTime)
    completed_at     = db.Column(db.DateTime)
    due_date         = db.Column(db.Date)
    estimated_hours  = db.Column(db.Float, default=0)
    actual_hours     = db.Column(db.Float, default=0)
    completion_notes = db.Column(db.Text, default='')
    resolution       = db.Column(db.String(50), default='')
    parts_used       = db.Column(db.Text, default='')
    total_cost       = db.Column(db.Float, default=0)
    attachment       = db.Column(db.String(255), default='')

    __table_args__ = (
        db.UniqueConstraint('company_id', 'wo_number', name='uq_wo_number_company'),
    )

    comments = db.relationship('WOComment', backref='wo', lazy=True,
                               order_by='WOComment.created_at')

    def to_dict(self):
        return {
            'id': self.id, 'wo_number': self.wo_number, 'title': self.title,
            'description': self.description, 'machine_id': self.machine_id,
            'machine_name': self.machine.name if self.machine else 'N/A',
            'requester_name': self.requester_name, 'priority': self.priority,
            'status': self.status, 'category': self.category,
            'assigned_to': self.assigned_to,
            'created_at': self.created_at.isoformat(),
            'due_date': self.due_date.isoformat() if self.due_date else None,
            'actual_hours': self.actual_hours, 'total_cost': self.total_cost
        }


class InventoryItem(db.Model):
    __tablename__ = 'inventory'
    id                   = db.Column(db.Integer, primary_key=True)
    company_id           = db.Column(db.Integer, db.ForeignKey('companies.id'), nullable=False)
    part_number          = db.Column(db.String(50), nullable=False)
    name                 = db.Column(db.String(200), nullable=False)
    description          = db.Column(db.Text, default='')
    category             = db.Column(db.String(50), default='')
    location             = db.Column(db.String(100), default='')
    quantity_on_hand     = db.Column(db.Integer, default=0)
    min_stock_level      = db.Column(db.Integer, default=0)
    reorder_point        = db.Column(db.Integer, default=0)
    unit_cost            = db.Column(db.Float, default=0)
    supplier             = db.Column(db.String(100), default='')
    supplier_part_number = db.Column(db.String(50), default='')
    unit_of_measure      = db.Column(db.String(20), default='EA')
    status               = db.Column(db.String(20), default='Active')
    notes                = db.Column(db.Text, default='')
    used_on              = db.Column(db.Text, default='')
    created_at           = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at           = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('company_id', 'part_number', name='uq_inv_part_company'),
    )

    @property
    def is_low_stock(self):
        return self.quantity_on_hand <= self.min_stock_level

    @property
    def total_value(self):
        return self.quantity_on_hand * self.unit_cost

    def to_dict(self):
        return {
            'id': self.id, 'part_number': self.part_number, 'name': self.name,
            'category': self.category, 'location': self.location,
            'quantity_on_hand': self.quantity_on_hand,
            'min_stock_level': self.min_stock_level,
            'unit_cost': self.unit_cost, 'supplier': self.supplier,
            'status': self.status,
            'is_low_stock': self.quantity_on_hand <= self.min_stock_level,
            'total_value': self.total_value
        }


class PMSchedule(db.Model):
    """Recurring PM template — generates a WO automatically on interval."""
    __tablename__ = 'pm_schedules'
    id                = db.Column(db.Integer, primary_key=True)
    company_id        = db.Column(db.Integer, db.ForeignKey('companies.id'), nullable=False)
    machine_id        = db.Column(db.Integer, db.ForeignKey('machines.id'))
    title             = db.Column(db.String(200), nullable=False)
    description       = db.Column(db.Text, default='')
    interval_days     = db.Column(db.Integer, nullable=False, default=30)
    estimated_hours   = db.Column(db.Float, default=0)
    assigned_to       = db.Column(db.String(100), default='')
    last_generated_at = db.Column(db.Date)
    next_due          = db.Column(db.Date)
    is_active         = db.Column(db.Boolean, default=True)
    created_at        = db.Column(db.DateTime, default=datetime.utcnow)

    machine = db.relationship('Machine', backref='pm_schedules', lazy=True)


class WOComment(db.Model):
    __tablename__ = 'wo_comments'
    id         = db.Column(db.Integer, primary_key=True)
    wo_id      = db.Column(db.Integer, db.ForeignKey('work_orders.id'), nullable=False)
    author     = db.Column(db.String(100), nullable=False)
    body       = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class WOStatusLog(db.Model):
    __tablename__ = 'wo_status_log'
    id          = db.Column(db.Integer, primary_key=True)
    wo_id       = db.Column(db.Integer, db.ForeignKey('work_orders.id'), nullable=False)
    from_status = db.Column(db.String(20), default='')
    to_status   = db.Column(db.String(20), nullable=False)
    changed_by  = db.Column(db.String(100), default='')
    changed_at  = db.Column(db.DateTime, default=datetime.utcnow)


class WOAttachment(db.Model):
    __tablename__ = 'wo_attachments'
    id          = db.Column(db.Integer, primary_key=True)
    wo_id       = db.Column(db.Integer, db.ForeignKey('work_orders.id'), nullable=False)
    filename    = db.Column(db.String(255), nullable=False)
    label       = db.Column(db.String(100), default='')
    uploaded_by = db.Column(db.String(100), default='')
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)


class Notification(db.Model):
    __tablename__ = 'notifications'
    id         = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'), nullable=False)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id'))
    title      = db.Column(db.String(200), nullable=False)
    message    = db.Column(db.Text, default='')
    link       = db.Column(db.String(255), default='')
    icon       = db.Column(db.String(10), default='🔔')
    is_read    = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class InventoryTransaction(db.Model):
    __tablename__ = 'inventory_transactions'
    id               = db.Column(db.Integer, primary_key=True)
    item_id          = db.Column(db.Integer, db.ForeignKey('inventory.id'), nullable=False)
    transaction_type = db.Column(db.String(20), nullable=False)
    quantity         = db.Column(db.Integer, nullable=False)
    unit_cost        = db.Column(db.Float, default=0)
    reference_wo     = db.Column(db.String(50), default='')
    reference_po     = db.Column(db.String(50), default='')
    notes            = db.Column(db.Text, default='')
    performed_by     = db.Column(db.String(100), default='')
    created_at       = db.Column(db.DateTime, default=datetime.utcnow)

    item = db.relationship('InventoryItem', backref='transactions')

    def to_dict(self):
        return {
            'id': self.id, 'item_id': self.item_id,
            'item_name': self.item.name if self.item else 'N/A',
            'transaction_type': self.transaction_type,
            'quantity': self.quantity, 'unit_cost': self.unit_cost,
            'reference_wo': self.reference_wo, 'notes': self.notes,
            'performed_by': self.performed_by,
            'created_at': self.created_at.isoformat()
        }


class Vendor(db.Model):
    __tablename__ = 'vendors'
    id           = db.Column(db.Integer, primary_key=True)
    company_id   = db.Column(db.Integer, db.ForeignKey('companies.id'), nullable=False)
    name         = db.Column(db.String(200), nullable=False)
    contact_name = db.Column(db.String(100), default='')
    email        = db.Column(db.String(100), default='')
    phone        = db.Column(db.String(50), default='')
    address      = db.Column(db.Text, default='')
    terms        = db.Column(db.String(50), default='Net 30')
    is_active    = db.Column(db.Boolean, default=True)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('company_id', 'name', name='uq_vendor_name_company'),
    )

    purchase_orders = db.relationship('PurchaseOrder', backref='vendor', lazy=True)

    def to_dict(self):
        return {
            'id': self.id, 'name': self.name,
            'contact_name': self.contact_name, 'email': self.email,
            'phone': self.phone, 'address': self.address,
            'terms': self.terms, 'is_active': self.is_active,
            'created_at': self.created_at.isoformat()
        }


class PurchaseOrder(db.Model):
    __tablename__ = 'purchase_orders'
    id            = db.Column(db.Integer, primary_key=True)
    company_id    = db.Column(db.Integer, db.ForeignKey('companies.id'), nullable=False)
    po_number     = db.Column(db.String(20), nullable=False)
    vendor_id     = db.Column(db.Integer, db.ForeignKey('vendors.id'), nullable=False)
    status        = db.Column(db.String(20), default='Draft')
    created_by    = db.Column(db.String(100), default='')
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    order_date    = db.Column(db.Date)
    expected_date = db.Column(db.Date)
    received_date = db.Column(db.Date)
    shipping_cost = db.Column(db.Float, default=0)
    tax_amount    = db.Column(db.Float, default=0)
    notes         = db.Column(db.Text, default='')
    linked_wo     = db.Column(db.Integer, db.ForeignKey('work_orders.id'), nullable=True)

    __table_args__ = (
        db.UniqueConstraint('company_id', 'po_number', name='uq_po_number_company'),
    )

    line_items = db.relationship('POLineItem', backref='po', lazy=True,
                                 order_by='POLineItem.line_number',
                                 cascade='all, delete-orphan')

    @property
    def subtotal(self):
        return sum(li.total for li in self.line_items)

    @property
    def total(self):
        return self.subtotal + (self.shipping_cost or 0) + (self.tax_amount or 0)

    def to_dict(self):
        return {
            'id': self.id, 'po_number': self.po_number,
            'vendor_id': self.vendor_id,
            'vendor_name': self.vendor.name if self.vendor else 'N/A',
            'status': self.status,
            'created_by': self.created_by,
            'created_at': self.created_at.isoformat(),
            'order_date': self.order_date.isoformat() if self.order_date else None,
            'expected_date': self.expected_date.isoformat() if self.expected_date else None,
            'received_date': self.received_date.isoformat() if self.received_date else None,
            'shipping_cost': self.shipping_cost,
            'tax_amount': self.tax_amount,
            'subtotal': self.subtotal,
            'total': self.total,
            'line_item_count': len(self.line_items),
            'notes': self.notes,
            'linked_wo': self.linked_wo
        }


class POLineItem(db.Model):
    __tablename__ = 'po_line_items'
    id                = db.Column(db.Integer, primary_key=True)
    po_id             = db.Column(db.Integer, db.ForeignKey('purchase_orders.id'), nullable=False)
    line_number       = db.Column(db.Integer, nullable=False)
    inventory_item_id = db.Column(db.Integer, db.ForeignKey('inventory.id'), nullable=True)
    part_number       = db.Column(db.String(50), default='')
    description       = db.Column(db.String(200), default='')
    quantity_ordered  = db.Column(db.Integer, default=0)
    quantity_received = db.Column(db.Integer, default=0)
    unit_cost         = db.Column(db.Float, default=0)

    inventory_item = db.relationship('InventoryItem', backref='po_line_items', lazy=True)

    @property
    def total(self):
        return (self.quantity_ordered or 0) * (self.unit_cost or 0)

    def to_dict(self):
        return {
            'id': self.id, 'po_id': self.po_id,
            'line_number': self.line_number,
            'inventory_item_id': self.inventory_item_id,
            'part_number': self.part_number,
            'description': self.description,
            'quantity_ordered': self.quantity_ordered,
            'quantity_received': self.quantity_received,
            'unit_cost': self.unit_cost,
            'total': self.total
        }
