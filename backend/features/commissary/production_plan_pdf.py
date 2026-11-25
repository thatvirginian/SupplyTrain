# =============================================================================
# backend/features/commissary/production_plan_pdf.py
# =============================================================================
# The Production Plan as a PDF, laid out like the paper "Daily Prep Production"
# sheet: each store cell split by a / diagonal, INV (store count) top-left and
# ORD (store order) bottom-right, then Total and Comm Inv.
#
#   build_production_plan_pdf(plan) -> bytes
#       plan = the dict the /api/production-plan endpoint returns.
#
# Portrait when the columns fit (about 7 stores), landscape when there are more.
# =============================================================================

import io
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Flowable
from reportlab.lib.styles import ParagraphStyle

RED   = colors.HexColor('#C0392B')
DARK  = colors.HexColor('#1a1a1a')
MUTED = colors.HexColor('#666666')
GRID  = colors.HexColor('#999999')
SHADE = colors.HexColor('#f2f2f2')

MARGIN  = 0.5 * inch
PROD_W  = 1.9 * inch
UNIT_W  = 0.55 * inch
STORE_W = 0.62 * inch
TOTAL_W = 0.7 * inch
COMM_W  = 0.75 * inch
ROW_H   = 0.42 * inch

STORE_TZ = os.environ.get('STORE_TIMEZONE', 'America/New_York')


def _fmt(v):
    if v is None:
        return ''
    v = round(float(v), 1)
    return str(int(v)) if v == int(v) else f'{v:g}'


def _short_date(d):
    if not d:
        return ''
    dt = datetime.strptime(str(d)[:10], '%Y-%m-%d')
    return f'{dt.month}/{dt.day}'


class SplitCell(Flowable):
    """A cell split by a / diagonal: INV top-left, ORD bottom-right."""

    def __init__(self, w, h, inv, ord_, shade=False):
        super().__init__()
        self.w, self.h, self.inv, self.ord, self.shade = w, h, inv, ord_, shade

    def wrap(self, aw, ah):
        return self.w, self.h

    def draw(self):
        c = self.canv
        if self.shade:
            c.setFillColor(SHADE)
            c.rect(0, 0, self.w, self.h, stroke=0, fill=1)
        if self.inv is None and self.ord is None:
            return
        c.setStrokeColor(GRID)
        c.setLineWidth(0.5)
        c.line(0, 0, self.w, self.h)                     # bottom-left to top-right: /
        c.setFillColor(MUTED)
        c.setFont('Helvetica', 8)
        c.drawString(3, self.h - 10, _fmt(self.inv) or '-')
        c.setFillColor(DARK)
        c.setFont('Helvetica-Bold', 11)
        c.drawRightString(self.w - 3, 4, _fmt(self.ord) or '-')


