import warnings
warnings.filterwarnings("ignore", category=FutureWarning)

import fitz  # PyMuPDF
import google.generativeai as genai
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
import os
import re
import json
import time
import random
import hashlib
import requests
from urllib.parse import urlparse
from duckduckgo_search import DDGS
from PIL import Image
import io
import traceback
from typing import Optional, Dict, List, Any, Tuple

# ---------------------------------------------------------------------------
# Environment & Constants
# ---------------------------------------------------------------------------
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
AI_STUDIO_API_KEY = os.getenv("AI_STUDIO_API_KEY")
OLLAMA_BASE_URL = "http://localhost:11434"
CACHE_DIR = os.path.join(os.getcwd(), ".ppt_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# API Key / Failover Manager
# ---------------------------------------------------------------------------
class APIKeyManager:
    def __init__(self):
        self.primary_key = GEMINI_API_KEY
        self.secondary_key = AI_STUDIO_API_KEY
        self.current_key = self.primary_key
        self.using_primary = True
        if self.current_key:
            self._configure()

    def _configure(self):
        if self.current_key:
            try:
                genai.configure(api_key=self.current_key)
                label = "PRIMARY" if self.using_primary else "SECONDARY"
                print(f"[AI] Gemini configured with {label} key.")
            except Exception as e:
                print(f"[AI] Gemini config error: {e}")
                self.current_key = None

    def switch_to_backup(self):
        if self.using_primary and self.secondary_key:
            print("[AI] Switching to backup key...")
            self.current_key = self.secondary_key
            self.using_primary = False
            self._configure()
            return True
        return False

    @staticmethod
    def is_quota_error(err: str) -> bool:
        markers = ["429", "quota", "rate limit", "limit: 0", "generaterequestsperd"]
        return any(m in err.lower() for m in markers)

key_manager = APIKeyManager()

# ---------------------------------------------------------------------------
# Ollama Helper
# ---------------------------------------------------------------------------
def _ollama_generate(model_name: str, prompt: str) -> Optional[str]:
    try:
        r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=10)
        if r.status_code != 200:
            return None
        available_models = [m['name'] for m in r.json().get('models', [])]
        if not available_models:
            return None
    except Exception:
        return None

    models_to_try = [model_name, "llama3", "mistral", "gemma:2b"]
    models_to_try = [m for m in models_to_try if any(m in avail for avail in available_models)]
    if not models_to_try:
        models_to_try = available_models[:3]

    for m in models_to_try:
        try:
            payload = {
                "model": m,
                "prompt": prompt[:12000],
                "stream": False,
                "options": {"temperature": 0.3, "num_predict": 2500}
            }
            if "json" in prompt.lower() and "slides" in prompt.lower():
                payload["format"] = "json"

            r = requests.post(f"{OLLAMA_BASE_URL}/api/generate", json=payload, timeout=120)
            if r.status_code == 200:
                text = r.json().get("response", "")
                if text and len(text) > 50:
                    return text
        except Exception:
            continue
    return None

class _OllamaResponse:
    def __init__(self, text: str):
        self.text = text

# ---------------------------------------------------------------------------
# Unified Generation
# ---------------------------------------------------------------------------
GEMINI_MODELS = ["gemini-1.5-flash", "gemini-1.5-flash-8b", "gemini-1.5-pro"]

def generate_with_failover(prompt: str, is_multimodal=None, max_retries=3):
    if not key_manager.current_key:
        ollama_text = _ollama_generate("llama3", prompt)
        if ollama_text:
            return _OllamaResponse(ollama_text)
        raise RuntimeError("No AI backends available")

    switched_once = False
    for attempt in range(max_retries):
        for model_name in GEMINI_MODELS:
            try:
                gmodel = genai.GenerativeModel(model_name)
                if is_multimodal:
                    response = gmodel.generate_content([prompt, is_multimodal])
                else:
                    response = gmodel.generate_content(prompt)
                
                if response and hasattr(response, 'text') and response.text:
                    return response
            except Exception as e:
                err = str(e)
                if key_manager.is_quota_error(err) and not switched_once:
                    if key_manager.switch_to_backup():
                        switched_once = True
                        break
                continue
        time.sleep(2)
    
    ollama_text = _ollama_generate("llama3", prompt)
    if ollama_text:
        return _OllamaResponse(ollama_text)
    raise RuntimeError("All AI backends exhausted")

