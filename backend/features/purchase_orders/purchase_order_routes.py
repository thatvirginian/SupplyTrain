# =============================================================================
# backend/features/purchase_orders/purchase_order_routes.py
# =============================================================================
# Purchase Orders (Order History): list, view, PDF, edit, add/edit/receive items, and the lifecycle
# open -> accepted -> shipped -> fulfilled.
#
# Endpoints in this file:
#   GET     /api/purchase-orders                             list_purchase_orders
#   GET     /api/purchase-orders/<int:po_id>/pdf             purchase_order_pdf
#   GET     /api/purchase-orders/<int:po_id>                 get_purchase_order
#   DELETE  /api/purchase-orders/<int:po_id>                 delete_purchase_order
#   PUT     /api/purchase-orders/<int:po_id>                 update_purchase_order
#   POST    /api/purchase-orders/<int:po_id>/items           add_order_item
#   PUT     /api/purchase-order-items/<int:item_id>          update_order_item
#   PUT     /api/purchase-order-items/<int:item_id>/receive  receive_order_item
#   POST    /api/purchase-orders/<int:po_id>/accept          accept_order
#   POST    /api/purchase-orders/<int:po_id>/ship            ship_order
#   POST    /api/purchase-orders/<int:po_id>/fulfill         fulfill_order
#   DELETE  /api/purchase-order-items/<int:item_id>          delete_order_item
# =============================================================================

from flask import Blueprint, jsonify, request, g
from sqlalchemy import text
import logging

from core.auth import (
    ADMIN, GM, STORE, COMMISSARY, COMM_GM, _has_role, admin_required, manage_required,
    staff_required, store_required, comm_manage_required, comm_item_edit_required,
    _get_user_location,
)
from core.database import get_engine

logger = logging.getLogger(__name__)

bp = Blueprint('purchase_order_routes', __name__, url_prefix='/api')


# =============================================================================
# Purchase Orders
# =============================================================================

