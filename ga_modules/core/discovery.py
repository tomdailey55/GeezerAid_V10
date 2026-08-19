"""
GeezerAid — Device Discovery

Discover GA devices on local network using mDNS/Bonjour.
Fallback to Tailscale for remote discovery.

Stolen from: mDNS/DNS-SD (Apple Bonjour, Avahi)
Replaces: hardcoded GA_V9_HOST=100.85.123.9:8766
"""
import logging
import socket
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)


class DeviceDiscovery:
    """Discover GA devices on local network."""

    SERVICE_TYPE = "_geeza._tcp.local."
    SERVICE_PORT = 8766

    def __init__(self, device_id: str, event_bus):
        self.device_id = device_id
        self.bus = event_bus
        self.devices: dict[str, dict] = {}  # device_id -> {host, port, capabilities}

    def advertise(self, port: int, capabilities: list[str]):
        """Advertise this device on local network.
        
        Args:
            port: Port this device listens on
            capabilities: List of capabilities
        """
        # In real impl: register mDNS service
        logger.info(f"Advertising {self.device_id} on port {port}")

    def discover(self, timeout: int = 5) -> list[dict]:
        """Discover GA devices on local network.
        
        Args:
            timeout: Search timeout in seconds
            
        Returns: List of device info dicts
        """
        # In real impl: browse mDNS services
        # For now, return known devices from cache
        return list(self.devices.values())

    def resolve(self, device_id: str) -> Optional[str]:
        """Get endpoint for a device.
        
        Args:
            device_id: Device ID to resolve
            
        Returns: URL or None
        """
        device = self.devices.get(device_id)
        if device:
            return f"http://{device['host']}:{device['port']}"
        return None

    def add_device(self, device_id: str, host: str, port: int, capabilities: Optional[list[str]] = None):
        """Add a device manually (for testing or static config)."""
        self.devices[device_id] = {
            "device_id": device_id,
            "host": host,
            "port": port,
            "capabilities": capabilities or [],
            "last_seen": time.time(),
        }

    def remove_device(self, device_id: str):
        """Remove a device."""
        self.devices.pop(device_id, None)
