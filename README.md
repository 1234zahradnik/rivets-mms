# E-Maintenance — Lightweight CMMS

A dead-simple Computerized Maintenance Management System (CMMS) built with **Flask + SQLite**. Designed for small manufacturing plants, maintenance shops, and anyone who needs to track machines, work orders, and inventory without fighting bloated enterprise software.

---

## What It Does

| Module | Features |
|--------|----------|
| **Dashboard** | Open WOs, overdue, low stock, machines down, upcoming PM, recent activity |
| **Machines** | Asset register with tags, locations, specs, install dates, criticality, full maintenance history, CSV export |
| **Work Orders** | Request → Approve → Assign → Work → Close out. Priority, status, hours, costs, parts auto-deduct, CSV export |
| **Inventory** | Spare parts with min-stock alerts, supplier info, unit costs, transaction audit trail, CSV export |
| **Reports** | WO summaries, MTTR by machine, top machines by WO count, inventory valuation by category, parts spend |

---

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run the app (development)
python app.py

# 3. Open in browser
http://localhost:5000
```

For production:
```bash
export FLASK_ENV=production
export SECRET_KEY="your-secret-key-here"
python app.py
```

---

## Data Model

### Machine
- `asset_tag` (unique, uppercase), `name`, `location`, `manufacturer`, `model_number`, `serial_number`
- `install_date`, `status` (Active/Down/Decommissioned), `criticality` (Low/Medium/High/Critical)
- Has many `WorkOrder`, `MachineHistory`
- **Auto status**: machine goes "Down" when open Corrective/Safety WOs exist, "Active" when none

### WorkOrder
- `wo_number` (auto: WO-YYYY-NNNNN), `title`, `description`, `machine_id`, `requester_name/email`
- `priority` (Low/Medium/High/Emergency), `status` (Requested→Approved→Assigned→In Progress→On Hold→Completed/Cancelled)
- `category` (Preventive/Corrective/Inspection/Safety/Project), `assigned_to`
- `scheduled_date`, `started_at`, `completed_at`, `due_date`
- `estimated_hours`, `actual_hours`, `completion_notes`, `resolution`, `parts_used` (JSON), `total_cost`
- **Auto machine history**: closing a WO on a machine auto-logs to that machine's history
- **Auto inventory deduct**: closing a WO deducts parts and creates transaction records

### MachineHistory
- Tracks every maintenance/repair/inspection/downtime event
- `event_type`, `description`, `technician`, `hours_spent`, `cost`

### InventoryItem
- `part_number` (unique, uppercase), `name`, `description`, `category`, `location`
- `quantity_on_hand`, `min_stock_level`, `reorder_point`, `unit_cost`
- `supplier`, `supplier_part_number`, `unit_of_measure` (EA/FT/GAL/LB/BOX)
- `status` (Active/Discontinued/On Order)
- **Low stock highlighting**: red row on list, badge on dashboard

### InventoryTransaction
- Every stock movement: Received, Used, Adjusted, Returned
- `reference_wo` links to WO, `reference_po` for future, `performed_by`
- Full audit trail — who, when, what, why

### User (placeholder)
- `username`, `display_name`, `email`, `role` (admin/supervisor/technician/requester)
- Ready for auth to be added

---

## Key Design Decisions

1. **SQLite for zero-config** — No separate DB server. Good for single-plant.
2. **Sequential WO numbering** — Human-readable, never collides.
3. **Parts auto-deduct on WO close** — No manual inventory juggling.
4. **Machine status auto-syncs** — Down if repair WOs are open, Active otherwise.
5. **Machine history auto-linked** — Closing a WO auto-creates a history entry.
6. **Low-stock alerts** — Red highlighting, dashboard counter.
7. **Search everywhere** — Machines, work orders, inventory all searchable.
8. **Pagination** — 25 items/page, scales to thousands without choking.
9. **CSV export** — All three main modules exportable for Excel/analysis.
10. **Responsive CSS** — Mobile-friendly, no JS framework.
11. **REST API** — `/api/machines`, `/api/work-orders`, `/api/inventory` for future integrations.
12. **Error handling** — 404/500 pages, safe number/date parsing, rollback on error.
13. **Config via env** — `SECRET_KEY`, `DATABASE_URL`, `FLASK_ENV`, `PORT` all overrideable.

---

## What Works Now

- [x] Full CRUD for machines, work orders, inventory
- [x] Search + pagination on all list views
- [x] CSV export on all list views
- [x] WO lifecycle with status transitions
- [x] Auto parts deduction + transaction logging on WO close
- [x] Auto machine history from WO close
- [x] Auto machine status sync (Down/Active)
- [x] Machine manual history entries
- [x] Inventory adjustment with audit trail
- [x] Low stock alerts
- [x] Dashboard with stats + upcoming PM
- [x] Reports: WO summary, MTTR, top machines, inventory valuation, parts spend
- [x] Responsive design
- [x] REST API skeleton
- [x] Error handlers (404/500)
- [x] Safe form parsing (no crashes on bad input)
- [x] Config via environment variables

---

## What's Missing / Could Add

- [ ] **Authentication & authorization** — Flask-Login or similar. Currently open.
- [ ] **File attachments** — Upload photos, manuals, schematics to machines and WOs.
- [ ] **Scheduled preventive maintenance** — Auto-generate WOs based on calendar or runtime hours.
- [ ] **Email notifications** — Notify requester/assignee on status changes.
- [ ] **Barcode/QR scanning** — Asset tags and part numbers via camera.
- [ ] **Multi-location** — Currently location is just a text field. Could be a hierarchy.
- [ ] **Purchase orders** — Request/receive parts against POs.
- [ ] **PostgreSQL option** — For multi-user deployments.
- [ ] **CSRF tokens** — Forms currently have no CSRF protection.
- [ ] **Soft deletes** — Currently hard-deletes. Add `deleted_at` columns.
- [ ] **User management UI** — Currently model exists but no UI.

---

## For Another AI Reviewer

This is a **MVP** intentionally kept simple. Before scaling, consider:

1. **Authentication** — Add Flask-Login. At minimum, enforce login on all routes.
2. **Validation** — More server-side validation (e.g., ensure asset_tag uniqueness at form level).
3. **Error handling** — Try/except around all DB writes, proper 404/500 pages.
4. **Testing** — Add pytest tests for routes and models.
5. **Deployment** — Use gunicorn + nginx. SQLite is fine for single-user but switch to PostgreSQL for teams.
6. **Security** — CSRF tokens, input sanitization, HTTPS in production, rate limiting.
7. **Data integrity** — Foreign key constraints with `ON DELETE` rules, soft deletes.

---

## Tech Stack

- **Backend**: Flask 3.x, Flask-SQLAlchemy 3.x
- **Database**: SQLite (auto-creates, env-overridable)
- **Frontend**: Pure HTML + CSS (no JS framework)
- **Templating**: Jinja2

---

Built by Rivet for Miles 🔧
