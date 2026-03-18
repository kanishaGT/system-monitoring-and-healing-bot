#!/usr/bin/env python3
import time
import psutil
import subprocess
from datetime import datetime

from llm_client import llm_recommend
from heal_rules import safe_to_kill, kill_proc

# ----------------- THRESHOLDS -----------------
CPU_TOTAL_THRESHOLD = 15   # %
MEM_TOTAL_THRESHOLD = 90   # %
DISK_THRESHOLD = 85        # %
COOLDOWN = 60             # seconds between popups per type
TOP_PROCS = 5              # how many to include

# ----------------- STATE -----------------
last_alert_time = {"cpu": 0, "mem": 0, "disk": 0, "net": 0}
last_net_connected = None

# ----------------- BASIC HELPERS -----------------
def now():
    return time.time()

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def notify(title, message):
    subprocess.run(
        ["notify-send", title, message],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

def zenity_yesno(title, message):
    r = subprocess.run(
        ["zenity", "--question", "--title", title, "--text", message],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return r.returncode == 0

def zenity_action(title, message, options):
    cmd = ["zenity", "--list", "--title", title, "--text", message, "--column=Action"]
    cmd += options
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    return r.stdout.strip()









   
    

   

# ----------------- APP/PROCESS HELPERS -----------------
def restart_app(app: str):
    subprocess.run(["pkill", "-TERM", app], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    subprocess.Popen([app], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def get_top_process_details_by_cpu(limit=5):
    procs = []
    for p in psutil.process_iter(["pid", "name", "username", "cmdline"]):
        try:
            p.cpu_percent(None)
            procs.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    time.sleep(0.15)

    rows = []
    for p in procs:
        try:
            cpu_p = p.cpu_percent(None)
            if cpu_p <= 0:
                continue
            mem_p = p.memory_percent()
            name = p.info.get("name") or p.name()
            user = p.info.get("username") or ""
            cmd = " ".join(p.info.get("cmdline") or [])[:180]
            rows.append({"pid": p.pid, "name": name, "cpu": round(cpu_p, 1), "mem": round(mem_p, 1), "user": user, "cmd": cmd})
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    rows.sort(key=lambda x: x["cpu"], reverse=True)
    return rows[:limit]

def get_top_process_details_by_mem(limit=5):
    rows = []
    for p in psutil.process_iter(["pid", "name", "username", "cmdline"]):
        try:
            mem_p = p.memory_percent()
            if mem_p <= 0:
                continue
            cpu_p = p.cpu_percent(None)
            name = p.info.get("name") or p.name()
            user = p.info.get("username") or ""
            cmd = " ".join(p.info.get("cmdline") or [])[:180]
            rows.append({"pid": p.pid, "name": name, "cpu": round(cpu_p, 1), "mem": round(mem_p, 1), "user": user, "cmd": cmd})
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    rows.sort(key=lambda x: x["mem"], reverse=True)
    return rows[:limit]

def apply_llm_action(action, top_details):
    typ = action.get("type")

    if typ == "open_monitor":
        subprocess.Popen(["gnome-system-monitor"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True, "Opened System Monitor"

    if typ == "restart_app":
        app = action.get("app", "")
        if not app:
            return False, "Missing app"
        restart_app(app)
        return True, f"Restarted {app}"

    if typ == "kill":
        pid = action.get("pid")
        if not isinstance(pid, int):
            return False, "Invalid pid"
        td = next((p for p in top_details if p.get("pid") == pid), None)
        if not td or not safe_to_kill(td):
            return False, "Refused (not safe)"
        ok, msg = kill_proc(pid)
        return ok, msg

    return True, "Ignored"

# ----------------- MAIN LOOP -----------------
def main():
    global last_net_connected

    log("✅ Monitor bot started")
    psutil.cpu_percent(None)




    while True:
        t = now()

        # ========= CPU =========
        cpu_total = psutil.cpu_percent(None)
        if cpu_total >= CPU_TOTAL_THRESHOLD and (t - last_alert_time["cpu"] > COOLDOWN):
           # notify("CPU Alert", f"CPU usage is {cpu_total:.1f}%")
            top_details = get_top_process_details_by_cpu(limit=TOP_PROCS)

            detail_lines = "\n".join([f"{p['name']} → CPU {p['cpu']}% | RAM {p['mem']}%" for p in top_details]) \
                           or "No significant CPU-heavy processes found."

            context = {
                "problem": "high_cpu",
                "cpu_total": round(cpu_total, 1),
                "mem_total": round(psutil.virtual_memory().percent, 1),
                "top_processes": top_details,
            }

            llm = llm_recommend(context)
            llm_msg = llm.get("message", "")
            llm_actions = llm.get("actions", [])

            options = [a["label"] for a in llm_actions if isinstance(a, dict) and "label" in a]
            if "Ignore" not in options:
                options.append("Ignore")

            choice = zenity_action(
                "CPU Healing Options",
                f"""
Hey 👋

Your CPU is currently at {cpu_total:.1f}%,
which means something is working pretty hard.

Here’s what I found:
{detail_lines}

My suggestion:
{llm_msg}

What would you like me to do?
""",
                options,
            )

            if choice:
                chosen = next((a for a in llm_actions if a.get("label") == choice), None)
                if chosen:
                    typ = chosen.get("type")
                    if typ in ("restart_app", "kill"):
                        if not zenity_yesno("Confirm", f"Do you want to run:\n{choice}?"):
                            chosen = {"type": "ignore", "label": "Ignore"}

                    ok, msg = apply_llm_action(chosen, top_details)
                    notify("Action result", f"{choice}: {'Success' if ok else 'Failed'} ({msg})")

            last_alert_time["cpu"] = t

        # ========= MEMORY =========
        mem_total = psutil.virtual_memory().percent
        if mem_total >= MEM_TOTAL_THRESHOLD and (t - last_alert_time["mem"] > COOLDOWN):
            notify("Memory Alert", f"Memory usage is {mem_total:.1f}%")
            top_details = get_top_process_details_by_mem(limit=TOP_PROCS)

            detail_lines = "\n".join([f"{p['name']} → RAM {p['mem']}% | CPU {p['cpu']}%" for p in top_details]) \
                           or "No significant memory-heavy processes found."

            context = {
                "problem": "high_memory",
                "cpu_total": round(psutil.cpu_percent(None), 1),
                "mem_total": round(mem_total, 1),
                "top_processes": top_details,
            }

            llm = llm_recommend(context)
            llm_msg = llm.get("message", "")
            llm_actions = llm.get("actions", [])

            options = [a["label"] for a in llm_actions if isinstance(a, dict) and "label" in a]
            if "Ignore" not in options:
                options.append("Ignore")

            choice = zenity_action(
                "Memory Healing Options",
                f"Total RAM: {mem_total:.1f}%\n\nTop processes:\n{detail_lines}\n\nLLM suggestion:\n{llm_msg}\n\nChoose an action:",
                options,
            )

            if choice:
                chosen = next((a for a in llm_actions if a.get("label") == choice), None)
                if chosen:
                    typ = chosen.get("type")
                    if typ in ("restart_app", "kill"):
                        if not zenity_yesno("Confirm", f"Do you want to run:\n{choice}?"):
                            chosen = {"type": "ignore", "label": "Ignore"}

                    ok, msg = apply_llm_action(chosen, top_details)
                    notify("Action result", f"{choice}: {'Success' if ok else 'Failed'} ({msg})")

            last_alert_time["mem"] = t

        # ========= DISK =========
        disk = psutil.disk_usage("/").percent
        if disk >= DISK_THRESHOLD and (t - last_alert_time["disk"] > COOLDOWN):
            notify("Disk Alert", f"Disk usage is {disk:.1f}%")
            if zenity_yesno("Disk Alert", f"Disk usage is {disk:.1f}%.\nOpen Disk Usage Analyzer?"):
                subprocess.Popen(["baobab"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            last_alert_time["disk"] = t

       
        time.sleep(1)

if __name__ == "__main__":
    main() 
