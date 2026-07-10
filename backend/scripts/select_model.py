import os
import sys

import inquirer
from dotenv import load_dotenv, set_key
from google import genai

# Add backend to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ENV_PATH = "/home/mcgar/projects/grocery-tracker/.env"
load_dotenv(ENV_PATH)


def get_available_models():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not set in .env")
        return []

    try:
        client = genai.Client(api_key=api_key)
        # Fetch models - try to filter for vision/multimodal if possible, but list all for now
        models = []
        for m in client.models.list():
            # Basic filtering for likely candidates
            if "gemini" in m.name or "flash" in m.name:
                models.append(m.name.replace("models/", ""))
        return sorted(models)
    except Exception as e:
        print(f"Error fetching models: {e}")
        return []


def select_model():
    print("Fetching available Gemini models...")
    models = get_available_models()

    if not models:
        print("Could not fetch models. Using hardcoded defaults.")
        models = ["gemini-flash-latest", "gemini-2.0-flash", "gemini-1.5-flash"]

    current_model = os.getenv("GEMINI_MODEL_NAME", "gemini-flash-latest")

    questions = [
        inquirer.List(
            "model",
            message=f"Select Gemini Model (Current: {current_model})",
            choices=models,
            default=current_model,
            carousel=True,
        ),
    ]

    answers = inquirer.prompt(questions)
    if answers:
        selected_model = answers["model"]
        set_key(ENV_PATH, "GEMINI_MODEL_NAME", selected_model)
        print(f"✓ Updated .env with GEMINI_MODEL_NAME={selected_model}")
    else:
        print("Selection cancelled.")


if __name__ == "__main__":
    select_model()