def build_production_plan_pdf(plan):
    stores = plan['stores']
    n = len(stores)
    table_w = PROD_W + UNIT_W + n * STORE_W + TOTAL_W + COMM_W
    pagesize = letter if table_w <= letter[0] - 2 * MARGIN else landscape(letter)
    page_w = pagesize[0]
    # Give any spare width to the product column
    prod_w = PROD_W + max(0, (page_w - 2 * MARGIN) - table_w)

    items = [i for s in plan['sections'] for i in s['items']]
    dates = {i.get('comm_inv_date') for i in items if i.get('comm_inv_date')}
    comm_date = next(iter(dates)) if len(dates) == 1 else None

    small = ParagraphStyle('small', fontName='Helvetica', fontSize=7, textColor=MUTED, leading=9)
    prod  = ParagraphStyle('prod', fontName='Helvetica-Bold', fontSize=9, textColor=DARK, leading=11)
    head  = ParagraphStyle('head', fontName='Helvetica-Bold', fontSize=7, textColor=DARK,
                           leading=9, alignment=1)

    show_routes = any(s.get('route') for s in stores)
    rows, style = [], [
        ('GRID',          (0, 0), (-1, -1), 0.5, GRID),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ('FONT',          (0, 0), (-1, -1), 'Helvetica', 8),
        ('TEXTCOLOR',     (0, 0), (-1, -1), DARK),
    ]

    # Header rows
    if show_routes:
        r = ['', '']
        groups = []
        for s in stores:
            route = s.get('route') or 'No route'
            if groups and groups[-1][0] == route:
                groups[-1][1] += 1
            else:
                groups.append([route, 1])
        col = 2
        for route, span in groups:
            r += [Paragraph(route.upper(), head)] + [''] * (span - 1)
            if span > 1:
                style.append(('SPAN', (col, 0), (col + span - 1, 0)))
            col += span
        r += ['', '']
        rows.append(r)
    hdr = len(rows)
    comm_head = 'COMM INV' + (f'<br/><font size="6" color="#666666">{_short_date(comm_date)}</font>'
                              if comm_date else '')
    rows.append([Paragraph('PRODUCT', head), Paragraph('UNIT', head)]
                + [Paragraph(s.get('abbreviation') or s.get('location_name') or '', head) for s in stores]
                + [Paragraph('TOTAL', head), Paragraph(comm_head, head)])
    style += [('BACKGROUND', (0, 0), (-1, hdr), SHADE)]
    header_rows = hdr + 1

    show_sections = len(plan['sections']) > 1
    for sec in plan['sections']:
        if show_sections:
            rows.append([Paragraph(sec['name'].upper(), ParagraphStyle('sec', parent=head, alignment=0))]
                        + [''] * (n + 3))
            ri = len(rows) - 1
            style += [('SPAN', (0, ri), (-1, ri)), ('BACKGROUND', (0, ri), (-1, ri), SHADE),
                      ('ALIGN', (0, ri), (-1, ri), 'LEFT')]
        for i in sec['items']:
            cells = [Paragraph(i['product_name'], prod), Paragraph(i.get('unit_name') or '', small)]
            for s in stores:
                c = i['stores'].get(s['location_id']) or {}
                cells.append(SplitCell(STORE_W, ROW_H, c.get('inv'), c.get('ord')))
            cells.append(SplitCell(TOTAL_W, ROW_H, i.get('total_inv'), i.get('total_ord'), shade=True))
            comm = _fmt(i.get('comm_inv'))
            if comm and i.get('comm_inv_date') and i.get('comm_inv_date') != comm_date:
                comm += f'<br/><font size="6" color="#666666">{_short_date(i["comm_inv_date"])}</font>'
            cells.append(Paragraph(comm, ParagraphStyle('c', fontName='Helvetica-Bold', fontSize=10,
                                                        leading=11, alignment=2)))
            rows.append(cells)

    col_w = [prod_w, UNIT_W] + [STORE_W] * n + [TOTAL_W, COMM_W]
    row_h = [None] * header_rows + [None if (show_sections and isinstance(r[1], str)) else ROW_H
                                    for r in rows[header_rows:]]
    t = Table(rows, colWidths=col_w, rowHeights=row_h, repeatRows=header_rows)
    first_split, last_split = 2, 2 + n          # store columns + Total: no padding
    style += [
        ('LEFTPADDING',   (first_split, header_rows), (last_split, -1), 0),
        ('RIGHTPADDING',  (first_split, header_rows), (last_split, -1), 0),
        ('TOPPADDING',    (first_split, header_rows), (last_split, -1), 0),
        ('BOTTOMPADDING', (first_split, header_rows), (last_split, -1), 0),
    ]
    t.setStyle(TableStyle(style))

    # Header drawn on every page
    delivery = datetime.strptime(plan['date'], '%Y-%m-%d')
    printed = datetime.now(ZoneInfo(STORE_TZ))

    def draw_header(canvas, doc):
        canvas.saveState()
        top = pagesize[1] - MARGIN
        canvas.setFillColor(RED)
        canvas.setFont('Helvetica-Bold', 9)
        canvas.drawString(MARGIN, top - 10, "Anita's New Mexico")
        canvas.setFillColor(DARK)
        canvas.setFont('Helvetica-Bold', 15)
        canvas.drawString(MARGIN, top - 28, f"PRODUCTION PLAN  ·  {plan['template_name']}")
        canvas.setFont('Helvetica', 9)
        canvas.drawString(MARGIN, top - 44,
                          f"{plan.get('location_name') or 'Commissary'}  ·  delivery "
                          f"{delivery.strftime('%A')} {delivery.month}/{delivery.day}/{delivery.year}")
        # Like the paper: Name / Day / Date
        canvas.drawString(MARGIN, top - 62, 'Name: ____________________')
        canvas.drawString(MARGIN + 2.6 * inch, top - 62, f"Day: {delivery.strftime('%A')}")
        canvas.drawString(MARGIN + 4.0 * inch, top - 62,
                          f"Date: {delivery.month}/{delivery.day}/{delivery.strftime('%y')}")
        right = pagesize[0] - MARGIN
        canvas.setFont('Helvetica', 7)
        canvas.setFillColor(MUTED)
        canvas.drawRightString(right, top - 10, f"Printed {printed.month}/{printed.day} {printed.strftime('%I:%M %p').lstrip('0')}")
        canvas.drawRightString(right, top - 21, 'Each store box: INV (store count) top left, ORD (order) bottom right')
        areas_txt = ' + '.join(a['name'] for a in (plan.get('comm_areas') or []))
        canvas.drawRightString(right, top - 32, 'Comm Inv: commissary count before this day'
                               + (f' ({areas_txt})' if areas_txt else ''))
        canvas.drawRightString(right, MARGIN - 14, f'Page {doc.page}')
        canvas.setStrokeColor(RED)
        canvas.setLineWidth(1.5)
        canvas.line(MARGIN, top - 72, right, top - 72)
        canvas.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=pagesize, leftMargin=MARGIN, rightMargin=MARGIN,
                            topMargin=MARGIN + 82, bottomMargin=MARGIN,
                            title=f"Production Plan {plan['template_name']} {plan['date']}")
    story = [t]
    if not stores:
        story = [Paragraph('No store has a commissary order for delivery on this day.', small),
                 Spacer(1, 6), t]
    doc.build(story, onFirstPage=draw_header, onLaterPages=draw_header)
    return buf.getvalue()
