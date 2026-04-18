# 👔 AI Professional Presentation Pipeline

A high-performance Python tool that transforms academic PDF papers into professional, real-world PowerPoint presentations using a 4-tier AI failover system.

## 🚀 Features
- **4-Tier AI Failover**: Gemini (Primary) → Gemini (Backup) → Groq (Llama 3 70B) → Ollama (Local).
- **Academic Standard**: Enforces a strict technical structure (WHAT/WHY/HOW) with exactly 5 bullets per slide.
- **Premium Design**: Built-in professional typography (Segoe UI), modern color themes, and automatic image fetching.
- **Automatic Scrubbing**: Removes institutional clutter (University headers, IDs) for a clean corporate look.

## 🛠️ Installation
1. Clone the repo:
   ```bash
   git clone <your-repo-url>
   cd pdf_ppt
   ```
2. Create and activate a virtual environment:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Create a `.env` file and add your keys:
   ```env
   GEMINI_API_KEY=your_key
   GROQ_API_KEY=your_key
   ```

## 💻 Usage
Run the Streamlit app:
```bash
streamlit run app.py
```

## 📜 License
MIT
