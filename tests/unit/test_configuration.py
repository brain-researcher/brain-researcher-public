# tests/test_configuration.py

import os
import re
import sys
import unittest

# Add the project root to the Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, project_root)


class TestConfiguration(unittest.TestCase):
    def test_deepseek_api_key_presence(self):
        """Check if DEEPSEEK_API_KEY environment variable is set (optional)."""
        # This test is more of a reminder/check during setup rather than a strict failure
        if "DEEPSEEK_API_KEY" not in os.environ:
            print(
                "\nINFO: DEEPSEEK_API_KEY environment variable is not set. "
                "Core Agent natural language processing will be limited."
            )
            # We don't fail the test, just inform the user/developer
            self.skipTest("DEEPSEEK_API_KEY not set.")
        else:
            api_key = os.environ["DEEPSEEK_API_KEY"]
            self.assertIsInstance(api_key, str, "API key should be a string.")
            self.assertTrue(
                len(api_key) > 10, "API key seems too short."
            )  # Basic sanity check

    def test_entrez_email_placeholder(self):
        """Check if the placeholder Entrez email has been replaced in rag_retrieval.py."""
        rag_file_path = os.path.join(project_root, "tools", "rag_retrieval.py")
        if not os.path.exists(rag_file_path):
            self.skipTest("tools/rag_retrieval.py not found.")

        try:
            with open(rag_file_path, encoding="utf-8") as f:
                content = f.read()

            # Use regex to find the Entrez.email assignment line
            match = None  # Initialize match
            match = re.search(r"Entrez\.email\s*=\s*\"(.+?)\"", content)

            self.assertIsNotNone(
                match, "Could not find Entrez.email assignment in rag_retrieval.py"
            )

            email = match.group(1)
            self.assertNotEqual(
                email,
                "your.email@example.com",
                "Placeholder Entrez email 'your.email@example.com' should be replaced in tools/rag_retrieval.py",
            )
            # Basic email format check
            self.assertIn("@", email, "Entrez email should contain an '@' symbol.")
            self.assertIn(
                ".",
                email.split("@")[-1],
                "Domain part of Entrez email should contain a '.'",
            )

        except FileNotFoundError:
            self.fail(f"Could not open {rag_file_path}")
        except Exception as e:
            self.fail(f"Error reading or parsing {rag_file_path}: {e}")


if __name__ == "__main__":
    unittest.main()
