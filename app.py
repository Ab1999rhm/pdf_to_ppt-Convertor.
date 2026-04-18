import streamlit as st
import os
import shutil
import fitz  # PyMuPDF
from engine import extract_pdf_data, fetch_image_for_topic, extract_first_page_image, generate_speaker_notes
from generator import generate_pptx, generate_html
import tempfile
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# Constants for validation
MAX_FILE_SIZE_MB = 50
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
MAX_PDF_PAGES = 100

st.set_page_config(page_title="PDF to AI Presentation", layout="wide", page_icon="🚀")

# Load environment variables
from dotenv import load_dotenv
load_dotenv()
GEMINI_READY = os.getenv("GEMINI_API_KEY") is not None

# Custom CSS for premium look
st.markdown("""
    <style>
    .main {
        background: radial-gradient(circle at top left, #1e2a4a 0%, #0d1117 100%);
        color: #e6edf3;
    }
    .stApp {
        background: radial-gradient(circle at top left, #1e2a4a 0%, #0d1117 100%);
    }
    .stButton>button {
        width: 100%;
        border-radius: 12px;
        height: 3.5em;
        background: linear-gradient(90deg, #4CAF50 0%, #45a049 100%);
        color: white;
        font-weight: bold;
        border: none;
        transition: all 0.3s ease;
        box-shadow: 0 4px 15px rgba(76, 175, 80, 0.3);
    }
    .stButton>button:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 20px rgba(76, 175, 80, 0.4);
    }
    .stDownloadButton>button {
        width: 100%;
        border-radius: 12px;
        background: linear-gradient(90deg, #008CBA 0%, #007bb5 100%);
        color: white;
        border: none;
        box-shadow: 0 4px 15px rgba(0, 140, 186, 0.3);
    }
    .css-1offfwp {
        background-color: rgba(255, 255, 255, 0.05);
        border-radius: 15px;
        padding: 20px;
        backdrop-filter: blur(10px);
    }
    h1, h2, h3 {
        color: #58a6ff !important;
        font-family: 'Inter', sans-serif;
    }
    </style>
    """, unsafe_allow_html=True)

st.title("PDF to AI Presentation Generator 🚀")
if GEMINI_READY:
    st.info("✅ Gemini AI is linked and ready for professional summarization.")
else:
    st.warning("⚠️ Gemini API Key not found. Using local summarizer (lower quality).")

st.write("Transform your PDFs into high-quality presentations using Gemini 1.5 Flash.")

# Setup directories
TEMP_DIR = os.path.join(os.getcwd(), "temp_workspace")
os.makedirs(TEMP_DIR, exist_ok=True)

st.header("📤 Upload Your Document")
uploaded_file = st.file_uploader(f"Upload a PDF file (Max {MAX_FILE_SIZE_MB}MB, {MAX_PDF_PAGES} pages)", type=["pdf"])

# Validate uploaded file immediately
if uploaded_file is not None:
    file_size = len(uploaded_file.getbuffer())
    if file_size > MAX_FILE_SIZE_BYTES:
        st.error(f"⚠️ File too large! Maximum size is {MAX_FILE_SIZE_MB}MB. Your file is {file_size / (1024*1024):.1f}MB.")
        uploaded_file = None
    else:
        # Check PDF page count
        try:
            pdf_bytes = uploaded_file.read()
            with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
                page_count = len(doc)
                if page_count > MAX_PDF_PAGES:
                    st.error(f"⚠️ PDF has too many pages! Maximum is {MAX_PDF_PAGES}. Your PDF has {page_count} pages.")
                    uploaded_file = None
                else:
                    st.info(f"✅ PDF validated: {page_count} pages, {len(pdf_bytes) / 1024:.1f}KB")
            uploaded_file.seek(0)  # Reset file pointer
        except Exception as e:
            st.error(f"⚠️ Could not read PDF: {str(e)}")
            uploaded_file = None

output_format = st.radio("Select Output Format:", ["PPTX (PowerPoint)", "HTML (Reveal.js Animated)"])

st.markdown("### Intelligence Options")
num_slides = st.slider("Target Number of Slides:", min_value=5, max_value=50, value=10)
use_external = st.checkbox("🚀 Supplement with External AI Knowledge", help="AI will add real-world context and extra details NOT found in the PDF.")

