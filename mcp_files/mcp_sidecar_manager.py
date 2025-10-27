"""
MCP Sidecar Manager - Register and manage subprocess/remote MCP servers
Allows heavy/unsafe tools to run in separate processes for isolation and scalability
"""
import asyncio
import os
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum

from mcp_files.mcp_router import MCPRouter
from mcp_files.mcp_transport import TransportFactory, MCPTransport

logger = logging.getLogger(__name__)


# ============================================================================
# Sidecar Types
# ============================================================================

class SidecarType(str, Enum):
    """Types of MCP sidecars"""
    STDIO = "stdio"  # Subprocess with stdio transport
    HTTP = "http"  # Remote HTTP server
    SSE = "sse"  # Remote SSE server (streaming)


@dataclass
class SidecarConfig:
    """Configuration for a sidecar MCP server"""
    name: str
    type: SidecarType
    priority: int = 0

    # For stdio sidecars
    command: Optional[str] = None
    args: Optional[List[str]] = None
    cwd: Optional[str] = None
    env: Optional[Dict[str, str]] = None

    # For HTTP/SSE sidecars
    base_url: Optional[str] = None
    timeout: float = 30.0
    headers: Optional[Dict[str, str]] = None

    # Health check
    enable_health_check: bool = True
    health_check_interval: float = 30.0
    restart_on_failure: bool = True
    max_restart_attempts: int = 3


# ============================================================================
# Sidecar Manager
# ============================================================================