@bp.route('/purchase-orders', methods=['GET'])
@staff_required
def list_purchase_orders():
    """
    List purchase orders — filtered by role:
    - admin: all orders
    - gm/store: their location's orders
    - commissary/comm_gm: commissary orders only
    """
    roles        = g.user.get('roles', [])
    is_admin     = ADMIN in roles
    is_gm        = GM in roles
    is_store     = STORE in roles
    is_comm_user = any(r in roles for r in [COMMISSARY, COMM_GM])

    location_id  = request.args.get('location_id')
    vendor_id    = request.args.get('vendor_id', type=int)
    status       = request.args.get('status')
    is_comm      = request.args.get('is_commissary')
    page         = request.args.get('page', 1, type=int)
    per_page     = request.args.get('per_page', 20, type=int)
    offset       = (page - 1) * per_page

    with get_engine().connect() as conn:
        if not is_admin and (is_gm or is_store):
            location_id = _get_user_location(conn)

    filters = []
    params  = {'limit': per_page, 'offset': offset}

    # Commissary users only see commissary orders
    if is_comm_user and not is_admin:
        filters.append('po.is_commissary = TRUE')

    if location_id:
        filters.append('po.location_id = :location_id')
        params['location_id'] = location_id
    if vendor_id:
        filters.append('po.vendor_id = :vendor_id')
        params['vendor_id'] = vendor_id
    if status:
        filters.append('po.status = :status')
        params['status'] = status
    if is_comm == 'true':
        filters.append('po.is_commissary = TRUE')
    elif is_comm == 'false':
        filters.append('po.is_commissary = FALSE')

    where = ('WHERE ' + ' AND '.join(filters)) if filters else ''

    with get_engine().connect() as conn:
        total = conn.execute(text(f"""
            SELECT COUNT(*) FROM purchase_orders po {where}
        """), params).scalar()

        rows = conn.execute(text(f"""
            SELECT
                po.id, po.location_id, po.order_date,
                po.status, po.is_commissary,
                po.created_by, po.submitted_at, po.received_at,
                po.created_at, po.notes,
                v.id   AS vendor_id,
                v.name AS vendor_name,
                l.location_name,
                COUNT(poi.id) AS line_item_count
            FROM purchase_orders po
            JOIN vendors v    ON po.vendor_id      = v.id
            LEFT JOIN locations l  ON l.store_guid::text = po.location_id
            LEFT JOIN purchase_order_items poi ON poi.purchase_order_id = po.id
            {where}
            GROUP BY po.id, v.id, v.name, l.location_name
            ORDER BY po.order_date DESC, po.created_at DESC
            LIMIT :limit OFFSET :offset
        """), params).mappings().all()

    return jsonify({
        'total':   total,
        'page':    page,
        'per_page': per_page,
        'pages':   max(1, (total + per_page - 1) // per_page),
        'orders':  [dict(r) for r in rows],
    })


@bp.route('/purchase-orders/<int:po_id>/pdf', methods=['GET'])
@store_required
def purchase_order_pdf(po_id):
    """Generate a compact printable PDF of a purchase order with par data."""
    import io
    import os
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.lib import colors
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    )
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus.frames import Frame
    from reportlab.platypus import BaseDocTemplate, PageTemplate, KeepTogether

    with get_engine().connect() as conn:
        po = conn.execute(text("""
            SELECT
                po.id, po.location_id, po.order_date, po.expected_date,
                po.status, po.is_commissary, po.notes,
                po.created_by, po.submitted_at,
                po.shipped_at, po.shipped_by,
                po.fulfilled_at, po.fulfilled_by,
                po.sheet_submission_id,
                v.name AS vendor_name,
                l.location_name,
                l.abbreviation
            FROM purchase_orders po
            JOIN vendors v       ON po.vendor_id       = v.id
            LEFT JOIN locations l ON l.store_guid::text = po.location_id
            WHERE po.id = :id
        """), {'id': po_id}).mappings().fetchone()

        if not po:
            return jsonify({'error': 'Order not found'}), 404

        # Get items with the par / on-hand snapshot of the order sheet inventory that created them
        items_raw = conn.execute(text("""
            SELECT
                poi.id,
                poi.product_name,
                poi.vendor_code,
                poi.order_quantity,
                poi.original_quantity,
                poi.is_short,
                poi.picked,
                poi.received_status,
                poi.received_note,
                poi.edited_by,
                poi.comm_section_id,
                u.name  AS order_unit,
                cs.name AS section_name,
                cs.sort_order AS section_sort,
                -- Par from inventory_counts snapshot
                ic.par_qty,
                pu.name  AS par_unit,
                -- On hand: convert base_quantity back to order unit if possible
                CASE
                    WHEN uc.conversion IS NOT NULL AND uc.from_unit_id = ic.base_unit_id
                        THEN ic.base_quantity * uc.conversion
                    WHEN uc.conversion IS NOT NULL AND uc.to_unit_id = ic.base_unit_id
                        THEN ic.base_quantity / uc.conversion
                    ELSE ic.base_quantity
                END AS on_hand_qty,
                COALESCE(u.name, bu.name) AS on_hand_unit
            FROM purchase_order_items poi
            LEFT JOIN units u                ON poi.order_unit_id   = u.id
            LEFT JOIN comm_order_sections cs ON poi.comm_section_id = cs.id
            LEFT JOIN LATERAL (
                -- What the order sheet's inventory counted for this product
                -- (inventory_submission_counts). These rows stay with their
                -- inventory, so a later recount that day does not change them.
                -- Last resort for orders older than that table, the count of the day.
                SELECT s.par_qty, s.par_unit_id, s.base_quantity, s.base_unit_id
                FROM (
                    SELECT c.par_qty, c.par_unit_id, c.base_quantity, c.base_unit_id,
                           1 AS source_rank, c.id AS row_id
                    FROM inventory_submission_counts c
                    JOIN inventory_submissions invs
                        ON c.inventory_submission_id = invs.id
                    WHERE c.product_id = poi.product_id
                    AND (
                        -- Direct match via sheet_submission_id
                        (:sheet_submission_id IS NOT NULL AND invs.sheet_submission_id = :sheet_submission_id)
                        OR
                        -- Fallback: match by location + date for older orders
                        (:sheet_submission_id IS NULL AND invs.location_id = :location_id AND invs.count_date = :order_date)
                    )
                    UNION ALL
                    SELECT ic2.par_qty, ic2.par_unit_id, ic2.base_quantity, ic2.base_unit_id,
                           2 AS source_rank, ic2.id AS row_id
                    FROM inventory_counts ic2
                    WHERE ic2.product_id  = poi.product_id
                      AND ic2.location_id = :location_id
                      AND ic2.count_date  = :order_date
                      AND :sheet_submission_id IS NULL
                ) s
                ORDER BY s.source_rank, (s.par_qty IS NOT NULL) DESC, s.row_id DESC
                LIMIT 1
            ) ic ON TRUE
            LEFT JOIN units pu ON ic.par_unit_id  = pu.id
            LEFT JOIN units bu ON ic.base_unit_id = bu.id
            LEFT JOIN LATERAL (
                SELECT uc2.conversion, uc2.from_unit_id, uc2.to_unit_id
                FROM unit_conversions uc2
                WHERE (
                    (uc2.from_unit_id = ic.base_unit_id AND uc2.to_unit_id = poi.order_unit_id)
                    OR
                    (uc2.to_unit_id = ic.base_unit_id AND uc2.from_unit_id = poi.order_unit_id)
                )
                AND (uc2.product_id = poi.product_id OR uc2.product_id IS NULL)
                ORDER BY uc2.product_id NULLS LAST
                LIMIT 1
            ) uc ON TRUE
            WHERE poi.purchase_order_id = :id
            ORDER BY cs.sort_order NULLS LAST, cs.name NULLS LAST, poi.product_name
        """), {
            'id':                  po_id,
            'sheet_submission_id': po['sheet_submission_id'],
            'location_id':         po['location_id'],
            'order_date':          po['order_date'],
        }).mappings().all()

        sections_raw = conn.execute(text("""
            SELECT id, name, sort_order FROM comm_order_sections
            WHERE purchase_order_id = :id ORDER BY sort_order
        """), {'id': po_id}).mappings().all()

    # Group by section
    section_map  = {s['id']: {'name': s['name'], 'items': []} for s in sections_raw}
    unsectioned  = []
    for item in items_raw:
        if item['comm_section_id'] and item['comm_section_id'] in section_map:
            section_map[item['comm_section_id']]['items'].append(item)
        else:
            unsectioned.append(item)

    sections = [section_map[s['id']] for s in sections_raw if section_map[s['id']]['items']]
    if unsectioned:
        sections.append({'name': 'Other', 'items': unsectioned})

    # ── PDF layout ─────────────────────────────────────────────────────────────
    buf2    = io.BytesIO()
    PAGE_W, PAGE_H = letter
    MARGIN  = 0.4 * inch
    HDR_H   = 0.70 * inch
    COL_W   = (PAGE_W - 2 * MARGIN - 6) / 2
    COL_GAP = 6

    RED   = colors.HexColor('#C0392B')
    DARK  = colors.HexColor('#1a1a1a')
    GREY  = colors.HexColor('#666666')
    LGREY = colors.HexColor('#f2f2f2')
    DGREY = colors.HexColor('#dddddd')
    WHITE = colors.white
    BLUE  = colors.HexColor('#2563eb')

    def sty(name, **kw): return ParagraphStyle(name, **kw)
    sec_hdr   = sty('S', fontSize=8,   fontName='Times-Bold',   textColor=WHITE,  leading=6)
    sub_hdr   = sty('H', fontSize=7, fontName='Times-Bold',   textColor=DARK,   leading=7)
    item_name = sty('I', fontSize=6,   fontName='Times-Roman',    textColor=DARK,   leading=5)
    par_style = sty('P', fontSize=6,   fontName='Times-Roman',    textColor=GREY,   leading=5)
    short_sty = sty('X', fontSize=6,   fontName='Times-Bold', textColor=RED,  leading=5)

    # Col widths: Product | Status | Ordered | Par | On Hand | Status
    ITEM_W = [COL_W * 0.35, COL_W * 0.15, COL_W * 0.10, COL_W * 0.10, COL_W * 0.13, COL_W * 0.17 ]

    def build_section_table(section):
        rows = []
        rows.append([Paragraph(section['name'], sec_hdr), '', '', '', '',''])
        rows.append([
            Paragraph('Product',  sub_hdr),
            Paragraph('Unit', sub_hdr),
            Paragraph('O/H', sub_hdr),
            Paragraph('Par', sub_hdr),
            Paragraph('Ord',  sub_hdr),
            Paragraph('Status', sub_hdr),

        ])
        for item in section['items']:
            par_text = ''
            if item['par_qty'] is not None:
                par_text = f"{float(item['par_qty']):g}"

            oh_text = ''
            if item['on_hand_qty'] is not None:
                oh_text = f"{float(item['on_hand_qty']):g}"

            order_text = f"{float(item['order_quantity']):g}" if item['order_quantity'] is not None else ''


            if (item['original_quantity'] is not None and
                item['order_quantity'] is not None and
                float(item['original_quantity']) != float(item['order_quantity'])):
                order_text += f" (was {float(item['original_quantity']):g})"

            status_text = ''
            if item['is_short']:       status_text = 'SHORT'
            if item['received_status']: status_text = item['received_status'].upper()

            unit_text = ''
            if item['par_qty'] is not None:
                unit_text = f"{item['par_unit'] or ''}"

            name_style = short_sty if item['is_short'] else item_name
            rows.append([
                Paragraph(item['product_name'], name_style),
                Paragraph(unit_text, par_style),
                Paragraph(oh_text,    par_style),
                Paragraph(par_text, par_style),
                Paragraph(order_text, par_style),
                Paragraph(status_text, short_sty if item['is_short'] else par_style),

            ])

        row_count = len(rows)
        t = Table(rows, colWidths=ITEM_W, repeatRows=2)
        t.setStyle(TableStyle([
            ('BACKGROUND',    (0,0), (-1,0), RED),
            ('TEXTCOLOR',     (0,0), (-1,0), WHITE),
            ('SPAN',          (0,0), (-1,0)),
            ('FONTNAME',      (0,0), (-1,0), 'Times-Bold'),
            ('FONTSIZE',      (0,0), (-1,0), 4),
            ('TOPPADDING',    (0,0), (-1,0), 0),
            ('BOTTOMPADDING', (0,0), (-1,0), 3),
            ('LEFTPADDING',   (0,0), (-1,0), 3),
            ('BACKGROUND',    (0,1), (-1,1), LGREY),
            ('TOPPADDING',    (0,1), (-1,1), 3),
            ('BOTTOMPADDING', (0,1), (-1,1), 3),
            ('FONTSIZE',      (0,2), (-1,-1), 4),
            ('TOPPADDING',    (0,2), (-1,-1), 1),
            ('BOTTOMPADDING', (0,2), (-1,-1), 5),
            ('LEFTPADDING',   (0,0), (-1,-1), 2),
            ('RIGHTPADDING',  (0,0), (-1,-1), 2),
            ('VALIGN',        (0,0), (-1,-1), 'MIDDLE'),
            *[('BACKGROUND',  (0,i), (-1,i), LGREY if i % 2 == 0 else WHITE)
              for i in range(2, row_count)],
            ('LINEBELOW',     (0,1), (-1,-1), 0.25, DGREY),
            ('BOX',           (0,0), (-1,-1), 0.5, DGREY),
        ]))
        return t

    story = []
    for section in sections:
        story.append(build_section_table(section))
        story.append(Spacer(1, 4))

    # ── Canvas header ──────────────────────────────────────────────────────────
    logo_path   = os.path.join(os.path.dirname(__file__), '..', 'frontend', 'public', 'logo.png')
    order_date  = str(po['order_date'])[:10] if po['order_date'] else '—'
    status_str  = po['status'].upper()

    def draw_header(canvas, doc):
        canvas.saveState()
        y_top = PAGE_H - MARGIN * 0.6

        if os.path.exists(logo_path):
            canvas.drawImage(logo_path, MARGIN, y_top - 0.5*inch,
                             width=1.0*inch, height=0.4*inch,
                             preserveAspectRatio=True, mask='auto')
            x_title = MARGIN + 1.1*inch
        else:
            canvas.setFont('Helvetica-Bold', 9)
            canvas.setFillColor(RED)
            canvas.drawString(MARGIN, y_top - 0.25*inch, "Anita's New Mexico")
            x_title = MARGIN + 1.4*inch

        canvas.setFillColor(DARK)
        canvas.setFont('Helvetica-Bold', 14)
        canvas.drawString(x_title, y_top - 0.28*inch, po['location_name'] or '')
        canvas.setFont('Helvetica', 7.5)
        canvas.setFillColor(GREY)
        canvas.drawString(x_title, y_top - 0.44*inch, f"{po['vendor_name']} · {po['is_commissary'] and 'Commissary' or 'Purchase'}")

        # Right side meta
        meta_x = PAGE_W - MARGIN - 2.2*inch
        lines = [
            ('Order Date', order_date),
            ('Status',     status_str),
            ('Created by', (po['created_by'] or '').split('@')[0]),
        ]
        if po['shipped_at']:
            lines.append(('Shipped', f"{str(po['shipped_at'])[:10]} · {(po['shipped_by'] or '').split('@')[0]}"))
        if po['fulfilled_at']:
            lines.append(('Fulfilled', f"{str(po['fulfilled_at'])[:10]} · {(po['fulfilled_by'] or '').split('@')[0]}"))
        if po['notes']:
            lines.append(('Notes', po['notes']))

        y = y_top - 0.15*inch
        for label, val in lines:
            canvas.setFont('Helvetica', 6.5)
            canvas.setFillColor(GREY)
            canvas.drawString(meta_x, y, f"{label}:")
            canvas.setFont('Helvetica-Bold', 6.5)
            canvas.setFillColor(DARK)
            canvas.drawString(meta_x + 0.65*inch, y, str(val))
            y -= 0.11*inch

        canvas.setStrokeColor(RED)
        canvas.setLineWidth(1.5)
        canvas.line(MARGIN, y_top - HDR_H + 4, PAGE_W - MARGIN, y_top - HDR_H + 4)
        canvas.restoreState()

    def draw_later(canvas, doc): pass

    doc2 = BaseDocTemplate(buf2, pagesize=letter,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN,  bottomMargin=MARGIN)

    def first_frames():
        body_h = PAGE_H - 2*MARGIN - HDR_H - 8
        return [
            Frame(MARGIN, MARGIN, COL_W, body_h,
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, id='left'),
            Frame(MARGIN + COL_W + COL_GAP, MARGIN, COL_W, body_h,
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, id='right'),
        ]

    def later_frames():
        body_h = PAGE_H - 2*MARGIN
        return [
            Frame(MARGIN, MARGIN, COL_W, body_h,
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, id='left'),
            Frame(MARGIN + COL_W + COL_GAP, MARGIN, COL_W, body_h,
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, id='right'),
        ]

    from reportlab.platypus import NextPageTemplate
    doc2.addPageTemplates([
        PageTemplate(id='First', frames=first_frames(), onPage=draw_header),
        PageTemplate(id='Later', frames=later_frames(), onPage=draw_later),
    ])

    full_story = [NextPageTemplate('Later')] + story
    doc2.build(full_story)
    buf2.seek(0)

    from flask import send_file
    filename = f"order-{po_id}-{po['vendor_name']}-{order_date}.pdf".replace(' ', '-')
    return send_file(buf2, mimetype='application/pdf', as_attachment=False, download_name=filename)


