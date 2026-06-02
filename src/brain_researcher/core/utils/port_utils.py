#!/usr/bin/env python3
"""Utility functions for finding and managing free ports."""

import socket


def find_free_port(start_port: int = 8000, max_attempts: int = 100) -> int | None:
    """Find a free port starting from start_port.

    Args:
        start_port: Port number to start searching from
        max_attempts: Maximum number of ports to try

    Returns:
        Free port number, or None if no free port found
    """
    for port in range(start_port, start_port + max_attempts):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("", port))
                return port
        except OSError:
            continue
    return None


def is_port_free(port: int) -> bool:
    """Check if a port is free.

    Args:
        port: Port number to check

    Returns:
        True if port is free, False otherwise
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", port))
            return True
    except OSError:
        return False


def find_multiple_free_ports(ports: list[int], max_attempts: int = 100) -> dict:
    """Find free ports for multiple services.

    Args:
        ports: List of preferred ports for each service
        max_attempts: Maximum number of ports to try for each service

    Returns:
        Dictionary mapping original port to assigned free port
    """
    assigned_ports = {}
    used_ports = set()

    for preferred_port in ports:
        if preferred_port not in used_ports and is_port_free(preferred_port):
            assigned_ports[preferred_port] = preferred_port
            used_ports.add(preferred_port)
        else:
            # Find next free port
            free_port = None
            for p in range(preferred_port, preferred_port + max_attempts):
                if p not in used_ports and is_port_free(p):
                    free_port = p
                    break

            if free_port:
                assigned_ports[preferred_port] = free_port
                used_ports.add(free_port)
            else:
                # Try from a higher range
                for p in range(9000, 9000 + max_attempts):
                    if p not in used_ports and is_port_free(p):
                        free_port = p
                        break

                if free_port:
                    assigned_ports[preferred_port] = free_port
                    used_ports.add(free_port)

    return assigned_ports


if __name__ == "__main__":
    # Test the functions
    print("Testing port utilities...")

    # Test single port
    free_port = find_free_port(8000)
    print(f"Found free port: {free_port}")

    # Test multiple ports
    preferred_ports = [5000, 8000, 8054, 3000]
    assigned = find_multiple_free_ports(preferred_ports)
    print("\nPort assignments:")
    for orig, assigned_port in assigned.items():
        status = "✓" if orig == assigned_port else "→"
        print(f"  {orig} {status} {assigned_port}")
