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
| Custom TCP | TCP | 8000 | Custom IP range | Key server access (only if testing directly without Nginx) |
| HTTP | TCP | 80 | 0.0.0.0/0 | Only needed if testing key server without SSL |
| HTTPS | TCP | 443 | 0.0.0.0/0 | Recommended for production (Nginx+SSL) |

> **Note**: The recommended production setup uses Nginx with SSL, which only requires ports 22, 8022, and 443 to be open. Ports 8000 and 80 are only needed for direct testing without a proper reverse proxy setup.

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
uv run m2m-mcp-server-ssh-server --host 0.0.0.0 --run-key-server --key-server-host 0.0.0.0
```

## Step 6: Setting Up Nginx as a Reverse Proxy

Nginx allows you to expose your key server securely and handle SSL termination.

1. **Install Nginx**:
   ```bash
   sudo apt update
   sudo apt install nginx -y
   ```

2. **Configure firewall to allow Nginx**:
   ```bash
   sudo ufw allow 'Nginx HTTP'  # For initial setup
   sudo ufw allow 'Nginx HTTPS' # For SSL (added later)
   ```

3. **Verify Nginx is running**:
   ```bash
   systemctl status nginx
   ```

4. **Create a site configuration**:
   ```bash
   sudo nano /etc/nginx/sites-available/mcp-key-server
   ```

5. **Add the following configuration**:
   ```nginx
   server {
       listen 80;
       listen [::]:80;

       server_name your_domain.com;  # Replace with your actual domain name

       location / {
           proxy_pass http://127.0.0.1:8000;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;
       }
   }
   ```

6. **Enable the site**:
   ```bash
   sudo ln -s /etc/nginx/sites-available/mcp-key-server /etc/nginx/sites-enabled/
   sudo nginx -t  # Test the configuration
   sudo systemctl restart nginx
   ```

## Step 7: Configure systemd Service for Automatic Startup

Setting up a systemd service ensures that your server automatically starts after system reboots and is managed properly.

1. **Create the systemd service file**:
   ```bash
   sudo nano /etc/systemd/system/mcp-ssh-server.service
   ```

2. **Add the following configuration**:
   ```ini
   [Unit]
   Description=M2M MCP Server SSH Server
   After=network.target

   [Service]
   WorkingDirectory=/home/ubuntu/m2m-mcp-server-ssh-server
   ExecStart=/bin/bash -c 'source /home/ubuntu/.bashrc && /home/ubuntu/.local/bin/uv sync --all-extras && /home/ubuntu/.local/bin/uv run m2m-mcp-server-ssh-server --host 0.0.0.0 --run-key-server --key-server-host 0.0.0.0'
   Environment="PATH=/home/ubuntu/.local/bin:/usr/local/bin:/usr/bin:/bin"
   Environment="PYTHONPATH=/home/ubuntu/m2m-mcp-server-ssh-server"
   Restart=always
   RestartSec=10
   User=ubuntu
   ProtectSystem=full
   PrivateTmp=true
   NoNewPrivileges=true

   [Install]
   WantedBy=multi-user.target
   ```

   > **Note**: Replace `/home/ubuntu` with your actual user's home directory path.

3. **Enable and start the service**:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable mcp-ssh-server.service
   sudo systemctl start mcp-ssh-server.service
   ```

4. **Check the service status**:
   ```bash
   sudo systemctl status mcp-ssh-server.service
   ```

5. **View logs if needed**:
   ```bash
   journalctl -u mcp-ssh-server.service --follow
   ```

## Step 8: Secure with HTTPS (Recommended for Production)

Adding HTTPS encryption is essential for production environments to secure the communication with your key server.

1. **Install Certbot for Nginx**:
   ```bash
   sudo apt install certbot python3-certbot-nginx -y
   ```

2. **Obtain and install SSL certificate**:
   ```bash
   sudo certbot --nginx -d your_domain.com
   ```
   > Follow the prompts to complete the certificate setup. Certbot will automatically modify your Nginx configuration.

3. **Test the certificate auto-renewal**:
   ```bash
   sudo certbot renew --dry-run
   ```

4. **Verify Nginx configuration**:
   ```bash
   sudo nginx -t
   sudo systemctl restart nginx
   ```

5. **Verify open ports**:
   ```bash
   sudo apt install net-tools -y
   sudo netstat -ntlp | grep 'nginx\|8000\|8022'
   ```

## Step 9: Testing the Connection

From your local development machine, test the connection to your server:

1. **Using the MCP Inspector tool**:
   ```bash
   # Install and run the MCP client with inspector
   npx @modelcontextprotocol/inspector -- uv run m2m-mcp-server-ssh-client --host your_domain.com --use-key-server
   ```

2. **Testing the key server API**:
   ```bash
   # Test the landing page
   curl https://your_domain.com/
   
   # Get the server's public key
   curl https://your_domain.com/server_pub_key
   
   # Check server health
   curl https://your_domain.com/health
   ```

## Troubleshooting

### Connection Issues
- Verify firewall rules allow traffic on required ports
- Check that both the SSH server and key server are running (systemctl status)
- Review logs: `journalctl -u mcp-ssh-server.service`
- Ensure Nginx is properly configured and running

### Certificate Issues
- Run `certbot certificates` to view all installed certificates
- Check Nginx error logs: `sudo tail -f /var/log/nginx/error.log`

### Permission Issues
- Ensure your service is running as the correct user
- Check file ownership and permissions for SSH keys and configuration files
