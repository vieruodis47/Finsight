import chromadb
import yfinance as yf
from dotenv import load_dotenv
import os
import google.generativeai as genai

load_dotenv()
print("✅ All imports working")

# Test yfinance
ticker = yf.Ticker("GPS")
info = ticker.info
print(f"✅ yfinance working — Gap market cap: {info.get('marketCap')}")

# Test ChromaDB
client = chromadb.Client()
collection = client.create_collection("test")
print("✅ ChromaDB working")

# Test Gemini
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-pro")
response = model.generate_content("Say hello in one word")
print(f"✅ Gemini working — {response.text}")
