#!/usr/bin/env python3
import time
import psutil
import subprocess
from datetime import datetime

# ----------------- THRESHOLDS -----------------
CPU_TOTAL_THRESHOLD = 10         # total CPU %
MEM_TOTAL_THRESHOLD = 90          # total RAM %
DISK_THRESHOLD = 85               # disk usage %
COOLDOWN = 30                     # seconds between popups per type

# ----------------- STATE -----------------
last_alert_time = {
    "cpu": 0,
    "mem": 0,
    "disk": 0,
    "net": 0
}

last_net_connected = None  # track disconnect/reconnect changes


# ----------------- HELPERS -----------------
def now():
    return time.time()


def log(msg):
    # goes to systemd journal
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def notify(title, message):
    # notification bubble (works only when desktop session exists)
    subprocess.run(["notify-send", title, message], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def zenity_yesno(title, message):
    r = subprocess.run(
        ["zenity", "--question", "--title", title, "--text", message],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    return r.returncode == 0


def zenity_action(title, message, options):
    """
    Show a list and return selected option text.
    If user closes dialog -> returns "".
    """
    cmd = ["zenity", "--list", "--title", title, "--text", message, "--column=Action"]
    cmd += options
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    return r.stdout.strip()


def net_connectivity_nmcli():
    """
    Uses NetworkManager to check internet connectivity.
    Returns one of: 'full', 'limited', 'portal', 'none', 'unknown'
    """
    r = subprocess.run(
        ["nmcli", "-t", "-f", "CONNECTIVITY", "general"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True
    )
    status = r.stdout.strip()
    # Sometimes nmcli outputs "CONNECTIVITY:full" if -t not used correctly; handle both
    status = status.replace("CONNECTIVITY:", "").strip()
    return status if status else "unknown"


def net_is_connected():
    # consider "full" as connected (internet working)
    return net_connectivity_nmcli() == "full"


def restart_networking():
    # toggles networking via NetworkManager
    subprocess.run(["nmcli", "networking", "off"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3)
    subprocess.run(["nmcli", "networking", "on"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ----------------- MAIN LOOP -----------------
def main():
    global last_net_connected

    log("✅ Monitor bot started")

    # initialize last_net_connected on first run
    last_net_connected = net_is_connected()
    log(f"Initial network connected: {last_net_connected} (nmcli={net_connectivity_nmcli()})")

    while True:
        t = now()

        # -------- CPU TOTAL --------
        cpu = psutil.cpu_percent(interval=1)
        if cpu >= CPU_TOTAL_THRESHOLD and (t - last_alert_time["cpu"] > COOLDOWN):
            log(f"⚠ CPU high: {cpu}%")
            notify("CPU Alert", f"CPU usage is {cpu}%")

            if zenity_yesno("CPU Alert", f"CPU usage is {cpu}%.\nDo you want action options?"):
                choice = zenity_action(
                    "CPU Actions",
                    "Choose an action:",
                    ["Open System Monitor", "Ignore"]
                )
                if choice == "Open System Monitor":
                    subprocess.Popen(["gnome-system-monitor"])
            last_alert_time["cpu"] = t

        # -------- MEMORY TOTAL --------
        mem = psutil.virtual_memory().percent
        if mem >= MEM_TOTAL_THRESHOLD and (t - last_alert_time["mem"] > COOLDOWN):
            log(f"⚠ Memory high: {mem}%")
            notify("Memory Alert", f"Memory usage is {mem}%")

            if zenity_yesno("Memory Alert", f"Memory usage is {mem}%.\nDo you want action options?"):
                choice = zenity_action(
                    "Memory Actions",
                    "Choose an action:",
                    ["Open System Monitor", "Ignore"]
                )
                if choice == "Open System Monitor":
                    subprocess.Popen(["gnome-system-monitor"])
            last_alert_time["mem"] = t

        # -------- DISK USAGE --------
        disk = psutil.disk_usage("/").percent
        if disk >= DISK_THRESHOLD and (t - last_alert_time["disk"] > COOLDOWN):
            log(f"⚠ Disk high: {disk}%")
            notify("Disk Alert", f"Disk usage is {disk}%")

            if zenity_yesno("Disk Alert", f"Disk usage is {disk}%.\nOpen Disk Usage Analyzer?"):
                # baobab = GNOME Disk Usage Analyzer (install if needed)
                subprocess.Popen(["baobab"])
            last_alert_time["disk"] = t

        # -------- NETWORK (RELIABLE) --------
        connected = net_is_connected()
        nmcli_state = net_connectivity_nmcli()

        # Detect change (disconnect/reconnect)
        if connected != last_net_connected:
            log(f"Network changed: connected={connected} (nmcli={nmcli_state})")

            # DISCONNECTED event
            if not connected and (t - last_alert_time["net"] > COOLDOWN):
                notify("Network Alert", f"Internet disconnected (nmcli={nmcli_state})")

                if zenity_yesno("Network Disconnected",
                                f"Internet disconnected.\n(nmcli connectivity = {nmcli_state})\n\nDo you want action options?"):
                    choice = zenity_action(
                        "Network Actions",
                        "Choose an action:",
                        ["Restart Networking", "Open Network Settings", "Ignore"]
                    )
                    if choice == "Restart Networking":
                        restart_networking()
                        notify("Network", "Restarted networking")
                        log("✅ Restarted networking via nmcli")
                    elif choice == "Open Network Settings":
                        # GNOME settings
                        subprocess.Popen(["gnome-control-center", "network"])

                last_alert_time["net"] = t

            # RECONNECTED event (optional)
            if connected:
                notify("Network", "Internet is back online ✅")

            last_net_connected = connected

        time.sleep(2)


if __name__ == "__main__":
    main()

