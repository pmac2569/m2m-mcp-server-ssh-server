# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

## Reporting a Vulnerability

We take security issues seriously. If you discover a security vulnerability in the `m2m-mcp-server-ssh-server`, please follow these steps:

1. **Do not disclose the vulnerability publicly**
2. Email us at support@machinetomachine.ai with details about the vulnerability
3. Allow us time to investigate and address the vulnerability
4. We will coordinate the public disclosure with you once the issue is resolved

## Security Best Practices

When deploying `m2m-mcp-server-ssh-server`:

1. **Network Security:**
   - Avoid binding the key server to all interfaces (0.0.0.0) unless necessary
   - Use a reverse proxy (Nginx) with HTTPS for the key server in production
   - Configure firewalls to limit access to SSH (port 8022) and key server (port 8000) endpoints
   
2. **SSH Security:**
   - Generate dedicated server SSH keys with appropriate permissions (600 for private keys on Unix systems)
   - Store client keys securely in the database or authorized_keys file
   - Use passphrase-protected keys where possible

3. **Deployment Security:**
   - Run the server with the least privileged user possible