@bp.route('/purchase-orders/<int:po_id>', methods=['GET'])
@staff_required
def get_purchase_order(po_id):
    """Get purchase order detail with line items."""
    with get_engine().connect() as conn:
        po = conn.execute(text("""
            SELECT
                po.id, po.location_id, po.order_date, po.expected_date,
                po.status, po.is_commissary, po.notes,
                po.created_by, po.submitted_at,
                po.shipped_at, po.shipped_by,
                po.fulfilled_at, po.fulfilled_by,
                po.sheet_submission_id,
                po.created_at, po.updated_at,
                v.id   AS vendor_id,
                v.name AS vendor_name,
                l.location_name
            FROM purchase_orders po
            JOIN vendors v   ON po.vendor_id      = v.id
            LEFT JOIN locations l ON l.store_guid::text = po.location_id
            WHERE po.id = :id
        """), {'id': po_id}).mappings().fetchone()

        if not po:
            return jsonify({'error': 'Order not found'}), 404

        items = conn.execute(text("""
            SELECT
                poi.id,
                poi.product_id,
                poi.vendor_item_id,
                poi.vendor_code,
                poi.product_name,
                poi.order_quantity,
                poi.original_quantity,
                poi.base_quantity,
                poi.base_unit_id,
                poi.is_short,
                poi.picked,
                poi.received_status,
                poi.received_note,
                poi.received_by,
                poi.received_at,
                poi.edited_by,
                poi.edited_at,
                poi.notes,
                poi.comm_section_id,
                u.name  AS order_unit,
                u.id    AS order_unit_id,
                cs.name AS section_name,
                cs.sort_order AS section_sort
            FROM purchase_order_items poi
            LEFT JOIN units u             ON poi.order_unit_id   = u.id
            LEFT JOIN comm_order_sections cs ON poi.comm_section_id = cs.id
            WHERE poi.purchase_order_id = :id
            ORDER BY cs.sort_order NULLS LAST, cs.name NULLS LAST, poi.product_name
        """), {'id': po_id}).mappings().all()

        sections = conn.execute(text("""
            SELECT id, name, sort_order
            FROM comm_order_sections
            WHERE purchase_order_id = :id
            ORDER BY sort_order
        """), {'id': po_id}).mappings().all()

    result = dict(po)
    result['items']    = [dict(i) for i in items]
    result['sections'] = [dict(s) for s in sections]
    return jsonify(result)


