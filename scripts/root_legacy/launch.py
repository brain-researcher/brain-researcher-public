#!/usr/bin/env python3
"""
Simple launcher for Brain Researcher services with real data integration.
"""

import os
import sys
import time
import subprocess
import signal
from pathlib import Path

# Add project to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root / "src"))

def check_port(port):
    """Check if a port is in use."""
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(('localhost', port))
    sock.close()
    return result == 0

def kill_process_on_port(port):
    """Kill process using a specific port."""
    try:
        result = subprocess.run(
            f"lsof -ti:{port} | xargs kill -9",
            shell=True,
            capture_output=True
        )
        time.sleep(1)
    except:
        pass

def launch_services():
    """Launch all Brain Researcher services."""
    print("🚀 Brain Researcher Launcher")
    print("=" * 50)

    # Set environment variables
    os.environ["PYTHONPATH"] = str(project_root / "src") + ":" + os.environ.get(
        "PYTHONPATH", ""
    )
    os.environ["AGENT_MODE"] = "langgraph"
    os.environ["BR_KG_API_URL"] = "http://localhost:5001"

    # Check and clean ports
    services = [
        ("BR-KG API", 5001),
        ("Brain Researcher Agent", 8000)
    ]

    print("\n📍 Checking ports...")
    for name, port in services:
        if check_port(port):
            print(f"   Port {port} ({name}) is in use. Killing...")
            kill_process_on_port(port)
            print(f"   ✓ Port {port} cleared")
        else:
            print(f"   ✓ Port {port} is free")

    # Create logs directory
    logs_dir = project_root / "logs"
    logs_dir.mkdir(exist_ok=True)

    processes = []

    try:
        # 1. Start BR-KG API
        print("\n📦 Starting BR-KG API on port 5001...")
        br_kg_log = open(logs_dir / "br_kg.log", "w")
        br_kg_proc = subprocess.Popen(
            [
                sys.executable, "-m", "uvicorn",
                "brain_researcher.services.br_kg.web_service:app",
                "--host", "0.0.0.0", "--port", "5001"
            ],
            stdout=br_kg_log,
            stderr=subprocess.STDOUT,
            cwd=project_root
        )
        processes.append(("BR-KG", br_kg_proc, br_kg_log))
        print(f"   ✓ Started (PID: {br_kg_proc.pid})")
        time.sleep(3)

        # 2. Start Brain Researcher Agent
        print("\n🧠 Starting Brain Researcher Agent on port 8000...")
        agent_log = open(logs_dir / "agent.log", "w")
        agent_proc = subprocess.Popen(
            [
                sys.executable, "-m", "uvicorn",
                "brain_researcher.legacy.agent.web_service_langgraph:app",
                "--host", "0.0.0.0", "--port", "8000", "--reload"
            ],
            stdout=agent_log,
            stderr=subprocess.STDOUT,
            cwd=project_root
        )
        processes.append(("Agent", agent_proc, agent_log))
        print(f"   ✓ Started (PID: {agent_proc.pid})")

        # Wait for services to initialize
        print("\n⏳ Waiting for services to initialize...")
        time.sleep(5)

        # Check services are running
        print("\n✅ Service Status:")
        all_good = True
        for name, port in services:
            if check_port(port):
                print(f"   ✓ {name} is running on port {port}")
            else:
                print(f"   ✗ {name} failed to start on port {port}")
                all_good = False

        if all_good:
            print("\n🎉 All services started successfully!")
            print("\n📊 Real Data Integration Active:")
            print("   • Vocabulary: ca_topics_level0_v2.json")
            print("   • GLM data: Balloon task z-statistic maps")
            print("   • NiCLIP: Brain-language alignment models")
            print("   • BR-KG: Knowledge graph API")

            print("\n🔧 Quick Test Commands:")
            print("   curl -X POST http://localhost:8000/chat \\")
            print("     -H 'Content-Type: application/json' \\")
            print("     -d '{\"message\": \"What brain regions are involved in working memory?\", \"thread_id\": \"test\"}'")

            print("\n📝 Logs:")
            print(f"   tail -f {logs_dir}/br_kg.log")
            print(f"   tail -f {logs_dir}/agent.log")

            print("\n⚠️  Press Ctrl+C to stop all services")

            # Keep running
            while True:
                time.sleep(1)

    except KeyboardInterrupt:
        print("\n\n🛑 Shutting down services...")
        for name, proc, log_file in processes:
            proc.terminate()
            log_file.close()
            print(f"   ✓ Stopped {name}")
        print("\n👋 Goodbye!")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        for name, proc, log_file in processes:
            proc.terminate()
            log_file.close()
        sys.exit(1)

if __name__ == "__main__":
    launch_services()
