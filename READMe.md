# VPCctl Project Summary

VPCctl is a powerful Linux-based command-line tool designed to recreate the functionality of a Virtual Private Cloud (VPC), similar to what is offered by major cloud providers like AWS, entirely on a Linux host.

## Core Concept and Technology

- The project achieves complex networking using standard Linux primitives:

- Network Namespaces: Used to create isolated environments for VPCs and subnets.

- Bridges and Veth Pairs: Used for routing traffic between subnets within a VPC (acting as a virtual router).

- IPTables: Used to enforce firewall rules (Security Groups) and provide NAT Gateway functionality for public subnets to access the Internet.

## Key Features

VPCctl offers full lifecycle management for virtual cloud resources:

- VPC and Subnets: Create isolated VPCs with custom CIDRs, including both Public (with NAT-enabled Internet access) and Private subnets (isolated).

- Isolation and Routing: Guarantees complete isolation between different VPCs while providing seamless Inter-subnet Routing within a single VPC.

- Advanced Networking: Supports VPC Peering to connect two different VPCs and enable cross-VPC communication.

- Security Groups: Apply granular, JSON-defined firewall rules via iptables to control ingress/egress traffic.

- Workloads: Easily deploy test applications (like nginx or python servers) into the defined subnets for connectivity testing.

- Operational Safety: All operations are idempotent (safe to run multiple times) and actions are recorded in a comprehensive log file.

## Quick Start Overview

Using the vpcctl.py script requires root access and follows a simple, logical sequence:

1. create-vpc: Define the overall network (e.g., 10.0.0.0/16).

2. create-subnet: Segment the VPC into isolated public and private networks.

4. deploy: Place test workloads into the subnets.

5. delete-vpc: Cleanly remove all associated resources and network primitives.

The project is highly valuable for both developing practical network solutions and serving as an in-depth learning resource on how Linux network virtualization works.