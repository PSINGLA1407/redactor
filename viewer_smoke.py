import pathlib, streamlit as st
from streamlit_pdf_viewer import pdf_viewer

st.title("smoke test")
pdf_path = pathlib.Path("sample.pdf")
if not pdf_path.exists():
    st.error("Put a small sample.pdf next to this file.")
else:
    pdf_viewer(pdf_path.read_bytes(), width=800, height=600, pages_to_render=[-1])
