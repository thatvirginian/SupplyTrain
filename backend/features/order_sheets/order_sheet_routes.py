# =============================================================================
# backend/features/order_sheets/order_sheet_routes.py
# =============================================================================
# Order Sheets (store side): create/open a sheet, enter counts, save drafts, PDF, delete, and SUBMIT.
# Submitting creates the purchase orders and the inventory record.
#
# Endpoints in this file:
#   GET     /api/sheet-submissions                                    list_sheet_submissions
#   POST    /api/sheet-submissions                                    create_sheet_submission
#   GET     /api/sheet-submissions/<int:submission_id>                get_sheet_submission
#   GET     /api/sheet-submissions/<int:submission_id>/pdf            sheet_submission_pdf
#   PUT     /api/sheet-submissions/<int:submission_id>                save_draft_entries
#   DELETE  /api/sheet-submissions/<int:submission_id>                delete_sheet_submission
#   POST    /api/sheet-submissions/<int:submission_id>/toggle-active  toggle_submission_active
#   POST    /api/sheet-submissions/<int:submission_id>/submit         submit_sheet
# =============================================================================

from flask import Blueprint, jsonify, request, g
from sqlalchemy import text
import logging
from datetime import date, timedelta

from core.auth import (
    admin_required, store_required, _get_user_location,
)
from core.database import get_engine
from features.inventory.inventory_count_service import (
    adopt_day_counts, copy_sheet_entries, refresh_day_counts,
)

logger = logging.getLogger(__name__)

bp = Blueprint('order_sheet_routes', __name__, url_prefix='/api')


# =============================================================================
# Sheet Submissions — list / create
# =============================================================================

