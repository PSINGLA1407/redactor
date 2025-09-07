# redactor.py
# Usage:
#   python redactor.py input.pdf input.with_pii.json output.redacted.pdf
#                      [--dpi 300] [--margin 2]
#                      [--types email,phone,name,address,ip,id_number,other]
#                      [--label] [--label-size 8]
#
import argparse, json, sys
import fitz  # PyMuPDF

ALL_TYPES = {"name","email","phone","address","ip","id_number","other"}

# map pii.type -> short label burned on the box
TYPE_LABELS = {
    "name": "NAME",
    "email": "EMAIL",
    "phone": "PHONE",
    "address": "ADDRESS",
    "ip": "IP",
    "id_number": "ID",
    "other": "OTHER",
}

def parse_args():
    ap = argparse.ArgumentParser(description="Apply real PDF redactions from PII JSON")
    ap.add_argument("input_pdf")
    ap.add_argument("with_pii_json")
    ap.add_argument("output_pdf")
    ap.add_argument("--dpi", type=int, default=300, help="OCR render DPI used for positions.json (default 300)")
    ap.add_argument("--margin", type=float, default=2.0, help="Padding in image pixels around each bbox")
    ap.add_argument("--types", default="all",
                    help="Comma-separated PII types to redact (default 'all'). "
                         "Allowed: name,email,phone,address,ip,id_number,other")
    # NEW: optional label on black boxes
    ap.add_argument("--label", action="store_true", help="Print a short type label on each redaction box")
    ap.add_argument("--label-size", type=float, default=8.0, help="Label font size (points)")
    return ap.parse_args()

def load_pages(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    pages = data.get("pages")
    if not isinstance(pages, list):
        raise SystemExit("Invalid JSON: missing top-level 'pages' array.")
    return pages

def parse_types(s):
    if s.strip().lower() == "all":
        return ALL_TYPES
    chosen = {t.strip().lower() for t in s.split(",") if t.strip()}
    bad = chosen - ALL_TYPES
    if bad:
        print(f"WARNING: unknown types ignored: {', '.join(sorted(bad))}", file=sys.stderr)
    return (chosen & ALL_TYPES) or set()

def expand_bbox(b, margin):
    return {"x": b["x"] - margin, "y": b["y"] - margin, "w": b["w"] + 2*margin, "h": b["h"] + 2*margin}

def clamp_rect(rect, page_rect):
    # ensure rect stays within page bounds
    r = fitz.Rect(rect)
    r.intersect(page_rect)
    return r

def px_to_pdf_rect(bbox_px, scale):
    x0 = bbox_px["x"] * scale
    y0 = bbox_px["y"] * scale
    x1 = (bbox_px["x"] + bbox_px["w"]) * scale
    y1 = (bbox_px["y"] + bbox_px["h"]) * scale
    return fitz.Rect(x0, y0, x1, y1)

def label_for_type(t: str) -> str:
    t = (t or "other").lower()
    return TYPE_LABELS.get(t, "OTHER")

def main():
    args = parse_args()
    pages_json = load_pages(args.with_pii_json)
    wanted = parse_types(args.types)
    if not wanted:
        print("No valid PII types selected — nothing to do.", file=sys.stderr)
        sys.exit(0)

    scale = 72.0 / float(args.dpi)  # pixels -> points
    doc = fitz.open(args.input_pdf)

    total = 0
    for pinfo in pages_json:
        pno1 = int(pinfo.get("page") or 0)
        if pno1 < 1 or pno1 > len(doc):
            continue
        page = doc[pno1 - 1]
        page_rect = page.rect

        words = pinfo.get("words") or []
        boxes = []
        for w in words:
            pii = w.get("pii") or {}
            if not pii.get("is_pii"):
                continue
            wtype = str(pii.get("type") or "other").lower()
            if wtype not in wanted:
                continue
            b = w.get("bbox")
            if not b:
                continue
            expanded = expand_bbox(b, args.margin)
            rect = px_to_pdf_rect(expanded, scale)
            rect = clamp_rect(rect, page_rect)
            if rect.width > 0 and rect.height > 0:
                boxes.append((rect, wtype))

        added = 0
        for r, wtype in boxes:
            # True redaction annotation; black fill; optional white label text
            try:
                if args.label:
                    page.add_redact_annot(
                        r,
                        text=label_for_type(wtype),
                        fill=(0, 0, 0),
                        text_color=(1, 1, 1),
                        fontsize=args.label_size,
                        cross_out=False,
                    )
                else:
                    page.add_redact_annot(r, fill=(0, 0, 0))
                added += 1
            except Exception as e:
                # fallback: draw a black rectangle (not true redaction)
                page.draw_rect(r, fill=(0, 0, 0), color=None)
                added += 1

        total += added
        print(f"page {pno1}: added {added} boxes")

    # Apply redactions – support both new & old API
    apply_doc = getattr(doc, "apply_redactions", None)
    if callable(apply_doc):
        apply_doc()
    else:
        for p in doc:
            p.apply_redactions()

    doc.save(args.output_pdf, deflate=True, garbage=4)
    doc.close()
    print(f"[OK] redacted {total} boxes to {args.output_pdf}")

if __name__ == "__main__":
    main()