@bp.route('/purchase-orders/<int:po_id>', methods=['DELETE'])
@admin_required
def delete_purchase_order(po_id):
    """Delete a purchase order and all its line items. Admin only."""
    try:
        with get_engine().begin() as conn:
            # CASCADE handles purchase_order_items
            conn.execute(text("""
                DELETE FROM purchase_orders WHERE id = :id
            """), {'id': po_id})
        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f'delete_purchase_order: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/purchase-orders/<int:po_id>', methods=['PUT'])
@manage_required
def update_purchase_order(po_id):
    """Update order status, notes, or expected_date."""
    data = request.get_json(force=True)
    new_status = data.get('status')
    try:
        with get_engine().begin() as conn:
            conn.execute(text("""
                UPDATE purchase_orders SET
                    status        = COALESCE(:status, status),
                    notes         = COALESCE(:notes, notes),
                    expected_date = COALESCE(:expected_date, expected_date),
                    submitted_at  = CASE WHEN :status = 'submitted' AND submitted_at IS NULL
                                         THEN NOW() ELSE submitted_at END,
                    shipped_at    = CASE WHEN :status = 'shipped' AND shipped_at IS NULL
                                         THEN NOW() ELSE shipped_at END,
                    shipped_by    = CASE WHEN :status = 'shipped' AND shipped_by IS NULL
                                         THEN :by ELSE shipped_by END,
                    fulfilled_at  = CASE WHEN :status = 'fulfilled' AND fulfilled_at IS NULL
                                         THEN NOW() ELSE fulfilled_at END,
                    fulfilled_by  = CASE WHEN :status = 'fulfilled' AND fulfilled_by IS NULL
                                         THEN :by ELSE fulfilled_by END,
                    updated_at    = NOW()
                WHERE id = :id
            """), {
                'id':            po_id,
                'status':        new_status,
                'notes':         data.get('notes'),
                'expected_date': data.get('expected_date'),
                'by':            g.user.get('email'),
            })
        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f'update_purchase_order: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/purchase-orders/<int:po_id>/items', methods=['POST'])