@bp.route('/sheet-submissions', methods=['GET'])
@store_required
def list_sheet_submissions():
    """
    List submissions. Admin sees all or filtered by location.
    Staff sees only their location.
    """
    roles       = g.user.get('roles', [])
    is_admin    = 'admin' in roles
    location_id = request.args.get('location_id')
    status      = request.args.get('status')
    template_id = request.args.get('template_id', type=int)
    show_inactive = request.args.get('show_inactive', 'false').lower() == 'true'
    page        = request.args.get('page', 1, type=int)
    per_page    = request.args.get('per_page', 20, type=int)
    offset      = (page - 1) * per_page

    with get_engine().connect() as conn:
        if not is_admin:
            location_id = _get_user_location(conn)

    filters = ['ss.active = TRUE'] if not show_inactive else []
    params  = {'limit': per_page, 'offset': offset}

    if location_id:
        filters.append('ss.location_id = :location_id')
        params['location_id'] = location_id
    if status:
        filters.append('ss.status = :status')
        params['status'] = status
    if template_id:
        filters.append('ss.template_id = :template_id')
        params['template_id'] = template_id

    where = ('WHERE ' + ' AND '.join(filters)) if filters else ''

    with get_engine().connect() as conn:
        total = conn.execute(text(f"""
            SELECT COUNT(*) FROM sheet_submissions ss {where}
        """), params).scalar()

        rows = conn.execute(text(f"""
            SELECT
                ss.id, ss.template_id, ss.location_id,
                ss.count_date, ss.status,
                ss.submitted_by, ss.submitted_at,
                ss.notes, ss.created_at,
                st.name AS template_name,
                l.location_name,
                COUNT(se.id) AS entry_count
            FROM sheet_submissions ss
            JOIN sheet_templates st ON ss.template_id = st.id
            LEFT JOIN locations l   ON l.store_guid::text = ss.location_id
            LEFT JOIN sheet_entries se ON se.submission_id = ss.id
            {where}
            GROUP BY ss.id, st.name, l.location_name
            ORDER BY ss.count_date DESC, ss.created_at DESC
            LIMIT :limit OFFSET :offset
        """), params).mappings().all()

    return jsonify({
        'total':       total,
        'page':        page,
        'per_page':    per_page,
        'pages':       max(1, (total + per_page - 1) // per_page),
        'submissions': [dict(r) for r in rows],
    })


@bp.route('/sheet-submissions', methods=['POST'])
@store_required
def create_sheet_submission():
    """
    Open a new sheet submission.
    If a draft already exists for this template/location/date, return it.
    """
    data        = request.get_json(force=True)
    template_id = data.get('template_id')
    location_id = data.get('location_id')
    count_date  = data.get('count_date', str(date.today()))

    if not template_id:
        return jsonify({'error': 'template_id is required'}), 400

    roles    = g.user.get('roles', [])
    is_admin = 'admin' in roles

    with get_engine().connect() as conn:
        if not is_admin or not location_id:
            location_id = _get_user_location(conn)

    if not location_id:
        return jsonify({'error': 'Could not determine location'}), 400

    try:
        with get_engine().begin() as conn:
            # Check for existing draft
            existing = conn.execute(text("""
                SELECT id FROM sheet_submissions
                WHERE template_id  = :template_id
                AND location_id    = :location_id
                AND count_date     = :count_date
                AND status         = 'open'
                LIMIT 1
            """), {
                'template_id': template_id,
                'location_id': location_id,
                'count_date':  count_date,
            }).fetchone()

            if existing:
                return jsonify({'id': existing.id, 'existing': True}), 200

            # Create new submission
            result = conn.execute(text("""
                INSERT INTO sheet_submissions (
                    template_id, location_id, count_date, submitted_by
                ) VALUES (
                    :template_id, :location_id, :count_date, :submitted_by
                )
                RETURNING id
            """), {
                'template_id':  template_id,
                'location_id':  location_id,
                'count_date':   count_date,
                'submitted_by': g.user.get('email'),
            })
            submission_id = result.fetchone().id
        return jsonify({'id': submission_id, 'existing': False}), 201
    except Exception as e:
        logger.error(f'create_sheet_submission: {e}')
        return jsonify({'error': str(e)}), 500


# =============================================================================
# Sheet Submissions — detail / save draft
# =============================================================================

@bp.route('/sheet-submissions/<int:submission_id>', methods=['GET'])
@store_required
def get_sheet_submission(submission_id):
    """
    Full submission detail with template structure and current entries.
    Returns the template sections/items with any saved counts merged in.
    """
    with get_engine().connect() as conn:
        submission = conn.execute(text("""
            SELECT
                ss.id, ss.template_id, ss.location_id,
                ss.count_date, ss.status,
                ss.submitted_by, ss.submitted_at, ss.notes,
                st.name AS template_name,
                l.location_name
            FROM sheet_submissions ss
            JOIN sheet_templates st ON ss.template_id = st.id
            LEFT JOIN locations l   ON l.store_guid::text = ss.location_id
            WHERE ss.id = :id
        """), {'id': submission_id}).mappings().fetchone()

        if not submission:
            return jsonify({'error': 'Submission not found'}), 404

        # Template sections with items
        sections = conn.execute(text("""
            SELECT
                sec.id    AS section_id,
                sec.name  AS section_name,
                sec.sort_order AS section_sort,
                ssi.id    AS item_id,
                ssi.product_id,
                ssi.sort_order AS item_sort,
                p.name    AS product_name,
                p.base_unit_id,
                u.name    AS base_unit,
                c.name    AS category
            FROM sheet_sections sec
            JOIN sheet_section_items ssi ON ssi.section_id   = sec.id
            JOIN products p              ON ssi.product_id   = p.id
            LEFT JOIN units u            ON p.base_unit_id   = u.id
            LEFT JOIN product_categories c ON p.category_id = c.id
            WHERE sec.template_id = :template_id
            ORDER BY sec.sort_order, ssi.sort_order
        """), {'template_id': submission['template_id']}).mappings().all()

        # Existing entries for this submission — one per product per unit
        entries = conn.execute(text("""
            SELECT
                se.product_id,
                se.quantity,
                se.unit_id,
                se.base_quantity,
                se.base_unit_id,
                se.notes,
                u.name AS unit_name
            FROM sheet_entries se
            LEFT JOIN units u ON se.unit_id = u.id
            WHERE se.submission_id = :id
        """), {'id': submission_id}).mappings().all()

        # Available units per product (for dropdowns)
        product_ids = list(set(s['product_id'] for s in sections))
        available_units = {}
        if product_ids:
            unit_rows = conn.execute(text("""
                SELECT DISTINCT
                    COALESCE(uc.product_id, p.id) AS product_id,
                    u.id   AS unit_id,
                    u.name AS unit_name,
                    u.display AS unit_display
                FROM products p
                JOIN unit_conversions uc ON
                    (uc.product_id = p.id OR uc.product_id IS NULL)
                JOIN units u ON uc.from_unit_id = u.id
                WHERE p.id = ANY(:product_ids)

                UNION

                SELECT p.id, u.id, u.name, u.display
                FROM products p
                JOIN units u ON p.base_unit_id = u.id
                WHERE p.id = ANY(:product_ids)

                ORDER BY product_id, unit_name
            """), {'product_ids': product_ids}).mappings().all()

            for row in unit_rows:
                pid = row['product_id']
                if pid not in available_units:
                    available_units[pid] = []
                available_units[pid].append({
                    'unit_id':      row['unit_id'],
                    'unit_name':    row['unit_name'],
                    'unit_display': row['unit_display'],
                })

        # Active vendor items per product for this location
        vendor_items = {}
        if product_ids:
            # Also fetch effective par levels for the submission date
            from datetime import datetime
            count_date = submission['count_date']
            if hasattr(count_date, 'strftime'):
                dow = count_date.weekday()  # 0=Monday in Python
                # Convert to 0=Sunday
                dow = (dow + 1) % 7
            else:
                try:
                    dt = datetime.strptime(str(count_date)[:10], '%Y-%m-%d')
                    dow = (dt.weekday() + 1) % 7
                except:
                    dow = None

            par_rows = conn.execute(text("""
                SELECT DISTINCT ON (ppl.product_id)
                    ppl.product_id,
                    COALESCE(ppl.override_qty,      ppl.recommended_qty)      AS par_qty,
                    COALESCE(ppl.override_unit_id,  ppl.recommended_unit_id)  AS unit_id,
                    COALESCE(ou.name,               ru.name)                  AS unit_name
                FROM product_par_levels ppl
                LEFT JOIN units ru ON ppl.recommended_unit_id = ru.id
                LEFT JOIN units ou ON ppl.override_unit_id    = ou.id
                WHERE ppl.product_id  = ANY(:product_ids)
                AND ppl.location_id   = :location_id
                AND (ppl.day_of_week  = :dow OR ppl.day_of_week IS NULL)
                ORDER BY ppl.product_id, ppl.day_of_week NULLS LAST
            """), {
                'product_ids': product_ids,
                'location_id': submission['location_id'],
                'dow':         dow,
            }).mappings().all()

            par_map = {r['product_id']: dict(r) for r in par_rows}

            vi_rows = conn.execute(text("""
                SELECT
                    vi.product_id,
                    vi.id          AS vendor_item_id,
                    vi.vendor_code,
                    vi.order_unit_id,
                    vi.order_quantity,
                    vi.price,
                    v.name         AS vendor_name,
                    u.name         AS order_unit
                FROM vendor_items vi
                JOIN vendors v    ON vi.vendor_id     = v.id
                LEFT JOIN units u ON vi.order_unit_id = u.id
                WHERE vi.product_id = ANY(:product_ids)
                AND vi.active = TRUE
            """), {'product_ids': product_ids}).mappings().all()

            for row in vi_rows:
                vendor_items[row['product_id']] = dict(row)

    # Build entry map: (product_id, unit_id) → entry
    entry_map = {}
    for e in entries:
        key = (e['product_id'], e['unit_id'])
        entry_map[key] = dict(e)

    # Build count units map for submission items
    with get_engine().connect() as conn2:
        product_ids = list(set(s['product_id'] for s in sections))
        item_ids    = list(set(s['item_id'] for s in sections))
        count_units_map = {}
        if item_ids:
            cu_rows = conn2.execute(text("""
                SELECT ssiu.id, ssiu.item_id, ssiu.unit_id,
                       u.name AS unit_name, u.display AS unit_display
                FROM sheet_section_item_units ssiu
                JOIN units u ON ssiu.unit_id = u.id
                WHERE ssiu.item_id = ANY(:item_ids)
                ORDER BY ssiu.item_id, ssiu.sort_order
            """), {'item_ids': item_ids}).mappings().all()
            for cu in cu_rows:
                iid = cu['item_id']
                if iid not in count_units_map:
                    count_units_map[iid] = []
                count_units_map[iid].append(dict(cu))

    # Build section structure with merged entries
    section_map = {}
    for row in sections:
        sid = row['section_id']
        if sid not in section_map:
            section_map[sid] = {
                'id':         sid,
                'name':       row['section_name'],
                'sort_order': row['section_sort'],
                'items':      [],
            }
        pid    = row['product_id']
        iid    = row['item_id']
        # If no count units defined for this item, fall back to base unit
        item_count_units = count_units_map.get(iid, [])
        if not item_count_units:
            item_count_units = [{
                'unit_id':      row['base_unit_id'],
                'unit_name':    row['base_unit'],
                'unit_display': row['base_unit'],
                'is_default':   True,
            }]

        # Merge saved quantities into count units
        for cu in item_count_units:
            key   = (pid, cu['unit_id'])
            saved = entry_map.get(key)
            cu['saved_quantity'] = float(saved['quantity']) if saved and saved['quantity'] is not None else None

        section_map[sid]['items'].append({
            'item_id':         iid,
            'product_id':      pid,
            'product_name':    row['product_name'],
            'base_unit':       row['base_unit'],
            'base_unit_id':    row['base_unit_id'],
            'category':        row['category'],
            'sort_order':      row['item_sort'],
            'count_units':     item_count_units,
            'par':             par_map.get(pid),
            'available_units': available_units.get(pid, []),
            'vendor_item':     vendor_items.get(pid),
        })

    result = dict(submission)
    result['sections'] = sorted(section_map.values(), key=lambda s: s['sort_order'])
    return jsonify(result)


@bp.route('/sheet-submissions/<int:submission_id>/pdf', methods=['GET'])
@store_required
def sheet_submission_pdf(submission_id):
    """Generate a compact printable PDF of a count sheet."""
    import io
    import os
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.lib import colors
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
        HRFlowable, Image
    )
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT

    with get_engine().connect() as conn:
        submission = conn.execute(text("""
            SELECT
                ss.id, ss.template_id, ss.location_id,
                ss.count_date, ss.status,
                ss.submitted_by, ss.submitted_at, ss.notes,
                st.name     AS template_name,
                l.location_name,
                l.abbreviation
            FROM sheet_submissions ss
            JOIN sheet_templates st ON ss.template_id = st.id
            LEFT JOIN locations l   ON l.store_guid::text = ss.location_id
            WHERE ss.id = :id
        """), {'id': submission_id}).mappings().fetchone()

        if not submission:
            return jsonify({'error': 'Submission not found'}), 404

        # Calculate day of week from count_date (0=Sunday)
        from datetime import datetime
        try:
            count_date = submission['count_date']
            if hasattr(count_date, 'weekday'):
                dow = (count_date.weekday() + 1) % 7
            else:
                dt  = datetime.strptime(str(count_date)[:10], '%Y-%m-%d')
                dow = (dt.weekday() + 1) % 7
        except Exception:
            dow = None

        sections_raw = conn.execute(text("""
            SELECT
                sec.id         AS section_id,
                sec.name       AS section_name,
                sec.sort_order AS section_sort,
                ssi.id         AS item_id,
                ssi.product_id,
                ssi.sort_order AS item_sort,
                p.name         AS product_name,
                -- On hand entries (summed across all units for this product)
                se.quantity    AS on_hand_qty,
                u_se.name      AS on_hand_unit,
                -- DOW-aware par: prefer day-specific override, fall back to default
                COALESCE(
                    ppl_dow.override_qty,     ppl_dow.recommended_qty,
                    ppl_def.override_qty,     ppl_def.recommended_qty
                ) AS par_qty,
                COALESCE(
                    ppl_dow.override_unit_id, ppl_dow.recommended_unit_id,
                    ppl_def.override_unit_id, ppl_def.recommended_unit_id
                ) AS par_unit_id,
                COALESCE(pu_dow.name, ru_dow.name, pu_def.name, ru_def.name) AS par_unit
            FROM sheet_sections sec
            JOIN sheet_section_items ssi ON ssi.section_id    = sec.id
            JOIN products p              ON ssi.product_id    = p.id
            LEFT JOIN sheet_entries se
                ON se.submission_id = :submission_id
                AND se.product_id   = p.id
            LEFT JOIN units u_se ON se.unit_id = u_se.id
            LEFT JOIN product_par_levels ppl_dow
                ON ppl_dow.product_id   = p.id
                AND ppl_dow.location_id = :location_id
                AND ppl_dow.day_of_week = :dow
            LEFT JOIN product_par_levels ppl_def
                ON ppl_def.product_id   = p.id
                AND ppl_def.location_id = :location_id
                AND ppl_def.day_of_week IS NULL
            LEFT JOIN units pu_dow ON ppl_dow.override_unit_id     = pu_dow.id
            LEFT JOIN units ru_dow ON ppl_dow.recommended_unit_id  = ru_dow.id
            LEFT JOIN units pu_def ON ppl_def.override_unit_id     = pu_def.id
            LEFT JOIN units ru_def ON ppl_def.recommended_unit_id  = ru_def.id
            WHERE sec.template_id = :template_id
            ORDER BY sec.sort_order, ssi.sort_order
        """), {
            'submission_id': submission_id,
            'template_id':   submission['template_id'],
            'location_id':   submission['location_id'],
            'dow':           dow,
        }).mappings().all()

    # Build sections dict
    section_map = {}
    section_order = []
    for row in sections_raw:
        sid = row['section_id']
        if sid not in section_map:
            section_map[sid] = {
                'name':  row['section_name'],
                'items': [],
            }
            section_order.append(sid)
        section_map[sid]['items'].append(row)

    sections = [section_map[sid] for sid in section_order]

    # ── PDF layout ─────────────────────────────────────────────────────────────
    buf = io.BytesIO()  # kept for compatibility, buf2 used for actual output
    PAGE_W, PAGE_H = letter
    MARGIN = 0.5 * inch

    # Colours
    RED   = colors.HexColor('#C0392B')
    DARK  = colors.HexColor('#1a1a1a')
    GREY  = colors.HexColor('#666666')
    LGREY = colors.HexColor('#f2f2f2')
    DGREY = colors.HexColor('#dddddd')
    WHITE = colors.white

    # Styles
    def style(name, **kw):
        return ParagraphStyle(name, **kw)

    hdr_title = style('HdrTitle', fontSize=16, fontName='Helvetica-Bold',
                      textColor=DARK, leading=20)
    hdr_sub   = style('HdrSub',   fontSize=8,  fontName='Helvetica',
                      textColor=GREY, leading=11)
    sec_hdr   = style('SecHdr',   fontSize=7,  fontName='Helvetica-Bold',
                      textColor=WHITE, leading=9)
    item_name = style('ItemName', fontSize=7,  fontName='Helvetica',
                      textColor=DARK, leading=9)
    par_style = style('Par',      fontSize=6.5,fontName='Helvetica',
                      textColor=GREY, leading=8)

    story = []

    # ── 2-column section layout using Frames ──────────────────────────────────
    from reportlab.platypus import FrameBreak
    from reportlab.platypus.frames import Frame
    from reportlab.platypus import BaseDocTemplate, PageTemplate

    count_date_str = str(submission['count_date'])[:10] if submission['count_date'] else '—'
    submitted_str  = submission['submitted_by'] or '—'
    logo_path = os.path.join(os.path.dirname(__file__), '..', 'frontend', 'public', 'logo.png')

    COL_W   = (PAGE_W - 2 * MARGIN - 6) / 2  # 6pt gutter
    ITEM_W  = [COL_W * 0.62, COL_W * 0.2, COL_W * 0.18]

    def build_section_table(section):
        """Build a mini-table for one section."""
        rows = []
        rows.append([Paragraph(section['name'], sec_hdr), '', ''])
        rows.append([
            Paragraph('Product', par_style),
            Paragraph('O/H', par_style),
            Paragraph('Par', par_style),
        ])
        for item in section['items']:
            par_text = ''
            if item['par_qty'] is not None:
                par_val = float(item['par_qty'])
                par_text = f"{par_val:g} - {item['par_unit'] or ''}"

            # On hand — show if entered, blank box if not
            on_hand_text = ''
            if item['on_hand_qty'] is not None:
                oh_val = float(item['on_hand_qty'])
                on_hand_text = f"{oh_val:g}"

            rows.append([
                Paragraph(item['product_name'], item_name),
                Paragraph(on_hand_text, par_style) if on_hand_text else '',
                Paragraph(par_text, par_style),
            ])

        row_count = len(rows)
        # repeatRows=2 repeats section header + column subheader when split
        t = Table(rows, colWidths=ITEM_W, repeatRows=2)
        t.setStyle(TableStyle([
            ('BACKGROUND',    (0,0), (2,0),  RED),
            ('TEXTCOLOR',     (0,0), (2,0),  WHITE),
            ('FONTNAME',      (0,0), (2,0),  'Times-Bold'),
            ('FONTSIZE',      (0,0), (2,0),  4),
            ('SPAN',          (0,0), (2,0)),
            ('TOPPADDING',    (0,0), (2,0),  0),
            ('BOTTOMPADDING', (0,0), (2,0),  0),
            ('LEFTPADDING',   (0,0), (2,0),  4),
            ('BACKGROUND',    (0,1), (2,1),  LGREY),
            ('FONTNAME',      (0,1), (2,1),  'Times-Bold'),
            ('FONTSIZE',      (0,1), (2,1),  6),
            ('TOPPADDING',    (0,1), (2,1),  2),
            ('BOTTOMPADDING', (0,1), (2,1),  2),
            ('FONTSIZE',      (0,2), (-1,-1), 4),
            ('TOPPADDING',    (0,2), (-1,-1), 0),
            ('BOTTOMPADDING', (0,2), (-1,-1), 0),
            ('LEFTPADDING',   (0,0), (-1,-1), 3),
            ('RIGHTPADDING',  (0,0), (-1,-1), 3),
            ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
            ('BOX',           (1,2), (1, row_count-1), 0.5, DARK),
            ('BACKGROUND',    (1,2), (1, row_count-1), WHITE),
            *[('BACKGROUND',  (0,i), (2,i), LGREY if i % 2 == 0 else WHITE)
              for i in range(2, row_count)],
            ('LINEBELOW',     (0,1), (-1,-1), 0.25, DGREY),
            ('BOX',           (0,0), (-1,-1), 0.5, DGREY),
        ]))
        return t

    # Add sections to story — each section is a separate flowable
    # Use KeepTogether to avoid splitting a section header from its first row
    from reportlab.platypus import KeepTogether
    for section in sections:
        tbl = build_section_table(section)
        # KeepTogether only for header + first few rows to avoid orphan headers
        story.append(tbl)
        story.append(Spacer(1, 5))

    # ── Build with canvas callback for header ─────────────────────────────────
    buf2    = io.BytesIO()
    HDR_H   = 0.65 * inch   # reserved space at top of first page for header
    COL_GAP = 6

    # Two-column frames for later pages (full height)
    def later_frames():
        return [
            Frame(MARGIN, MARGIN, COL_W, PAGE_H - 2*MARGIN,
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, id='left'),
            Frame(MARGIN + COL_W + COL_GAP, MARGIN, COL_W, PAGE_H - 2*MARGIN,
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, id='right'),
        ]

    # First page frames — shorter to leave room for header drawn by canvas
    def first_frames():
        body_h = PAGE_H - 1.5*MARGIN - HDR_H - 8
        return [
            Frame(MARGIN, MARGIN, COL_W, body_h,
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, id='left'),
            Frame(MARGIN + COL_W + COL_GAP, MARGIN, COL_W, body_h,
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, id='right'),
        ]

    def draw_header(canvas, doc):
        """Draw header directly onto canvas — runs on first page only."""
        canvas.saveState()
        y_top = PAGE_H - 0.3 * inch

        # Logo or brand text
        if os.path.exists(logo_path):
            canvas.drawImage(logo_path, MARGIN, y_top - 0.55*inch,
                             width=1.1*inch, height=0.45*inch,
                             preserveAspectRatio=True, mask='auto')
            x_title = MARGIN + 1.2*inch
        else:
            canvas.setFont('Helvetica-Bold', 10)
            canvas.setFillColor(RED)
            canvas.drawString(MARGIN, y_top - 0.28*inch, "Anita's New Mexico")
            x_title = MARGIN + 1.5*inch

        # Title
        canvas.setFillColor(DARK)
        canvas.setFont('Times-Bold', 16)
        canvas.drawString(x_title, y_top - 0.3*inch, submission['abbreviation'] or '')
        canvas.setFont('Times-Roman', 8)
        canvas.setFillColor(DARK)
        canvas.drawString(x_title, y_top - 0.48*inch, submission['template_name'] + " - " + str(submission['count_date'].strftime("%a").upper()) + " for " + str((submission['count_date']+ timedelta(days=1)).strftime("%a").upper()) or '')

        # Meta — right side
        meta_x = PAGE_W - MARGIN - 2.5*inch
        canvas.setFont('Times-Roman', 8)
        canvas.setFillColor(DARK)
        canvas.drawString(meta_x, y_top - 0.22*inch, f"Count Date:")
        canvas.setFont('Times-Bold', 8)
        canvas.setFillColor(DARK)
        canvas.drawString(meta_x + 0.60*inch, y_top - 0.22*inch, count_date_str +", "+str(submission['count_date'].strftime("%a").upper()))

        canvas.setFont('Times-Roman', 8)
        canvas.setFillColor(DARK)
        canvas.drawString(meta_x, y_top - 0.37*inch, f"Submitted by:")
        canvas.setFont('Times-Bold', 8)
        canvas.setFillColor(DARK)
        canvas.drawString(meta_x + 0.70*inch, y_top - 0.37*inch, submitted_str)

        canvas.setFont('Times-Roman', 8)
        canvas.setFillColor(DARK)
        canvas.drawString(meta_x, y_top - 0.52*inch, "Status:")
        canvas.setFont('Times-Bold', 8)
        canvas.setFillColor(DARK)
        canvas.drawString(meta_x + 0.40*inch, y_top - 0.52*inch, submission['status'].upper())

        # Red rule
        rule_y = y_top - HDR_H + 4
        canvas.setStrokeColor(RED)
        canvas.setLineWidth(1.5)
        canvas.line(MARGIN, rule_y, PAGE_W - MARGIN, rule_y)

        canvas.restoreState()

    def draw_later(canvas, doc):
        pass  # no header on subsequent pages

    doc2 = BaseDocTemplate(
        buf2,
        pagesize=letter,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN,  bottomMargin=MARGIN,
    )

    first_page  = PageTemplate(id='First', frames=first_frames(), onPage=draw_header)
    later_pages = PageTemplate(id='Later', frames=later_frames(), onPage=draw_later)
    doc2.addPageTemplates([first_page, later_pages])

    from reportlab.platypus import NextPageTemplate, KeepTogether
    full_story = [NextPageTemplate('Later')]
    for section in sections:
        tbl = build_section_table(section)
        full_story.append(KeepTogether([tbl, Spacer(1, 6)]))

    doc2.build(full_story)
    buf2.seek(0)

    from flask import send_file
    filename = f"count-sheet-{submission_id}-{count_date_str}.pdf"
    return send_file(
        buf2,
        mimetype='application/pdf',
        as_attachment=False,
        download_name=filename,
    )


