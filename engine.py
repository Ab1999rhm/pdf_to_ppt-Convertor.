import warnings
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", message=".*duckduckgo_search.*renamed to.*ddgs.*")

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
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
OLLAMA_BASE_URL = "http://localhost:11434"
CACHE_DIR = os.path.join(os.getcwd(), ".ppt_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

try:
    from groq import Groq
    groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
except ImportError:
    groq_client = None

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
# Ollama / Cloud Fallbacks
# ---------------------------------------------------------------------------
def _groq_generate(prompt: str) -> Optional[str]:
    """Call Groq API as a high-speed cloud fallback."""
    if not groq_client: return None
    try:
        chat_completion = groq_client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.3-70b-versatile",
            temperature=0.2,
        )
        return chat_completion.choices[0].message.content
    except Exception as e:
        print(f"[Groq] Error: {e}")
        return None

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
        # Check Groq First as it's faster
        groq_text = _groq_generate(prompt)
        if groq_text: return _OllamaResponse(groq_text)
        
        ollama_text = _ollama_generate("llama3", prompt)
        if ollama_text: return _OllamaResponse(ollama_text)
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
                
                # Try Groq as next best option
                print("[AI] Gemini quota reached, trying Groq...")
                groq_text = _groq_generate(prompt)
                if groq_text:
                    return _OllamaResponse(groq_text)
                continue
        time.sleep(2)
    
    ollama_text = _ollama_generate("llama3", prompt)
    if ollama_text:
        return _OllamaResponse(ollama_text)
    raise RuntimeError("All AI backends exhausted")

# ---------------------------------------------------------------------------
# PDF Functions
# ---------------------------------------------------------------------------
def extract_first_page_image(pdf_path: str, output_dir: str):
    """Extracts the first page of the PDF as an image for the cover slide."""
    try:
        doc = fitz.open(pdf_path)
        page = doc.load_page(0)
        pix = page.get_pixmap(dpi=150)
        path = os.path.join(output_dir, "cover_page.png")
        pix.save(path)
        doc.close()
        return path
    except:
        return None

# ---------------------------------------------------------------------------
# Metadata & Note Extraction
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

def generate_speaker_notes(slide_title: str, bullets: list, context: str = "") -> str:
    """Uses AI to generate a 3-4 sentence presentation script for a slide."""
    prompt = f"Write 3-4 professional speaker note sentences for: {slide_title}\nBullets: {bullets}\nContext: {context}"
    try: 
        return generate_with_failover(prompt).text.strip()
    except Exception as e: 
        print(f"[Notes] Error: {e}")
        return ""

# ---------------------------------------------------------------------------
# Helper Functions for Formatting Bullets
# ---------------------------------------------------------------------------
def clean_text_for_bullet(text: str, max_length: int = 150) -> str:
    """Clean and truncate text for bullet points."""
    # Remove Roman numerals (i, ii, iii, iv, etc.) at start
    text = re.sub(r'^[ivxlc]+\.?\s+', '', text, flags=re.IGNORECASE)
    # Remove Table of Contents dots
    text = re.sub(r'\.{3,}', '', text)
    # Remove stray page numbers at end
    text = re.sub(r'\s+\d+$', '', text)
    
    text = re.sub(r'\s+', ' ', text).strip()
    # Remove numbering like 1.1 or 1.
    text = re.sub(r'^\d+\.?\d*\.?\s*', '', text)
    
    # Truncate if too long (Optimized for substantial 2-3 line bullets)
    if len(text) > 300:
        text = text[:297] + "..."
    return text

def extract_key_bullets_from_text(text: str, max_bullets: int = 5) -> List[str]:
    """Extract key bullet points from text."""
    sentences = re.split(r'(?<=[.!?])\s+', text)
    bullets = []
    for sent in sentences:
        sent = sent.strip()
        # SCRUB: Aggressively remove ID numbers or institutional headers
        sent = re.sub(r'(?i)(?:ID No|DIRE DAWA UNIVERSITY|SCHOOL OF|DEPARTMENT OF).*', '', sent).strip()
        
        if len(sent) > 25 and len(sent) < 250 and not sent.isdigit():
            cleaned = clean_text_for_bullet(sent, 180)
            if cleaned and len(cleaned) > 15:
                bullets.append(cleaned)
        if len(bullets) >= max_bullets: break
    
    if not bullets:
        phrases = re.split(r'[;,]\s+', text)
        for phrase in phrases[:max_bullets]:
            phrase = phrase.strip()
            if len(phrase) > 20 and len(phrase) < 150:
                bullets.append(clean_text_for_bullet(phrase))
    return bullets