image_option = st.radio("How should images be handled?", 
                        ["Automatically fetch free images (DuckDuckGo Search)", 
                         "Do not use images"])

generate_notes = st.checkbox("📝 Generate Speaker Notes", help="AI will create speaker notes for each slide to help presenters explain the content.")

st.markdown("### 📑 Slide Generation Strategy")
generation_strategy = st.radio(
    "Choose how slides are created:",
    [
        "🤖 AI-Synthesized (Recommended) - AI redistributes content into your requested slide count",
        "📋 Preserve PDF Structure - Create slides for each major PDF section/heading",
        "📑 Extract TOC First - AI identifies all sections, then creates detailed slides for each"
    ],
    index=0,
    help="Select how you want the presentation structured"
)

strategy_map = {
    "🤖 AI-Synthesized (Recommended) - AI redistributes content into your requested slide count": "ai_synthesized",
    "📋 Preserve PDF Structure - Create slides for each major PDF section/heading": "preserve_structure",
    "📑 Extract TOC First - AI identifies all sections, then creates detailed slides for each": "extract_toc"
}
selected_strategy = strategy_map.get(generation_strategy, "ai_synthesized")

st.markdown("### 📄 Document Type")
doc_type = st.radio(
    "What type of document is this?",
    [
        "🔍 Auto-detect (Recommended)",
        "🎓 Academic Paper / Assignment",
        "💼 Business Report",
        "📚 General Document / Article",
        "📖 Book / E-book"
    ],
    index=0,
    help="Helps the AI understand how to extract titles and structure"
)

doc_type_map = {
    "🔍 Auto-detect (Recommended)": "auto",
    "🎓 Academic Paper / Assignment": "academic",
    "💼 Business Report": "business",
    "📚 General Document / Article": "general",
    "📖 Book / E-book": "general"
}
selected_doc_type = doc_type_map.get(doc_type, "auto")

st.markdown("### 🎨 Brand Customization")
col1, col2 = st.columns(2)
with col1:
    theme_color = st.selectbox("Theme Color:", ["Blue (Professional)", "Red (Bold)", "Green (Fresh)", "Purple (Creative)", "Dark (Modern)", "Premium Gold (Luxurious)"])
with col2:
    accent_color = st.selectbox("Accent Style:", ["Standard", "Gradient", "Minimal"])

# Cover page option
use_cover_page = st.checkbox("📄 Use PDF first page as cover slide background", value=True,
                              help="Uses the original PDF's cover page as the presentation title slide background")

# Theme mapping
theme_map = {
    "Blue (Professional)": "blue",
    "Red (Bold)": "red", 
    "Green (Fresh)": "green",
    "Purple (Creative)": "purple",
    "Dark (Modern)": "dark",
    "Premium Gold (Luxurious)": "premium_gold"
}
selected_theme = theme_map.get(theme_color, "blue")

