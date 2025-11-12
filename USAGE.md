# VPCctl Usage Guide

Complete guide for using the Linux-based VPC implementation.

🏗️ Architecture
┌─────────────────────────────────────────────────────────────┐
│                        Host System                          │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              VPC 1 (10.0.0.0/16)                     │  │
│  │  ┌──────────────────┐      ┌──────────────────┐    │  │
│  │  │ Public Subnet    │      │ Private Subnet   │    │  │
│  │  │ (Namespace)      │      │ (Namespace)      │    │  │
│  │  │ 10.0.1.0/24      │      │ 10.0.2.0/24      │    │  │
│  │  │  [nginx:80]      │      │  [app:8080]      │    │  │
│  │  └────────┬─────────┘      └────────┬─────────┘    │  │
│  │           │ veth                     │ veth         │  │
│  │           └──────────┬───────────────┘              │  │
│  │                      │                               │  │
│  │                ┌─────▼──────┐                       │  │
│  │                │   Bridge   │ (VPC Router)          │  │
│  │                │ (br-vpc1)  │                       │  │
│  │                └─────┬──────┘                       │  │
│  │                      │ (NAT enabled)                │  │
│  └──────────────────────┼───────────────────────────────┘  │
│                         │                                   │
│                         ▼                                   │
│                [Host eth0] ──► Internet                    │
└─────────────────────────────────────────────────────────────┘

## Prerequisites

```bash
# Ensure you have required tools
sudo apt-get update
sudo apt-get install -y python3 iproute2 iptables bridge-utils

# Verify you're running as root
sudo -i
```

## Installation

```bash
# Make the script executable
chmod +x vpcctl.py

# Optionally, create a symlink for easier access
ln -s $(pwd)/vpcctl.py /usr/local/bin/vpcctl
```

## Quick Start Example

```bash
# 1. Create a VPC
sudo python3 vpcctl.py create-vpc --name myvpc --cidr 10.0.0.0/16

# 2. Add public subnet (with internet access)
sudo python3 vpcctl.py create-subnet --vpc myvpc --name public --cidr 10.0.1.0/24 --type public

# 3. Add private subnet (no internet access)
sudo python3 vpcctl.py create-subnet --vpc myvpc --name private --cidr 10.0.2.0/24 --type private

# 4. Deploy a web server
sudo python3 vpcctl.py deploy --vpc myvpc --subnet public --type nginx --port 80

# 5. List all VPCs
sudo python3 vpcctl.py list

# 6. Clean up
sudo python3 vpcctl.py delete-vpc --name myvpc
```

## Detailed Command Reference

### 1. Create VPC

Create a new Virtual Private Cloud with a specified CIDR range.

```bash
sudo python3 vpcctl.py create-vpc --name <vpc_name> --cidr <cidr_block>

# Example
sudo python3 vpcctl.py create-vpc --name production --cidr 10.0.0.0/16
```

**What happens:**
- Creates a Linux bridge (`br-<vpc_name>`)
- Assigns gateway IP (first usable IP in CIDR)
- Enables IP forwarding
- Saves metadata to `/etc/vpcctl/<vpc_name>.json`

### 2. Create Subnet

Add a subnet to an existing VPC.

```bash
sudo python3 vpcctl.py create-subnet \
  --vpc <vpc_name> \
  --name <subnet_name> \
  --cidr <subnet_cidr> \
  --type <public|private>

# Examples
sudo python3 vpcctl.py create-subnet --vpc production --name web --cidr 10.0.1.0/24 --type public
sudo python3 vpcctl.py create-subnet --vpc production --name db --cidr 10.0.2.0/24 --type private
```

**What happens:**
- Creates network namespace
- Creates veth pair
- Connects subnet to VPC bridge
- Configures routing
- If public: enables NAT for internet access

### 3. Deploy Workload

Deploy a test application in a subnet.

```bash
sudo python3 vpcctl.py deploy \
  --vpc <vpc_name> \
  --subnet <subnet_name> \
  --type <nginx|python> \
  --port <port_number>

# Examples
sudo python3 vpcctl.py deploy --vpc production --subnet web --type nginx --port 80
sudo python3 vpcctl.py deploy --vpc production --subnet db --type python --port 8080
```

**Supported workload types:**
- `nginx`: Creates an HTML page and serves it with Python HTTP server
- `python`: Simple Python HTTP server

### 4. Apply Firewall Rules

Apply security group rules to a subnet.

```bash
sudo python3 vpcctl.py apply-firewall \
  --vpc <vpc_name> \
  --subnet <subnet_name> \
  --policy <policy_file.json>

# Example
sudo python3 vpcctl.py apply-firewall --vpc production --subnet web --policy web_policy.json
```

**Policy file format:**

