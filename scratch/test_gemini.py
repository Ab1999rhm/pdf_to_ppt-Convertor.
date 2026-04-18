import google.generativeai as genai
import os
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

print(f"Testing Gemini with key: {api_key[:5]}...{api_key[-5:] if api_key else 'NONE'}")

if not api_key:
    print("No API key found in .env")
    exit(1)

try:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-1.5-flash')
    response = model.generate_content("Hello, can you hear me?")
    print("Response successful!")
    print(response.text)
except Exception as e:
    print(f"Error occurred: {e}")
