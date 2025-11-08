"""
vpcctl - Virtual Private Cloud Control Tool
A Linux-based VPC implementation using network namespaces, bridges, and iptables
"""

import os
import sys
import json
import subprocess
import argparse
import ipaddress
from pathlib import Path
from datetime import datetime

# Configuration
VPCCTL_DIR = Path("/etc/vpcctl")
VPCCTL_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = VPCCTL_DIR / "vpcctl.log"

class VPCManager:
    """Core VPC management class"""
    
    def __init__(self):
        self.ensure_root()
        
    def ensure_root(self):
        """Ensure script is run as root"""
        if os.geteuid() != 0:
            print("Error: This script must be run as root")
            sys.exit(1)
    
    def log(self, message, level="INFO"):
        """Log messages to file and console"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] [{level}] {message}"
        print(log_entry)
        with open(LOG_FILE, "a") as f:
            f.write(log_entry + "\n")
    
    def run_command(self, cmd, check=True, capture=True):
        """Execute shell command with logging"""
        self.log(f"Executing: {cmd}", "DEBUG")
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                check=check,
                capture_output=capture,
                text=True
            )
            if capture and result.stdout:
                self.log(f"Output: {result.stdout.strip()}", "DEBUG")
            return result
        except subprocess.CalledProcessError as e:
            self.log(f"Command failed: {cmd}\nError: {e.stderr}", "ERROR")
            if check:
                raise
            return e
    
    def vpc_exists(self, vpc_name):
        """Check if VPC exists"""
        vpc_file = VPCCTL_DIR / f"{vpc_name}.json"
        return vpc_file.exists()
    
    def load_vpc(self, vpc_name):
        """Load VPC metadata from JSON file"""
        vpc_file = VPCCTL_DIR / f"{vpc_name}.json"
        if not vpc_file.exists():
            raise ValueError(f"VPC '{vpc_name}' does not exist")
        with open(vpc_file, "r") as f:
            return json.load(f)
    
    def save_vpc(self, vpc_data):
        """Save VPC metadata to JSON file"""
        vpc_file = VPCCTL_DIR / f"{vpc_data['vpc_name']}.json"
        with open(vpc_file, "w") as f:
            json.dump(vpc_data, f, indent=2)
        self.log(f"Saved VPC metadata: {vpc_file}")
    
    def create_vpc(self, vpc_name, cidr):
        """Create a new VPC with specified CIDR"""
        # Validate inputs
        if self.vpc_exists(vpc_name):
            raise ValueError(f"VPC '{vpc_name}' already exists")
        
        try:
            network = ipaddress.ip_network(cidr)
        except ValueError as e:
            raise ValueError(f"Invalid CIDR: {e}")
        
        self.log(f"Creating VPC: {vpc_name} with CIDR: {cidr}")
        
        # Bridge name
        bridge_name = f"br-{vpc_name}"
        
        # Gateway IP (first usable IP in the range)
        gateway_ip = str(list(network.hosts())[0])
        
        # Create bridge
        self.log(f"Creating bridge: {bridge_name}")
        self.run_command(f"ip link add {bridge_name} type bridge")
        self.run_command(f"ip addr add {gateway_ip}/{network.prefixlen} dev {bridge_name}")
        self.run_command(f"ip link set {bridge_name} up")
        
        # Enable IP forwarding on bridge
        self.run_command(f"sysctl -w net.ipv4.ip_forward=1")
        
        # Create VPC metadata
        vpc_data = {
            "vpc_name": vpc_name,
            "cidr": cidr,
            "bridge": bridge_name,
            "gateway_ip": gateway_ip,
            "subnets": {},
            "peerings": [],
            "created_at": datetime.now().isoformat()
        }
        
        self.save_vpc(vpc_data)
        self.log(f"VPC '{vpc_name}' created successfully")
        return vpc_data
    
    def create_subnet(self, vpc_name, subnet_name, subnet_cidr, subnet_type="private"):
        """Add a subnet to an existing VPC"""
        vpc_data = self.load_vpc(vpc_name)
        
        # Validate subnet doesn't exist
        if subnet_name in vpc_data["subnets"]:
            raise ValueError(f"Subnet '{subnet_name}' already exists in VPC '{vpc_name}'")
        
        # Validate CIDR
        try:
            subnet_network = ipaddress.ip_network(subnet_cidr)
            vpc_network = ipaddress.ip_network(vpc_data["cidr"])
        except ValueError as e:
            raise ValueError(f"Invalid CIDR: {e}")
        
        # Ensure subnet is within VPC CIDR
        if not subnet_network.subnet_of(vpc_network):
            raise ValueError(f"Subnet {subnet_cidr} is not within VPC CIDR {vpc_data['cidr']}")
        
        self.log(f"Creating {subnet_type} subnet: {subnet_name} ({subnet_cidr}) in VPC {vpc_name}")
        
        # Namespace name
        ns_name = f"ns-{vpc_name}-{subnet_name}"
        
        # Veth pair names
        veth_host = f"veth-{subnet_name}"
        veth_ns = f"veth-{subnet_name}-ns"
        
        # IP for the interface inside namespace (second usable IP)
        subnet_ip = str(list(subnet_network.hosts())[1])
        
        # Create network namespace
        self.log(f"Creating namespace: {ns_name}")
        self.run_command(f"ip netns add {ns_name}")
        
        # Create veth pair
        self.log(f"Creating veth pair: {veth_host} <-> {veth_ns}")
        self.run_command(f"ip link add {veth_host} type veth peer name {veth_ns}")
        
        # Move one end into namespace
        self.run_command(f"ip link set {veth_ns} netns {ns_name}")
        
        # Attach host-side veth to bridge
        self.run_command(f"ip link set {veth_host} master {vpc_data['bridge']}")
        self.run_command(f"ip link set {veth_host} up")
        
        # Configure namespace
        self.log(f"Configuring namespace {ns_name}")
        self.run_command(f"ip netns exec {ns_name} ip link set lo up")
        self.run_command(f"ip netns exec {ns_name} ip addr add {subnet_ip}/{subnet_network.prefixlen} dev {veth_ns}")
        self.run_command(f"ip netns exec {ns_name} ip link set {veth_ns} up")
        self.run_command(f"ip netns exec {ns_name} ip route add default via {vpc_data['gateway_ip']}")
        
        # If public subnet, configure NAT
        if subnet_type == "public":
            self.configure_nat(vpc_name, subnet_cidr)
        
        # Save subnet metadata
        vpc_data["subnets"][subnet_name] = {
            "cidr": subnet_cidr,
            "namespace": ns_name,
            "veth_host": veth_host,
            "veth_ns": veth_ns,
            "gateway": vpc_data["gateway_ip"],
            "ip": subnet_ip,
            "type": subnet_type,
            "firewall_rules": None
        }
        
        self.save_vpc(vpc_data)
        self.log(f"Subnet '{subnet_name}' created successfully in VPC '{vpc_name}'")
        return vpc_data
    
    def configure_nat(self, vpc_name, subnet_cidr):
        """Configure NAT for a public subnet"""
        self.log(f"Configuring NAT for subnet {subnet_cidr}")
        
        # Get default outbound interface
        result = self.run_command("ip route | grep default | awk '{print $5}' | head -n1")
        default_iface = result.stdout.strip()
        
        if not default_iface:
            self.log("Warning: Could not determine default network interface", "WARN")
            return
        
        vpc_data = self.load_vpc(vpc_name)
        bridge = vpc_data["bridge"]
        
        # Enable masquerading for outbound traffic
        self.run_command(
            f"iptables -t nat -A POSTROUTING -s {subnet_cidr} -o {default_iface} -j MASQUERADE",
            check=False
        )
        
        # Allow forwarding from bridge to default interface
        self.run_command(
            f"iptables -A FORWARD -i {bridge} -o {default_iface} -j ACCEPT",
            check=False
        )
        
        # Allow established connections back
        self.run_command(
            f"iptables -A FORWARD -i {default_iface} -o {bridge} -m state --state RELATED,ESTABLISHED -j ACCEPT",
            check=False
        )
        
        self.log(f"NAT configured for {subnet_cidr} via {default_iface}")
    
    def deploy_workload(self, vpc_name, subnet_name, workload_type="nginx", port=80):
        """Deploy a test workload in a subnet"""
        vpc_data = self.load_vpc(vpc_name)
        
        if subnet_name not in vpc_data["subnets"]:
            raise ValueError(f"Subnet '{subnet_name}' not found in VPC '{vpc_name}'")
        
        subnet = vpc_data["subnets"][subnet_name]
        ns_name = subnet["namespace"]
        subnet_ip = subnet["ip"]
        
        self.log(f"Deploying {workload_type} in subnet {subnet_name} (namespace: {ns_name})")
        
        if workload_type == "nginx":
            # Create a simple HTML file
            html_content = f"""
