# streamlit_app.py — OCR → PII → Redact pipeline with category toggles,
# side-by-side PDF preview, and a Redaction Report (JSON/CSV exports)

import csv
import io
import json
import pathlib
import shlex
import subprocess
import sys
from collections import Counter
from typing import Any

import streamlit as st
from streamlit_pdf_viewer import pdf_viewer    # pdf.js-based component
import fitz  # PyMuPDF (fallback image rendering)

HERE = pathlib.Path(__file__).parent.resolve()
WORKDIR = HERE / "workdir"
WORKDIR.mkdir(exist_ok=True)

# ----------------- helpers -----------------

def _run(cmd_list, workdir: pathlib.Path):
    """Run a command and stream logs into an expander; raise on nonzero exit."""
    with st.expander("Logs", expanded=False):
        st.write("```bash\n" + " ".join(shlex.quote(c) for c in cmd_list) + "\n```")
        ph = st.empty()
        p = subprocess.Popen(
            cmd_list,
            cwd=str(workdir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        buf = []
        while True:
            line = p.stdout.readline()
            if not line and p.poll() is not None:
                break
            if line:
                buf.append(line)
                ph.code("".join(buf)[-4000:])
        code = p.wait()
        if code != 0:
            st.error(f"Command failed ({code}). See logs above.")
            st.stop()

def _is_positions_json(path: pathlib.Path) -> bool:
    """Quick sanity check: JSON file exists and has a top-level 'pages' list."""
    try:
        if not path.exists() or path.suffix.lower() != ".json":
            return False
        data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
        return isinstance(data, dict) and isinstance(data.get("pages"), list)
    except Exception:
        return False

def _find_positions_json(workdir: pathlib.Path, out_base: pathlib.Path) -> pathlib.Path | None:
    """Find the positions JSON produced by pos-ocr.py (supports multiple naming styles)."""
    candidates = [
        out_base.with_suffix(".positions.json"),
        out_base.with_suffix(".json"),
    ]
    for c in candidates:
        if _is_positions_json(c):
            return c
    # fallback: any json in workdir
    for p in workdir.glob("*.json"):
        if _is_positions_json(p):
            return p
    return None

def render_pdf_in_streamlit(pdf_path: pathlib.Path, *, width=800, height=720):
    """
    Try pdf_viewer with BYTES, then PATH, else fallback to images.
    Handles version differences of streamlit-pdf-viewer and avoids blanks.
    """
    # try BYTES
    try:
        pdf_viewer(pdf_path.read_bytes(), width=width, height=height)
        return
    except Exception:
        pass
    # try PATH
    try:
        pdf_viewer(str(pdf_path), width=width, height=height)
        return
    except Exception:
        pass
    # fallback → images
    try:
        doc = fitz.open(str(pdf_path))
        pages = min(len(doc), 10)
        for i in range(pages):
            pix = doc[i].get_pixmap(matrix=fitz.Matrix(2, 2))
            st.image(pix.tobytes("png"), use_container_width=True)
        doc.close()
    except Exception as e:
        st.error(f"Could not render PDF (fallback failed): {e}")

# ---- PII normalization / filtering ----

_ID_ALIASES = {"ssn", "tax_id", "routing_number", "bank_account", "client_id"}
_NAME_ALIASES = {
    "name", "person", "personal_name", "full_name", "human_name",
    "first_name", "last_name", "surname", "given_name"
}

def _normalize_type(t: str | None) -> str:
    """Map model/tagger types into UI categories."""
    if not t:
        return "other"
    t = str(t).lower().strip()
    if t in _NAME_ALIASES:
        return "name"
    if t in {"email", "phone", "ip", "address", "id_number", "password", "other"}:
        return t
    if t in _ID_ALIASES:
        return "id_number"
    return "other"

def filter_pii(in_json: pathlib.Path, out_json: pathlib.Path, keep_types: list[str]) -> pathlib.Path:
    """
    Turn off PII flags for tokens whose normalized type is NOT in keep_types.
    Unknowns become non-PII unless 'other' is selected.
    """
    data = json.loads(in_json.read_text(encoding="utf-8"))
    pages = data.get("pages", [])
    for page in pages:
        for w in page.get("words", []):
            pii = w.get("pii") or {}
            if not pii.get("is_pii"):
                continue
            t = _normalize_type(pii.get("type"))
            if t not in keep_types:
                w["pii"]["is_pii"] = False
                w["pii"]["type"] = None
    out_json.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return out_json

# ---- Report helpers ----

def _safe_text(x: Any) -> str:
    s = x if isinstance(x, str) else ("" if x is None else str(x))
    return s.strip()

def _collect_context(words, idx, left_n=3, right_n=3) -> str:
    left = []
    j = idx - 1
    while j >= 0 and len(left) < left_n:
        t = _safe_text(words[j].get("text"))
        if t:
            left.append(t)
        j -= 1
    left.reverse()
    center = _safe_text(words[idx].get("text"))
    right = []
    j = idx + 1
    while j < len(words) and len(right) < right_n:
        t = _safe_text(words[j].get("text"))
        if t:
            right.append(t)
        j += 1
    return " ".join(left + [center] + right)

def build_redaction_report(pii_json_path: pathlib.Path) -> dict:
    """
    Build a detailed report from the (filtered) with_pii.json.
    Returns:
      {
        "summary": {"total": int, "by_type": {type: count}, "by_page": {page: count}},
        "items": [
          {
            "page": int, "index": int, "type": str, "source": str,
            "text": str, "confidence": float|None,
            "bbox": [x0,y0,x1,y1] or {"x","y","w","h"},
            "page_width": int, "page_height": int,
            "context": str
          }, ...
        ]
      }
    """
    data = json.loads(pii_json_path.read_text(encoding="utf-8"))
    items = []
    by_type, by_page = Counter(), Counter()
    total = 0

    for pg in data.get("pages", []):
        page_no = pg.get("page")
        width, height = pg.get("width"), pg.get("height")
        words = pg.get("words", [])
        for i, w in enumerate(words):
            pii = w.get("pii") or {}
            if not pii.get("is_pii"):
                continue
            typ = _normalize_type(pii.get("type"))
            src = _safe_text(pii.get("source") or "unknown")
            text = _safe_text(w.get("text"))
            conf = w.get("conf")
            try:
                conf = float(conf) if conf is not None else None
            except Exception:
                conf = None
            bbox = w.get("bbox") or w.get("box") or w.get("bbox_px")
            items.append({
                "page": page_no,
                "index": i,
                "type": typ,
                "source": src,
                "text": text,
                "confidence": conf,
                "bbox": bbox,
                "page_width": width,
                "page_height": height,
                "context": _collect_context(words, i, 3, 3),
            })
            by_type[typ] += 1
            by_page[page_no] += 1
            total += 1

    return {
        "summary": {
            "total": total,
            "by_type": dict(by_type),
            "by_page": dict(by_page),
        },
        "items": items,
    }

def report_to_csv_bytes(report: dict) -> bytes:
    buf = io.StringIO()
    wr = csv.writer(buf)
    wr.writerow(["page","index","type","source","text","confidence","bbox","page_width","page_height","context"])
    for r in report["items"]:
        wr.writerow([
            r.get("page"), r.get("index"), r.get("type"), r.get("source"),
            r.get("text"), r.get("confidence"), json.dumps(r.get("bbox")),
            r.get("page_width"), r.get("page_height"), r.get("context"),
        ])
    return buf.getvalue().encode("utf-8")

# ----------------- UI -----------------

st.set_page_config(page_title="PDF PII Redactor", page_icon="🕶️", layout="wide")
st.title("PDF PII Redactor")

with st.sidebar:
    st.subheader("OCR / Redaction Options")
    dpi = st.number_input("OCR DPI", min_value=150, max_value=600, value=300, step=50)
    psm = st.text_input("Tesseract PSM", value="6")
    lang = st.text_input("Tesseract language", value="eng")
    tesseract_path = st.text_input("Path to tesseract.exe (optional)", value="")
    margin = st.number_input("Redaction padding (px)", min_value=0, max_value=20, value=3, step=1)
    label_boxes = st.checkbox("Print type label on redaction boxes", value=True)
    label_size = st.number_input("Label font size (pt)", min_value=6.0, max_value=18.0, value=8.0, step=0.5)

    st.divider()
    st.subheader("PII Categories to Redact")
    redact_names = st.checkbox("Names (personal names)", value=True)
    redact_email = st.checkbox("Email", value=True)
    redact_phone = st.checkbox("Phone", value=True)
    redact_ip = st.checkbox("IP Address", value=True)
    redact_address = st.checkbox("Postal Address", value=True)
    redact_id = st.checkbox("ID Numbers (SSN, Tax ID, Bank, etc.)", value=True)
    redact_password = st.checkbox("Passwords / Secrets / Tokens", value=True)
    redact_other = st.checkbox("Other (usernames, misc.)", value=True)
    st.caption("Unchecked categories will not be redacted. Unknown tags count as 'Other'.")

    st.divider()
    run_pii = st.checkbox("Run PII identification (Gemini)", value=True)
    run_redact = st.checkbox("Run redaction", value=True)

pdf_file = st.file_uploader("Upload a PDF", type=["pdf"])
run_btn = st.button("Run")

if run_btn:
    if not pdf_file:
        st.error("Upload a PDF first.")
        st.stop()

    # clean out old files in workdir (don’t nuke dirs)
    for f in WORKDIR.iterdir():
        try:
            if f.is_file():
                f.unlink()
        except Exception:
            pass

    status = st.empty()
    bar = st.progress(0)

    in_pdf = WORKDIR / pdf_file.name
    in_pdf.write_bytes(pdf_file.read())
    out_base = WORKDIR / in_pdf.stem

    positions_json = None
    with_pii_path = None
    filtered_pii_path = None
    redacted_pdf = out_base.with_suffix(".redacted.pdf")

    try:
        # Step 1: OCR
        status.text("Running OCR…")
        cmd = [
            sys.executable, str(HERE / "pos-ocr.py"),
            str(in_pdf), str(out_base),
            "--dpi", str(dpi), "--lang", lang, "--psm", psm,
        ]
        if tesseract_path.strip():
            cmd += ["--tesseract", tesseract_path.strip()]
        _run(cmd, HERE)
        bar.progress(30)

        positions_json = _find_positions_json(WORKDIR, out_base)
        if not positions_json:
            st.error("Could not locate positions JSON produced by pos-ocr.py.")
            st.stop()

        # Step 2: PII (Gemini)
        if run_pii:
            status.text("Identifying PII…")
            with_pii_path = out_base.with_suffix(".with_pii.json")
            cmd = [
                sys.executable, str(HERE / "pii-identifier.py"),
                str(positions_json), str(with_pii_path),
            ]
            _run(cmd, HERE)
            bar.progress(60)

            # Category filter
            status.text("Filtering selected categories…")
            keep_types = []
            if redact_names: keep_types.append("name")
            if redact_email: keep_types.append("email")
            if redact_phone: keep_types.append("phone")
            if redact_ip: keep_types.append("ip")
            if redact_address: keep_types.append("address")
            if redact_id: keep_types.append("id_number")
            if redact_password: keep_types.append("password")
            if redact_other: keep_types.append("other")

            filtered_pii_path = out_base.with_suffix(".filtered_pii.json")
            with_pii_path = filter_pii(with_pii_path, filtered_pii_path, keep_types)
            bar.progress(70)
        else:
            bar.progress(55)

        # Step 3: Redaction
        if run_redact:
            if not with_pii_path or not pathlib.Path(with_pii_path).exists():
                st.error("Redaction needs a '*.with_pii.json'. Enable PII or provide one.")
                st.stop()
            status.text("Applying redactions…")
            cmd = [
                sys.executable, str(HERE / "redactor.py"),
                str(in_pdf), str(with_pii_path), str(redacted_pdf),
                "--dpi", str(dpi), "--margin", str(margin),
            ]
            if label_boxes:
                cmd += ["--label", "--label-size", str(label_size)]
            _run(cmd, HERE)
            bar.progress(85)
        else:
            bar.progress(80)

        # Step 4: Redaction Report
        status.text("Generating redaction report…")
        if with_pii_path and pathlib.Path(with_pii_path).exists():
            report = build_redaction_report(pathlib.Path(with_pii_path))
            report_json_bytes = json.dumps(report, indent=2).encode("utf-8")
            report_csv_bytes = report_to_csv_bytes(report)
        else:
            report = {"summary": {"total": 0, "by_type": {}, "by_page": {}}, "items": []}
            report_json_bytes = json.dumps(report, indent=2).encode("utf-8")
            report_csv_bytes = report_to_csv_bytes(report)

        bar.progress(100)
        status.text("Done")
        st.success("Pipeline complete.")

        # Side-by-side previews
        col1, col2 = st.columns(2, gap="large")
        with col1:
            st.subheader("Input PDF")
            render_pdf_in_streamlit(in_pdf)
            st.download_button("Download input PDF", in_pdf.read_bytes(), file_name=in_pdf.name)

        with col2:
            if redacted_pdf.exists():
                st.subheader("Redacted PDF")
                render_pdf_in_streamlit(redacted_pdf)
                st.download_button("Download redacted PDF", redacted_pdf.read_bytes(), file_name=redacted_pdf.name)
            else:
                st.subheader("Redacted PDF")
                st.info("Run with redaction enabled to see output here.")

        # ---- Redaction Report ----
        st.divider()
        st.subheader("Redaction Report")
        s = report["summary"]
        st.write(f"**Total redactions:** {s.get('total', 0)}")
        cols = st.columns(2)
        with cols[0]:
            st.write("**By Type**")
            st.json(s.get("by_type", {}))
        with cols[1]:
            st.write("**By Page**")
            st.json(s.get("by_page", {}))

        if report["items"]:
            preview = [
                {
                    "page": r["page"], "type": r["type"], "source": r["source"],
                    "text": r["text"], "confidence": r["confidence"], "context": r["context"],
                }
                for r in report["items"][:500]
            ]
            st.dataframe(preview, use_container_width=True, hide_index=True)
        else:
            st.info("No redactions recorded under the selected categories.")

        c1, c2 = st.columns(2)
        with c1:
            st.download_button(
                "Download Report (JSON)",
                data=report_json_bytes,
                file_name=f"{out_base.stem}.redaction_report.json",
                mime="application/json",
            )
        with c2:
            st.download_button(
                "Download Report (CSV)",
                data=report_csv_bytes,
                file_name=f"{out_base.stem}.redaction_report.csv",
                mime="text/csv",
            )

        # Artifacts
        st.divider()
        st.write("Artifacts")
        if positions_json and pathlib.Path(positions_json).exists():
            st.write(f"• positions: `{pathlib.Path(positions_json).name}`")
            st.download_button(
                "Download positions.json",
                pathlib.Path(positions_json).read_bytes(),
                file_name=pathlib.Path(positions_json).name,
            )
        if with_pii_path and pathlib.Path(with_pii_path).exists():
            st.write(f"• with_pii (filtered): `{pathlib.Path(with_pii_path).name}`")
            st.download_button(
                "Download with_pii.json",
                pathlib.Path(with_pii_path).read_bytes(),
                file_name=pathlib.Path(with_pii_path).name,
            )

    except Exception as e:
        st.error(f"Unexpected error: {e}")
        files = "\n".join(sorted(p.name for p in WORKDIR.glob('*')))
        st.text_area("Workdir contents", files, height=200)
        st.stop()
