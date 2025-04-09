"""
M2M MCP Server SSH Server Package.

This package provides an SSH server that serves MCP (Machine Control Protocol) tools.
It allows for remote execution of locally hosted tools through a secure SSH connection.

The package includes:
- An SSH server for securely serving MCP tools
- A key management HTTP server for client key registration
- Proxy functionality to merge multiple MCP tool servers
"""

import argparse
import logging
import sys
from pathlib import Path

# Third-party imports
import anyio

# Local imports
from .ssh_server import (
    DEFAULT_AUTHORIZED_KEYS_PATH,
    DEFAULT_KEY_PATH,
    DEFAULT_SERVERS_CONFIG,
    run_ssh_server,
)


def check_dependencies() -> list[str]:
    """
    Check for missing optional dependencies.

    Returns:
        List of missing optional dependencies
    """
    missing = []
    try:
        import aiohttp  # noqa
    except ImportError:
        missing.append("aiohttp")

    return missing


def main() -> None:
    """
    Execute the M2M Remote MCP Server to serve tools hosted locally over SSH.

    This function parses command line arguments, sets up logging, and starts the
    SSH server with the specified configuration. It uses anyio for asynchronous
    execution.
    """
    parser = argparse.ArgumentParser(
        description="M2M Remote MCP Server - Serve Local Tools Over SSH"
    )

    # Add arguments
    parser.add_argument(
        "--host",
        default="127.0.0.1",  # Default to localhost for security
        help="SSH server host address to bind to",
    )
    parser.add_argument(
        "--port", type=int, default=8022, help="SSH server port to listen on"
    )
    parser.add_argument(
        "--authorized-clients",
        default=str(DEFAULT_AUTHORIZED_KEYS_PATH),
        help="Authorized clients file (ignored when --run-key-server is used)",
    )
    parser.add_argument(
        "--server-key",
        default=str(DEFAULT_KEY_PATH),
        help="Path to server private key file",
    )
    parser.add_argument(
        "--passphrase", default=None, help="Passphrase for the private key"
    )
    parser.add_argument(
        "--servers-config",
        default=DEFAULT_SERVERS_CONFIG,
        help="Path to server configurations JSON",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Set the logging level",
    )
    parser.add_argument(
        "--run-key-server",
        action="store_true",
        help="Run the HTTP key management server and use database authentication",
    )
    parser.add_argument(
        "--key-server-port",
        type=int,
        default=8000,
        help="Port for the HTTP key management server",
    )
    parser.add_argument(
        "--key-server-host",
        default="127.0.0.1",
        help="Host address for the HTTP key management server",
    )

    # Parse arguments
    args = parser.parse_args()
    # Check dependencies for key server
    if args.run_key_server:
        missing = check_dependencies()
        if "aiohttp" in missing:
            print(
                "ERROR: Key server requires aiohttp. Install with: pip install aiohttp"
            )
            sys.exit(1)

    # Configure logging with more details
    logging_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    logging.basicConfig(level=getattr(logging, args.log_level), format=logging_format)
    logger = logging.getLogger(__name__)
    logger.debug("MCP SSH Server starting with debug logging enabled")

    # Check for conflicting arguments
    if args.run_key_server and args.authorized_clients != str(
        DEFAULT_AUTHORIZED_KEYS_PATH
    ):
        logger.warning(
            "Warning: --authorized-clients is ignored when --run-key-server is "
            "specified. The key server database will be used for authentication "
            "instead."
        )

    # Check if servers_config file exists
    if not Path(args.servers_config).exists():
        logger.error(f"Server configuration file not found: {args.servers_config}")
        print(f"ERROR: Server configuration file not found: {args.servers_config}")
        print("Create a configuration file with MCP server definitions.")
        sys.exit(1)

    # Run the async function
    async def run_server() -> None:
        """Start and run the SSH server asynchronously."""
        logger.debug(f"Starting SSH server on {args.host}:{args.port}")

        # Start key server if requested
        key_server_runner = None
        if args.run_key_server:
            try:
                from .key_server import start_key_server

                logger.info(
                    "Starting key management HTTP server on "
                    f"{args.key_server_host}:{args.key_server_port}"
                )
                key_server_runner = await start_key_server(
                    host=args.key_server_host,
                    port=args.key_server_port,
                    server_host_key_path=args.server_key,
                )
                logger.info("Key server started successfully")
            except ImportError:
                logger.error(
                    "Key server requires aiohttp. Install with: pip install aiohttp"
                )
                raise
            except Exception as e:
                logger.error(f"Failed to start key server: {e}")
                raise

        try:
            # Start SSH server with database authentication if key server is running
            await run_ssh_server(
                host=args.host,
                port=args.port,
                server_host_keys=args.server_key,
                authorized_client_keys=args.authorized_clients,
                passphrase=args.passphrase,
                servers_config=args.servers_config,
                use_key_db=args.run_key_server,
            )
        finally:
            # Clean up key server if it was started
            if key_server_runner:
                logger.debug("Cleaning up key server")
                await key_server_runner.cleanup()

    # Handle keyboard interrupt more gracefully
    try:
        anyio.run(run_server)
    except KeyboardInterrupt:
        print("\nServer stopping due to keyboard interrupt...")
    except Exception as e:
        logger.error(f"Server error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
