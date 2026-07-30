import os

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle
)

# PO PDFs live under the already-mounted /uploads static path.
PO_PDF_FOLDER = "uploads/purchase_orders"

COMPANY_NAME = "Abhinav Group"
COMPANY_TAGLINE = "Purchase Order"


def _fmt(value) -> str:
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return "0.00"


def generate_po_pdf(po, items, vendor) -> str:
    """
    Render a Purchase Order to a PDF file and return its stored path.

    `po` is a PurchaseOrder, `items` its PurchaseOrderItem list, and
    `vendor` the Supplier. All values are read as already-snapshotted
    on the PO so the document never changes once generated.
    """
    os.makedirs(PO_PDF_FOLDER, exist_ok=True)

    filename = f"{po.po_number.replace('/', '-')}.pdf"
    file_path = os.path.join(PO_PDF_FOLDER, filename)

    doc = SimpleDocTemplate(
        file_path,
        pagesize=A4,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        leftMargin=15 * mm,
        rightMargin=15 * mm
    )

    styles = getSampleStyleSheet()
    small = ParagraphStyle(
        "small", parent=styles["Normal"], fontSize=8, leading=10
    )
    normal = styles["Normal"]
    h_title = ParagraphStyle(
        "h_title", parent=styles["Title"], fontSize=18, spaceAfter=2
    )
    h_sub = ParagraphStyle(
        "h_sub", parent=styles["Normal"], fontSize=11,
        textColor=colors.HexColor("#555555")
    )

    elements = []

    # ---- Header ----
    elements.append(Paragraph(COMPANY_NAME, h_title))
    elements.append(Paragraph(COMPANY_TAGLINE, h_sub))
    elements.append(Spacer(1, 6))

    po_date = po.po_date.strftime("%d-%b-%Y") if po.po_date else "-"
    meta = [
        [
            Paragraph(f"<b>PO Number:</b> {po.po_number}", normal),
            Paragraph(f"<b>PO Date:</b> {po_date}", normal),
        ],
        [
            Paragraph(f"<b>Status:</b> {po.status}", normal),
            Paragraph(f"<b>Payment Terms:</b> {po.payment_terms or '-'}", normal),
        ],
    ]
    meta_table = Table(meta, colWidths=[90 * mm, 90 * mm])
    meta_table.setStyle(TableStyle([
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
    ]))
    elements.append(meta_table)
    elements.append(Spacer(1, 8))

    # ---- Vendor / Ship-to ----
    vendor_block = (
        f"<b>Vendor:</b><br/>{vendor.company_name}<br/>"
        f"{(vendor.registered_address or '').replace(chr(10), '<br/>')}<br/>"
        f"GSTIN: {vendor.gst_number or '-'}<br/>"
        f"Contact: {vendor.contact_person_name or '-'} "
        f"({vendor.whatsapp_number or '-'})"
    )
    ship_block = (
        f"<b>Ship To:</b><br/>{po.site_name or '-'}<br/>"
        f"{(po.shipping_address or '').replace(chr(10), '<br/>')}<br/>"
        f"Contact: {po.contact_person or '-'} ({po.contact_number or '-'})"
    )
    addr = Table(
        [[Paragraph(vendor_block, small), Paragraph(ship_block, small)]],
        colWidths=[90 * mm, 90 * mm]
    )
    addr.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cccccc")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(addr)
    elements.append(Spacer(1, 10))

    # ---- Item table ----
    header = [
        "#", "Material", "Brand", "Qty", "Unit",
        "Rate", "Disc%", "GST%", "Landed", "Amount"
    ]
    data = [header]
    for idx, it in enumerate(items, start=1):
        data.append([
            str(idx),
            Paragraph(it.material_name or "-", small),
            Paragraph(it.brand or "-", small),
            _fmt(it.ordered_quantity),
            it.unit or "-",
            _fmt(it.basic_rate),
            _fmt(it.discount_percent),
            _fmt(it.tax_percent),
            _fmt(it.final_landed_rate),
            _fmt(it.total_amount),
        ])

    item_table = Table(
        data,
        colWidths=[8 * mm, 42 * mm, 22 * mm, 16 * mm, 12 * mm,
                   18 * mm, 14 * mm, 12 * mm, 18 * mm, 20 * mm],
        repeatRows=1
    )
    item_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0d6efd")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
        ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#f5f8ff")]),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    elements.append(item_table)
    elements.append(Spacer(1, 8))

    # ---- Totals ----
    totals = [
        ["Freight Total", _fmt(po.freight_total)],
        ["Loading / Unloading", _fmt(po.loading_unloading_total)],
        ["Grand Total (INR)", _fmt(po.grand_total)],
    ]
    totals_table = Table(totals, colWidths=[45 * mm, 35 * mm])
    totals_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LINEABOVE", (0, -1), (-1, -1), 0.5, colors.black),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    right_align = Table(
        [[Spacer(1, 1), totals_table]],
        colWidths=[100 * mm, 80 * mm]
    )
    elements.append(right_align)
    elements.append(Spacer(1, 12))

    # ---- Terms ----
    if po.delivery_timeline:
        elements.append(Paragraph(
            f"<b>Delivery Timeline:</b> {po.delivery_timeline}", small
        ))
    if po.penalty_terms:
        elements.append(Paragraph(
            f"<b>Penalty Terms:</b> {po.penalty_terms}", small
        ))
    if po.terms_conditions:
        elements.append(Spacer(1, 4))
        elements.append(Paragraph("<b>Terms &amp; Conditions:</b>", small))
        for line in po.terms_conditions.split("\n"):
            if line.strip():
                elements.append(Paragraph(line.strip(), small))

    elements.append(Spacer(1, 24))

    # ---- Signature ----
    sign = Table(
        [[
            Paragraph("Prepared By<br/><br/>_______________", small),
            Paragraph(
                f"For {COMPANY_NAME}<br/><br/>_______________<br/>"
                "Authorised Signatory", small
            ),
        ]],
        colWidths=[90 * mm, 90 * mm]
    )
    sign.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
    ]))
    elements.append(sign)

    doc.build(elements)

    return file_path.replace("\\", "/")
