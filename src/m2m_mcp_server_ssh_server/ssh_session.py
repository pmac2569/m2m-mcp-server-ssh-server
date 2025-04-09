"""
SSH Session Handler Module.

This module provides the SSH session handling functionality for the M2M MCP Server,
SSH Server managing connections, data processing, and proxy server integration.
"""

# Standard library imports
import asyncio
import json
import logging
import uuid
from collections.abc import Mapping
from typing import Any

# Third-party imports
import anyio
import asyncssh
import mcp.types as types
from mcp import server

# Local imports
from .proxy_server import Server, create_merged_proxy_server

logger = logging.getLogger(__name__)


class SSHSessionHandler(asyncssh.SSHServerSession[str]):
    """
    Handle SSH sessions for the MCP server.

    This class manages the lifecycle of an SSH session, including connection handling,
    data processing, server initialization, and cleanup.
    """

    def __init__(self, server_configs_path: str):
        """
        Initialize the SSH session handler.

        Args:
            server_configs_path: Path to the JSON file containing server configurations
        """
        self._chan: asyncssh.SSHServerChannel[str] | None = None
        self._input_buffer = ""
        self._pending_lines = []
        self._line_available = asyncio.Event()
        self._session_id = str(uuid.uuid4())
        self._server_configs_path = server_configs_path
        self._servers: list[Server] = []
        self._merged_server: server.Server[object] | None = None
        self._connection_active = True
        self._task: asyncio.Task | None = None
        logger.debug(f"SSH session handler {self._session_id} initialized")

    def connection_made(self, chan: asyncssh.SSHServerChannel[str]) -> None:
        """
        Handle new SSH connections.

        Args:
            chan: The SSH server channel for this connection
        """
        self._chan = chan
        remote_addr = self._chan.get_extra_info("peername")[0]
        logger.info(
            f"Connection made from {remote_addr}, session ID: {self._session_id}"
        )
        logger.debug(
            f"SSH channel properties: {self._chan.get_extra_info('connection')}"
        )

    def shell_requested(self) -> bool:
        """
        Handle shell requests from SSH clients.

        Returns:
            True to accept the (custom) shell request
        """
        logger.info(f"Shell requested for session {self._session_id}")
        logger.debug(
            "Shell environment: "
            f"{self._chan.get_environment() if self._chan else 'No channel'}"
        )
        # Return True to accept the shell request
        # The actual handling is done in session_started
        return True

    def pty_requested(
        self,
        term_type: str,
        term_size: tuple[int, int, int, int],
        term_modes: Mapping[int, int],
    ) -> bool:
        """
        Handle pseudo-terminal requests.

        Args:
            term_type: Terminal type requested
            term_size: Terminal dimensions (width, height, pixel width, pixel height)
            term_modes: Terminal modes

        Returns:
            False to reject PTY requests (we don't need PTY for MCP)
        """
        logger.info(f"Pseudo-terminal requested for session {self._session_id}")
        logger.debug(
            f"Terminal type: {term_type}, size: {term_size}, modes: {term_modes}"
        )
        return False

    def session_started(self) -> None:
        """
        Handle the start of an SSH session after connection is established.

        This method initiates the asynchronous processing of the session.
        """
        if self._chan is None:
            logger.error("SSH channel is None during session start")
            return

        remote_addr = self._chan.get_extra_info("peername")[0]
        logger.info(f"SSH session {self._session_id} started from {remote_addr}")
        logger.debug(
            "Session protocol version: "
            f"{self._chan.get_extra_info('server_version', 'unknown')}"
        )

        # Start processing the connection
        self._task = asyncio.create_task(self.process_session())

    def data_received(self, data: str, datatype: asyncssh.DataType) -> None:
        """
        Process incoming data from the SSH channel.

        Args:
            data: String data received from the client
            datatype: Type of data received
        """
        if self._chan is None:
            logger.error("SSH channel is None during data reception")
            return

        # Add the received data to the input buffer
        logger.debug(
            f"Session {self._session_id} received data: "
            f"{data[:100]}{'...' if len(data) > 100 else ''}"
        )
        self._input_buffer += data

        # Process any complete lines
        lines = self._input_buffer.splitlines(keepends=True)
        if lines:
            # If the last line doesn't end with a newline, keep it in the buffer
            if not lines[-1].endswith("\n"):
                self._input_buffer = lines.pop()
                logger.debug(
                    f"Keeping incomplete line in buffer: {self._input_buffer[:100]}"
                )
            else:
                self._input_buffer = ""

            # Add complete lines to the pending lines queue
            for line in lines:
                clean_line = line.rstrip("\n")
                self._pending_lines.append(clean_line)
                logger.debug(
                    f"Added complete line to pending queue: {clean_line[:100]}"
                )

            # Signal that new lines are available
            logger.debug(f"Signaling {len(lines)} new lines available")
            self._line_available.set()

    async def readline(self) -> str | None:
        """
        Read a line asynchronously from the input buffer.

        Returns:
            A line of text, or None if the connection has been lost
        """
        logger.debug(f"Readline called, pending lines: {len(self._pending_lines)}")
        while not self._pending_lines:
            # Check if connection is lost before waiting
            if not self._connection_active:
                logger.debug("Connection no longer active, exiting readline")
                return None  # Return None to signal connection ended

            # Wait for new data
            logger.debug("Waiting for new lines...")
            self._line_available.clear()
            await self._line_available.wait()
            logger.debug(f"New lines available, count: {len(self._pending_lines)}")

            # Check again after wait to prevent race conditions
            if not self._connection_active and not self._pending_lines:
                logger.debug("Connection lost during wait, exiting readline")
                return None

        # We have data to return
        line = self._pending_lines.pop(0) if self._pending_lines else None
        logger.debug(f"Returning line: {line[:100] if line else 'None'}")
        return line

    def connection_lost(self, exc: Exception | None) -> None:
        """
        Handle connection loss events.

        Args:
            exc: Exception that caused the connection loss, if any
        """
        if exc:
            logger.error(f"SSH session {self._session_id} error: {exc}")
            logger.debug(
                f"Connection lost exception details: {type(exc).__name__}: {str(exc)}"
            )
        logger.info(f"SSH session {self._session_id} closed")

        if self._chan is not None:
            logger.debug(f"Closing SSH channel for session {self._session_id}")
            self._chan.close()

        # Mark connection as inactive (this will cause process_session to exit properly)
        self._connection_active = False
        if self._task:
            logger.debug(f"Cancelling task for session {self._session_id}")
            self._task.cancel()

        # Signal the read loop to exit
        logger.debug("Signaling read loop to exit")
        self._line_available.set()

        # DO NOT create new tasks for server cleanup here -
        # Let the main task handle cleanup in its finally block

    async def load_server_configs(self) -> dict[str, Any]:
        """
        Load server configurations from the config file.

        Returns:
            Dictionary containing server configurations
        """
        try:
            logger.debug(f"Loading server configs from {self._server_configs_path}")
            with open(self._server_configs_path) as f:
                config = json.load(f)
                logger.debug(
                    f"Loaded server configs: {len(config.get('mcpServers', {}))}"
                )
                return config
        except Exception as e:
            logger.error(f"Error loading server configs: {e}")
            logger.debug("Stack trace for config loading error:", exc_info=True)
            return {"mcpServers": {}}

    async def initialize_servers(self) -> None:
        """
        Initialize MCP proxy servers based on configuration.

        This method creates and initializes server instances for each server defined
        in the configuration file, then creates a merged proxy server.
        """
        try:
            logger.debug("Beginning server initialization...")
            config = await self.load_server_configs()

            for name, srv_config in config.get("mcpServers", {}).items():
                logger.info(f"Initializing proxy server for {name}")
                logger.debug(f"Server config for {name}: {srv_config}")
                # Create a new server
                server = Server(name, srv_config)
                await server.initialize()
                self._servers.append(server)
                logger.debug(f"Server {name} initialized successfully")

            logger.debug("Creating merged proxy server")
            self._merged_server = await create_merged_proxy_server(self._servers)
            logger.info(
                f"Merged proxy server initialized with {len(self._servers)} servers"
            )

        except Exception as e:
            logger.error(f"Error initializing proxy servers: {e}")
            logger.debug("Stack trace for initialization error:", exc_info=True)

    async def process_session(self) -> None:
        """
        Process the SSH session, handling communication between client and servers.

        This method is the main entry point for session handling after it's established.
        It initializes servers, sets up communication streams, and manages the
        lifecycle of the session until it ends.
        """
        if self._chan is None:
            logger.error("SSH channel is None during process_session")
            return

        remote_addr = self._chan.get_extra_info("peername")[0]
        logger.info(f"Processing session {self._session_id} from: {remote_addr}")

        try:
            # Initialize proxy servers for this session
            logger.debug(f"Initializing servers for session {self._session_id}")
            await self.initialize_servers()

            # Create streams for SSH communication
            logger.debug("Creating memory streams for SSH communication")
            ssh_read_writer, ssh_read_stream = anyio.create_memory_object_stream(0)
            ssh_write_stream, ssh_write_reader = anyio.create_memory_object_stream(0)

            async def ssh_reader() -> None:
                """Read JSON-RPC messages from the SSH connection."""
                try:
                    logger.debug(f"SSH reader started for session {self._session_id}")
                    while True:
                        logger.debug("Waiting for next line from SSH...")
                        line = await self.readline()
                        if line is None:
                            logger.debug("Connection closed, exiting reader")
                            break
                        if not line:
                            logger.debug("Empty line received, skipping")
                            continue

                        try:
                            logger.debug(f"Parsing JSON-RPC message: {line[:100]}")
                            message = types.JSONRPCMessage.model_validate_json(line)
                            logger.debug(
                                f"Session {self._session_id} received: {message}"
                            )
                            await ssh_read_writer.send(message)
                        except Exception as exc:
                            logger.error(f"Error parsing message: {exc}")
                            logger.debug(f"Invalid message: {line[:200]}")
                            await ssh_read_writer.send(exc)
                except asyncio.CancelledError:
                    logger.debug(f"SSH reader for session {self._session_id} cancelled")
                except Exception as e:
                    logger.error(f"Error in SSH reader: {e}")
                    logger.debug("SSH reader exception details:", exc_info=True)
                    await ssh_read_writer.send(Exception(f"SSH transport error: {e}"))

            async def ssh_writer() -> None:
                """Write JSON-RPC messages to the SSH connection."""
                try:
                    logger.debug(f"SSH writer started for session {self._session_id}")
                    async for message in ssh_write_reader:
                        # Check if the channel is still open before writing
                        if self._chan is None or self._chan.is_closing():
                            logger.warning(
                                f"Session {self._session_id}: "
                                "Cannot send message: SSH channel is closed"
                            )
                            continue

                        json_str = message.model_dump_json(
                            by_alias=True, exclude_none=True
                        )
                        logger.debug(
                            f"Session {self._session_id} sending: {json_str[:200]}"
                        )
                        self._chan.write(json_str + "\n")
                except asyncio.CancelledError:
                    logger.debug(f"SSH writer for session {self._session_id} cancelled")
                except Exception as e:
                    logger.error(f"Error in SSH writer: {e}")
                    logger.debug("SSH writer exception details:", exc_info=True)

            # Run the server with stdio transport
            logger.debug("Setting up task group for processing")
            async with anyio.create_task_group() as tg:
                # Start SSH reader and writer tasks
                logger.debug("Starting SSH reader and writer tasks")
                tg.start_soon(ssh_reader)
                tg.start_soon(ssh_writer)

                # Create stdio server for handling MCP protocol
                logger.debug("Creating stdio server")
                # Run the merged server
                if self._merged_server:
                    logger.debug(
                        f"Running merged server for session {self._session_id}"
                    )
                    init_options = self._merged_server.create_initialization_options()
                    logger.debug(f"Server initialization options: {init_options}")
                    await self._merged_server.run(
                        ssh_read_stream, ssh_write_stream, init_options
                    )
                else:
                    logger.error("No merged server available to run")

        except Exception as e:
            logger.error(f"Session {self._session_id} processing error: {e}")
            logger.debug("Session processing exception details:", exc_info=True)
        finally:
            # Clean up resources if needed
            logger.debug(f"Cleaning up session {self._session_id}")
            for _server in reversed(self._servers):
                try:
                    logger.debug(f"Cleaning up server {_server.name}")
                    await _server.cleanup()
                except Exception as e:
                    logger.error(f"Error closing client session: {e}")
                    logger.debug("Cleanup exception details:", exc_info=True)
            logger.info(f"Session {self._session_id} processing finished")