```json
{
  "subnet": "10.0.1.0/24",
  "ingress": [
    {"port": 80, "protocol": "tcp", "action": "allow"},
    {"port": 443, "protocol": "tcp", "action": "allow"},
    {"port": 22, "protocol": "ssh", "action": "deny"}
  ],
  "egress": [
    {"action": "allow"}
  ]
}
```

### 5. Peer VPCs

Establish peering connection between two VPCs.

```bash
sudo python3 vpcctl.py peer --vpc1 <vpc1_name> --vpc2 <vpc2_name>

# Example
sudo python3 vpcctl.py peer --vpc1 production --vpc2 development
```

**What happens:**
- Creates veth pair connecting both bridges
- Adds routes for cross-VPC communication
- Updates all namespace routing tables
- Configures iptables for forwarding

### 6. List VPCs

Display all VPCs and their configuration.

```bash
sudo python3 vpcctl.py list
```

### 7. Delete Subnet

Remove a subnet from a VPC.

```bash
sudo python3 vpcctl.py delete-subnet --vpc <vpc_name> --name <subnet_name>

# Example
sudo python3 vpcctl.py delete-subnet --vpc production --name web
```

### 8. Delete VPC

Remove a VPC and all its resources.

```bash
sudo python3 vpcctl.py delete-vpc --name <vpc_name>

# Example
sudo python3 vpcctl.py delete-vpc --name production
```

## Testing & Validation

### Test Intra-VPC Communication

```bash
# From one subnet to another in the same VPC
sudo ip netns exec ns-myvpc-public ping 10.0.2.11
```

### Test Internet Access

```bash
# Public subnet should have internet access
sudo ip netns exec ns-myvpc-public ping 8.8.8.8
sudo ip netns exec ns-myvpc-public curl google.com

# Private subnet should NOT have internet access
sudo ip netns exec ns-myvpc-private ping 8.8.8.8  # Should timeout
```

### Test VPC Isolation

```bash
# Without peering, VPCs should be isolated
sudo ip netns exec ns-vpc1-public ping 10.1.1.11  # Should fail
```

### Test VPC Peering

```bash
# After peering, should work
sudo python3 vpcctl.py peer --vpc1 vpc1 --vpc2 vpc2
sudo ip netns exec ns-vpc1-public ping 10.1.1.11  # Should succeed
```

### Test Web Servers

```bash
# Access from host
curl http://10.0.1.11:80

# Access from another namespace
sudo ip netns exec ns-myvpc-private curl http://10.0.1.11:80
```

### Test Firewall Rules

```bash
# Test allowed port
sudo ip netns exec ns-myvpc-private nc -zv 10.0.1.11 80

# Test blocked port
sudo ip netns exec ns-myvpc-private nc -zv 10.0.1.11 22
```

## Advanced Usage

### Multi-Tier Application Setup

```bash
# Create VPC
sudo python3 vpcctl.py create-vpc --name app --cidr 10.0.0.0/16

# Web tier (public)
sudo python3 vpcctl.py create-subnet --vpc app --name web --cidr 10.0.1.0/24 --type public
sudo python3 vpcctl.py deploy --vpc app --subnet web --type nginx --port 80

# Application tier (private)
sudo python3 vpcctl.py create-subnet --vpc app --name app --cidr 10.0.2.0/24 --type private
sudo python3 vpcctl.py deploy --vpc app --subnet app --type python --port 8080

# Database tier (private)
sudo python3 vpcctl.py create-subnet --vpc app --name db --cidr 10.0.3.0/24 --type private

# Apply security rules
cat > web_policy.json << EOF
{
  "subnet": "10.0.1.0/24",
  "ingress": [
    {"port": 80, "protocol": "tcp", "action": "allow"},
    {"port": 443, "protocol": "tcp", "action": "allow"}
  ]
}
EOF

sudo python3 vpcctl.py apply-firewall --vpc app --subnet web --policy web_policy.json
```

### Hub-and-Spoke Network

```bash
# Create hub VPC
sudo python3 vpcctl.py create-vpc --name hub --cidr 10.0.0.0/16
sudo python3 vpcctl.py create-subnet --vpc hub --name transit --cidr 10.0.1.0/24 --type public

# Create spoke VPCs
sudo python3 vpcctl.py create-vpc --name spoke1 --cidr 10.1.0.0/16
sudo python3 vpcctl.py create-subnet --vpc spoke1 --name app --cidr 10.1.1.0/24 --type private

sudo python3 vpcctl.py create-vpc --name spoke2 --cidr 10.2.0.0/16
sudo python3 vpcctl.py create-subnet --vpc spoke2 --name app --cidr 10.2.1.0/24 --type private

# Peer hub with spokes
sudo python3 vpcctl.py peer --vpc1 hub --vpc2 spoke1
sudo python3 vpcctl.py peer --vpc1 hub --vpc2 spoke2
```

