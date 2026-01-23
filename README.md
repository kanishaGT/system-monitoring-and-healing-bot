# System Monitoring Bot (Linux)

A Linux system monitoring and alerting bot built with Python and systemd.

## Features
- Monitors CPU, Memory, Disk, Network connectivity
- Alerts using notify-send and Zenity (Yes/No + action options)
- Runs in background using systemd user service

## Project Structure
- `src/` - Python source code
- `systemd/` - systemd service file
- `scripts/` - install/uninstall scripts (optional)
- `docs/` - documentation

## Run (Developer)
```bash
python3 src/monitor_bot.py