@bp.route('/sheet-submissions/<int:submission_id>', methods=['PUT'])
@store_required
def save_draft_entries(submission_id):
    """
    Save draft entries. Batched version — 3 queries regardless of entry count.
    """
    data    = request.get_json(force=True)
    entries = data.get('entries', [])

    with get_engine().connect() as conn:
        sub = conn.execute(text("""
            SELECT status FROM sheet_submissions WHERE id = :id
        """), {'id': submission_id}).fetchone()

    if not sub:
        return jsonify({'error': 'Submission not found'}), 404

    roles    = g.user.get('roles', [])
    is_admin = 'admin' in roles
    if sub.status == 'submitted' and not is_admin:
        return jsonify({'error': 'Cannot edit a submitted sheet'}), 400

    # Filter valid entries
    valid = [
        e for e in entries
        if e.get('product_id') and e.get('quantity') is not None and e.get('unit_id')
    ]
    if not valid:
        return jsonify({'status': 'ok'})

    try:
        with get_engine().begin() as conn:
            product_ids = list({e['product_id'] for e in valid})
            unit_ids    = list({e['unit_id']    for e in valid})

            # ── BATCH 1: all base unit IDs for these products ─────────────────
            prod_rows = conn.execute(text("""
                SELECT id, base_unit_id FROM products
                WHERE id = ANY(:ids)
            """), {'ids': product_ids}).fetchall()
            base_unit_map = {r.id: r.base_unit_id for r in prod_rows}

            # ── BATCH 2: all relevant unit conversions ────────────────────────
            base_unit_ids = list(set(base_unit_map.values()))
            conv_rows = conn.execute(text("""
                SELECT from_unit_id, to_unit_id, conversion, product_id
                FROM unit_conversions
                WHERE (from_unit_id = ANY(:unit_ids) OR to_unit_id = ANY(:unit_ids))
                AND (from_unit_id = ANY(:base_ids) OR to_unit_id = ANY(:base_ids))
                AND (product_id = ANY(:product_ids) OR product_id IS NULL)
                ORDER BY product_id NULLS LAST
            """), {
                'unit_ids':   unit_ids,
                'base_ids':   base_unit_ids,
                'product_ids': product_ids,
            }).fetchall()

            # Build conversion map: (from_unit, to_unit, product_id) → conversion
            # product-specific entries come first (ordered by product_id NULLS LAST)
            conv_map = {}
            for r in conv_rows:
                key = (r.from_unit_id, r.to_unit_id, r.product_id)
                conv_map[key] = float(r.conversion)
                # Also store global fallback key
                global_key = (r.from_unit_id, r.to_unit_id, None)
                if global_key not in conv_map:
                    conv_map[global_key] = float(r.conversion)

            def get_conversion(from_uid, to_uid, product_id):
                # Product-specific first, then global, then inverse
                for pid in [product_id, None]:
                    v = conv_map.get((from_uid, to_uid, pid))
                    if v is not None:
                        return v
                    v = conv_map.get((to_uid, from_uid, pid))
                    if v is not None:
                        return 1.0 / v
                return None

            # ── Calculate base quantities in Python ───────────────────────────
            rows_to_upsert = []
            for e in valid:
                pid          = e['product_id']
                unit_id      = e['unit_id']
                quantity     = float(e['quantity'])
                base_unit_id = base_unit_map.get(pid)
                base_quantity = None

                if base_unit_id:
                    if unit_id == base_unit_id:
                        base_quantity = quantity
                    else:
                        factor = get_conversion(unit_id, base_unit_id, pid)
                        if factor:
                            base_quantity = quantity * factor

                rows_to_upsert.append({
                    'submission_id': submission_id,
                    'product_id':    pid,
                    'quantity':      quantity,
                    'unit_id':       unit_id,
                    'base_quantity': base_quantity,
                    'base_unit_id':  base_unit_id,
                    'notes':         e.get('notes'),
                })

            # ── BATCH 3: upsert all entries at once ───────────────────────────
            conn.execute(text("""
                INSERT INTO sheet_entries (
                    submission_id, product_id,
                    quantity, unit_id,
                    base_quantity, base_unit_id,
                    notes
                ) VALUES (
                    :submission_id, :product_id,
                    :quantity, :unit_id,
                    :base_quantity, :base_unit_id,
                    :notes
                )
                ON CONFLICT (submission_id, product_id, unit_id) DO UPDATE SET
                    quantity      = EXCLUDED.quantity,
                    base_quantity = EXCLUDED.base_quantity,
                    base_unit_id  = EXCLUDED.base_unit_id,
                    notes         = EXCLUDED.notes,
                    updated_at    = NOW()
            """), rows_to_upsert)

            conn.execute(text("""
                UPDATE sheet_submissions SET updated_at = NOW() WHERE id = :id
            """), {'id': submission_id})

        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f'save_draft_entries: {e}')
        return jsonify({'error': str(e)}), 500