@manage_required
def add_order_item(po_id):
    """
    Add a product to an existing draft PO.
    - Resolves vendor item from location_vendor_items (falls back to global active)
    - For commissary POs, looks up comm template to assign correct section
    - Creates 'Other' section if product not found in template
    """
    data       = request.get_json(force=True)
    product_id = data.get('product_id')
    quantity   = data.get('order_quantity', 0)
    unit_id    = data.get('unit_id')  # optional override

    if not product_id:
        return jsonify({'error': 'product_id is required'}), 400

    try:
        with get_engine().begin() as conn:
            # Get PO info
            po = conn.execute(text("""
                SELECT po.id, po.location_id, po.vendor_id, po.is_commissary, po.status
                FROM purchase_orders po
                WHERE po.id = :id
            """), {'id': po_id}).fetchone()

            if not po:
                return jsonify({'error': 'Order not found'}), 404
            if po.status != 'accepted':
                return jsonify({'error': 'Can only add items to draft orders'}), 400

            # Resolve vendor item
            vendor_item = conn.execute(text("""
                SELECT
                    COALESCE(lvi_vi.id,            vi_g.id)            AS vendor_item_id,
                    COALESCE(lvi_vi.vendor_code,   vi_g.vendor_code)   AS vendor_code,
                    COALESCE(lvi_vi.order_unit_id, vi_g.order_unit_id) AS order_unit_id,
                    COALESCE(lvi_vi.price,         vi_g.price)         AS price,
                    p.name      AS product_name,
                    p.base_unit_id
                FROM products p
                LEFT JOIN location_vendor_items lvi
                    ON lvi.product_id = p.id AND lvi.location_id = :location_id
                LEFT JOIN vendor_items lvi_vi ON lvi.vendor_item_id = lvi_vi.id
                LEFT JOIN vendor_items vi_g
                    ON vi_g.product_id = p.id AND vi_g.active = TRUE
                WHERE p.id = :product_id
            """), {
                'product_id':  product_id,
                'location_id': po.location_id,
            }).fetchone()

            if not vendor_item:
                return jsonify({'error': 'Product not found'}), 404

            # Resolve comm section if commissary order
            comm_section_id = None
            if po.is_commissary:
                # Look up template for this location+vendor
                template = conn.execute(text("""
                    SELECT ct.id FROM comm_order_templates ct
                    WHERE ct.location_id = :location_id
                    AND ct.vendor_id     = :vendor_id
                    AND ct.active        = TRUE
                    LIMIT 1
                """), {
                    'location_id': po.location_id,
                    'vendor_id':   po.vendor_id,
                }).fetchone()

                if template:
                    # Find which section this product belongs to
                    section_row = conn.execute(text("""
                        SELECT s.name, s.sort_order
                        FROM comm_order_template_items i
                        JOIN comm_order_template_sections s ON i.section_id = s.id
                        WHERE s.template_id = :template_id
                        AND i.product_id    = :product_id
                        LIMIT 1
                    """), {
                        'template_id': template.id,
                        'product_id':  product_id,
                    }).fetchone()

                    section_name = section_row.name if section_row else 'Other'
                    section_sort = section_row.sort_order if section_row else 999

                    # Find or create the comm_order_section on this PO
                    existing_section = conn.execute(text("""
                        SELECT id FROM comm_order_sections
                        WHERE purchase_order_id = :po_id AND name = :name
                    """), {'po_id': po_id, 'name': section_name}).fetchone()

                    if existing_section:
                        comm_section_id = existing_section.id
                    else:
                        comm_section_id = conn.execute(text("""
                            INSERT INTO comm_order_sections (purchase_order_id, name, sort_order)
                            VALUES (:po_id, :name, :sort_order)
                            RETURNING id
                        """), {
                            'po_id':      po_id,
                            'name':       section_name,
                            'sort_order': section_sort,
                        }).fetchone().id

            # Use provided unit_id or fall back to vendor item's order unit
            resolved_unit_id = unit_id or vendor_item.order_unit_id

            # Calculate base_quantity
            base_quantity = None
            base_unit_id  = vendor_item.base_unit_id
            if resolved_unit_id and base_unit_id and float(quantity) > 0:
                if resolved_unit_id == base_unit_id:
                    base_quantity = float(quantity)
                else:
                    conv = conn.execute(text("""
                        SELECT conversion, from_unit_id, to_unit_id
                        FROM unit_conversions
                        WHERE (
                            (from_unit_id = :unit_id AND to_unit_id = :base_unit_id)
                            OR
                            (from_unit_id = :base_unit_id AND to_unit_id = :unit_id)
                        )
                        AND (product_id = :product_id OR product_id IS NULL)
                        ORDER BY product_id NULLS LAST,
                                 CASE WHEN from_unit_id = :unit_id THEN 0 ELSE 1 END
                        LIMIT 1
                    """), {
                        'unit_id':      resolved_unit_id,
                        'base_unit_id': base_unit_id,
                        'product_id':   product_id,
                    }).fetchone()
                    if conv:
                        if conv.from_unit_id == resolved_unit_id:
                            base_quantity = float(quantity) * float(conv.conversion)
                        else:
                            base_quantity = float(quantity) / float(conv.conversion)

            # Insert item
            result = conn.execute(text("""
                INSERT INTO purchase_order_items (
                    purchase_order_id, product_id, vendor_item_id,
                    vendor_code, product_name, order_unit_id,
                    order_quantity, original_quantity,
                    base_quantity, base_unit_id,
                    comm_section_id,
                    edited_by, edited_at
                ) VALUES (
                    :po_id, :product_id, :vendor_item_id,
                    :vendor_code, :product_name, :order_unit_id,
                    :order_quantity, :order_quantity,
                    :base_quantity, :base_unit_id,
                    :comm_section_id,
                    :edited_by, NOW()
                )
                ON CONFLICT (purchase_order_id, product_id) DO UPDATE SET
                    order_quantity   = EXCLUDED.order_quantity,
                    original_quantity = EXCLUDED.original_quantity,
                    order_unit_id    = EXCLUDED.order_unit_id,
                    base_quantity    = EXCLUDED.base_quantity,
                    base_unit_id     = EXCLUDED.base_unit_id,
                    comm_section_id  = EXCLUDED.comm_section_id,
                    edited_by        = EXCLUDED.edited_by,
                    edited_at        = NOW()
                RETURNING id
            """), {
                'po_id':           po_id,
                'product_id':      product_id,
                'vendor_item_id':  vendor_item.vendor_item_id,
                'vendor_code':     vendor_item.vendor_code,
                'product_name':    vendor_item.product_name,
                'order_unit_id':   resolved_unit_id,
                'order_quantity':  float(quantity),
                'base_quantity':   base_quantity,
                'base_unit_id':    base_unit_id,
                'comm_section_id': comm_section_id,
                'edited_by':       g.user.get('email'),
            })
            item_id = result.fetchone().id
        return jsonify({'id': item_id}), 201
    except Exception as e:
        logger.error(f'add_order_item: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/purchase-order-items/<int:item_id>', methods=['PUT'])
