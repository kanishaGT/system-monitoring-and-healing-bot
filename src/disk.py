#!/usr/bin/env python3

import os
import subprocess
import time
from datetime import datetime
import psutil

# ----------------- Settings -----------------
THRESHOLD = 50  # alert % usage
HOME = os.path.expanduser("~")
TOP_FOLDERS = 5
BLOCKED_FOLDERS = ["psutil-env"]  # folders to skip
MIN_FOLDER_SIZE = 1 * 1024**2  # 1 MB minimum to show

# ----------------- Helpers -----------------
def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def run_cmd(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except Exception as e:
        return 1, "", str(e)

def notify(title, message):
    subprocess.run(["notify-send", title, message], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def zenity_yesno(title, message):
    p = subprocess.Popen(
        ["zenity", "--question", "--title", title, "--text", message]
    )

    # wait for window to exist
    window_found = False
    for _ in range(20):
        rc, out, err = run_cmd(["wmctrl", "-l"])
        if title in out:
            window_found = True
            break
        time.sleep(0.1)

    if window_found:
        target_x = 1320
        y = 730
        start_x = 1920
        x = start_x
        while x > target_x:
            subprocess.run(["wmctrl", "-r", title, "-e", f"0,{x},{y},-1,-1"])
            x -= 10
            time.sleep(0.001)
        subprocess.run(["wmctrl", "-r", title, "-e", f"0,{target_x},{y},-1,-1"])

    return p.wait() == 0

# ----------------- Disk Info -----------------
def get_disk_summary():
    disk = psutil.disk_usage('/')
    return {
        "total": disk.total / (1024**3),
        "used": disk.used / (1024**3),
        "free": disk.free / (1024**3),
        "percent": disk.percent
    }

def get_folder_size(path):
    """Fast folder size using Linux 'du'"""
    try:
        out = subprocess.check_output(["du", "-sb", path], text=True)
        size_bytes = int(out.split()[0])
        return size_bytes
    except Exception:
        return 0

def format_size(size_bytes):
    gb = size_bytes / (1024**3)
    if gb >= 0.01:
        return f"{gb:.2f} GB"
    else:
        mb = size_bytes / (1024**2)
        return f"{mb:.2f} MB"

def find_largest_folders():
    folders = []
    for name in os.listdir(HOME):
        if name in BLOCKED_FOLDERS or name.startswith("."):
            continue

        path = os.path.join(HOME, name)
        if os.path.isdir(path):
            size = get_folder_size(path)
            if size < MIN_FOLDER_SIZE:
                continue
            folders.append((size, path))

    folders.sort(reverse=True)
    return folders[:TOP_FOLDERS]

# ----------------- Actions -----------------
def show_disk_alert():
    d = get_disk_summary()
    message = (
        f"📊 Disk Usage Summary:\n"
        f"Total: {d['total']:.2f} GB\n"
        f"Used: {d['used']:.2f} GB\n"
        f"Free: {d['free']:.2f} GB\n"
    )
    if d['percent'] >= THRESHOLD:
        message += "⚠ Disk usage is high! This may slow down your system.\n\n"
    message += "Do you want to see which folders are using the most space?"
    return zenity_yesno("Disk Action", message)

def choose_folder_to_open(folders):
    options = [f"{os.path.basename(path)} ({format_size(size)})" for size, path in folders]
    cmd = ["zenity", "--list", "--title=Top Storage Consumers",
           "--text=Select a folder to open", "--column=Folder"] + options
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    title = "Top Storage Consumers"
    window_found = False
    for _ in range(20):
        rc, out, err = run_cmd(["wmctrl", "-l"])
        if title in out:
            window_found = True
            break
        time.sleep(0.05)

    if window_found:
        target_x = 1320
        target_y = 680
        start_x = 1920
        x = start_x
        while x > target_x:
            subprocess.run(["wmctrl", "-r", title, "-e", f"0,{x},{target_y},-1,-1"])
            x -= 10
            time.sleep(0.001)
        subprocess.run(["wmctrl", "-r", title, "-e", f"0,{target_x},{target_y},-1,-1"])

    out, _ = p.communicate()
    choice = out.strip()

    for size, path in folders:
        option_text = f"{os.path.basename(path)} ({format_size(size)})"
        if choice == option_text:
            try:
                if os.name == 'nt':
                    subprocess.run(["explorer", path])
                else:
                    subprocess.run(["xdg-open", path])
            except Exception as e:
                notify("❌ Error Opening Folder", f"Failed to open {os.path.basename(path)}\n{e}")

# ----------------- Main Loop -----------------
def main():
    log("Disk Guardian started ✅")
    while True:
        if show_disk_alert():
            folders = find_largest_folders()
            choose_folder_to_open(folders)
        time.sleep(60)

if __name__ == "__main__":
    main()
