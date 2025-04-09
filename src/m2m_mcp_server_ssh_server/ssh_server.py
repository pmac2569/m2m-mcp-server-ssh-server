"""
SSH Server Module.

This module provides the SSH server functionality for the M2M MCP Server
SSH Server, handling server setup, connection management, and session creation.
"""

# Standard library imports
import asyncio
import logging
import os
from pathlib import Path

# Third-party imports
import asyncssh

# Local imports
from .ssh_session import SSHSessionHandler

DEFAULT_KEY_PATH = Path.home() / ".ssh" / "m2m_mcp_server_ssh_server"
DEFAULT_AUTHORIZED_KEYS_PATH = Path.home() / ".ssh" / "authorized_keys"
DEFAULT_SERVERS_CONFIG = "servers_config.json"
KEY_PERMISSIONS = 0o600  # Read/write for user only
PUBKEY_PERMISSIONS = 0o644  # Read for everyone, write for user

logger = logging.getLogger(__name__)

# Track active sessions by UUID
active_sessions: dict[str, SSHSessionHandler] = {}


def ensure_server_key_exists(
    key_path: str | Path | None = None, generate_key: bool = True
) -> Path:
    """
    Ensure that a server key exists at the given path, creating it if needed.

    Args:
        key_path: Path to the private key file or None for default
        generate_key: Whether to generate a new key if not found

    Returns:
        Path object pointing to the private key file

    Raises:
        FileNotFoundError: If key doesn't exist and generate_key is False
        ValueError: If key generation fails
    """
    if key_path is None:
        key_path = DEFAULT_KEY_PATH
    elif isinstance(key_path, str):
        key_path = Path(key_path)

    logger.debug(f"Checking for server key at: {key_path}")

    if not key_path.exists():
        if not generate_key:
            logger.error(f"Key file does not exist: {key_path}")
            raise FileNotFoundError(f"Key file does not exist: {key_path}")
        try:
            logger.debug("Generating Ed25519 key pair...")
            ssh_key = asyncssh.generate_private_key(alg_name="ssh-ed25519")

            # Create directory if it doesn't exist
            key_path.parent.mkdir(parents=True, exist_ok=True)

            # Save the private key with restricted permissions
            logger.debug(f"Saving private key to {key_path}")
            with open(key_path, "wb") as f:
                f.write(ssh_key.export_private_key())

            # Explicitly set permissions before continuing
            os.chmod(key_path, KEY_PERMISSIONS)
            if not check_file_permissions(key_path, KEY_PERMISSIONS):
                logger.warning(f"Could not set secure permissions on {key_path}")

            # Save the public key
            public_key_path = key_path.with_suffix(".pub")
            logger.debug(f"Saving public key to {public_key_path}")
            with open(public_key_path, "wb") as f:
                f.write(ssh_key.export_public_key())

            # Set public key permissions
            os.chmod(public_key_path, PUBKEY_PERMISSIONS)
            if not check_file_permissions(public_key_path, PUBKEY_PERMISSIONS):
                logger.warning(f"Could not set permissions on {public_key_path}")

            logger.info(f"Ed25519 key pair generated and saved to: {key_path}")

        except Exception as e:
            logger.error(f"Error generating Ed25519 key: {e}")
            logger.debug("Key generation error details:", exc_info=True)
            raise ValueError(f"Failed to generate SSH key: {str(e)}") from e
    else:
        # Check existing key permissions
        if not check_file_permissions(key_path, KEY_PERMISSIONS):
            logger.warning(f"Key file {key_path} has insecure permissions!")
        logger.debug(f"Using existing key: {key_path}")

    return key_path


def check_file_permissions(file_path: Path, required_permissions: int) -> bool:
    """
    Check if a file has the correct permissions.

    Args:
        file_path: Path to the file to check
        required_permissions: Required permissions as octal

    Returns:
        True if the file has appropriate permissions, False otherwise
    """
    if not file_path.exists():
        return False

    # On Unix systems, check permissions directly
    if hasattr(os, "chmod"):
        return (file_path.stat().st_mode & 0o777) == required_permissions

    # On Windows, just check if file exists (can't check POSIX permissions)
    return True


