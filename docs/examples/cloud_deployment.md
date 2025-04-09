# Cloud Deployment Instructions for M2M MCP Server SSH Server

## Overview

This document provides detailed instructions on how to set up the M2M MCP Server SSH Server on cloud platforms, specifically focusing on AWS. The setup process includes creating an EC2 instance, configuring security groups, deploying the server application, and testing the connection.

## Prerequisites

- An AWS account with administrative access
- Basic knowledge of AWS services
- M2M MCP Server SSH client, i.e., [`m2m-mcp-server-ssh-client`](https://github.com/Machine-To-Machine/m2m-mcp-server-ssh-client), installed on your local machine
- Git or another method to clone/transfer the repository

## Step 1: Launch an EC2 Instance

1. **Log in to the AWS Management Console**.
2. Navigate to the **EC2 Dashboard**.
3. Click on **Launch Instance**.
4. Choose an Amazon Machine Image (AMI):
   - For production: Amazon Linux 2023 or Ubuntu 22.04 LTS
   - For testing: A `t2.micro` instance is sufficient
   - For higher load: Consider `t3.medium` or higher
5. Select an instance type based on your expected load:
   - For testing: `t2.micro` (eligible for AWS free tier)
   - For production: `t3.medium` or higher depending on expected traffic
6. Configure instance details:
   - Network: Choose your VPC
   - Subnet: Choose a public subnet if you need direct access
   - Auto-assign Public IP: Enable
7. Add Storage: Default is usually sufficient (8 GB gp3), but increase if you expect to store lots of data.
8. Add Tags (for better resource management):
   - Key: `Name`, Value: `mcp-ssh-server`
   - Key: `Environment`, Value: `production` or `staging`

## Step 2: Configure Security Group

1. Create a new security group named `mcp-ssh-server-sg`.
2. Add the following inbound rules:

| Type | Protocol | Port Range | Source | Purpose |
|------|----------|------------|--------|---------|
| SSH | TCP | 22 | Your IP address | Secure admin access |
| Custom TCP | TCP | 8022 | Custom IP range or security group ID of clients | MCP SSH server access |
| Custom TCP | TCP | 8000 | Custom IP range | Key server access |
| HTTP | TCP | 80 | 0.0.0.0/0 | Health checks (if needed) |
| HTTPS | TCP | 443 | 0.0.0.0/0 | SSL connections (if needed) |

3. Add outbound rules:

| Type | Protocol | Destination | Purpose |
|------|----------|------------|---------|
| All traffic | All | 0.0.0.0/0 | Default outbound access |

4. Review and launch the instance:
   - Create a new key pair or use an existing one
   - Save the key pair file securely (`.pem` file)

## Step 3: Connect to Your EC2 Instance

1. Open your terminal or command prompt.
2. Make sure your key file has the correct permissions:
   ```bash
   chmod 400 your-key.pem
   ```
3. Connect to your instance:
   ```bash
   ssh -i your-key.pem ec2-user@your-instance-public-dns
   # or for Ubuntu:
   # ssh -i your-key.pem ubuntu@your-instance-public-dns
   ```

## Step 4: Install Dependencies and Deploy the Server

1. **Install additional dependencies**:
   ```bash
   # Verify Python installation
   python3 --version
   
   # Verify uv installation
   uv --version
   
   # If uv isn't installed, install it
   curl -LsSf https://astral.sh/uv/install.sh | sh
   source ~/.bashrc
   ```

2. **Clone the repository**:
   ```bash
   git clone https://github.com/Machine-To-Machine/m2m-mcp-server-ssh-server.git
   cd m2m-mcp-server-ssh-server
   ```

3. **Install the project**:
   ```bash
   # Using uv
   uv sync --all-extras
   ```

4. **Set up your configuration**:
   Create or edit your `servers_config.json` file:
   ```bash
   # Create a custom config if needed
   cat > servers_config.json << EOL
   {
     "mcpServers": {
       "HackerNews": {
         "command": "uvx",
         "args": ["mcp-hn"]
       },
       "major-league-baseball": {
         "command": "uvx",
         "args": ["mcp_mlb_statsapi"]
       },
       "formula-one": {
         "command": "uvx",
         "args": ["f1-mcp-server"]
       },
       "custom-tool": {
         "command": "uvx",
         "args": ["your-custom-mcp-tool"]
       }
     }
   }
   EOL
   ```

5. **Set up and generate SSH keys**:
   
   This step can be skipped if you are going to run the key server to handle key management automatically.

   ```bash
   # Create .ssh directory if it doesn't exist
   mkdir -p ~/.ssh
   
   # Generate a key for the server if needed
   ssh-keygen -t ed25519 -f ~/.ssh/m2m_mcp_server_ssh_server -N ""
   
   # Set proper permissions
   chmod 600 ~/.ssh/m2m_mcp_server_ssh_server
   chmod 644 ~/.ssh/m2m_mcp_server_ssh_server.pub
   ```

6. **Configure Firewall**:

   Make sure ports 8022 (SSH server) and 8000 (key server) are open:

   ```bash
   # For UFW (Ubuntu)
   sudo ufw allow 8022/tcp
   sudo ufw allow 8000/tcp

   # For firewalld (CentOS/RHEL)
   sudo firewall-cmd --permanent --add-port=8022/tcp
   sudo firewall-cmd --permanent --add-port=8000/tcp
   sudo firewall-cmd --reload
   ```

## Step 5: Running the Server

### Basic Setup

```bash
uv run m2m_mcp_server_ssh_server --host 0.0.0.0 --run-key-server --key-server-host 0.0.0.0
```

### Using systemd for Service Management

For a more robust production deployment, set up the server as a systemd service.

## Step 6: Access and Test the Server

### Basic Access

From your local machine:

```bash
uv run m2m-mcp-server-ssh-client --host your-instance-public-dns --port 8022 --use-key-server
```

### Testing Key Management API

```bash
# Get server public key
curl http://your-instance-public-dns:8000/server_pub_key

# Register a client key
curl -X POST -H "Content-Type: application/json" \
  -d '{"client_pub_key": "ssh-rsa AAAA...your-public-key..."}' \
  http://your-instance-public-dns:8000/register

# Check health
curl http://your-instance-public-dns:8000/health
```

## Basic Security Considerations

- Use a non-root user
- Set up proper firewalls, only exposing necessary ports
- Consider setting up HTTPS for the key server in production
- Regularly update your system and packages

## Troubleshooting

### Connection Refused
- Check that the server is running
- Verify firewall settings allow traffic on ports 8022 and 8000

### Authentication Issues
- Verify the key server is running and accessible
