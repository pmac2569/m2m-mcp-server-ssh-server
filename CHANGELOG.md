# CHANGELOG.md

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2025-04-08

### Added
- Initial release with basic SSH server functionality
- Support for hosting multiple MCP tools
- Proxy server implementation to merge multiple tools into one interface
- Automatic key generation if no SSH key is provided
- Key server with REST API endpoints for client key registration and server key sharing
- SQLite database for storing client public keys
- Option to run with traditional `authorized_keys` file or SQLite database
- Health check endpoint for the key server
- Documentation for deployment on cloud platforms
- Support for Formula One, MLB, and HackerNews MCP servers

### Security
- Secure file permissions for SSH keys (0o600 for private, 0o644 for public)
- Input validation for key registration
- Rate limiting for key registration API
- Default binding to localhost (127.0.0.1) for better security
- Warning when binding to all interfaces (0.0.0.0)
- SQL injection protection with parameterized queries