# =============================================================================
# Sheet Submissions — submit
# =============================================================================

@bp.route('/sheet-submissions/<int:submission_id>', methods=['DELETE'])
@store_required
def delete_sheet_submission(submission_id):
    """
    Delete a sheet submission.
    Staff can only delete drafts.
    Admin can delete any status.
    """
    roles    = g.user.get('roles', [])
    is_admin = 'admin' in roles

    try:
        with get_engine().begin() as conn:
            sub = conn.execute(text("""
                SELECT status FROM sheet_submissions WHERE id = :id
            """), {'id': submission_id}).fetchone()

            if not sub:
                return jsonify({'error': 'Submission not found'}), 404
            if sub.status == 'submitted' and not is_admin:
                return jsonify({'error': 'Only admin can delete submitted sheets'}), 403

            # Delete cascade handles sheet_entries
            conn.execute(text("""
                DELETE FROM sheet_submissions WHERE id = :id
            """), {'id': submission_id})

        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f'delete_sheet_submission: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/sheet-submissions/<int:submission_id>/toggle-active', methods=['POST'])
@admin_required
def toggle_submission_active(submission_id):
    """Toggle a sheet submission active/inactive."""
    try:
        with get_engine().begin() as conn:
            conn.execute(text("""
                UPDATE sheet_submissions SET
                    active     = NOT active,
                    updated_at = NOW()
                WHERE id = :id
            """), {'id': submission_id})
        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f'toggle_submission_active: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/sheet-submissions/<int:submission_id>/submit', methods=['POST'])
