# Smart PC Guardian

AI-Based System Monitoring and Self-Healing Bot

------------------------------------------------------------------------

## Project Description

### Problem Statement

Modern computers frequently experience performance issues caused by high
CPU usage, excessive memory consumption, low disk space, and unstable
network connectivity. Although operating systems provide monitoring
utilities, these tools usually display only raw statistics without
helping users understand the root cause of the problem or suggesting
corrective actions.

Many users lack the technical knowledge required to diagnose system
performance issues, identify resource-intensive processes, or
troubleshoot network problems. As a result, system slowdowns and
connectivity failures often remain unresolved.

### Objectives

The main objectives of the Smart PC Guardian project are:

-   Continuously monitor system health in real time
-   Detect abnormal CPU, memory, disk, and network conditions
-   Provide intelligent recommendations using an AI model
-   Assist users in diagnosing and resolving system issues
-   Protect critical system processes using a whitelist mechanism

### Target Users

-   General computer users
-   Developers and students
-   Linux desktop users who want automated system monitoring

### System Overview

Smart PC Guardian is a lightweight AI-assisted monitoring system that
continuously observes system health. When abnormal conditions are
detected, the system alerts the user and provides recommended actions
using a local Large Language Model.

The system monitors:

-   CPU usage
-   Memory usage
-   Disk storage
-   Network connectivity

------------------------------------------------------------------------

## System Architecture / Design

### Workflow

System Monitoring Loop → Collect System Metrics (psutil) → Detect
abnormal resource usage → Send system context to AI model → Generate
recommendations → Show Zenity dialog → User selects action → Execute
safe healing action

### Core Components

1.  System Monitoring Module Monitors CPU, memory, disk usage, and
    network status.

2.  Process Analyzer Identifies processes consuming the most resources.

3.  AI Recommendation Engine Uses the Ollama LLaMA 3 -- 1B model to
    generate suggestions.

4.  Healing Engine Executes safe actions such as restarting applications
    or reconnecting networks.

5.  Safety Protection Module Prevents termination of critical system
    processes using a whitelist.

6.  User Interface Module Uses Zenity dialogs and notifications to
    interact with the user.

------------------------------------------------------------------------

## Technologies Used

Programming Language: Python 3

Libraries: - psutil - subprocess - datetime

AI Model: - Ollama - LLaMA 3 -- 1B parameter model

Linux Utilities: - nmcli - rfkill - ping - wmctrl

System Tools: - Zenity - systemd

Operating System: Linux (Ubuntu recommended)

------------------------------------------------------------------------

## Installation Instructions

### Requirements

-   Python 3.9+
-   Linux operating system
-   Ollama installed
-   Zenity
-   nmcli
-   rfkill

### Install dependencies

sudo apt update sudo apt install python3-pip zenity wmctrl
network-manager rfkill

Install Python library:

pip install psutil

Install Ollama:

curl -fsSL https://ollama.com/install.sh \| sh

Download the AI model:

ollama pull llama3:1b

------------------------------------------------------------------------

## How to Run the System

Run the main bot:

python main.py

To run as a background service:

sudo systemctl enable guardian.service sudo systemctl start
guardian.service

Check service status:

systemctl status guardian.service

------------------------------------------------------------------------

## Usage Instructions

### CPU Monitoring

When CPU usage is high, the system identifies top processes and suggests
actions such as:

-   Restart application
-   Kill process
-   Open system monitor

Example output:

CPU usage high (85%) Top processes: firefox → CPU 45% code → CPU 20%

------------------------------------------------------------------------

### Disk Monitoring

When disk usage is high, the system shows folders consuming the most
storage and allows users to open them.

Example:

Downloads (5.2 GB) Videos (3.8 GB) Projects (2.4 GB)

------------------------------------------------------------------------

### Network Monitoring

Detects problems such as:

-   WiFi disabled
-   Airplane mode enabled
-   Ethernet cable unplugged
-   No internet connectivity

The system suggests fixes such as enabling WiFi or reconnecting to saved
networks.

------------------------------------------------------------------------

## Dataset

Not applicable.

This system uses real-time system data collected from the operating
system rather than a static dataset.