class SSHServerHandler(asyncssh.SSHServer):
    """
    Handle SSH server connections and session creation.

    This class processes SSH connections, creates sessions, and manages their
    lifecycle. It supports both traditional authorized_keys file and database
    authentication methods.
    """

    def __init__(self, servers_config: str, key_db=None):
        """
        Initialize the SSH server handler.

        Args:
            servers_config: Path to the server configurations file
            key_db: Key database instance for database authentication (optional)
        """
        self.servers_config = servers_config
        self.key_db = key_db
        # Track client connection attempts for basic rate limiting
        self._connection_attempts: dict[str, int] = {}
        super().__init__()

    def connection_made(self, conn: asyncssh.SSHServerConnection) -> None:
        """
        Handle new SSH connections.

        Args:
            conn: The SSH server connection
        """
        peer_addr = (
            conn.get_extra_info("peername")[0]
            if conn.get_extra_info("peername")
            else "unknown"
        )

        # Implement basic rate limiting
        if peer_addr != "unknown":
            self._connection_attempts[peer_addr] = (
                self._connection_attempts.get(peer_addr, 0) + 1
            )
            if (
                self._connection_attempts[peer_addr] > 10
            ):  # More than 10 attempts in a short period
                logger.warning(f"Excessive connection attempts from {peer_addr}")
                # Additional actions could be taken here (temporary ban, etc.)

        logger.info(f"SSH connection established from {peer_addr}")
        logger.debug(
            f"Connection details: {conn.get_extra_info('peer_addr')}:"
            f"{conn.get_extra_info('peer_port')}"
        )
        logger.debug(
            f"Client version: {conn.get_extra_info('client_version', 'unknown')}"
        )

    def connection_lost(self, exc: Exception | None) -> None:
        """
        Handle SSH connection closure.

        Args:
            exc: Exception that caused the connection loss, if any
        """
        if exc:
            # Log full details at debug level, but only basic info at error
            # level for security
            logger.error(f"SSH connection error: {type(exc).__name__}")
            logger.debug(
                f"Connection lost exception details: {type(exc).__name__}: {str(exc)}"
            )
        logger.info("SSH connection closed")

    def begin_auth(self, username: str) -> bool:
        """
        Begin authentication process for a user.

        Args:
            username: The username provided by the client

        Returns:
            True to proceed with authentication regardless of username when using key_db
        """
        # Sanitize username for logging
        safe_username = username.replace("\n", "").replace("\r", "")[:32]

        # Always proceed with authentication regardless of username
        # when using database authentication
        if self.key_db is not None:
            logger.debug(f"Beginning database authentication for user: {safe_username}")
            return True
        # For standard auth, let asyncssh handle it
        logger.debug(f"Using standard authentication for user: {safe_username}")
        return False

    def public_key_auth_supported(self) -> bool:
        """
        Indicate whether public key authentication is supported.

        Returns:
            True since we always support public key authentication
        """
        return True

    def validate_public_key(self, username: str, key: asyncssh.SSHKey) -> bool:
        """
        Validate a client's public key when using database authentication.

        Args:
            username: The username provided by the client
            key: The public key provided by the client

        Returns:
            True if the key is valid, False otherwise
        """
        if self.key_db is None:
            # Let asyncssh handle validation with authorized_keys file
            return False

        # Sanitize username for logging
        safe_username = username.replace("\n", "").replace("\r", "")[:32]

        try:
            client_keys = self.key_db.get_client_keys()
            key_str = key.export_public_key().decode("utf-8").strip()

            # Check if the client's key is in our database
            for stored_key in client_keys:
                try:
                    stored_ssh_key = asyncssh.import_public_key(stored_key)
                    if (
                        key_str
                        == stored_ssh_key.export_public_key().decode("utf-8").strip()
                    ):
                        logger.info(
                            f"Authenticated user {safe_username} with registered key"
                        )
                        return True
                except (ValueError, asyncssh.KeyImportError):
                    continue

            logger.warning(
                f"Authentication failed for user {safe_username}: "
                "key not found in database"
            )
            return False
        except Exception as e:
            # Don't expose internal errors to the client
            logger.error(f"Error during key validation: {e}")
            return False

    def session_requested(self) -> SSHSessionHandler:
        """
        Handle a new session request from a client.

        Returns:
            A new SSH session handler instance
        """
        logger.debug(f"New session requested, using config: {self.servers_config}")
        session = SSHSessionHandler(self.servers_config)
        session_id = session._session_id
        active_sessions[session_id] = session
        logger.info(
            f"New SSH session created: {session_id} "
            f"({len(active_sessions)} active sessions)"
        )
        logger.debug(f"Active sessions: {', '.join(active_sessions.keys())}")
        return session


