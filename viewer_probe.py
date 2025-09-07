import pathlib, streamlit as st
from streamlit_pdf_viewer import pdf_viewer  # this package is installed

st.title("pdf_viewer probe")

pdf_path = pathlib.Path("sample.pdf")
if not pdf_path.exists():
    st.error("Put a small sample.pdf next to this file and rerun.")
    st.stop()

data = pdf_path.read_bytes()

st.write("### Try calling with BYTES")
ok = False
try:
    # many versions accept bytes as the first (or 'input=') arg
    pdf_viewer(data, width=800, height=600)              # positional
    # pdf_viewer(input=data, width=800, height=600)      # some builds need named param
    ok = True
except Exception as e:
    st.error(f"bytes call raised: {e}")

st.write("---")
st.write("### Try calling with PATH")
try:
    # some versions accept a string path instead of bytes
    pdf_viewer(str(pdf_path), width=800, height=600)
    ok = True
except Exception as e:
    st.error(f"path call raised: {e}")

if not ok:
    st.warning("pdf_viewer did not render via bytes or path. Falling back to image rendering below.")
    try:
        import fitz
        doc = fitz.open(str(pdf_path))
        st.write(f"(fallback) pages: {len(doc)}")
        for i in range(min(5, len(doc))):
            pix = doc[i].get_pixmap(matrix=fitz.Matrix(2, 2))
            st.image(pix.tobytes("png"), use_container_width=True)
        doc.close()
    except Exception as e:
        st.error(f"fallback failed too: {e}")
