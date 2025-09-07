import sys, os, json, argparse
import fitz  # PyMuPDF
from PIL import Image
import pytesseract

def parse_args():
    p = argparse.ArgumentParser(description="PDF OCR (PyMuPDF) with word boxes")
    p.add_argument("pdf", help="Input PDF path")
    p.add_argument("out_base", nargs="?", help="Output base name (no extension)")
    p.add_argument("--tesseract", default=None, help="Path to tesseract.exe (Windows)")
    p.add_argument("--dpi", type=int, default=300, help="Render DPI (default 300)")
    p.add_argument("--lang", default="eng", help="Language code (default eng)")
    p.add_argument("--psm", default="6", help="Tesseract PSM (default 6)")
    return p.parse_args()

def ensure_tesseract(tesseract_path: str | None):
    if tesseract_path:
        pytesseract.pytesseract.tesseract_cmd = tesseract_path
    try:
        _ = pytesseract.get_tesseract_version()
    except Exception:
        print("ERROR: Tesseract not found. Install it or pass --tesseract path.", file=sys.stderr)
        print("Windows installer: https://github.com/UB-Mannheim/tesseract/wiki", file=sys.stderr)
        sys.exit(1)

def pixmap_to_pil(pix: fitz.Pixmap) -> Image.Image:
    if pix.alpha:  # drop alpha for OCR
        pix = fitz.Pixmap(pix, 0)  # flatten
    mode = "RGB" if pix.n >= 3 else "L"
    return Image.frombytes(mode, [pix.width, pix.height], pix.samples)

def ocr_text_and_boxes(img: Image.Image, lang: str, psm: str):
    cfg = f"--psm {psm}"
    text = pytesseract.image_to_string(img, lang=lang, config=cfg) or ""

    data = pytesseract.image_to_data(img, lang=lang, config=cfg, output_type=pytesseract.Output.DICT)
    words = []
    n = len(data.get("text", []))
    for i in range(n):
        t = str(data["text"][i]).strip() if data["text"][i] is not None else ""
        if not t:
            continue
        # conf may be str or int depending on versions
        try:
            conf_val = int(data["conf"][i])
        except Exception:
            conf_val = -1
        words.append({
            "text": t,
            "bbox": {
                "x": int(data["left"][i]),
                "y": int(data["top"][i]),
                "w": int(data["width"][i]),
                "h": int(data["height"][i]),
            },
            "conf": conf_val,
            "source": "ocr"
        })
    return text, words

def main():
    args = parse_args()
    ensure_tesseract(args.tesseract)

    pdf_path = args.pdf
    if not os.path.exists(pdf_path):
        print(f"ERROR: PDF not found: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    out_base = args.out_base or os.path.splitext(os.path.basename(pdf_path))[0]
    out_txt = f"{out_base}.txt"
    out_json = f"{out_base}.positions.json"

    doc = fitz.open(pdf_path)
    positions = {"pages": []}

    with open(out_txt, "w", encoding="utf-8") as txtout:
        for page_num in range(len(doc)):
            page = doc[page_num]
            # render with DPI scaling
            zoom = args.dpi / 72.0
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img = pixmap_to_pil(pix)

            # OCR
            text, words = ocr_text_and_boxes(img, args.lang, args.psm)

            # write page text
            txtout.write(f"\n===== Page {page_num + 1} =====\n{text}\n")

            positions["pages"].append({
                "page": page_num + 1,
                "width": img.width,
                "height": img.height,
                "words": words
            })

            print(f"page {page_num + 1}/{len(doc)}: {len(words)} words")

    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(positions, f, indent=2)

    print(f"[OK] wrote {out_txt}")
    print(f"[OK] wrote {out_json}")

if __name__ == "__main__":
    main()
