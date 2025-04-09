"""
SSH Key Server Module.

This module provides an HTTP server for managing SSH keys, including endpoints
for registering client public keys and retrieving the server's public key.

Security Note:
    This server allows remote registration of SSH keys and should only be exposed
    on trusted networks or with additional authentication mechanisms in place.
"""

# Standard library imports
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

# Third-party imports
import asyncssh
from aiohttp import web

# Import the shared key management function
from .ssh_server import ensure_server_key_exists

logger = logging.getLogger(__name__)

KEY_DB_PATH = Path.home() / ".ssh" / "m2m_mcp_server_ssh_clients.db"


class RateLimiter:
    """Simple rate limiting implementation."""

    def __init__(self, max_requests: int = 5, window_seconds: int = 60):
        """
        Initialize rate limiter.

        Args:
            max_requests: Maximum number of requests allowed in the time window
            window_seconds: Time window in seconds
        """
        self.max_requests = max_requests
        self.window = window_seconds
        self.requests: dict[str, list[float]] = {}

    def is_allowed(self, client_ip: str) -> bool:
        """
        Check if a request from the client IP is allowed.

        Args:
            client_ip: The client's IP address

        Returns:
            True if the request is allowed, False otherwise
        """
        now = time.time()

        # Initialize if this is first request from this IP
        if client_ip not in self.requests:
            self.requests[client_ip] = [now]
            return True

        # Clean up old entries
        valid_requests = [t for t in self.requests[client_ip] if now - t < self.window]
        self.requests[client_ip] = valid_requests

        # Check if under limit
        if len(valid_requests) < self.max_requests:
            self.requests[client_ip].append(now)
            return True

        return False

    def cleanup(self) -> None:
        """Remove expired entries to prevent memory growth."""
        now = time.time()
        for ip in list(self.requests.keys()):
            self.requests[ip] = [t for t in self.requests[ip] if now - t < self.window]
            if not self.requests[ip]:
                del self.requests[ip]


class KeyDatabase:
    """
    Manage the SQLite database for storing SSH public keys.

    This class provides methods for initializing the database, adding client
    public keys, and retrieving keys for authentication.
    """

    def __init__(self, db_path: str = str(KEY_DB_PATH)):
        """
        Initialize the key database.

        Args:
            db_path: Path to the SQLite database file

        Raises:
            ValueError: If database initialization fails
        """
        self.db_path = db_path
        self._initialize_db()
        logger.debug(f"Key database initialized at {db_path}")

    def _initialize_db(self) -> None:
        """
        Create the database tables if they don't exist.

        Raises:
            ValueError: If database initialization fails
        """
        # Ensure the parent directory exists
        db_dir = Path(self.db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)

        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS client_keys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_pub_key TEXT NOT NULL UNIQUE,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()
            logger.debug("Database schema initialized")
        except Exception as e:
            logger.error(f"Error initializing database: {e}")
            raise ValueError(f"Failed to initialize key database: {e}") from e
        finally:
            if conn:
                conn.close()

    def add_client_key(self, client_pub_key: str) -> bool:
        """
        Add a client public key to the database.

        Args:
            client_pub_key: The client's public key in OpenSSH format

        Returns:
            True if the key was added successfully, False otherwise
        """
        # Validate client_pub_key
        if not client_pub_key or not isinstance(client_pub_key, str):
            logger.error("Invalid key format: Empty or non-string key")
            return False

        client_pub_key = client_pub_key.strip()
        if not client_pub_key:
            logger.error("Invalid key format: Key contains only whitespace")
            return False

        try:
            # Validate the key format using asyncssh
            asyncssh.import_public_key(client_pub_key)

            conn = None
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT OR REPLACE INTO client_keys (client_pub_key) VALUES (?)",
                    (client_pub_key,),
                )
                conn.commit()
                logger.info("Client key registered successfully")
                return True
            except sqlite3.Error as e:
                logger.error(f"Database error adding client key: {e}")
                return False
            finally:
                if conn:
                    conn.close()
        except (ValueError, asyncssh.KeyImportError) as e:
            logger.error(f"Invalid key format: {e}")
            return False

    def get_client_keys(self) -> list[str]:
        """
        Retrieve all client public keys from the database.

        Returns:
            List of client public keys
        """
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT client_pub_key FROM client_keys")
            keys = [row[0] for row in cursor.fetchall()]
            logger.debug(f"Retrieved {len(keys)} client keys from database")
            return keys
        except sqlite3.Error as e:
            logger.error(f"Database error retrieving client keys: {e}")
            return []
        finally:
            if conn:
                conn.close()