class MCPSidecarManager:
    """
    Manages lifecycle of MCP sidecar servers
    Handles registration, health checks, and automatic restarts
    """

    def __init__(self, router: MCPRouter):
        self.router = router
        self._sidecars: Dict[str, SidecarConfig] = {}
        self._transports: Dict[str, MCPTransport] = {}
        self._health_check_tasks: Dict[str, asyncio.Task] = {}
        self._restart_attempts: Dict[str, int] = {}

    # ========================================================================
    # Registration
    # ========================================================================

    async def register_stdio_sidecar(
        self,
        name: str,
        command: str,
        args: List[str],
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        priority: int = 0,
        **kwargs
    ):
        """
        Register a stdio subprocess sidecar
        Example: Python script, Node.js server, etc.
        """
        config = SidecarConfig(
            name=name,
            type=SidecarType.STDIO,
            command=command,
            args=args,
            cwd=cwd,
            env=env or {},
            priority=priority,
            **kwargs
        )

        await self._start_sidecar(config)

    async def register_http_sidecar(
        self,
        name: str,
        base_url: str,
        timeout: float = 30.0,
        headers: Optional[Dict[str, str]] = None,
        priority: int = 0,
        **kwargs
    ):
        """
        Register a remote HTTP sidecar
        Example: Separate FastAPI/Flask service
        """
        config = SidecarConfig(
            name=name,
            type=SidecarType.HTTP,
            base_url=base_url,
            timeout=timeout,
            headers=headers,
            priority=priority,
            **kwargs
        )

        await self._start_sidecar(config)

    async def register_sse_sidecar(
        self,
        name: str,
        base_url: str,
        timeout: float = 30.0,
        headers: Optional[Dict[str, str]] = None,
        priority: int = 0,
        **kwargs
    ):
        """
        Register a remote SSE sidecar (streaming)
        Example: Long-running visualization or analysis service
        """
        config = SidecarConfig(
            name=name,
            type=SidecarType.SSE,
            base_url=base_url,
            timeout=timeout,
            headers=headers,
            priority=priority,
            **kwargs
        )

        await self._start_sidecar(config)

    # ========================================================================
    # Lifecycle Management
    # ========================================================================

    async def _start_sidecar(self, config: SidecarConfig):
        """Start a sidecar server"""
        logger.info(f"Starting sidecar: {config.name} ({config.type.value})")

        try:
            # Create transport based on type
            if config.type == SidecarType.STDIO:
                transport = await TransportFactory.create_stdio(
                    command=config.command,
                    args=config.args,
                    cwd=config.cwd,
                    env=config.env,
                )
            elif config.type == SidecarType.HTTP:
                transport = TransportFactory.create_http(
                    base_url=config.base_url,
                    timeout=config.timeout,
                )
                if config.headers:
                    transport.headers.update(config.headers)
            elif config.type == SidecarType.SSE:
                transport = TransportFactory.create_sse(
                    base_url=config.base_url,
                    timeout=config.timeout,
                )
                if config.headers:
                    transport.headers.update(config.headers)
            else:
                raise ValueError(f"Unknown sidecar type: {config.type}")

            # Register with router
            await self.router.register_server(
                name=config.name,
                transport=transport,
                priority=config.priority,
                auto_initialize=True,
            )

            # Store config and transport
            self._sidecars[config.name] = config
            self._transports[config.name] = transport
            self._restart_attempts[config.name] = 0

            # Start health check if enabled
            if config.enable_health_check:
                self._start_health_check(config.name)

            logger.info(f"Sidecar {config.name} started successfully")

        except Exception as e:
            logger.error(f"Failed to start sidecar {config.name}: {e}", exc_info=True)
            raise

    async def stop_sidecar(self, name: str):
        """Stop a sidecar server"""
        logger.info(f"Stopping sidecar: {name}")

        # Stop health check
        if name in self._health_check_tasks:
            self._health_check_tasks[name].cancel()
            del self._health_check_tasks[name]

        # Unregister from router
        self.router.unregister_server(name)

        # Close transport
        if name in self._transports:
            await self._transports[name].close()
            del self._transports[name]

        # Remove config
        if name in self._sidecars:
            del self._sidecars[name]

        if name in self._restart_attempts:
            del self._restart_attempts[name]

        logger.info(f"Sidecar {name} stopped")

    async def restart_sidecar(self, name: str):
        """Restart a sidecar server"""
        logger.info(f"Restarting sidecar: {name}")

        config = self._sidecars.get(name)
        if not config:
            raise ValueError(f"Sidecar {name} not found")

        # Stop
        await self.stop_sidecar(name)

        # Wait a bit
        await asyncio.sleep(1.0)

        # Start
        await self._start_sidecar(config)

    # ========================================================================
    # Health Checks
    # ========================================================================

    def _start_health_check(self, name: str):
        """Start periodic health check for a sidecar"""
        config = self._sidecars[name]

        async def health_check_loop():
            while True:
                try:
                    await asyncio.sleep(config.health_check_interval)

                    # Check if server is still in router
                    server = self.router.get_server(name)
                    if not server or not server.active:
                        logger.warning(f"Sidecar {name} is not active")

                        # Attempt restart if enabled
                        if config.restart_on_failure:
                            await self._attempt_restart(name)
                        continue

                    # Check transport health
                    transport = self._transports.get(name)
                    if transport and transport.is_closed:
                        logger.warning(f"Sidecar {name} transport is closed")

                        if config.restart_on_failure:
                            await self._attempt_restart(name)

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Health check error for {name}: {e}")

        task = asyncio.create_task(health_check_loop())
        self._health_check_tasks[name] = task

    async def _attempt_restart(self, name: str):
        """Attempt to restart a failed sidecar"""
        config = self._sidecars.get(name)
        if not config:
            return

        attempts = self._restart_attempts.get(name, 0)

        if attempts >= config.max_restart_attempts:
            logger.error(
                f"Max restart attempts reached for {name}, giving up"
            )
            return

        self._restart_attempts[name] = attempts + 1

        logger.info(
            f"Attempting to restart {name} (attempt {attempts + 1}/"
            f"{config.max_restart_attempts})"
        )

        try:
            await self.restart_sidecar(name)
            # Reset counter on success
            self._restart_attempts[name] = 0
        except Exception as e:
            logger.error(f"Restart attempt failed for {name}: {e}")

    # ========================================================================
    # Management
    # ========================================================================

    def list_sidecars(self) -> List[Dict[str, Any]]:
        """List all registered sidecars"""
        result = []
        for name, config in self._sidecars.items():
            server = self.router.get_server(name)
            transport = self._transports.get(name)

            result.append({
                "name": name,
                "type": config.type.value,
                "priority": config.priority,
                "active": server.active if server else False,
                "transport_closed": transport.is_closed if transport else True,
                "restart_attempts": self._restart_attempts.get(name, 0),
                "health_check_enabled": config.enable_health_check,
            })

        return result

    async def close_all(self):
        """Close all sidecars"""
        logger.info("Closing all sidecars...")

        for name in list(self._sidecars.keys()):
            try:
                await self.stop_sidecar(name)
            except Exception as e:
                logger.error(f"Error closing sidecar {name}: {e}")


# ============================================================================
# Example Sidecar Configurations
# ============================================================================

"""
Example 1: Plotly generation as a separate Python subprocess

await sidecar_manager.register_stdio_sidecar(
    name="plotly-service",
    command="python",
    args=["mcp_files/tools/plotly_mcp_server.py"],
    cwd=os.getcwd(),
    priority=50,
)

Example 2: PDF processing as a remote HTTP service

await sidecar_manager.register_http_sidecar(
    name="pdf-service",
    base_url="http://localhost:8001",
    timeout=60.0,
    priority=50,
)

Example 3: Heavy analytics as an SSE streaming service

await sidecar_manager.register_sse_sidecar(
    name="analytics-service",
    base_url="http://localhost:8002",
    timeout=120.0,
    priority=30,
)

The router will automatically discover tools from these sidecars
and route tool calls to the appropriate server.
"""


# ============================================================================
# Export
# ============================================================================

__all__ = [
    "MCPSidecarManager",
    "SidecarConfig",
    "SidecarType",
]