if st.button("Generate Presentation") and uploaded_file is not None:
    st.write("DEBUG: Button clicked, starting processing...")
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    try:
        # Step 1: Save PDF to temp
        status_text.text("Step 1/4: Saving PDF...")
        pdf_path = os.path.join(TEMP_DIR, uploaded_file.name)
        with open(pdf_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        progress_bar.progress(10)
        
        # Step 2: Extract and Synthesize Narrative
        status_text.text("Step 2/4: Extracting text and generating narrative with AI...")
        
        # Progress callback for chunk processing
        chunk_progress = st.empty()
        def update_chunk_progress(current, total):
            chunk_progress.text(f"Processing document section {current}/{total}...")
        
        result = extract_pdf_data(pdf_path, max_slides=num_slides, use_external=use_external,
                                  progress_callback=update_chunk_progress, strategy=selected_strategy,
                                  doc_type=selected_doc_type)
        chunk_progress.empty()
        
        slides_data = result.get("slides", [])
        
        # Step 2.5: Generate Speaker Notes if requested
        if generate_notes and slides_data:
            status_text.text("Step 2/4: Generating speaker notes (Parallel)...")
            notes_progress = st.progress(0)
            
            # Parallel note generation
            with ThreadPoolExecutor(max_workers=8) as executor:
                futures = {
                    executor.submit(
                        generate_speaker_notes, 
                        slide.get('title', ''), 
                        slide.get('bullets', []), 
                        f"Slide {i+1}"
                    ): i for i, slide in enumerate(slides_data)
                }
                
                done_count = 0
                for future in as_completed(futures):
                    idx = futures[future]
                    slides_data[idx]['speaker_notes'] = future.result()
                    done_count += 1
                    notes_progress.progress(int((done_count / len(slides_data)) * 100))
            
            notes_progress.empty()
            st.success(f"✅ Generated speaker notes for {len(slides_data)} slides in record time!")
        
        # Support both old academic fields and new generic fields
        author_name = result.get("author_name") or result.get("student_name", "Author")
        doc_identifier = result.get("doc_identifier") or result.get("student_id", "")
        document_title = result.get("document_title") or result.get("academic_title", "")
        if not document_title and slides_data:
            document_title = slides_data[0].get("title", "Presentation")
        progress_bar.progress(40)
        
        if not slides_data:
            st.error("❌ No text could be extracted from the PDF. The PDF may be scanned images or empty.")
            status_text.empty()
            progress_bar.empty()
        else:
            st.write(f"DEBUG: slides_data has {len(slides_data)} slides")
            st.success(f"✅ Successfully generated narrative with {len(slides_data)} slides!")
            if author_name and author_name != "Unknown":
                if doc_identifier:
                    st.info(f"✨ Document by: {author_name} ({doc_identifier})")
                else:
                    st.info(f"✨ Document by: {author_name}")
            
            # Slide Preview & Editing Section
            st.markdown("---")
            st.subheader("📊 Slide Preview & Editor")
            st.write("Review and edit your slides before downloading:")
            
            # Edit mode toggle
            edit_mode = st.toggle("✏️ Enable Edit Mode", help="Turn on to edit slide content")
            
            # Fact-check warning
            with st.expander("⚠️ AI Content Verification", expanded=False):
                st.warning("This content was generated by AI. Please verify technical details and key facts before presenting.")
                st.info("Tip: Cross-reference important statistics, dates, and technical specifications with your source material.")
            
            # Create tabs for slide preview
            preview_tabs = st.tabs([f"Slide {i+1}" for i in range(min(len(slides_data), 10))])
            
            for idx, tab in enumerate(preview_tabs):
                with tab:
                    slide = slides_data[idx]
                    
                    if edit_mode:
                        # Edit mode - allow modifications
                        st.markdown("**Edit Slide Content:**")
                        new_title = st.text_input(f"Title {idx}", slide.get('title', ''), key=f"title_{idx}")
                        slide['title'] = new_title
                        
                        st.markdown("**Bullet Points:**")
                        bullets = slide.get('bullets', [])
                        new_bullets = []
                        for b_idx, bullet in enumerate(bullets):
                            new_bullet = st.text_area(f"Bullet {b_idx+1}", bullet, key=f"bullet_{idx}_{b_idx}", height=60)
                            new_bullets.append(new_bullet)
                        slide['bullets'] = new_bullets
                        
                        # Add new bullet option
                        if st.button(f"➕ Add Bullet", key=f"add_bullet_{idx}"):
                            slide['bullets'].append("New bullet point")
                            st.rerun()
                        
                        # Speaker notes edit
                        if slide.get('speaker_notes'):
                            new_notes = st.text_area("Speaker Notes", slide['speaker_notes'], key=f"notes_{idx}", height=80)
                            slide['speaker_notes'] = new_notes
                        
                        # Collaboration - comments
                        st.markdown("---")
                        st.markdown("💬 **Collaboration**")
                        if 'comments' not in slide:
                            slide['comments'] = []
                        
                        # Show existing comments
                        for c_idx, comment in enumerate(slide['comments']):
                            col1, col2 = st.columns([5, 1])
                            with col1:
                                st.info(f"📝 {comment}")
                            with col2:
                                if st.button("🗑️", key=f"del_comment_{idx}_{c_idx}"):
                                    slide['comments'].pop(c_idx)
                                    st.rerun()
                        
                        # Add new comment
                        new_comment = st.text_input("Add comment/feedback:", key=f"new_comment_{idx}")
                        if st.button("💬 Add Comment", key=f"add_comment_{idx}") and new_comment:
                            slide['comments'].append(new_comment)
                            st.rerun()
                    else:
                        # View mode
                        col1, col2 = st.columns([2, 1])
                        
                        with col1:
                            st.markdown(f"**{slide.get('title', f'Slide {idx+1}')}**")
                            for bullet in slide.get('bullets', []):
                                st.markdown(f"• {bullet}")
                        
                        with col2:
                            if slide.get('image_path') and os.path.exists(slide['image_path']):
                                st.image(slide['image_path'], caption="Slide Image", use_container_width=True)
                            else:
                                st.info("No image")
                        
                        # Show speaker notes if available
                        if slide.get('speaker_notes'):
                            with st.expander("📝 Speaker Notes"):
                                st.write(slide['speaker_notes'])
            
            if len(slides_data) > 10:
                st.info(f"... and {len(slides_data) - 10} more slides")
            
            st.markdown("---")
            
            # Step 3: Fetch Images if requested
            if image_option == "Automatically fetch free images (DuckDuckGo Search)":
                status_text.text("Step 3/4: Fetching images (Parallel)...")
                image_progress = st.progress(0)
                
                with ThreadPoolExecutor(max_workers=5) as executor:
                    futures = {
                        executor.submit(
                            fetch_image_for_topic,
                            slide.get("art_prompt", slide.get("title", f"topic {i}")),
                            TEMP_DIR,
                            f"slide_{i}"
                        ): i for i, slide in enumerate(slides_data)
                    }
                    
                    done_img = 0
                    for future in as_completed(futures):
                        idx = futures[future]
                        slides_data[idx]["image_path"] = future.result()
                        done_img += 1
                        image_progress.progress(int((done_img / len(slides_data)) * 100))
                
                image_progress.empty()
                st.success(f"✅ Images downloaded successfully!")
            progress_bar.progress(70)
            
            # Step 4: Generate Format
            status_text.text("Step 4/4: Generating final presentation...")
            st.write(f"DEBUG: output_format = {output_format}")
            
            # Extract cover page image for first slide (only if enabled)
            cover_page_image = extract_first_page_image(pdf_path, TEMP_DIR) if use_cover_page else None
            
            if "PPTX" in output_format:
                st.write("DEBUG: Generating PPTX format")
                out_file = os.path.join(TEMP_DIR, "output.pptx")
                generate_pptx(slides_data, out_file, author_name, doc_identifier, theme=selected_theme, cover_page_image=cover_page_image, first_slide_title=document_title)
                mime = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
                filename = "presentation.pptx"
            else:
                out_file = os.path.join(TEMP_DIR, "index.html")
                generate_html(slides_data, out_file, author_name, doc_identifier)
                mime = "text/html"
                filename = "presentation.html"
            progress_bar.progress(100)
                
            status_text.empty()
            progress_bar.empty()
            
            # Export/Share options
            st.markdown("---")
            st.subheader("📤 Export & Share")
            
            col1, col2 = st.columns(2)
            with col1:
                # Provide Download
                with open(out_file, "rb") as f:
                    st.download_button(
                        label=f"⬇️ Download {filename}",
                        data=f,
                        file_name=filename,
                        mime=mime,
                        use_container_width=True
                    )
            
            with col2:
                # Export as JSON for sharing
                import json
                from datetime import datetime
                export_data = {
                    "slides": slides_data,
                    "author_name": author_name,
                    "doc_identifier": doc_identifier,
                    "document_title": document_title,
                    "theme": selected_theme,
                    "exported_at": datetime.now().isoformat()
                }
                json_str = json.dumps(export_data, indent=2)
                st.download_button(
                    label="📋 Export as JSON",
                    data=json_str,
                    file_name="presentation_data.json",
                    mime="application/json",
                    use_container_width=True
                )
            
            st.balloons()
            
    except Exception as e:
        st.error(f"❌ An error occurred: {str(e)}")
        status_text.empty()
        progress_bar.empty()
        
elif uploaded_file is None:
    st.info("Please upload a PDF to begin.")