async def start_key_server(
    host: str = "127.0.0.1",  # Default to localhost for security
    port: int = 8000,
    server_host_key_path: str | Path | None = None,
) -> web.AppRunner:
    """
    Start the HTTP key management server.

    Args:
        host: Host address to bind to
        port: Port to listen on
        server_host_key_path: Path to the server's host key file

    Returns:
        The web application runner

    Raises:
        ValueError: If server key cannot be loaded
    """
    # Security warning if binding to all interfaces
    if host == "0.0.0.0":  # noqa: S104
        logger.warning(
            "SECURITY WARNING: Binding to all network interfaces (0.0.0.0). "
            "This may expose the key management API to the public internet."
        )

    # Initialize database
    db_path = KEY_DB_PATH
    db_dir = db_path.parent
    db_dir.mkdir(parents=True, exist_ok=True)

    key_db = KeyDatabase(str(db_path))
    logger.info(f"Key database initialized at {db_path}")

    # Create rate limiter
    rate_limiter = RateLimiter(
        max_requests=5, window_seconds=60
    )  # 5 requests per minute

    # Get server public key using the shared key management function
    if server_host_key_path:
        key_path = ensure_server_key_exists(server_host_key_path)
        public_key_path = key_path.with_suffix(".pub")

        try:
            with open(public_key_path) as f:
                server_pub_key = f.read().strip()
            logger.debug(f"Loaded server public key from {public_key_path}")
        except FileNotFoundError as e:
            logger.error(f"Server public key file not found: {public_key_path}")
            raise ValueError(
                f"Server public key file not found: {public_key_path}"
            ) from e
    else:
        key_path = ensure_server_key_exists()
        public_key_path = key_path.with_suffix(".pub")
        try:
            with open(public_key_path) as f:
                server_pub_key = f.read().strip()
        except FileNotFoundError as e:
            raise ValueError("Server public key file could not be loaded") from e

    # Create the web application
    app = web.Application()

    # Basic middleware for rate limiting
    @web.middleware
    async def rate_limit_middleware(request: web.Request, handler: Any) -> web.Response:
        client_ip = request.remote
        if not client_ip or not rate_limiter.is_allowed(client_ip):
            logger.warning(f"Rate limit exceeded for {client_ip}")
            return web.json_response(
                {"error": "Rate limit exceeded. Try again later."}, status=429
            )

        response = await handler(request)
        return response

    # Create the web application with middleware
    app = web.Application(middlewares=[rate_limit_middleware])

    # Define route handlers
    async def register_client_key(request: web.Request) -> web.Response:
        """Handle client key registration requests."""
        client_ip = request.remote

        try:
            # Validate request content type
            if (
                not request.content_type
                or "application/json" not in request.content_type
            ):
                logger.warning(f"Invalid content type from {client_ip}")
                return web.json_response(
                    {"error": "Content-Type must be application/json"}, status=415
                )

            # Extract and validate data
            try:
                data = await request.json()
            except json.JSONDecodeError:
                return web.json_response({"error": "Invalid JSON data"}, status=400)

            client_pub_key = data.get("client_pub_key")

            if not client_pub_key:
                return web.json_response(
                    {"error": "Missing client_pub_key parameter"}, status=400
                )

            # Add key to database
            success = key_db.add_client_key(client_pub_key)
            if success:
                logger.info(f"Key registered successfully for client {client_ip}")
                return web.json_response({"status": "success"})
            else:
                return web.json_response(
                    {"error": "Failed to register key"}, status=400
                )

        except Exception as e:
            logger.error(f"Error in register endpoint: {e}")
            # Don't expose internal errors
            return web.json_response({"error": "Internal server error"}, status=500)

    async def get_server_pub_key(request: web.Request) -> web.Response:
        """Return the server's public key."""
        return web.json_response({"server_pub_key": server_pub_key})

    async def health_check(request: web.Request) -> web.Response:
        """Simple health check endpoint."""
        return web.json_response({"status": "healthy"})

    # Add routes
    app.router.add_post("/register", register_client_key)
    app.router.add_get("/server_pub_key", get_server_pub_key)
    app.router.add_get("/health", health_check)

    # Start the server
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    logger.info(f"Key management server running on http://{host}:{port}")

    # Return the runner for later cleanup
    return runner


def get_key_db() -> KeyDatabase:
    """
    Get a reference to the key database.

    Returns:
        The key database instance
    """
    return KeyDatabase(str(KEY_DB_PATH))