# ---------------------------------------------------------------------------
# Cache Helpers
# ---------------------------------------------------------------------------
def _cache_key(pdf_path: str, max_slides: int, use_external: bool, strategy: str) -> str:
    with open(pdf_path, "rb") as f:
        h = hashlib.md5(f.read()).hexdigest()
    return f"{h}_{max_slides}_{use_external}_{strategy}"

def get_cached_result(key: str):
    path = os.path.join(CACHE_DIR, f"{key}.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return None

def save_cached_result(key: str, result: dict):
    path = os.path.join(CACHE_DIR, f"{key}.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[Cache] Error: {e}")

# ---------------------------------------------------------------------------
# PDF Utilities
# ---------------------------------------------------------------------------
def get_all_pdf_text(pdf_path: str) -> str:
    try:
        doc = fitz.open(pdf_path)
        parts = []
        for page in doc:
            text = page.get_text().strip()
            if text:
                parts.append(text)
        doc.close()
        return "\n\n".join(parts).strip()
    except Exception as e:
        print(f"[PDF] Error: {e}")
        return ""

def extract_first_page_image(pdf_path: str, output_dir: str):
    try:
        doc = fitz.open(pdf_path)
        pix = doc[0].get_pixmap(matrix=fitz.Matrix(2, 2))
        path = os.path.join(output_dir, "cover_page.png")
        pix.save(path)
        doc.close()
        return path
    except:
        return None

# ---------------------------------------------------------------------------
# Metadata Extraction
# ---------------------------------------------------------------------------
def extract_document_metadata(text: str, doc_type: str = "auto"):
    head = text[:3000]
    name, identifier, title = "Author", "", "Presentation"
    
    m = re.search(r'(?:name|prepared\s+by|author)[:\s]+([A-Za-z\s\.]+)', head, re.IGNORECASE)
    if m:
        name = m.group(1).strip()[:60]
    
    m = re.search(r'(?:id\s*[#:]|id\s*number|student\s+id)[:\s]+([\w/\-]+)', head, re.IGNORECASE)
    if m:
        identifier = m.group(1).strip()[:25]
    
    m = re.search(r'Title[:\s]+(.+?)(?:\n|$)', head, re.IGNORECASE)
    if m:
        title = m.group(1).strip()
    
    return name, identifier, title

# ---------------------------------------------------------------------------
# Helper Functions for Formatting Bullets
# ---------------------------------------------------------------------------
def clean_text_for_bullet(text: str, max_length: int = 150) -> str:
    """Clean and truncate text for bullet points."""
    # Remove extra whitespace
    text = re.sub(r'\s+', ' ', text)
    text = text.strip()
    
    # Remove numbering
    text = re.sub(r'^\d+\.\s*', '', text)
    text = re.sub(r'^[ivx]+\.\s*', '', text, flags=re.IGNORECASE)
    
    # Truncate if too long
    if len(text) > max_length:
        text = text[:max_length-3] + "..."
    
    return text

def extract_key_bullets_from_text(text: str, max_bullets: int = 5) -> List[str]:
    """Extract key bullet points from text - no raw text dumps."""
    # Split into sentences
    sentences = re.split(r'(?<=[.!?])\s+', text)
    
    bullets = []
    for sent in sentences:
        sent = sent.strip()
        # Filter for meaningful sentences
        if len(sent) > 25 and len(sent) < 200 and not sent.isdigit():
            cleaned = clean_text_for_bullet(sent, 150)
            if cleaned and len(cleaned) > 10:
                bullets.append(cleaned)
        
        if len(bullets) >= max_bullets:
            break
    
    # If no bullets found, try to extract phrases
    if not bullets:
        # Look for key phrases separated by commas or semicolons
        phrases = re.split(r'[;,]\s+', text)
        for phrase in phrases[:max_bullets]:
            phrase = phrase.strip()
            if len(phrase) > 20 and len(phrase) < 150:
                bullets.append(clean_text_for_bullet(phrase))
    
    return bullets

def extract_cover_info(text: str) -> dict:
    """Extract cover page information for slide 1."""
    info = {
        "university": "",
        "school": "",
        "department": "",
        "title": "",
        "name": "",
        "id": "",
        "date": ""
    }
    
    # Extract university/institution
    uni_match = re.search(r'(DIRE DAWA UNIVERSITY[^\n]*)', text, re.IGNORECASE)
    if uni_match:
        info["university"] = uni_match.group(1).strip()
    
    # Extract school
    school_match = re.search(r'(SCHOOL OF[^\n]*)', text, re.IGNORECASE)
    if school_match:
        info["school"] = school_match.group(1).strip()
    
    # Extract department
    dept_match = re.search(r'(DEPARTMENT OF[^\n]*)', text, re.IGNORECASE)
    if dept_match:
        info["department"] = dept_match.group(1).strip()
    
    # Extract title
    title_match = re.search(r'Title[:\s]+([^\n]+)', text, re.IGNORECASE)
    if title_match:
        info["title"] = title_match.group(1).strip()
    
    # Extract name
    name_match = re.search(r'NAME[:\s]+([A-Za-z\s]+?)(?:\n|ID)', text, re.IGNORECASE)
    if name_match:
        info["name"] = name_match.group(1).strip()
    
    # Extract ID
    id_match = re.search(r'ID No[:\s]+(\d+)', text, re.IGNORECASE)
    if id_match:
        info["id"] = id_match.group(1).strip()
    
    # Extract date
    date_match = re.search(r'Submit Date[:\s]+([^\n]+)', text, re.IGNORECASE)
    if date_match:
        info["date"] = date_match.group(1).strip()
    
    return info

def generate_cover_slide(text: str) -> dict:
    """Generate properly formatted cover slide."""
    info = extract_cover_info(text)
    
    bullets = []
    if info["university"]:
        bullets.append(info["university"])
    if info["school"]:
        bullets.append(info["school"])
    if info["department"]:
        bullets.append(info["department"])
    if info["title"]:
        bullets.append(f"Title: {info['title']}")
    if info["name"]:
        bullets.append(f"Presented by: {info['name']}")
    if info["id"]:
        bullets.append(f"ID: {info['id']}")
    if info["date"]:
        bullets.append(f"Date: {info['date']}")
    
    if not bullets:
        bullets = ["Academic Presentation"]
    
    return {
        "title": "Cover Page",
        "bullets": bullets[:6],
        "layout_type": "cover",
        "art_prompt": "university academic presentation cover"
    }

# ---------------------------------------------------------------------------
# Strategy 1: AI-Synthesized (Working correctly)
# ---------------------------------------------------------------------------
def generate_ai_synthesized_slides(full_text: str, max_slides: int, progress_callback=None) -> dict:
    """Generate slides using AI - this is working correctly."""
    print("[AI-Synthesized] Generating slides with AI...")
    
    # Clean the text
    clean_text = re.sub(r'DIRE DAWA UNIVERSITY.*?Submit Date:.*?\d{4}', '', full_text, flags=re.DOTALL|re.IGNORECASE)
    clean_text = re.sub(r'Abstract\s+.*?(?=\n\n|\d+\.)', '', clean_text, flags=re.DOTALL|re.IGNORECASE)
    
    # Get metadata
    name, sid, title = extract_document_metadata(full_text)
    
    # Create prompt for AI
    prompt = f"""Create exactly {max_slides} professional presentation slides from this academic text.

CRITICAL RULES:
1. Slide 1 must be a COVER PAGE with title, author, institution
2. Each content slide must have 3-5 bullet points (max 150 chars each)
3. NO raw text dumps - extract key insights only
4. Focus on: WHAT, WHY, and HOW

Output JSON format:
{{
  "slides": [
    {{"title": "Cover Page", "bullets": ["Institution", "Title", "Author", "Date"]}},
    {{"title": "Section Title", "bullets": ["Key point 1", "Key point 2", "Key point 3"]}}
  ]
}}

Text:
{clean_text[:20000]}

Return ONLY valid JSON."""
    
    try:
        response = generate_with_failover(prompt)
        raw = response.text
        
        # Extract JSON
        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            slides = data.get("slides", [])
            
            # Validate slides
            validated = []
            for slide in slides:
                if isinstance(slide, dict):
                    title = slide.get("title", "Slide")[:60]
                    bullets = slide.get("bullets", [])
                    # Clean bullets
                    clean_bullets = [clean_text_for_bullet(b, 150) for b in bullets[:5] if b and len(b) > 10]
                    if clean_bullets:
                        validated.append({
                            "title": title,
                            "bullets": clean_bullets,
                            "art_prompt": title[:50]
                        })
            
            if validated:
                print(f"[AI-Synthesized] Generated {len(validated)} slides")
                return {
                    "slides": validated[:max_slides],
                    "student_name": name,
                    "student_id": sid,
                    "academic_title": title
                }
    except Exception as e:
        print(f"[AI-Synthesized] Error: {e}")
    
    # Fallback
    return generate_preserve_structure_slides(full_text, max_slides, progress_callback)

# ---------------------------------------------------------------------------
# Strategy 2: Preserve PDF Structure (FIXED - No raw text dumps)
# ---------------------------------------------------------------------------
def extract_main_sections(text: str) -> List[Dict]:
    """Extract main sections only (no subsections like 2.1, 3.2)."""
    # Remove cover page content
    text = re.sub(r'DIRE DAWA UNIVERSITY.*?Submit Date:.*?\d{4}', '', text, flags=re.DOTALL|re.IGNORECASE)
    text = re.sub(r'Abstract\s+.*?(?=\n\n|\d+\.\s+[A-Z]|Introduction)', '', text, flags=re.DOTALL|re.IGNORECASE)
    text = re.sub(r'Table of Contents.*?(?=\n\n|\d+\.\s+[A-Z])', '', text, flags=re.DOTALL|re.IGNORECASE)
    
    # Define main section headers (not subsections)
    main_headers = [
        'introduction', 'background', 'literature review', 'related work',
        'methodology', 'methods', 'implementation', 'system architecture',
        'results', 'findings', 'discussion', 'analysis', 'evaluation',
        'conclusion', 'future work', 'recommendations', 'references'
    ]
    
    lines = text.split('\n')
    sections = []
    current_title = "Introduction"
    current_content = []
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        line_lower = line.lower()
        is_main_header = False
        
        # Skip subsections (patterns like 2.1, 3.2, 1.1.1)
        if re.match(r'^\d+\.\d+', line):
            current_content.append(line)
            continue
        
        # Check if this is a main section header
        for header in main_headers:
            if line_lower == header or line_lower.startswith(header + ' ') or line_lower.startswith(header + ':'):
                if len(line) < 60:
                    is_main_header = True
                    break
        
        # Check for numbered main sections (1. Introduction, 2. Background)
        if not is_main_header and re.match(r'^\d+\.\s+[A-Za-z]', line) and len(line) < 80:
            # Check it's not a subsection
            if not re.match(r'^\d+\.\d+', line):
                is_main_header = True
        
        # Check for ALL CAPS headers
        if not is_main_header and line.isupper() and 5 < len(line) < 50:
            if not re.match(r'^\d+\.\d+', line):
                is_main_header = True
        
        if is_main_header and current_content:
            if current_content:
                sections.append({
                    "title": current_title,
                    "content": ' '.join(current_content)
                })
            current_title = line[:50]
            current_content = []
        else:
            current_content.append(line)
    
    # Add last section
    if current_content:
        sections.append({
            "title": current_title,
            "content": ' '.join(current_content)
        })
    
    return sections

def generate_preserve_structure_slides(full_text: str, max_slides: int, progress_callback=None) -> dict:
    """Generate slides preserving PDF structure - FIXED: No raw text dumps."""
    print("[Preserve Structure] Extracting sections...")
    
    # Get metadata
    name, sid, title = extract_document_metadata(full_text)
    
    # Create cover slide
    slides = [generate_cover_slide(full_text)]
    
    if progress_callback:
        progress_callback(1, max_slides)
    
    # Extract main sections
    sections = extract_main_sections(full_text)
    
    if not sections:
        print("[Preserve Structure] No sections found, using fallback")
        # Create fallback sections from paragraphs
        paragraphs = full_text.split('\n\n')
        for i, para in enumerate(paragraphs[:max_slides-1]):
            if len(para.strip()) > 100:
                sections.append({
                    "title": f"Section {i+1}",
                    "content": para.strip()
                })
    
    print(f"[Preserve Structure] Found {len(sections)} sections")
    
    # Create content slides from sections
    for section in sections:
        if len(slides) >= max_slides:
            break
        
        content = section["content"]
        title = section["title"]
        
        # Extract key bullet points (not raw text)
        bullets = extract_key_bullets_from_text(content, max_bullets=5)
        
        # If no bullets extracted, create a summary bullet
        if not bullets:
            # Take first 150 chars as a summary
            summary = clean_text_for_bullet(content[:150], 150)
            if summary:
                bullets = [summary]
        
        if bullets:
            slides.append({
                "title": title[:60],
                "bullets": bullets[:5],  # Max 5 bullets
                "layout_type": "standard",
                "art_prompt": title[:50]
            })
            
            if progress_callback:
                progress_callback(len(slides), max_slides)
    
    # Trim to max_slides
    slides = slides[:max_slides]
    
    print(f"[Preserve Structure] Generated {len(slides)} slides")
    
    return {
        "slides": slides,
        "student_name": name,
        "student_id": sid,
        "academic_title": title
    }

# ---------------------------------------------------------------------------
# Strategy 3: Extract TOC First
# ---------------------------------------------------------------------------
def generate_toc_based_slides(full_text: str, max_slides: int, progress_callback=None) -> dict:
    """Generate slides by extracting TOC first."""
    print("[Extract TOC] Finding table of contents...")
    
    # Get metadata
    name, sid, title = extract_document_metadata(full_text)
    
    # Create cover slide
    slides = [generate_cover_slide(full_text)]
    
    if progress_callback:
        progress_callback(1, max_slides)
    
    # Extract sections (this serves as TOC)
    sections = extract_main_sections(full_text)
    
    if not sections:
        print("[Extract TOC] No sections found, using preserve structure fallback")
        return generate_preserve_structure_slides(full_text, max_slides, progress_callback)
    
    print(f"[Extract TOC] Found {len(sections)} sections")
    
    # Create detailed slides for each TOC entry
    remaining_slides = max_slides - 1
    slides_per_section = max(1, remaining_slides // len(sections))
    
    for section in sections:
        if len(slides) >= max_slides:
            break
        
        content = section["content"]
        base_title = section["title"]
        
        # Extract multiple bullet points from this section
        all_bullets = extract_key_bullets_from_text(content, max_bullets=slides_per_section * 4)
        
        # Distribute bullets across multiple slides if needed
        for i in range(slides_per_section):
            if len(slides) >= max_slides:
                break
            
            start_idx = i * 4
            end_idx = start_idx + 4
            slide_bullets = all_bullets[start_idx:end_idx]
            
            if not slide_bullets:
                break
            
            # Create slide title
            if slides_per_section > 1 and i > 0:
                slide_title = f"{base_title} (Part {i+1})"
            else:
                slide_title = base_title
            
            slides.append({
                "title": slide_title[:60],
                "bullets": slide_bullets[:5],
                "layout_type": "standard",
                "art_prompt": base_title[:50]
            })
            
            if progress_callback:
                progress_callback(len(slides), max_slides)
    
    # Trim to max_slides
    slides = slides[:max_slides]
    
    print(f"[Extract TOC] Generated {len(slides)} slides")
    
    return {
        "slides": slides,
        "student_name": name,
        "student_id": sid,
        "academic_title": title
    }

# ---------------------------------------------------------------------------
# Main Public Function
# ---------------------------------------------------------------------------
def extract_pdf_data(pdf_path: str, max_slides: int = 15, use_external: bool = False,
                     progress_callback=None, use_cache: bool = True,
                     strategy: str = "ai_synthesized", doc_type: str = "auto") -> dict:
    """Main function to extract and process PDF data into slides."""
    
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    
    if use_cache:
        key = _cache_key(pdf_path, max_slides, use_external, strategy)
        cached = get_cached_result(key)
        if cached:
            print("[Cache] Using cached result")
            return cached
    
    print(f"[PDF] Processing: {pdf_path}")
    full_text = get_all_pdf_text(pdf_path)
    
    if not full_text:
        print("[Error] No text extracted")
        return {"slides": [], "student_name": "Author", "student_id": "", "academic_title": ""}
    
    # Choose strategy
    if strategy == "ai_synthesized":
        result = generate_ai_synthesized_slides(full_text, max_slides, progress_callback)
    elif strategy == "preserve_structure":
        result = generate_preserve_structure_slides(full_text, max_slides, progress_callback)
    elif strategy == "extract_toc":
        result = generate_toc_based_slides(full_text, max_slides, progress_callback)
    else:
        result = generate_preserve_structure_slides(full_text, max_slides, progress_callback)
    
    if use_cache and result.get("slides"):
        save_cached_result(key, result)
    
    return result

# ---------------------------------------------------------------------------
# Image Functions
# ---------------------------------------------------------------------------
def download_image(url: str, save_path: str) -> bool:
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        r = requests.get(url, timeout=10, headers=headers)
        if r.status_code == 200:
            with open(save_path, "wb") as f:
                f.write(r.content)
            return True
    except:
        pass
    return False

def fetch_image_for_topic(topic: str, save_dir: str, filename: str):
    time.sleep(random.uniform(0.5, 1.5))
    try:
        with DDGS() as ddgs:
            results = list(ddgs.images(keywords=topic, max_results=3))
            if results:
                url = results[0].get("image", "")
                if url:
                    path = os.path.join(save_dir, f"{filename}.jpg")
                    if download_image(url, path):
                        return path
    except Exception as e:
        print(f"[Image] Error: {e}")
    return None

# ---------------------------------------------------------------------------
# Test Function
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("Testing PDF to Slides Converter...")
    
    test_pdf = "Abraham_Fikadu_seminar_software_Assignment.pdf"
    if os.path.exists(test_pdf):
        # Test preserve structure strategy
        print("\n=== Testing Preserve Structure Strategy ===")
        result = extract_pdf_data(test_pdf, max_slides=10, strategy="preserve_structure")
        
        print(f"\n✅ Generated {len(result['slides'])} slides")
        
        # Preview slides
        for i, slide in enumerate(result['slides'][:5], 1):
            print(f"\n📊 Slide {i}: {slide['title']}")
            for bullet in slide['bullets'][:3]:
                print(f"   • {bullet[:100]}")
    else:
        print(f"Test PDF not found: {test_pdf}")