async def run_ssh_server(
    host: str = "127.0.0.1",  # Default to localhost for security
    port: int = 8022,
    server_host_keys: list[str] | str | None = None,
    authorized_client_keys: str | None = None,
    passphrase: str | None = None,
    servers_config: str = DEFAULT_SERVERS_CONFIG,
    use_key_db: bool = False,
) -> None:
    """
    Run an SSH server that accepts connections and creates MCP server sessions.

    Args:
        host: The host address to bind to
        port: The port to listen on
        server_host_keys: List of paths to SSH host key files or a single key path
        authorized_client_keys: Path to authorized keys file
            (ignored if use_key_db=True)
        passphrase: Passphrase for the private key
        servers_config: Path to server configurations JSON
        use_key_db: Whether to use the SQLite key database for client authentication

    Raises:
        ValueError: If no valid server host keys are provided
        ImportError: If key_db is needed but module not available
        FileNotFoundError: If required files don't exist
    """
    # Security warning if binding to all interfaces
    if host == "0.0.0.0":  # noqa: S104
        logger.warning(
            "SECURITY WARNING: Binding to all network interfaces (0.0.0.0). "
            "This may expose your server to the public internet."
        )

    logger.debug(f"Starting SSH server on {host}:{port}")
    logger.debug(f"Server config file: {servers_config}")

    # Validate servers_config file exists
    if not Path(servers_config).exists():
        logger.error(f"Server configuration file not found: {servers_config}")
        raise FileNotFoundError(
            f"Server configuration file not found: {servers_config}"
        )

    # Convert single key path to list and ensure keys exist
    validated_keys = []
    if server_host_keys is None:
        # Generate a default key if none provided
        key_path = ensure_server_key_exists()
        validated_keys = [str(key_path)]
    elif isinstance(server_host_keys, str):
        # Ensure the key exists
        key_path = ensure_server_key_exists(server_host_keys)
        validated_keys = [str(key_path)]
    else:
        # It's already a list, make sure all keys exist
        for key in server_host_keys:
            try:
                key_path = ensure_server_key_exists(key)
                validated_keys.append(str(key_path))
            except FileNotFoundError:
                logger.error(f"Key file does not exist: {key}")
                raise

    if not validated_keys:
        logger.error("No valid server host keys provided")
        raise ValueError("No valid server host keys provided")

    logger.debug(f"Using server host keys: {validated_keys}")

    if not authorized_client_keys and not use_key_db:
        # Default to standard authorized_keys location
        authorized_client_keys = str(DEFAULT_AUTHORIZED_KEYS_PATH)
        logger.debug(f"Using default authorized client keys: {authorized_client_keys}")

        # Check if the file exists, create empty if not
        auth_keys_path = Path(authorized_client_keys)
        if not auth_keys_path.exists():
            logger.warning(
                f"Authorized keys file doesn't exist: {authorized_client_keys}"
            )
            logger.info(
                f"Creating empty authorized keys file: {authorized_client_keys}"
            )
            auth_keys_path.parent.mkdir(parents=True, exist_ok=True)
            auth_keys_path.touch(mode=PUBKEY_PERMISSIONS)

    # Set up key database if needed
    key_db = None
    if use_key_db:
        try:
            from .key_server import get_key_db

            logger.info("Using key database for client authentication")
            key_db = get_key_db()
        except ImportError as e:
            logger.error("Key database module not available")
            raise ImportError(
                "Key database functionality requires aiohttp. Install with: "
                "pip install aiohttp"
            ) from e

    # Initialize the server handler factory
    def handler_factory() -> SSHServerHandler:
        return SSHServerHandler(servers_config, key_db)

    try:
        logger.debug("Creating SSH server with the following options:")
        logger.debug(f"  Host: {host}")
        logger.debug(f"  Port: {port}")
        logger.debug(f"  Server host keys: {validated_keys}")
        logger.debug(
            "  Authorized client keys: "
            f"{'<DB>' if use_key_db else authorized_client_keys}"
        )
        logger.debug(f"  Passphrase provided: {'Yes' if passphrase else 'No'}")
        logger.debug(f"  Using key database: {use_key_db}")

        await asyncssh.create_server(
            handler_factory,
            host,
            port,
            server_host_keys=validated_keys,
            authorized_client_keys=None if use_key_db else authorized_client_keys,
            passphrase=passphrase,
        )

        logger.info(f"SSH server listening on {host}:{port}")

        # Keep the server running indefinitely
        while True:
            logger.debug(
                f"SSH server alive with {len(active_sessions)} active sessions"
            )
            await asyncio.sleep(3600)  # Sleep for an hour and continue

    except (OSError, asyncssh.Error) as exc:
        if isinstance(exc, OSError) and exc.errno == 13:  # Permission error
            logger.error(
                f"Permission denied when binding to {host}:{port}. "
                "Try using a higher port number or run with elevated privileges."
            )
        elif isinstance(exc, OSError) and exc.errno == 98:  # Address already in use
            logger.error(f"Port {port} is already in use. Choose a different port.")
        else:
            logger.error(f"Error in SSH server: {exc}")

        logger.debug("SSH server error details:", exc_info=True)
        raise

    except asyncio.CancelledError:
        logger.info("SSH server shutting down")
        raise

    finally:
        # Clean up any remaining sessions
        logger.debug(f"Cleaning up {len(active_sessions)} active sessions")
        for session_id, session in list(active_sessions.items()):
            logger.debug(f"Cleaning up session {session_id}")
            if session._chan:
                try:
                    session._chan.close()
                except Exception as e:
                    logger.debug(f"Error closing session channel: {e}")
            del active_sessions[session_id]
        logger.debug("All sessions cleaned up")
