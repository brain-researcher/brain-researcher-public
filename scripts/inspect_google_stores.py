
import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

try:
    from google import genai
except ImportError:
    print("Error: google-genai package not found. Please activate the correct environment.")
    sys.exit(1)

def list_stores():
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: GOOGLE_API_KEY or GEMINI_API_KEY not found in environment.")
        return

    print(f"Using API Key: {api_key[:10]}...")

    try:
        client = genai.Client(api_key=api_key)
        print("Fetching Google File Search Stores...")

        # Note: The SDK might return an iterator
        stores = list(client.file_search_stores.list())

        if not stores:
            print("No file search stores found.")
        else:
            print(f"Found {len(stores)} stores:")
            for store in stores:
                display_name = getattr(store, "display_name", "N/A")
                name = store.name
                print(f"- Name: {name}")
                print(f"  Display Name: {display_name}")
                print("---")

    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    list_stores()
