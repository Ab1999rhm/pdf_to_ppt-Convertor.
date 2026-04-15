import streamlit as st
import os
import shutil
from engine import extract_pdf_data, fetch_image_for_topic
from generator import generate_pptx, generate_html
import tempfile

st.set_page_config(page_title="PDF to Presentation", layout="wide")

st.title("PDF to Presentation Generator 🚀")
st.write("Convert your PDFs into beautifully structured PowerPoint or interactive HTML presentations automatically—no API keys required.")

# Setup directories
TEMP_DIR = os.path.join(os.getcwd(), "temp_workspace")
os.makedirs(TEMP_DIR, exist_ok=True)

uploaded_file = st.file_uploader("Upload a PDF file", type=["pdf"])
output_format = st.radio("Select Output Format:", ["PPTX (PowerPoint)", "HTML (Reveal.js Animated)"])

st.markdown("### Image Options")
image_option = st.radio("How should images be handled?", 
                        ["Automatically fetch free images (DuckDuckGo Search)", 
                         "Do not use images"])

if st.button("Generate Presentation") and uploaded_file is not None:
    with st.spinner("Processing PDF (Extracting & Summarizing)..."):
        # Save PDF to temp
        pdf_path = os.path.join(TEMP_DIR, uploaded_file.name)
        with open(pdf_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        
        # 1. Extract data
        slides_data = extract_pdf_data(pdf_path)
        
    if not slides_data:
        st.error("No text could be extracted from the PDF.")
    else:
        st.success(f"Successfully extracted {len(slides_data)} slides from PDF!")
        
        # 2. Fetch Images if requested
        if image_option == "Automatically fetch free images (DuckDuckGo Search)":
            with st.spinner("Fetching relevant images for slides..."):
                for idx, slide in enumerate(slides_data):
                    topic = slide.get("title", f"topic {idx}")
                    img_path = fetch_image_for_topic(topic, TEMP_DIR, f"slide_{idx}")
                    slide["image_path"] = img_path
        
        # 3. Generate Format
        with st.spinner(f"Generating {output_format} format..."):
            if "PPTX" in output_format:
                out_file = os.path.join(TEMP_DIR, "output.pptx")
                generate_pptx(slides_data, out_file)
                mime = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
                filename = "presentation.pptx"
            else:
                out_file = os.path.join(TEMP_DIR, "index.html")
                generate_html(slides_data, out_file)
                mime = "text/html"
                filename = "presentation.html"
                
        # 4. Provide Download
        with open(out_file, "rb") as f:
            st.download_button(
                label=f"⬇️ Download {filename}",
                data=f,
                file_name=filename,
                mime=mime
            )
        
        st.balloons()
        
elif uploaded_file is None:
    st.info("Please upload a PDF to begin.")
