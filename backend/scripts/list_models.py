import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from google import genai

# Setup paths
root_dir = Path(__file__).parent.parent.parent
sys.path.append(str(root_dir / "backend"))

# Load env vars
load_dotenv(root_dir / ".env")

api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    # Try backend/.env as backup
    load_dotenv(root_dir / "backend" / ".env")
    api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    print("Error: GEMINI_API_KEY not found in .env files")
    sys.exit(1)

client = genai.Client(api_key=api_key)

print(f"Fetching available models for key ending in ...{api_key[-4:]}...\n")

try:
    # List models
    # Note: the new SDK (google-genai) usage might differ slightly from google-generativeai
    # We'll try to iterate and print.
    # Based on SDK: client.models.list()

    print(f"{'Model Name':<40} | {'Display Name':<30} | {'capabilities'}")
    print("-" * 100)

    for model in client.models.list():
        # Filter for recent/relevant models to keep it clean, or just show all
        name = model.name
        display_name = getattr(model, "display_name", "N/A")

        # Check for vision capability if possible, or just list generic ones
        # The new SDK models object might not explicitly list 'supported_generation_methods' in the same way
        # as the old library, but often implies it.
        # We'll print what we have.

        print(f"{name:<40} | {display_name:<30}")

except Exception as e:
    print(f"Error listing models: {e}")
    import traceback

    traceback.print_exc()