@comm_item_edit_required  # allows admin, gm, comm_gm, commissary — plus store checked inside
def update_order_item(item_id):
    """
    Update a line item. Permission depends on order status:
    - open: store/gm/admin can edit qty
    - accepted: comm/comm_gm/admin can edit qty, short, picked
    - admin: always
    """
    data    = request.get_json(force=True)
    new_qty = data.get('order_quantity')
    roles   = g.user.get('roles', [])
    is_admin    = 'admin' in roles
    is_comm_only = _has_role(COMMISSARY) and not _has_role(ADMIN, GM, COMM_GM)

    try:
        with get_engine().begin() as conn:
            # Get item + order status for permission check
            current = conn.execute(text("""
                SELECT poi.order_quantity, poi.order_unit_id, poi.base_unit_id,
                       poi.product_id, po.status
                FROM purchase_order_items poi
                JOIN purchase_orders po ON poi.purchase_order_id = po.id
                WHERE poi.id = :id
            """), {'id': item_id}).fetchone()

            if not current:
                return jsonify({'error': 'Item not found'}), 404

            # Status-based permission check
            if not is_admin:
                status = current.status
                if status == 'open':
                    # Store/GM can edit when open
                    if not any(r in roles for r in ['store', 'gm', 'admin']):
                        return jsonify({'error': 'Not authorized'}), 403
                elif status == 'accepted':
                    # Comm/comm_gm can edit when accepted
                    if not any(r in roles for r in ['commissary', 'commissary_gm', 'admin']):
                        return jsonify({'error': 'Not authorized'}), 403
                else:
                    return jsonify({'error': 'Order is locked'}), 403

            # Recalculate base_quantity if qty is changing
            new_base_qty = None
            if new_qty is not None and current.order_unit_id and current.base_unit_id:
                conv = conn.execute(text("""
                    SELECT conversion, from_unit_id, to_unit_id
                    FROM unit_conversions
                    WHERE (
                        (from_unit_id = :order_unit_id AND to_unit_id = :base_unit_id)
                        OR
                        (from_unit_id = :base_unit_id  AND to_unit_id = :order_unit_id)
                    )
                    AND (product_id = :product_id OR product_id IS NULL)
                    ORDER BY product_id NULLS LAST,
                             CASE WHEN from_unit_id = :order_unit_id THEN 0 ELSE 1 END
                    LIMIT 1
                """), {
                    'order_unit_id': current.order_unit_id,
                    'base_unit_id':  current.base_unit_id,
                    'product_id':    current.product_id,
                }).fetchone()

                if conv:
                    factor = float(conv.conversion) if conv.from_unit_id == current.order_unit_id \
                             else 1.0 / float(conv.conversion)
                    new_base_qty = float(new_qty) * factor

            conn.execute(text("""
                UPDATE purchase_order_items SET
                    order_quantity  = COALESCE(:order_quantity, order_quantity),
                    base_quantity   = CASE WHEN :new_base_qty IS NOT NULL
                                          THEN :new_base_qty ELSE base_quantity END,
                    is_short        = COALESCE(:is_short, is_short),
                    picked          = COALESCE(:picked, picked),
                    notes           = CASE WHEN :comm_only THEN notes
                                          ELSE COALESCE(:notes, notes) END,
                    vendor_code     = CASE WHEN :comm_only THEN vendor_code
                                          ELSE COALESCE(:vendor_code, vendor_code) END,
                    edited_by       = CASE
                                         WHEN :order_quantity IS NOT NULL
                                          AND :order_quantity != order_quantity
                                         THEN :edited_by ELSE edited_by END,
                    edited_at       = CASE
                                         WHEN :order_quantity IS NOT NULL
                                          AND :order_quantity != order_quantity
                                         THEN NOW() ELSE edited_at END
                WHERE id = :id
            """), {
                'id':             item_id,
                'order_quantity': float(new_qty) if new_qty is not None else None,
                'new_base_qty':   new_base_qty,
                'is_short':       data.get('is_short'),
                'picked':         data.get('picked'),
                'notes':          data.get('notes'),
                'vendor_code':    data.get('vendor_code'),
                'edited_by':      g.user.get('email'),
                'comm_only':      is_comm_only,
            })
        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f'update_order_item: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/purchase-order-items/<int:item_id>/receive', methods=['PUT'])
