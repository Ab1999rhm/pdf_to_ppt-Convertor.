import fitz  # PyMuPDF
from sumy.parsers.plaintext import PlaintextParser
from sumy.nlp.tokenizers import Tokenizer
from sumy.summarizers.text_rank import TextRankSummarizer
import nltk
from duckduckgo_search import DDGS
import os
import requests
import re
from urllib.parse import urlparse

# Ensure NLTK punkt is available
try:
    nltk.data.find('tokenizers/punkt')
    nltk.data.find('tokenizers/punkt_tab')
except LookupError:
    nltk.download('punkt')
    nltk.download('punkt_tab')

def clean_text(text):
    # Remove excessive newlines and spaces
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def summarize_text(text, sentences_count=3):
    if not text or len(text.split()) < 10:
        return [text] if text else []
    
    parser = PlaintextParser.from_string(text, Tokenizer("english"))
    summarizer = TextRankSummarizer()
    summary = summarizer(parser.document, sentences_count)
    return [str(sentence) for sentence in summary]

def extract_pdf_data(pdf_path):
    # Extracts text per page, summarizes it, and tries to get a topic
    pdf_doc = fitz.open(pdf_path)
    slides_data = []
    
    for page_num in range(len(pdf_doc)):
        page = pdf_doc.load_page(page_num)
        text = page.get_text()
        text = clean_text(text)
        
        if not text:
            continue
            
        # Simplistic heuristic: first few words as title
        words = text.split()
        title = " ".join(words[:5]) + "..." if len(words) > 5 else text
        
        # Summarize
        bullets = summarize_text(text, sentences_count=4)
        if not bullets:
            bullets = [text[:100] + "..."] # fallback
            
        slides_data.append({
            "title": title,
            "bullets": bullets,
            "raw_text": text
        })
        
    pdf_doc.close()
    return slides_data

def download_image(url, save_path):
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        with open(save_path, 'wb') as f:
            f.write(response.content)
        return True
    except Exception as e:
        print(f"Failed to download {url}: {e}")
        return False

def fetch_image_for_topic(topic, save_dir, filename):
    try:
        # Search for an image using DDG
        results = DDGS().images(
            keywords=topic,
            region="wt-wt",
            safesearch="moderate",
            size="Medium",
            max_results=3
        )
        for r in results:
            image_url = r.get("image")
            if image_url:
                os.makedirs(save_dir, exist_ok=True)
                ext = ".jpg" # Default
                parsed_url = urlparse(image_url)
                if parsed_url.path:
                    _, url_ext = os.path.splitext(parsed_url.path)
                    if url_ext.lower() in ['.jpg', '.jpeg', '.png']:
                        ext = url_ext.lower()
                
                save_path = os.path.join(save_dir, filename + ext)
                if download_image(image_url, save_path):
                    return save_path
        return None
    except Exception as e:
        print(f"Error fetching image for {topic}: {e}")
        return None
