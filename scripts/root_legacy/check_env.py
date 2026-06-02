#!/usr/bin/env python3
"""
Environment Configuration Checker for Brain Researcher
This script verifies that all required environment variables are properly configured.
"""

import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple
import json

REPO_ROOT = Path(__file__).resolve().parents[2]

# Color codes for terminal output
class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    RESET = '\033[0m'
    BOLD = '\033[1m'

def check_env_var(var_name: str, required: bool = False, mask_value: bool = False) -> Tuple[bool, str]:
    """Check if an environment variable is set and return its status."""
    value = os.environ.get(var_name)

    if value:
        if mask_value and len(value) > 8:
            # Mask sensitive values like API keys
            display_value = value[:4] + "****" + value[-4:]
        else:
            display_value = value
        return True, display_value
    else:
        return False, "Not set"

def check_file_exists(file_path: str | Path) -> bool:
    """Check if a file exists."""
    return Path(file_path).exists()

def load_env_file(file_path: str | Path) -> Dict[str, str]:
    """Load environment variables from a .env file."""
    env_vars = {}
    path = Path(file_path)
    if not path.exists():
        return env_vars

    try:
        with open(path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    env_vars[key.strip()] = value.strip()
    except Exception as e:
        print(f"Error reading {file_path}: {e}")

    return env_vars

def check_port_availability(port: int) -> bool:
    """Check if a port is available."""
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            result = s.connect_ex(('localhost', port))
            return result != 0  # True if port is available
    except:
        return False

def main():
    print(f"\n{Colors.BOLD}{'='*60}")
    print("Brain Researcher Environment Configuration Checker")
    print(f"{'='*60}{Colors.RESET}\n")

    # Track overall status
    all_good = True
    warnings = []
    errors = []

    # 1. Check .env files
    print(f"{Colors.BOLD}1. Environment Files:{Colors.RESET}")
    env_files = {
        "Main .env": ".env",
        "Agent .env": "src/brain_researcher/services/agent/.env",
        "BR-KG .env": "src/brain_researcher/services/br_kg/.env"
    }

    loaded_env_vars = {}
    for name, rel_path in env_files.items():
        path = REPO_ROOT / rel_path
        exists = check_file_exists(path)
        if exists:
            print(f"  {Colors.GREEN}✓{Colors.RESET} {name}: {rel_path}")
            # Load variables from file
            file_vars = load_env_file(path)
            loaded_env_vars.update(file_vars)
        else:
            print(f"  {Colors.YELLOW}⚠{Colors.RESET} {name}: Not found at {rel_path}")
            warnings.append(f"{name} not found")

    # 2. Check API Keys
    print(f"\n{Colors.BOLD}2. API Keys:{Colors.RESET}")
    api_keys = {
        "DEEPSEEK_API_KEY": ("DeepSeek API", True),
        "OPENAI_API_KEY": ("OpenAI API", True),
        "ANTHROPIC_API_KEY": ("Anthropic API", True),
        "HUGGINGFACE_API_KEY": ("HuggingFace API", False),
        "NEUROMAPS_OSF_TOKEN": ("NeuroMaps OSF", False)
    }

    has_llm_key = False
    for key, (name, mask) in api_keys.items():
        # Check both environment and loaded .env files
        env_exists, env_value = check_env_var(key, mask_value=mask)
        file_value = loaded_env_vars.get(key, "")

        if env_exists:
            print(f"  {Colors.GREEN}✓{Colors.RESET} {name:20} (env): {env_value}")
            if key in ["DEEPSEEK_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"]:
                has_llm_key = True
        elif file_value and not file_value.startswith("your-") and not file_value.startswith("sk-your"):
            masked_value = file_value[:4] + "****" + file_value[-4:] if mask and len(file_value) > 8 else file_value
            print(f"  {Colors.BLUE}✓{Colors.RESET} {name:20} (file): {masked_value}")
            if key in ["DEEPSEEK_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"]:
                has_llm_key = True
        else:
            print(f"  {Colors.YELLOW}✗{Colors.RESET} {name:20}: Not configured")

    if not has_llm_key:
        errors.append("No LLM API key configured (need at least one: DeepSeek, OpenAI, or Anthropic)")

    # 3. Check Service Configuration
    print(f"\n{Colors.BOLD}3. Service Configuration:{Colors.RESET}")
    services = {
        "BR_KG_API_URL": ("BR-KG API URL", "http://localhost:5001"),
        "API_URL": ("General API URL", "http://localhost:5001"),
        "PORT": ("Default Port", None),
        "DEBUG": ("Debug Mode", "false"),
        "LOG_LEVEL": ("Log Level", "INFO")
    }

    for key, (name, default) in services.items():
        env_exists, env_value = check_env_var(key)
        file_value = loaded_env_vars.get(key, "")

        if env_exists:
            print(f"  {Colors.GREEN}✓{Colors.RESET} {name:20}: {env_value}")
        elif file_value:
            print(f"  {Colors.BLUE}✓{Colors.RESET} {name:20}: {file_value} (from file)")
        elif default:
            print(f"  {Colors.YELLOW}○{Colors.RESET} {name:20}: Using default ({default})")
        else:
            print(f"  {Colors.YELLOW}○{Colors.RESET} {name:20}: Not set")

    # 4. Check Port Configuration
    print(f"\n{Colors.BOLD}4. Port Configuration:{Colors.RESET}")
    ports = {
        "KG_PORT": ("BR-KG", 5001),
        "AGENT_PORT": ("Agent", 8000),
        "UI_PORT": ("Dashboard", 8050),
        "NICLIP_PORT": ("NICLIP", 8001)
    }

    for key, (name, default) in ports.items():
        env_value = os.environ.get(key) or loaded_env_vars.get(key, "")

        if env_value:
            if env_value == "auto":
                print(f"  {Colors.GREEN}✓{Colors.RESET} {name:12}: Auto-allocation enabled")
            else:
                try:
                    port = int(env_value)
                    available = check_port_availability(port)
                    if available:
                        print(f"  {Colors.GREEN}✓{Colors.RESET} {name:12}: Port {port} (available)")
                    else:
                        print(f"  {Colors.YELLOW}⚠{Colors.RESET} {name:12}: Port {port} (in use)")
                        warnings.append(f"Port {port} for {name} is already in use")
                except:
                    print(f"  {Colors.RED}✗{Colors.RESET} {name:12}: Invalid port value: {env_value}")
        else:
            available = check_port_availability(default)
            status = "available" if available else "in use"
            print(f"  {Colors.YELLOW}○{Colors.RESET} {name:12}: Using default port {default} ({status})")

    # 5. Check Data Directories
    print(f"\n{Colors.BOLD}5. Data Directories:{Colors.RESET}")
    directories = {
        "DATA_ROOT": ("Data Root", "data"),
        "BIDS_ROOT": ("BIDS Data", "data/bids"),
        "KG_DATA_ROOT": ("Knowledge Graph", "data/br-kg"),
        "CACHE_ROOT": ("Cache", "data/cache")
    }

    for key, (name, default) in directories.items():
        env_value = os.environ.get(key) or loaded_env_vars.get(key, default)
        path = Path(env_value)

        if path.exists():
            print(f"  {Colors.GREEN}✓{Colors.RESET} {name:20}: {env_value}")
        else:
            print(f"  {Colors.YELLOW}⚠{Colors.RESET} {name:20}: {env_value} (not found)")
            warnings.append(f"Directory {env_value} for {name} does not exist")

    # 6. Check Python Environment
    print(f"\n{Colors.BOLD}6. Python Environment:{Colors.RESET}")

    # Check Python version
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info >= (3, 8):
        print(f"  {Colors.GREEN}✓{Colors.RESET} Python Version: {python_version}")
    else:
        print(f"  {Colors.RED}✗{Colors.RESET} Python Version: {python_version} (requires >= 3.8)")
        errors.append("Python version must be 3.8 or higher")

    # Check virtual environment
    venv = os.environ.get("VIRTUAL_ENV") or os.environ.get("CONDA_DEFAULT_ENV")
    if venv:
        print(f"  {Colors.GREEN}✓{Colors.RESET} Virtual Environment: {Path(venv).name}")
    else:
        print(f"  {Colors.YELLOW}⚠{Colors.RESET} Virtual Environment: Not activated")
        warnings.append("Running outside virtual environment")

    # Check required packages
    print(f"\n{Colors.BOLD}7. Required Packages:{Colors.RESET}")
    try:
        import brain_researcher
        print(f"  {Colors.GREEN}✓{Colors.RESET} brain_researcher package installed")
    except ImportError:
        print(f"  {Colors.RED}✗{Colors.RESET} brain_researcher package not installed")
        errors.append("brain_researcher package not installed. Run: pip install -e .")

    # Summary
    print(f"\n{Colors.BOLD}{'='*60}")
    print("Summary")
    print(f"{'='*60}{Colors.RESET}\n")

    if errors:
        print(f"{Colors.RED}Errors ({len(errors)}):{Colors.RESET}")
        for error in errors:
            print(f"  • {error}")
        all_good = False

    if warnings:
        print(f"\n{Colors.YELLOW}Warnings ({len(warnings)}):{Colors.RESET}")
        for warning in warnings:
            print(f"  • {warning}")

    if all_good and not errors:
        if warnings:
            print(f"\n{Colors.YELLOW}✓ Environment is configured with warnings{Colors.RESET}")
            print("The system should work, but review warnings above.")
        else:
            print(f"{Colors.GREEN}✓ Environment is properly configured!{Colors.RESET}")
            print("All checks passed. You're ready to use Brain Researcher.")
    else:
        print(f"\n{Colors.RED}✗ Environment configuration has errors{Colors.RESET}")
        print("Please fix the errors above before proceeding.")
        sys.exit(1)

    print("\nTo start services, use:")
    print("  br serve kg      # BR-KG API")
    print("  br serve agent   # LLM Agent")
    print("  br serve web     # Next.js Web UI")
    print("")

if __name__ == "__main__":
    main()
