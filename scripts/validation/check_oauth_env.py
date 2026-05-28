#!/usr/bin/env python3
import os
import sys

REQUIRED_VARS = [
    "NEXTAUTH_URL",
    "NEXTAUTH_SECRET",
    # Google
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    # GitHub
    "GITHUB_CLIENT_ID",
    "GITHUB_CLIENT_SECRET",
    # Microsoft
    "AZURE_AD_CLIENT_ID",
    "AZURE_AD_CLIENT_SECRET",
    "AZURE_AD_TENANT_ID",
]

def check_env():
    print("Checking OAuth Environment Configuration...\n")
    missing = []
    present = []

    for var in REQUIRED_VARS:
        value = os.environ.get(var)
        if value:
            # Show partially masked value for confirmation
            masked = f"{value[:4]}...{value[-4:]}" if len(value) > 8 else "****"
            present.append(f"{var}: SET ({masked})")
        else:
            missing.append(var)

    if present:
        print("✅ Configured Variables:")
        for p in present:
            print(f"  - {p}")

    if missing:
        print("\n❌ Missing Variables:")
        for m in missing:
            print(f"  - {m}")

    if not missing:
        print("\nSUCCESS: All OAuth variables appear to be set.")
        sys.exit(0)
    else:
        print(f"\nWARNING: {len(missing)} required variables are missing.")
        sys.exit(1)

if __name__ == "__main__":
    check_env()