@store_required
def receive_order_item(item_id):
    """Store staff marks an item as received or returned with optional note."""
    data = request.get_json(force=True)
    status = data.get('received_status')  # 'received' or 'returned'
    note   = data.get('received_note')

    if status not in ('received', 'returned', None):
        return jsonify({'error': 'Invalid received_status'}), 400

    try:
        with get_engine().begin() as conn:
            conn.execute(text("""
                UPDATE purchase_order_items SET
                    received_status = COALESCE(:status, received_status),
                    received_note   = :note,
                    received_by     = :received_by,
                    received_at     = NOW()
                WHERE id = :id
            """), {
                'id':          item_id,
                'status':      status,
                'note':        note,
                'received_by': g.user.get('email'),
            })
        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f'receive_order_item: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/purchase-orders/<int:po_id>/accept', methods=['POST'])
@comm_manage_required
def accept_order(po_id):
    """Accept order — commissary GM or admin locks it for picking."""
    try:
        with get_engine().begin() as conn:
            po = conn.execute(text(
                "SELECT status FROM purchase_orders WHERE id = :id"
            ), {'id': po_id}).fetchone()
            if not po:
                return jsonify({'error': 'Order not found'}), 404
            if po.status != 'open':
                return jsonify({'error': f'Cannot accept order in {po.status} status'}), 400
            conn.execute(text("""
                UPDATE purchase_orders SET
                    status     = 'accepted',
                    updated_at = NOW()
                WHERE id = :id
            """), {'id': po_id})
        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f'accept_order: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/purchase-orders/<int:po_id>/ship', methods=['POST'])
