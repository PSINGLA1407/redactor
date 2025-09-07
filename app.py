# app.py
import argparse, os, sys, subprocess, shlex, pathlib

HERE = pathlib.Path(__file__).parent.resolve()

def run(cmd_list):
    print("▶", " ".join(shlex.quote(c) for c in cmd_list))
    p = subprocess.Popen(cmd_list, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for line in p.stdout:
        print(line, end="")
    p.wait()
    if p.returncode != 0:
        raise SystemExit(f"❌ step failed: {p.returncode}")

def main():
    ap = argparse.ArgumentParser(description="PDF → OCR → (PII) → Redact pipeline")
    ap.add_argument("pdf", help="Input PDF path")
    ap.add_argument("--out-base", help="Output base name (default: input filename w/o ext)")
    ap.add_argument("--skip-pii", action="store_true")
    ap.add_argument("--skip-redact", action="store_true")
    args = ap.parse_args()

    pdf = os.path.abspath(args.pdf)
    if not os.path.exists(pdf):
        raise SystemExit("PDF not found")

    out_base = args.out_base or os.path.splitext(os.path.basename(pdf))[0]
    out_base = os.path.abspath(out_base)

    positions = f"{out_base}.positions.json"
    with_pii  = f"{out_base}.with_pii.json"
    redacted  = f"{out_base}.redacted.pdf"

    # step 1 OCR
    if not os.path.exists(positions):
        print("\n=== Step 1: OCR ===")
        run([sys.executable, str(HERE / "pos-ocr.py"), pdf, out_base])
    else:
        print(f"ℹ using existing {positions}")

    # step 2 PII
    if not args.skip_pii:
        print("\n=== Step 2: PII Identify ===")
        run([sys.executable, str(HERE / "pii-identifier.py"), positions, with_pii])
    else:
        print("ℹ skipping PII")

    # step 3 Redact
    if not args.skip_redact:
        print("\n=== Step 3: Redact ===")
        run([sys.executable, str(HERE / "redactor.py"), pdf, with_pii, redacted])
    else:
        print("ℹ skipping redact")

    print("\n✅ pipeline complete")
    print("positions:", positions)
    print("with_pii: ", with_pii)
    print("redacted: ", redacted)

if __name__ == "__main__":
    main()
reamlit_app.py