# ---------------------------------------------------------------------------
# Extraction Strategies
# ---------------------------------------------------------------------------
def generate_ai_synthesized_slides(full_text: str, max_slides: int, progress_callback=None):
    """Deep synthesis using AI, with chunked generation to avoid truncation."""
    all_slides = []
    batch_size = 10  # Process in batches of 10 slides to avoid token limits
    
    for start in range(0, max_slides, batch_size):
        remaining = max_slides - start
        current_batch = min(batch_size, remaining)
        
        # Guide the AI to continue where it left off
        offset_context = f"This is part {start//batch_size + 1} of the presentation. Focus on slides {start+1} to {start+current_batch}."
        
        prompt = f"""
        Analyze this document and create technical slides {start+1} to {start+current_batch} (Total {current_batch} slides).
        {offset_context}
        
        For each slide, provide a Title and exactly 5 SUBSTANTIAL TECHNICAL bullet points.
        
        STRICT WRITING RULES:
        - Every bullet must be a clear, informative statement of 2 to 3 lines.
        - Avoid fragments like "Financial loss" or "Personal stress".
        - Focus on the technical 'How' and 'Why' (e.g., "Attackers utilize generative AI to automate the creation of hyper-personalized lures, which allows them to bypass traditional pattern-based filters that only detect simple spelling errors.")
        - Ensure each point provides enough detail to be understandable without reading the original PDF.
        
        JSON Output Format:
        {{
          "slides": [
            {{"title": "Slide Title", "bullets": ["detailed substantial sentence 1", "detailed substantial sentence 2", "detailed substantial sentence 3", "detailed substantial sentence 4", "detailed substantial sentence 5"]}}
          ]
        }}
        Document Content Fragment: {full_text[start*4000 : (start*4000) + 20000]}
        """
        try:
            response = generate_with_failover(prompt)
            raw_text = response.text
            
            # Robust JSON extraction
            json_match = re.search(r'(\{.*\})', raw_text, re.DOTALL)
            if json_match:
                clean_json = json_match.group(1).strip()
                # Fix minor truncation/format errors
                clean_json = re.sub(r'\}\s*\{', '},{', clean_json)
                clean_json = re.sub(r',\s*\]|,\s*\}', ']', clean_json)
                
                try:
                    data = json.loads(clean_json)
                    batch_slides = data.get("slides", [])
                    all_slides.extend(batch_slides)
                except:
                    # Fallback to ast for partial repair
                    import ast
                    try:
                        data = ast.literal_eval(clean_json)
                        all_slides.extend(data.get("slides", []))
                    except: pass
            
            if progress_callback:
                progress_callback(min(start + batch_size, max_slides), max_slides)
                
        except Exception as e:
            print(f"[AI] Batch Error: {e}")
            
    return {"slides": all_slides}

def generate_preserve_structure_slides(full_text: str, max_slides: int, progress_callback=None):
    """Maintains original document flow by extracting sections and their main points."""
    sections = re.split(r'\n(?=\d+\.\s+[A-Z])', full_text)
    if len(sections) < 3:
        sections = re.split(r'\n(?=[A-Z][A-Z\s]{5,}\n)', full_text)
    
    slides = []
    for i, section in enumerate(sections[:max_slides]):
        lines = section.strip().split('\n')
        if not lines: continue
        title = lines[0].strip()[:80]
        body = " ".join(lines[1:])
        bullets = extract_key_bullets_from_text(body, 5)
        # Filter for the most descriptive bullets
        bullets = [b for b in bullets if len(b) > 40]
        if bullets:
            slides.append({"title": title, "bullets": bullets[:5]})
    
    return {"slides": slides}

def extract_pdf_data(pdf_path: str, max_slides: int = 15, strategy: str = "ai_synthesized", use_external: bool = False, progress_callback=None, doc_type: str = "auto"):
    """Main entry point for extracting and structuring PDF data."""
    try:
        doc = fitz.open(pdf_path)
        full_text = ""
        for page in doc:
            full_text += page.get_text()
        doc.close()
    except Exception as e:
        print(f"[PDF] Error: {e}")
        return {"slides": []}

    student_name, student_id, academic_title = extract_document_metadata(full_text)
    
    if not full_text:
        return {"slides": [], "student_name": "Author", "student_id": "", "academic_title": ""}
    
    if strategy == "ai_synthesized":
        result = generate_ai_synthesized_slides(full_text, max_slides, progress_callback)
    else:
        result = generate_preserve_structure_slides(full_text, max_slides, progress_callback)
        
    result["student_name"] = student_name
    result["student_id"] = student_id
    result["academic_title"] = academic_title
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
    if len(topic) < 10 or "...." in topic: return None
    time.sleep(random.uniform(5.0, 8.0))
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with DDGS() as ddgs:
                results = list(ddgs.images(keywords=topic, max_results=3))
                if results:
                    url = results[0].get("image", "")
                    if url and download_image(url, os.path.join(save_dir, f"{filename}.jpg")):
                        return os.path.join(save_dir, f"{filename}.jpg")
    except Exception as e:
        if "403" in str(e): print(f"[Image] Rate-limited for: {topic[:20]}")
    return None

if __name__ == "__main__":
    print("PDF to Slides Pipeline Ready.")