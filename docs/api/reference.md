# API Reference for M2M MCP Server SSH Server

## Overview

The M2M MCP Server SSH Server provides an interface for managing SSH connections and executing Machine Control Protocol (MCP) tools. This document outlines the available classes, methods, and their usage.

## Classes

### `SSHSessionHandler`

Manages the lifecycle of an SSH session, including connection handling, data processing, and server initialization.

#### Methods

- **`__init__(self, server_configs_path: str)`**
  - Initializes the SSH session handler.
  - **Parameters:**
    - `server_configs_path`: Path to the JSON file containing server configurations.

- **`connection_made(self, chan: asyncssh.SSHServerChannel[str]) -> None`**
  - Handles new SSH connections.
  - **Parameters:**
    - `chan`: The SSH server channel for this connection.

- **`shell_requested(self) -> bool`**
  - Handles shell requests from SSH clients.
  - **Returns:** `True` to accept the shell request.

- **`pty_requested(self, term_type: str, term_size: tuple[int, int, int, int], term_modes: Mapping[int, int]) -> bool`**
  - Handles pseudo-terminal requests.
  - **Parameters:**
    - `term_type`: Terminal type requested.
    - `term_size`: Terminal dimensions (width, height, pixel width, pixel height).
    - `term_modes`: Terminal modes.
  - **Returns:** `False` to reject PTY requests.

- **`session_started(self) -> None`**
  - Handles the start of an SSH session after connection is established.

- **`data_received(self, data: str, datatype: asyncssh.DataType) -> None`**
  - Processes incoming data from the SSH channel.
  - **Parameters:**
    - `data`: String data received from the client.
    - `datatype`: Type of data received.

- **`readline(self) -> str | None`**
  - Reads a line asynchronously from the input buffer.
  - **Returns:** A line of text, or `None` if the connection has been lost.

- **`connection_lost(self, exc: Exception | None) -> None`**
  - Handles connection loss events.
  - **Parameters:**
    - `exc`: Exception that caused the connection loss, if any.

- **`load_server_configs(self) -> dict[str, Any]`**
  - Loads server configurations from the config file.
  - **Returns:** Dictionary containing server configurations.

- **`initialize_servers(self) -> None`**
  - Initializes MCP proxy servers based on configuration.

- **`process_session(self) -> None`**
  - Processes the SSH session, handling communication between client and servers.

## Functions

### `run_ssh_server`

Runs an SSH server that accepts connections and creates MCP server sessions.

#### Parameters

- **`host: str`** (default: "0.0.0.0")
- **`port: int`** (default: 8022)
- **`server_host_keys: list[str] | None`**
- **`authorized_client_keys: str | None`**
- **`passphrase: str | None`**
- **`servers_config: str`** (default: "servers_config.json")

#### Returns

- `None`

## Usage Example

```python
from m2m_mcp_server_ssh_server.ssh_server import run_ssh_server

async def main():
    await run_ssh_server(host="127.0.0.1", port=8022)

# To run the server
import anyio
anyio.run(main)
```

## Conclusion

This API reference provides a comprehensive overview of the classes and methods available in the M2M MCP Server SSH Server. For further details, please refer to the source code and additional documentation.