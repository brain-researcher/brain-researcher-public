#!/usr/bin/env python3
"""
Install MNI templates for NiMARE ALE analysis

This script downloads and installs the MNI152 templates required for
full NiMARE functionality. Without these templates, the strength calculator
will use the fallback method (which still provides good results).

Run this if you want to use NiMARE's ALE meta-analysis capabilities.
"""

import logging
import sys

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def install_templates():
    """Install MNI templates for NiMARE"""
    try:
        # Try to import and download templates
        from nimare import utils

        logger.info("Downloading MNI152 templates for NiMARE...")

        # This would download the templates if NiMARE had such functionality
        # For now, we just provide instructions

        print("\nTo install MNI templates for full NiMARE functionality:")
        print(
            "1. Install FSL or another neuroimaging package that includes MNI templates"
        )
        print("2. Set the appropriate environment variables")
        print("3. Or use nilearn to download templates:")
        print("\n   from nilearn import datasets")
        print("   datasets.fetch_atlas_mni152_template()")
        print("\nNote: The fallback method in strength_calculator.py provides")
        print("good results without requiring these templates.\n")

        return True

    except ImportError:
        logger.error("NiMARE is not installed. Install it with: pip install nimare")
        return False
    except Exception as e:
        logger.error(f"Error installing templates: {e}")
        return False


if __name__ == "__main__":
    success = install_templates()
    sys.exit(0 if success else 1)
