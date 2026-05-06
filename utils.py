from datetime import datetime, date
from flask import abort
import csv
import io

def safe_date(form_value):
    """Parse YYYY-MM-DD safely; return None on empty/invalid."""
    if not form_value:
        return None
    try:
        return datetime.strptime(form_value, '%Y-%m-%d').date()
    except ValueError:
        return None

def safe_float(form_value, default=0.0):
    """Parse float safely; return default on empty/invalid."""
    if not form_value:
        return default
    try:
        return float(form_value)
    except (ValueError, TypeError):
        return default

def safe_int(form_value, default=0):
    """Parse int safely; return default on empty/invalid."""
    if not form_value:
        return default
    try:
        return int(float(form_value))
    except (ValueError, TypeError):
        return default

def build_csv(rows, headers):
    """Build a CSV string from list-of-dicts + headers."""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=headers)
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row.get(k, '') for k in headers})
    return output.getvalue()

def paginate(query, page, per_page=25):
    """Simple pagination helper. Returns (items, total, pages)."""
    total = query.count()
    pages = (total + per_page - 1) // per_page
    items = query.limit(per_page).offset((page - 1) * per_page).all()
    return items, total, pages
