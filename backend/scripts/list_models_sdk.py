import os

from dotenv import load_dotenv
from google import genai

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=api_key)

print("Listing available models:")
for m in client.models.list():
    print(
        f"Name: {m.name}, Supported Methods: {getattr(m, 'supported_generation_methods', 'Unknown')}"
    )