@store_required
def submit_sheet(submission_id):
    """
    Submit a count sheet. Generates purchase orders grouped by vendor.
    Batched version — replaces N-query loops with set-based SQL.
    """
    import math
    from datetime import datetime

    data          = request.get_json(force=True) or {}
    expected_date = data.get('expected_date') or None

    with get_engine().connect() as conn:
        sub = conn.execute(text("""
            SELECT ss.id, ss.template_id, ss.location_id, ss.count_date, ss.status,
                   st.is_commissary
            FROM sheet_submissions ss
            JOIN sheet_templates st ON ss.template_id = st.id
            WHERE ss.id = :id
        """), {'id': submission_id}).mappings().fetchone()

    if not sub:
        return jsonify({'error': 'Submission not found'}), 404
    if sub['status'] == 'submitted':
        return jsonify({'error': 'Already submitted'}), 400

    # Day of week (0=Sunday)
    try:
        count_date = sub['count_date']
        if hasattr(count_date, 'weekday'):
            dow = (count_date.weekday() + 1) % 7
        else:
            dt  = datetime.strptime(str(count_date)[:10], '%Y-%m-%d')
            dow = (dt.weekday() + 1) % 7
    except Exception:
        dow = None

    try:
        import time
        t0 = time.time()
        with get_engine().begin() as conn:

            # ── BATCH QUERY 1: entries + vendor info ──────────────────────────
            # Single query returns all entries with vendor info resolved
            entries = conn.execute(text("""
                SELECT
                    se.product_id,
                    SUM(se.base_quantity)   AS total_base_quantity,
                    MAX(se.base_unit_id)    AS base_unit_id,
                    p.name                  AS product_name,
                    COALESCE(p.order_rounding_threshold, 0.5) AS order_rounding_threshold,
                    COALESCE(lvi_vi.id,            vi_g.id)            AS vendor_item_id,
                    COALESCE(lvi_vi.vendor_code,   vi_g.vendor_code)   AS vendor_code,
                    COALESCE(lvi_vi.order_unit_id, vi_g.order_unit_id) AS order_unit_id,
                    COALESCE(lvi_vi.order_quantity,vi_g.order_quantity) AS vendor_qty_per_unit,
                    COALESCE(lvi_vi.price,         vi_g.price)         AS price,
                    COALESCE(lvi_v.id,             vi_g_v.id)          AS vendor_id,
                    COALESCE(lvi_v.name,           vi_g_v.name)        AS vendor_name,
                    COALESCE(lvi_v.is_commissary,  vi_g_v.is_commissary, FALSE) AS is_commissary,
                    COALESCE(ou_l.name,            ou_g.name)          AS order_unit
                FROM sheet_entries se
                JOIN products p ON se.product_id = p.id
                LEFT JOIN location_vendor_items lvi
                    ON lvi.product_id = p.id AND lvi.location_id = :location_id
                LEFT JOIN vendor_items lvi_vi ON lvi.vendor_item_id  = lvi_vi.id
                LEFT JOIN vendors lvi_v       ON lvi_vi.vendor_id    = lvi_v.id
                LEFT JOIN units ou_l          ON lvi_vi.order_unit_id = ou_l.id
                LEFT JOIN vendor_items vi_g
                    ON vi_g.product_id = p.id AND vi_g.active = TRUE
                LEFT JOIN vendors vi_g_v ON vi_g.vendor_id     = vi_g_v.id
                LEFT JOIN units ou_g     ON vi_g.order_unit_id = ou_g.id
                WHERE se.submission_id = :id
                GROUP BY se.product_id, p.name, p.order_rounding_threshold,
                         lvi_vi.id, lvi_vi.vendor_code, lvi_vi.order_unit_id, lvi_vi.order_quantity, lvi_vi.price,
                         lvi_v.id, lvi_v.name, lvi_v.is_commissary, ou_l.name,
                         vi_g.id,  vi_g.vendor_code,  vi_g.order_unit_id,  vi_g.order_quantity,  vi_g.price,
                         vi_g_v.id, vi_g_v.name, vi_g_v.is_commissary, ou_g.name
            """), {'id': submission_id, 'location_id': sub['location_id']}).mappings().all()
            logger.info(f'submit_sheet [{submission_id}] entries query: {time.time()-t0:.2f}s')
            t1 = time.time()

            # Build lookup dicts — keyed by product_id for O(1) access later
            entries_by_product = {e['product_id']: e for e in entries}
            product_ids = list(entries_by_product.keys())

            if not product_ids:
                return jsonify({'error': 'No entries to submit'}), 400

            # ── BATCH QUERY 2: par levels for all products at once ─────────────
            par_rows = conn.execute(text("""
                WITH par_data AS (
                    SELECT
                        ppl.product_id,
                        ppl.day_of_week,
                        COALESCE(ppl.override_qty,      ppl.recommended_qty)     AS par_qty,
                        COALESCE(ppl.override_unit_id,  ppl.recommended_unit_id) AS par_unit_id,
                        ROW_NUMBER() OVER (
                            PARTITION BY ppl.product_id
                            ORDER BY ppl.day_of_week NULLS LAST
                        ) AS rn
                    FROM product_par_levels ppl
                    WHERE ppl.product_id  = ANY(:product_ids)
                    AND ppl.location_id   = :location_id
                    AND (ppl.day_of_week  = :dow OR ppl.day_of_week IS NULL)
                )
                SELECT pd.product_id, pd.par_qty, pd.par_unit_id,
                       uc.conversion, uc.from_unit_id, uc.to_unit_id
                FROM par_data pd
                LEFT JOIN products p ON pd.product_id = p.id
                LEFT JOIN unit_conversions uc ON (
                    (uc.from_unit_id = pd.par_unit_id AND uc.to_unit_id = p.base_unit_id)
                    OR
                    (uc.from_unit_id = p.base_unit_id AND uc.to_unit_id = pd.par_unit_id)
                )
                AND (uc.product_id = pd.product_id OR uc.product_id IS NULL)
                WHERE pd.rn = 1
                ORDER BY pd.product_id, uc.product_id NULLS LAST,
                         CASE WHEN uc.to_unit_id = p.base_unit_id THEN 0 ELSE 1 END
            """), {
                'product_ids': product_ids,
                'location_id': sub['location_id'],
                'dow':         dow,
            }).mappings().all()
            logger.info(f'submit_sheet [{submission_id}] par query: {time.time()-t1:.2f}s')
            t2 = time.time()

            # Build par map — keyed by product_id
            par_map = {}
            for row in par_rows:
                pid = row['product_id']
                if pid not in par_map:  # first row wins (best conversion match)
                    par_map[pid] = dict(row)

            # ── BATCH QUERY 3: unit conversions for all order units at once ────
            # Collect all unique (base_unit, order_unit, product) combos
            conv_keys = set()
            for e in entries:
                if e['order_unit_id'] and e['base_unit_id']:
                    conv_keys.add((e['base_unit_id'], e['order_unit_id'], e['product_id']))

            vendor_conv_map = {}  # (base_unit_id, order_unit_id, product_id) → factor
            if conv_keys:
                # Fetch all potentially relevant conversions in one query
                # then match in Python to avoid unnest parameter conflicts
                all_unit_ids = list(set(
                    [k[0] for k in conv_keys] + [k[1] for k in conv_keys]
                ))
                all_prod_ids = list(set(k[2] for k in conv_keys))

                conv_rows = conn.execute(text("""
                    SELECT uc.conversion, uc.from_unit_id, uc.to_unit_id, uc.product_id
                    FROM unit_conversions uc
                    WHERE (
                        uc.from_unit_id = ANY(:unit_ids)
                        OR uc.to_unit_id = ANY(:unit_ids)
                    )
                    AND (uc.product_id = ANY(:prod_ids) OR uc.product_id IS NULL)
                    ORDER BY uc.product_id NULLS LAST
                """), {
                    'unit_ids': all_unit_ids,
                    'prod_ids': all_prod_ids,
                }).mappings().all()

                # Match conversions — product-specific first, then global (product_id IS NULL)
                for base_uid, order_uid, pid in conv_keys:
                    best = None
                    for row in conv_rows:
                        matches = (
                            (row['from_unit_id'] == base_uid and row['to_unit_id'] == order_uid) or
                            (row['from_unit_id'] == order_uid and row['to_unit_id'] == base_uid)
                        )
                        if not matches:
                            continue
                        if row['product_id'] == pid:
                            best = row
                            break  # exact product match — stop looking
                        if row['product_id'] is None and best is None:
                            best = row  # global fallback — keep looking for product-specific
                    if best:
                        if best['from_unit_id'] == base_uid:
                            factor = float(best['conversion'])
                        else:
                            factor = 1.0 / float(best['conversion'])
                        vendor_conv_map[(base_uid, order_uid, pid)] = factor
            logger.info(f'submit_sheet [{submission_id}] conv query: {time.time()-t2:.2f}s')
            t3 = time.time()

            # ── BATCH QUERY 4: vendor snapshot update ─────────────────────────
            conn.execute(text("""
                UPDATE sheet_entries SET
                    vendor_item_id = :vendor_item_id,
                    vendor_code    = :vendor_code,
                    vendor_name    = :vendor_name,
                    order_unit_id  = :order_unit_id,
                    updated_at     = NOW()
                WHERE submission_id = :submission_id
                AND product_id = :product_id
            """), [
                {
                    'submission_id':  submission_id,
                    'product_id':     e['product_id'],
                    'vendor_item_id': e.get('vendor_item_id'),
                    'vendor_code':    e.get('vendor_code'),
                    'vendor_name':    e.get('vendor_name'),
                    'order_unit_id':  e.get('order_unit_id'),
                }
                for e in entries
            ])
            logger.info(f'submit_sheet [{submission_id}] vendor snapshot: {time.time()-t3:.2f}s')
            t4 = time.time()

            # ── Python: calculate order quantities ────────────────────────────
            # All the math happens here — no more per-product DB calls
            order_calc = {}  # product_id → { order_qty, order_base, par_qty, par_unit_id, par_base_qty }

            for e in entries:
                pid          = e['product_id']
                par          = par_map.get(pid)
                on_hand_base = float(e['total_base_quantity'] or 0)
                base_unit_id = e['base_unit_id']

                # Convert par to base units
                par_base = 0.0
                par_qty_snap     = None
                par_unit_id_snap = None
                par_base_qty_snap = None

                if par and par['par_qty'] is not None:
                    par_qty_snap     = par['par_qty']
                    par_unit_id_snap = par['par_unit_id']
                    if par['conversion']:
                        if par['to_unit_id'] == base_unit_id:
                            par_base = float(par['par_qty']) * float(par['conversion'])
                        else:
                            par_base = float(par['par_qty']) / float(par['conversion'])
                    else:
                        par_base = float(par['par_qty'])
                    par_base_qty_snap = par_base

                # Order qty in base units
                order_base = max(0.0, par_base - on_hand_base)

                # Convert to vendor order unit using pre-fetched conversion
                order_qty = order_base
                if e['order_unit_id'] and base_unit_id and order_base > 0:
                    key    = (base_unit_id, e['order_unit_id'], pid)
                    factor = vendor_conv_map.get(key)
                    if factor:
                        raw_qty   = order_base * factor
                        threshold = float(e.get('order_rounding_threshold') or 0.5)
                        whole     = math.floor(raw_qty)
                        frac      = raw_qty - whole
                        order_qty = whole + 1 if frac >= threshold else whole
                        order_qty = max(1, order_qty) if raw_qty > 0 else 0

                order_calc[pid] = {
                    'order_qty':        order_qty,
                    'order_base':       order_base,
                    'par_qty':          par_qty_snap,
                    'par_unit_id':      par_unit_id_snap,
                    'par_base_qty':     par_base_qty_snap,
                }

            # ── Group by vendor and create POs ────────────────────────────────
            vendor_entries = {}
            for e in entries:
                if not e['vendor_id']:
                    continue
                vid = e['vendor_id']
                if vid not in vendor_entries:
                    vendor_entries[vid] = {
                        'vendor_id':    vid,
                        'vendor_name':  e['vendor_name'],
                        'is_commissary': e['is_commissary'],
                        'items':        [],
                    }
                vendor_entries[vid]['items'].append(e)

            po_ids            = []
            commissary_po_ids = []
            po_item_map       = {}  # product_id → (order_qty, order_unit_id) for snapshot

            for vid, vdata in vendor_entries.items():
                is_comm = vdata['is_commissary']

                po_result = conn.execute(text("""
                    INSERT INTO purchase_orders (
                        location_id, order_date, expected_date, vendor_id,
                        status, created_by, is_commissary, sheet_submission_id
                    ) VALUES (
                        :location_id, :order_date, :expected_date, :vendor_id,
                        'open', :created_by, :is_commissary, :sheet_submission_id
                    )
                    RETURNING id
                """), {
                    'location_id':        sub['location_id'],
                    'order_date':         sub['count_date'],
                    'expected_date':      expected_date,
                    'vendor_id':          vid,
                    'created_by':         g.user.get('email'),
                    'is_commissary':      is_comm,
                    'sheet_submission_id': submission_id,
                })
                po_id = po_result.fetchone().id
                if is_comm:
                    commissary_po_ids.append(po_id)
                else:
                    po_ids.append(po_id)

                # Commissary section mapping
                comm_section_map = {}
                if is_comm:
                    comm_template = conn.execute(text("""
                        SELECT ct.id FROM comm_order_templates ct
                        WHERE ct.location_id = :location_id
                        AND ct.vendor_id     = :vendor_id
                        AND ct.active        = TRUE
                        LIMIT 1
                    """), {
                        'location_id': sub['location_id'],
                        'vendor_id':   vid,
                    }).fetchone()

                    if comm_template:
                        tmpl_sections = conn.execute(text("""
                            SELECT s.id AS section_id, s.name AS section_name,
                                   s.sort_order, i.product_id
                            FROM comm_order_template_sections s
                            LEFT JOIN comm_order_template_items i ON i.section_id = s.id
                            WHERE s.template_id = :template_id
                            ORDER BY s.sort_order, i.sort_order
                        """), {'template_id': comm_template.id}).mappings().all()

                        product_section_name = {}
                        section_sort = {}
                        for row in tmpl_sections:
                            if row['product_id']:
                                product_section_name[row['product_id']] = row['section_name']
                            section_sort[row['section_name']] = row['sort_order']

                        needed_sections = {}
                        for item in vdata['items']:
                            sec_name = product_section_name.get(item['product_id'], 'Other')
                            if sec_name not in needed_sections:
                                needed_sections[sec_name] = section_sort.get(sec_name, 999)

                        po_section_ids = {}
                        for sec_name, sort_order in sorted(needed_sections.items(), key=lambda x: x[1]):
                            result = conn.execute(text("""
                                INSERT INTO comm_order_sections (purchase_order_id, name, sort_order)
                                VALUES (:po_id, :name, :sort_order)
                                RETURNING id
                            """), {'po_id': po_id, 'name': sec_name, 'sort_order': sort_order})
                            po_section_ids[sec_name] = result.fetchone().id

                        for item in vdata['items']:
                            sec_name = product_section_name.get(item['product_id'], 'Other')
                            comm_section_map[item['product_id']] = po_section_ids.get(sec_name)

                # ── Insert all PO items for this vendor ───────────────────────
                if vdata['items']:
                    conn.execute(text("""
                        INSERT INTO purchase_order_items (
                            purchase_order_id, product_id,
                            vendor_item_id, vendor_code, product_name,
                            order_unit_id, order_quantity, original_quantity,
                            base_quantity, base_unit_id,
                            unit_price, comm_section_id
                        ) VALUES (
                            :po_id, :product_id,
                            :vendor_item_id, :vendor_code, :product_name,
                            :order_unit_id, :order_quantity, :order_quantity,
                            :base_quantity, :base_unit_id,
                            :unit_price, :comm_section_id
                        )
                        ON CONFLICT (purchase_order_id, product_id) DO NOTHING
                    """), [
                        {
                            'po_id':           po_id,
                            'product_id':      item['product_id'],
                            'vendor_item_id':  item['vendor_item_id'],
                            'vendor_code':     item['vendor_code'],
                            'product_name':    item['product_name'],
                            'order_unit_id':   item['order_unit_id'],
                            'order_quantity':  order_calc.get(item['product_id'], {}).get('order_qty', 0),
                            'base_quantity':   order_calc.get(item['product_id'], {}).get('order_base', 0),
                            'base_unit_id':    item['base_unit_id'],
                            'unit_price':      item['price'],
                            'comm_section_id': comm_section_map.get(item['product_id']),
                        }
                        for item in vdata['items']
                    ])
                    # Track for inventory snapshot
                    for item in vdata['items']:
                        pid = item['product_id']
                        po_item_map[pid] = {
                            'order_quantity': order_calc.get(pid, {}).get('order_qty', 0),
                            'order_unit_id':  item['order_unit_id'],
                        }

            logger.info(f'submit_sheet [{submission_id}] PO creation: {time.time()-t4:.2f}s')
            t5 = time.time()

            # ── Create inventory submission header ────────────────────────────
            inv_sub_result = conn.execute(text("""
                INSERT INTO inventory_submissions (
                    sheet_submission_id, location_id, count_date,
                    source, status, submitted_by, submitted_at
                ) VALUES (
                    :sheet_submission_id, :location_id, :count_date,
                    'count_sheet', 'submitted', :submitted_by, NOW()
                )
                RETURNING id
            """), {
                'sheet_submission_id': submission_id,
                'location_id':         sub['location_id'],
                'count_date':          sub['count_date'],
                'submitted_by':        g.user.get('email'),
            })
            inv_submission_id = inv_sub_result.fetchone().id

            # ── BATCH: what this order sheet counted, per product ────────────
            # Goes to inventory_submission_counts (this inventory's own rows, with
            # the par / order / vendor snapshot the purchase order reads back).
            # The day's count (inventory_counts) is picked afterwards by
            # refresh_day_counts: latest submitted inventory wins, per product.
            inv_rows = [e for e in entries if e['total_base_quantity'] is not None]
            if inv_rows:
                adopt_day_counts(conn, sub['location_id'], sub['count_date'])
                conn.execute(text("""
                    INSERT INTO inventory_submission_counts (
                        inventory_submission_id, product_id,
                        base_quantity, base_unit_id,
                        vendor_item_id, vendor_id, vendor_code,
                        par_qty, par_unit_id, par_base_qty,
                        order_qty, order_unit_id, entered_by
                    ) VALUES (
                        :inv_submission_id, :product_id,
                        :base_quantity, :base_unit_id,
                        :vendor_item_id, :vendor_id, :vendor_code,
                        :par_qty, :par_unit_id, :par_base_qty,
                        :order_qty, :order_unit_id, :entered_by
                    )
                    ON CONFLICT (inventory_submission_id, product_id) DO UPDATE SET
                        base_quantity  = EXCLUDED.base_quantity,
                        base_unit_id   = EXCLUDED.base_unit_id,
                        vendor_item_id = EXCLUDED.vendor_item_id,
                        vendor_id      = EXCLUDED.vendor_id,
                        vendor_code    = EXCLUDED.vendor_code,
                        par_qty        = EXCLUDED.par_qty,
                        par_unit_id    = EXCLUDED.par_unit_id,
                        par_base_qty   = EXCLUDED.par_base_qty,
                        order_qty      = EXCLUDED.order_qty,
                        order_unit_id  = EXCLUDED.order_unit_id,
                        entered_by     = EXCLUDED.entered_by
                """), [
                    {
                        'inv_submission_id':  inv_submission_id,
                        'product_id':         e['product_id'],
                        'base_quantity':      float(e['total_base_quantity']),
                        'base_unit_id':       e['base_unit_id'],
                        'vendor_item_id':     e.get('vendor_item_id'),
                        'vendor_id':          e.get('vendor_id'),
                        'vendor_code':        e.get('vendor_code'),
                        'par_qty':            order_calc.get(e['product_id'], {}).get('par_qty'),
                        'par_unit_id':        order_calc.get(e['product_id'], {}).get('par_unit_id'),
                        'par_base_qty':       order_calc.get(e['product_id'], {}).get('par_base_qty'),
                        'order_qty':          po_item_map.get(e['product_id'], {}).get('order_quantity'),
                        'order_unit_id':      po_item_map.get(e['product_id'], {}).get('order_unit_id'),
                        'entered_by':         g.user.get('email'),
                    }
                    for e in inv_rows
                ])

                # The lines as counted (units), so the inventory can show them.
                copy_sheet_entries(conn, inv_submission_id, submission_id, g.user.get('email'))

                # This inventory is the newest for the day: it takes the day's
                # count for every product it counted.
                refresh_day_counts(conn, sub['location_id'], sub['count_date'],
                                   [e['product_id'] for e in inv_rows])

            # ── Lock the submission ───────────────────────────────────────────
            logger.info(f'submit_sheet [{submission_id}] inventory counts: {time.time()-t5:.2f}s')
            t6 = time.time()
            conn.execute(text("""
                UPDATE sheet_submissions SET
                    status       = 'submitted',
                    submitted_at = NOW(),
                    submitted_by = :submitted_by,
                    updated_at   = NOW()
                WHERE id = :id
            """), {'id': submission_id, 'submitted_by': g.user.get('email')})
            logger.info(f'submit_sheet [{submission_id}] TOTAL: {time.time()-t0:.2f}s')

        return jsonify({
            'status':                  'submitted',
            'po_ids':                  po_ids,
            'po_count':                len(po_ids),
            'commissary_po_ids':       commissary_po_ids,
            'commissary_po_count':     len(commissary_po_ids),
            'inventory_submission_id': inv_submission_id,
        })
    except Exception as e:
        logger.error(f'submit_sheet: {e}')
        return jsonify({'error': str(e)}), 500