@comm_manage_required
def ship_order(po_id):
    """Mark order as shipped — commissary GM or admin only."""
    try:
        with get_engine().begin() as conn:
            po = conn.execute(text(
                "SELECT status FROM purchase_orders WHERE id = :id"
            ), {'id': po_id}).fetchone()
            if not po:
                return jsonify({'error': 'Order not found'}), 404
            if po.status != 'accepted':
                return jsonify({'error': f'Cannot ship order in {po.status} status'}), 400

            conn.execute(text("""
                UPDATE purchase_orders SET
                    status     = 'shipped',
                    shipped_at = NOW(),
                    shipped_by = :by,
                    updated_at = NOW()
                WHERE id = :id
            """), {'id': po_id, 'by': g.user.get('email')})
        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f'ship_order: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/purchase-orders/<int:po_id>/fulfill', methods=['POST'])
@store_required
def fulfill_order(po_id):
    """Store marks order as fulfilled after receiving."""
    data = request.get_json(force=True) or {}
    note = data.get('notes')
    try:
        with get_engine().begin() as conn:
            po = conn.execute(text(
                "SELECT status FROM purchase_orders WHERE id = :id"
            ), {'id': po_id}).fetchone()
            if not po:
                return jsonify({'error': 'Order not found'}), 404
            if po.status != 'shipped':
                return jsonify({'error': f'Cannot fulfill order in {po.status} status'}), 400

            conn.execute(text("""
                UPDATE purchase_orders SET
                    status       = 'fulfilled',
                    fulfilled_at = NOW(),
                    fulfilled_by = :by,
                    notes        = COALESCE(:notes, notes),
                    updated_at   = NOW()
                WHERE id = :id
            """), {'id': po_id, 'by': g.user.get('email'), 'notes': note})
        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f'fulfill_order: {e}')
        return jsonify({'error': str(e)}), 500


@bp.route('/purchase-order-items/<int:item_id>', methods=['DELETE'])
@admin_required
def delete_order_item(item_id):
    """Remove a line item from an order."""
    try:
        with get_engine().begin() as conn:
            conn.execute(text("""
                DELETE FROM purchase_order_items WHERE id = :id
            """), {'id': item_id})
        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f'delete_order_item: {e}')
        return jsonify({'error': str(e)}), 500