<!DOCTYPE html>
<html>
<head><title>VPC Test - {vpc_name}/{subnet_name}</title></head>
<body>
    <h1>Hello from {vpc_name}/{subnet_name}</h1>
    <p>IP: {subnet_ip}</p>
    <p>Subnet: {subnet['cidr']}</p>
    <p>Type: {subnet['type']}</p>
</body>
</html>
"""
            html_file = VPCCTL_DIR / f"{vpc_name}-{subnet_name}.html"
            with open(html_file, "w") as f:
                f.write(html_content)
            
            # Start Python HTTP server in namespace
            cmd = f"ip netns exec {ns_name} python3 -m http.server {port} --directory {VPCCTL_DIR} &"
            self.run_command(cmd, check=False)
            self.log(f"Nginx-like server deployed at {subnet_ip}:{port}")
            self.log(f"Test with: ip netns exec {ns_name} curl http://{subnet_ip}:{port}/{html_file.name}")
            
        elif workload_type == "python":
            # Simple Python HTTP server
            cmd = f"ip netns exec {ns_name} python3 -m http.server {port} &"
            self.run_command(cmd, check=False)
            self.log(f"Python HTTP server deployed at {subnet_ip}:{port}")
        
        else:
            raise ValueError(f"Unsupported workload type: {workload_type}")
    
    def apply_firewall(self, vpc_name, subnet_name, policy_file):
        """Apply firewall rules to a subnet based on JSON policy"""
        vpc_data = self.load_vpc(vpc_name)
        
        if subnet_name not in vpc_data["subnets"]:
            raise ValueError(f"Subnet '{subnet_name}' not found in VPC '{vpc_name}'")
        
        subnet = vpc_data["subnets"][subnet_name]
        ns_name = subnet["namespace"]
        
        self.log(f"Applying firewall rules to {subnet_name} from {policy_file}")
        
        # Load policy
        with open(policy_file, "r") as f:
            policy = json.load(f)
        
        # Set default DROP policy
        self.run_command(f"ip netns exec {ns_name} iptables -P INPUT DROP", check=False)
        
        # Allow loopback
        self.run_command(f"ip netns exec {ns_name} iptables -A INPUT -i lo -j ACCEPT", check=False)
        
        # Allow established connections
        self.run_command(
            f"ip netns exec {ns_name} iptables -A INPUT -m state --state ESTABLISHED,RELATED -j ACCEPT",
            check=False
        )
        
        # Apply ingress rules
        if "ingress" in policy:
            for rule in policy["ingress"]:
                port = rule.get("port")
                protocol = rule.get("protocol", "tcp")
                action = rule.get("action", "allow").upper()
                
                if action == "ALLOW":
                    iptables_action = "ACCEPT"
                else:
                    iptables_action = "DROP"
                
                cmd = f"ip netns exec {ns_name} iptables -A INPUT -p {protocol} --dport {port} -j {iptables_action}"
                self.run_command(cmd, check=False)
                self.log(f"Applied rule: {protocol}/{port} -> {action}")
        
        # Store policy path in metadata
        vpc_data["subnets"][subnet_name]["firewall_rules"] = policy_file
        self.save_vpc(vpc_data)
        
        self.log(f"Firewall rules applied to {subnet_name}")
    
    def peer_vpcs(self, vpc1_name, vpc2_name):
        """Establish peering between two VPCs"""
        vpc1_data = self.load_vpc(vpc1_name)
        vpc2_data = self.load_vpc(vpc2_name)
        
        # Check if already peered
        for peering in vpc1_data["peerings"]:
            if peering["peer_vpc"] == vpc2_name:
                self.log(f"VPCs {vpc1_name} and {vpc2_name} are already peered", "WARN")
                return
        
        self.log(f"Establishing peering between {vpc1_name} and {vpc2_name}")
        
        # Create veth pair for peering
        veth_vpc1 = f"peer-{vpc1_name}-{vpc2_name}"
        veth_vpc2 = f"peer-{vpc2_name}-{vpc1_name}"
        
        # Create veth pair
        self.run_command(f"ip link add {veth_vpc1} type veth peer name {veth_vpc2}")
        
        # Attach each end to respective bridge
        self.run_command(f"ip link set {veth_vpc1} master {vpc1_data['bridge']}")
        self.run_command(f"ip link set {veth_vpc2} master {vpc2_data['bridge']}")
        
        # Bring up both ends
        self.run_command(f"ip link set {veth_vpc1} up")
        self.run_command(f"ip link set {veth_vpc2} up")
        
        # Add routes for cross-VPC communication
        # On VPC1 bridge, add route to VPC2's CIDR
        self.run_command(
            f"ip route add {vpc2_data['cidr']} dev {vpc1_data['bridge']}",
            check=False
        )
        
        # On VPC2 bridge, add route to VPC1's CIDR
        self.run_command(
            f"ip route add {vpc1_data['cidr']} dev {vpc2_data['bridge']}",
            check=False
        )
        
        # Update namespaces with routes to peer VPC
        for subnet_name, subnet in vpc1_data["subnets"].items():
            self.run_command(
                f"ip netns exec {subnet['namespace']} ip route add {vpc2_data['cidr']} via {vpc1_data['gateway_ip']}",
                check=False
            )
        
        for subnet_name, subnet in vpc2_data["subnets"].items():
            self.run_command(
                f"ip netns exec {subnet['namespace']} ip route add {vpc1_data['cidr']} via {vpc2_data['gateway_ip']}",
                check=False
            )
        
        # Allow forwarding between bridges
        self.run_command(
            f"iptables -A FORWARD -i {vpc1_data['bridge']} -o {vpc2_data['bridge']} -j ACCEPT",
            check=False
        )
        self.run_command(
            f"iptables -A FORWARD -i {vpc2_data['bridge']} -o {vpc1_data['bridge']} -j ACCEPT",
            check=False
        )
        
        # Update peering metadata
        peering_info_vpc1 = {
            "peer_vpc": vpc2_name,
            "veth_local": veth_vpc1,
            "veth_remote": veth_vpc2
        }
        peering_info_vpc2 = {
            "peer_vpc": vpc1_name,
            "veth_local": veth_vpc2,
            "veth_remote": veth_vpc1
        }
        
        vpc1_data["peerings"].append(peering_info_vpc1)
        vpc2_data["peerings"].append(peering_info_vpc2)
        
        self.save_vpc(vpc1_data)
        self.save_vpc(vpc2_data)
        
        self.log(f"Peering established between {vpc1_name} and {vpc2_name}")
    
    def list_vpcs(self):
        """List all VPCs"""
        vpc_files = list(VPCCTL_DIR.glob("*.json"))
        
        if not vpc_files:
            self.log("No VPCs found")
            return
        
        self.log("=" * 80)
        self.log("EXISTING VPCs")
        self.log("=" * 80)
        
        for vpc_file in vpc_files:
            vpc_data = json.load(open(vpc_file))
            self.log(f"\nVPC: {vpc_data['vpc_name']}")
            self.log(f"  CIDR: {vpc_data['cidr']}")
            self.log(f"  Bridge: {vpc_data['bridge']}")
            self.log(f"  Gateway: {vpc_data['gateway_ip']}")
            self.log(f"  Subnets: {len(vpc_data['subnets'])}")
            
            for subnet_name, subnet in vpc_data['subnets'].items():
                self.log(f"    - {subnet_name} ({subnet['cidr']}) [{subnet['type']}]")
            
            if vpc_data['peerings']:
                self.log(f"  Peerings: {len(vpc_data['peerings'])}")
                for peering in vpc_data['peerings']:
                    self.log(f"    - {peering['peer_vpc']}")
        
        self.log("=" * 80)
    
    def delete_subnet(self, vpc_name, subnet_name):
        """Delete a subnet from a VPC"""
        vpc_data = self.load_vpc(vpc_name)
        
        if subnet_name not in vpc_data["subnets"]:
            raise ValueError(f"Subnet '{subnet_name}' not found in VPC '{vpc_name}'")
        
        subnet = vpc_data["subnets"][subnet_name]
        ns_name = subnet["namespace"]
        veth_host = subnet["veth_host"]
        
        self.log(f"Deleting subnet: {subnet_name} from VPC {vpc_name}")
        
        # Kill any processes in namespace
        self.run_command(f"ip netns pids {ns_name} | xargs -r kill -9", check=False)
        
        # Flush iptables in namespace
        self.run_command(f"ip netns exec {ns_name} iptables -F", check=False)
        self.run_command(f"ip netns exec {ns_name} iptables -t nat -F", check=False)
        
        # Delete veth pair (automatically removes both ends)
        self.run_command(f"ip link delete {veth_host}", check=False)
        
        # Delete namespace
        self.run_command(f"ip netns delete {ns_name}", check=False)
        
        # Remove NAT rules if public subnet
        if subnet["type"] == "public":
            self.run_command(
                f"iptables -t nat -D POSTROUTING -s {subnet['cidr']} -j MASQUERADE",
                check=False
            )
        
        # Remove from metadata
        del vpc_data["subnets"][subnet_name]
        self.save_vpc(vpc_data)
        
        self.log(f"Subnet '{subnet_name}' deleted successfully")
    
    def delete_vpc(self, vpc_name):
        """Delete a VPC and all its resources"""
        if not self.vpc_exists(vpc_name):
            raise ValueError(f"VPC '{vpc_name}' does not exist")
        
        vpc_data = self.load_vpc(vpc_name)
        
        self.log(f"Deleting VPC: {vpc_name}")
        
        # Delete all subnets first
        subnet_names = list(vpc_data["subnets"].keys())
        for subnet_name in subnet_names:
            try:
                self.delete_subnet(vpc_name, subnet_name)
            except Exception as e:
                self.log(f"Error deleting subnet {subnet_name}: {e}", "ERROR")
        
        # Delete peering connections
        for peering in vpc_data["peerings"]:
            try:
                veth_local = peering["veth_local"]
                self.run_command(f"ip link delete {veth_local}", check=False)
                
                # Remove routes
                peer_vpc_data = self.load_vpc(peering["peer_vpc"])
                self.run_command(
                    f"ip route del {peer_vpc_data['cidr']} dev {vpc_data['bridge']}",
                    check=False
                )
            except Exception as e:
                self.log(f"Error deleting peering: {e}", "ERROR")
        
        # Delete bridge
        bridge = vpc_data["bridge"]
        self.run_command(f"ip link set {bridge} down", check=False)
        self.run_command(f"ip link delete {bridge}", check=False)
        
        # Clean up iptables rules
        self.run_command(f"iptables -D FORWARD -i {bridge} -j ACCEPT", check=False)
        
        # Delete metadata file
        vpc_file = VPCCTL_DIR / f"{vpc_name}.json"
        vpc_file.unlink(missing_ok=True)
        
        self.log(f"VPC '{vpc_name}' deleted successfully")


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description="vpcctl - Virtual Private Cloud Control Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Create VPC
    create_vpc_parser = subparsers.add_parser("create-vpc", help="Create a new VPC")
    create_vpc_parser.add_argument("--name", required=True, help="VPC name")
    create_vpc_parser.add_argument("--cidr", required=True, help="CIDR block (e.g., 10.0.0.0/16)")
    
    # Create Subnet
    create_subnet_parser = subparsers.add_parser("create-subnet", help="Create a subnet in a VPC")
    create_subnet_parser.add_argument("--vpc", required=True, help="VPC name")
    create_subnet_parser.add_argument("--name", required=True, help="Subnet name")
    create_subnet_parser.add_argument("--cidr", required=True, help="Subnet CIDR")
    create_subnet_parser.add_argument("--type", choices=["public", "private"], default="private", help="Subnet type")
    
    # Deploy workload
    deploy_parser = subparsers.add_parser("deploy", help="Deploy workload in subnet")
    deploy_parser.add_argument("--vpc", required=True, help="VPC name")
    deploy_parser.add_argument("--subnet", required=True, help="Subnet name")
    deploy_parser.add_argument("--type", choices=["nginx", "python"], default="nginx", help="Workload type")
    deploy_parser.add_argument("--port", type=int, default=80, help="Port number")
    
    # Apply firewall
    firewall_parser = subparsers.add_parser("apply-firewall", help="Apply firewall rules")
    firewall_parser.add_argument("--vpc", required=True, help="VPC name")
    firewall_parser.add_argument("--subnet", required=True, help="Subnet name")
    firewall_parser.add_argument("--policy", required=True, help="Policy JSON file")
    
    # Peer VPCs
    peer_parser = subparsers.add_parser("peer", help="Establish VPC peering")
    peer_parser.add_argument("--vpc1", required=True, help="First VPC name")
    peer_parser.add_argument("--vpc2", required=True, help="Second VPC name")
    
    # List VPCs
    subparsers.add_parser("list", help="List all VPCs")
    
    # Delete subnet
    delete_subnet_parser = subparsers.add_parser("delete-subnet", help="Delete a subnet")
    delete_subnet_parser.add_argument("--vpc", required=True, help="VPC name")
    delete_subnet_parser.add_argument("--name", required=True, help="Subnet name")
    
    # Delete VPC
    delete_vpc_parser = subparsers.add_parser("delete-vpc", help="Delete a VPC")
    delete_vpc_parser.add_argument("--name", required=True, help="VPC name")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    # Initialize VPC Manager
    manager = VPCManager()
    
    try:
        if args.command == "create-vpc":
            manager.create_vpc(args.name, args.cidr)
        
        elif args.command == "create-subnet":
            manager.create_subnet(args.vpc, args.name, args.cidr, args.type)
        
        elif args.command == "deploy":
            manager.deploy_workload(args.vpc, args.subnet, args.type, args.port)
        
        elif args.command == "apply-firewall":
            manager.apply_firewall(args.vpc, args.subnet, args.policy)
        
        elif args.command == "peer":
            manager.peer_vpcs(args.vpc1, args.vpc2)
        
        elif args.command == "list":
            manager.list_vpcs()
        
        elif args.command == "delete-subnet":
            manager.delete_subnet(args.vpc, args.name)
        
        elif args.command == "delete-vpc":
            manager.delete_vpc(args.name)
    
    except Exception as e:
        manager.log(f"Error: {e}", "ERROR")
        sys.exit(1)


if __name__ == "__main__":
    main()