## Troubleshooting

### Check VPC Status

```bash
# List all bridges
ip link show type bridge

# List all namespaces
ip netns list

# Check namespace details
ip netns exec ns-myvpc-public ip addr
ip netns exec ns-myvpc-public ip route
```

### View Iptables Rules

```bash
# Host iptables
sudo iptables -L -v -n
sudo iptables -t nat -L -v -n

# Namespace iptables
sudo ip netns exec ns-myvpc-public iptables -L -v -n
```

### Check Logs

```bash
# View VPCctl logs
sudo cat /etc/vpcctl/vpcctl.log
sudo tail -f /etc/vpcctl/vpcctl.log
```

### Common Issues

**Issue: "Operation not permitted"**
```bash
# Solution: Run as root
sudo -i
```

**Issue: "Namespace already exists"**
```bash
# Solution: Delete existing resources first
sudo python3 vpcctl.py delete-vpc --name <vpc_name>
```

**Issue: "No route to host"**
```bash
# Solution: Check routing tables
sudo ip netns exec <namespace> ip route
```

**Issue: "Cannot reach internet from public subnet"**
```bash
# Solution: Check NAT rules and default interface
sudo iptables -t nat -L -v -n
ip route | grep default
```

## File Locations

- **Metadata**: `/etc/vpcctl/<vpc_name>.json`
- **Logs**: `/etc/vpcctl/vpcctl.log`
- **HTML files**: `/etc/vpcctl/<vpc>-<subnet>.html`

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                      Host System                        │
│                                                          │
│  ┌────────────── VPC (10.0.0.0/16) ─────────────────┐  │
│  │                                                    │  │
│  │   ┌─────────────────────┐  ┌──────────────────┐ │  │
│  │   │  Public Subnet      │  │  Private Subnet  │ │  │
│  │   │  (ns-vpc-public)    │  │  (ns-vpc-private)│ │  │
│  │   │  10.0.1.0/24        │  │  10.0.2.0/24     │ │  │
│  │   │  [nginx:80]         │  │  [app:8080]      │ │  │
│  │   └──────────┬──────────┘  └────────┬─────────┘ │  │
│  │              │ veth                   │ veth      │  │
│  │              └────────┬───────────────┘           │  │
│  │                       │                            │  │
│  │                 ┌─────▼──────┐                    │  │
│  │                 │   Bridge   │                    │  │
│  │                 │  (br-vpc)  │                    │  │
│  │                 └─────┬──────┘                    │  │
│  │                       │ (NAT for public)          │  │
│  └───────────────────────┼───────────────────────────┘  │
│                          │                               │
│                          ▼                               │
│                  [Host Interface] ──► Internet          │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

## Example Firewall Policies

### Web Server Policy
```json
{
  "subnet": "10.0.1.0/24",
  "ingress": [
    {"port": 80, "protocol": "tcp", "action": "allow"},
    {"port": 443, "protocol": "tcp", "action": "allow"},
    {"port": 22, "protocol": "tcp", "action": "deny"}
  ]
}
```

### Database Server Policy
```json
{
  "subnet": "10.0.3.0/24",
  "ingress": [
    {"port": 3306, "protocol": "tcp", "action": "allow"},
    {"port": 5432, "protocol": "tcp", "action": "allow"}
  ]
}
```

### Restrictive Policy (Deny All)
```json
{
  "subnet": "10.0.2.0/24",
  "ingress": []
}
```

## Performance Considerations

- Each subnet creates a separate network namespace (lightweight)
- Bridges operate at near-native speed
- Recommended limits:
  - VPCs per host: 50-100
  - Subnets per VPC: 10-20
  - Concurrent connections: Depends on host resources

## Security Best Practices

1. **Principle of Least Privilege**: Use private subnets by default
2. **Firewall Rules**: Always apply restrictive ingress rules
3. **Peering**: Only peer VPCs when necessary
4. **Monitoring**: Regularly check logs at `/etc/vpcctl/vpcctl.log`
5. **Clean Up**: Delete unused VPCs to free resources

## Integration with Real Workloads

### Running Docker Containers
```bash
# Run container in namespace
sudo ip netns exec ns-myvpc-public docker run -d -p 80:80 nginx
```

### Running Custom Applications
```bash
# Execute any command in namespace
sudo ip netns exec ns-myvpc-public /path/to/your/app
```

## Next Steps

1. Run the test suite: `sudo bash test_vpcctl.sh`
2. Create your first VPC with the Quick Start example
3. Experiment with different network topologies
4. Integrate with your own applications

For issues or questions, check the logs at `/etc/vpcctl/vpcctl.log`