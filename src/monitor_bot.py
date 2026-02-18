#!/usr/bin/env python3
import time
import psutil
import subprocess
from datetime import datetime

from llm_client import llm_recommend
from heal_rules import safe_to_kill, kill_proc

# ----------------- THRESHOLDS -----------------
CPU_TOTAL_THRESHOLD = 95   # %
MEM_TOTAL_THRESHOLD = 90   # %
DISK_THRESHOLD = 85        # %
COOLDOWN = 30              # seconds between popups per type
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

# ----------------- NETWORK HELPERS -----------------
def run_cmd(cmd, timeout=20):
    try:
        r = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
        return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except Exception as e:
        return 1, "", str(e)

def net_connectivity_nmcli():
    rc, out, err = run_cmd(["nmcli", "-t", "-f", "CONNECTIVITY", "general"], timeout=10)
    if rc != 0:
        log(f"nmcli connectivity error: {err}")
        return "unknown"
    status = out.replace("CONNECTIVITY:", "").strip()
    return status if status else "unknown"

def internet_http_check(timeout=4) -> bool:
    """
    HTTP 204 check (more reliable than ping on some networks).
    Needs: curl installed (sudo apt install curl).
    """
    r = subprocess.run(
        ["curl", "-I", "--max-time", str(timeout), "http://connectivitycheck.gstatic.com/generate_204"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return r.returncode == 0

def check_internet_live() -> bool:
    nm = net_connectivity_nmcli()
    if nm == "full":
        return True
    return internet_http_check(timeout=4)

def get_wifi_device():
    rc, out, err = run_cmd(["nmcli", "-t", "-f", "DEVICE,TYPE", "device"], timeout=10)
    if rc != 0:
        log(f"nmcli device failed: {err}")
        return ""
    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) >= 2 and parts[1] == "wifi":
            return parts[0]  # e.g. wlo1
    return ""

def wifi_state_num_and_reason(dev: str):
    """
    Returns (state_num, state_text, reason_num, reason_text)
    Example:
      100, "connected", 0, "No reason given"
    """
    rc, out, err = run_cmd(["nmcli", "-g", "GENERAL.STATE,GENERAL.REASON", "device", "show", dev], timeout=10)
    if rc != 0:
        log(f"nmcli device show failed for {dev}: {err}")
        return None, "", None, ""
    lines = [l.strip() for l in out.splitlines() if l.strip()]

    def parse_line(s):
        # e.g. "100 (connected)"
        try:
            num = int(s.split()[0])
        except Exception:
            num = None
        txt = ""
        if "(" in s and ")" in s:
            txt = s[s.find("(") + 1 : s.rfind(")")]
        return num, txt

    st_num, st_txt = parse_line(lines[0]) if len(lines) >= 1 else (None, "")
    rs_num, rs_txt = parse_line(lines[1]) if len(lines) >= 2 else (None, "")
    return st_num, st_txt, rs_num, rs_txt

def rfkill_soft_blocked_wifi() -> bool:
    rc, out, err = run_cmd(["rfkill", "list"], timeout=10)
    if rc != 0:
        log(f"rfkill list failed: {err}")
        return False
    txt = out.lower()
    return "wireless lan" in txt and "soft blocked: yes" in txt

def try_unblock_wifi_no_prompt() -> bool:
    rc, out, err = run_cmd(["rfkill", "unblock", "wifi"], timeout=10)
    if rc == 0:
        return True
    log(f"rfkill unblock failed rc={rc}: {err or out}")
    return False

def wifi_radio_enabled() -> bool:
    rc, out, err = run_cmd(["nmcli", "-t", "-f", "WIFI", "radio"], timeout=10)
    if rc != 0:
        log(f"nmcli radio query failed: {err}")
        return True
    return out.strip().lower() != "disabled"

def enable_wifi_radio():
    run_cmd(["nmcli", "radio", "wifi", "on"], timeout=10)

def wait_wifi_usable(dev: str, timeout=45, step=1.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        st_num, st_txt, rs_num, rs_txt = wifi_state_num_and_reason(dev)
        log(f"Wi-Fi {dev} state: {st_num} ({st_txt}) reason: {rs_num} ({rs_txt})")

        if st_num is None:
            time.sleep(step)
            continue

        if st_num >= 30:
            return True

        if st_num == 20:
            if rfkill_soft_blocked_wifi():
                ok = try_unblock_wifi_no_prompt()
                if not ok:
                    notify("Network", "Wi-Fi is blocked (rfkill). Run: sudo rfkill unblock wifi")
                    return False
        time.sleep(step)

    return False

def wait_for_internet(timeout=25, step=2):
    end = time.time() + timeout
    while time.time() < end:
        if check_internet_live():
            return True
        time.sleep(step)
    return False

def get_device_connection(dev):
    rc, out, err = run_cmd(["nmcli", "-g", "GENERAL.CONNECTION", "device", "show", dev], timeout=10)
    if rc != 0:
        log(f"nmcli device show failed for {dev}: {err}")
        return ""
    name = out.strip()
    if not name or name == "--":
        return ""
    return name

def list_saved_wifi_connections():
    rc, out, err = run_cmd(["nmcli", "-t", "-f", "NAME,TYPE", "con", "show"], timeout=10)
    if rc != 0:
        log(f"nmcli con show failed: {err}")
        return []
    names = []
    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) >= 2 and parts[1] == "802-11-wireless":
            names.append(parts[0])
    seen = set()
    uniq = []
    for n in names:
        if n not in seen:
            uniq.append(n)
            seen.add(n)
    return uniq

def get_profile_ssid(profile_name: str) -> str:
    rc, out, err = run_cmd(["nmcli", "-g", "802-11-wireless.ssid", "connection", "show", profile_name], timeout=10)
    if rc != 0:
        return ""
    return out.strip()

def get_saved_wifi_profiles_with_ssid():
    profiles = list_saved_wifi_connections()
    items = []
    for p in profiles:
        ssid = get_profile_ssid(p)
        if ssid:
            items.append({"profile": p, "ssid": ssid})
    return items

def connect_wifi_profile(profile_name, dev):
    rc, out, err = run_cmd(["nmcli", "connection", "up", profile_name, "ifname", dev], timeout=40)
    ok = (rc == 0)
    msg = (out or err or "unknown").strip()
    log(f"nmcli con up '{profile_name}' ifname {dev}: rc={rc} msg={msg}")

    lower = msg.lower()
    if (not ok) and (
        "secrets were required" in lower
        or "password" in lower
        or "no secrets" in lower
        or "authentication" in lower
    ):
        return False, "MISSING_SECRETS"

    return ok, msg

def list_available_wifi_networks(dev):
    run_cmd(["nmcli", "device", "wifi", "rescan", "ifname", dev], timeout=15)
    rc, out, err = run_cmd(
        ["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list", "ifname", dev],
        timeout=15
    )
    if rc != 0:
        log(f"nmcli wifi list failed: {err}")
        return []

    nets = []
    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) < 3:
            continue
        ssid = parts[0].strip()
        if not ssid:
            continue
        try:
            signal = int(parts[1].strip() or "0")
        except ValueError:
            signal = 0
        security = parts[2].strip()
        nets.append({"ssid": ssid, "signal": signal, "security": security})

    nets.sort(key=lambda x: x["signal"], reverse=True)

    seen = set()
    uniq = []
    for n in nets:
        if n["ssid"] not in seen:
            uniq.append(n)
            seen.add(n["ssid"])
    return uniq

def auto_connect_best_saved_visible(dev, max_tries=10):
    visible = list_available_wifi_networks(dev)
    saved_items = get_saved_wifi_profiles_with_ssid()

    if not visible:
        return False, "", "No visible Wi-Fi networks found."
    if not saved_items:
        return False, "", "No saved Wi-Fi profiles found."

    ssid_to_profiles = {}
    for it in saved_items:
        ssid_to_profiles.setdefault(it["ssid"], []).append(it["profile"])

    candidates = [n for n in visible if n["ssid"] in ssid_to_profiles]
    if not candidates:
        return False, "", "No visible networks match any saved Wi-Fi profile SSID."

    tried = 0
    for n in candidates:
        ssid = n["ssid"]
        for profile in ssid_to_profiles.get(ssid, []):
            ok, msg = connect_wifi_profile(profile, dev)
            tried += 1
            if ok:
                return True, ssid, f"Connected using saved profile '{profile}'"

            if msg == "MISSING_SECRETS":
                return False, "", (
                    f"Wi-Fi password not stored for '{profile}'. "
                    "Connect once via Wi-Fi settings and enable 'Connect automatically' (and 'Available to other users' if shown)."
                )

            log(f"Auto-connect failed ssid='{ssid}' profile='{profile}': {msg}")
            if tried >= max_tries:
                return False, "", "Tried multiple saved profiles, none connected."

    return False, "", "Tried saved profiles for visible networks, none connected."

def explain_wifi_unavailable(dev: str):
    rc, devst, _ = run_cmd(["nmcli", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"], timeout=10)
    rc, show, _  = run_cmd(["nmcli", "-f", "GENERAL.NM-MANAGED,GENERAL.STATE,GENERAL.REASON,GENERAL.DRIVER,GENERAL.FIRMWARE-MISSING", "device", "show", dev], timeout=10)
    rc, rf, _    = run_cmd(["rfkill", "list"], timeout=10)

    log("=== WIFI UNAVAILABLE DIAG ===")
    log("nmcli device status:\n" + devst)
    log(f"nmcli device show {dev}:\n" + show)
    log("rfkill list:\n" + rf)

# ----------------- ONLY MODIFIED PART START -----------------
def wifi_device_connected(dev: str) -> bool:
    """
    True if NM reports the Wi-Fi device state is 'connected' (100).
    """
    st_num, _, _, _ = wifi_state_num_and_reason(dev)
    return st_num == 100

def restart_networking():
    """
    Deep-ish restart + auto connect:
      - handles rfkill soft-block (without prompting)
      - avoids asking user which Wi-Fi
      - only uses saved profiles
      - if secrets missing, tells user to save password once

    FIX: don't show "Auto-connect failed" if the internet is actually back online
         (NM may have auto-connected a moment later).
    """
    log("🔄 Performing deep network reset...")

    dev = get_wifi_device()
    if not dev:
        notify("Network", "No Wi-Fi device found ❌")
        return

    prev_profile = get_device_connection(dev)
    log(f"Wi-Fi device={dev}, prev_profile={prev_profile or '(none)'}")
    notify("Network", f"Restarting Wi-Fi ({dev})…")

    # A) If rfkill soft-blocked, try to unblock (no prompt)
    if rfkill_soft_blocked_wifi():
        ok = try_unblock_wifi_no_prompt()
        if not ok:
            notify("Network", "Wi-Fi blocked. Run: sudo rfkill unblock wifi")
            return

    # B) Ensure wifi radio enabled
    enable_wifi_radio()

    # C) Toggle networking (NM)
    run_cmd(["nmcli", "networking", "off"], timeout=10)
    time.sleep(2)
    run_cmd(["nmcli", "networking", "on"], timeout=10)
    enable_wifi_radio()

    # D) Nudge interface up + device connect (helps after toggles)
    run_cmd(["ip", "link", "set", dev, "up"], timeout=10)
    run_cmd(["nmcli", "device", "connect", dev], timeout=20)

    # E) Wait until device usable (>= disconnected)
    if not wait_wifi_usable(dev, timeout=45, step=1.0):
        explain_wifi_unavailable(dev)
        notify("Network", f"{dev} still unavailable ❌")
        return

    # F) Disconnect/reconnect nudge
    run_cmd(["nmcli", "device", "disconnect", dev], timeout=10)
    time.sleep(2)

    # G) Try previous profile first (fastest)
    if prev_profile:
        notify("Network", f"Reconnecting: {prev_profile}")
        ok, msg = connect_wifi_profile(prev_profile, dev)
        if ok:
            notify("Network", f"Reconnected ✅ ({prev_profile})")
            return
        if msg == "MISSING_SECRETS":
            notify("Network", "Wi-Fi password not saved. Connect once in Wi-Fi Settings to store it.")
            return
        log(f"Prev profile reconnect failed '{prev_profile}': {msg}")

    # H) Auto connect best saved visible
    notify("Network", "Auto-connecting best saved Wi-Fi…")
    ok, ssid, msg = auto_connect_best_saved_visible(dev, max_tries=12)

    if ok:
        notify("Network", f"Connected ✅ ({ssid})")
        log(msg)
        return

    # -------- FIX STARTS HERE --------
    # If our auto-connect attempt "failed", NetworkManager might still connect
    # a moment later (or another interface is already online).
    # So we verify truth before showing a scary failure message.
    log(f"Auto-connect attempt returned failure: {msg}")

    # Give NM a short chance to finish background auto-connect.
    time.sleep(3)

    # Final truth checks
    internet_ok = wait_for_internet(timeout=10, step=2)  # uses your live probes
    wifi_ok = wifi_device_connected(dev)

    if internet_ok:
        # Internet is already back, so don't say "failed".
        # If Wi-Fi isn't connected but internet is OK, it might be ethernet/hotspot.
        if wifi_ok:
            notify("Network", "Connected ✅ (verified)")
            log("Post-check: Wi-Fi connected and internet OK.")
        else:
            notify("Network", "Internet online ✅ (verified)")
            log("Post-check: Internet OK but Wi-Fi device not reported as connected (maybe ethernet/other).")
        return

    # Still offline after verification → real failure
    notify("Network", f"Auto-connect failed ❌: {msg}")
    log(f"Verified still offline. Auto-connect failed: {msg}")
    # -------- FIX ENDS HERE --------
# ----------------- ONLY MODIFIED PART END -----------------

def diagnose_network():
    nm = net_connectivity_nmcli()
    dev = get_wifi_device()
    st_num, st_txt, rs_num, rs_txt = (None, "", None, "")
    if dev:
        st_num, st_txt, rs_num, rs_txt = wifi_state_num_and_reason(dev)

    if nm == "portal":
        return "Captive portal detected (login required)."
    if nm == "limited":
        rc, route_out, _ = run_cmd(["ip", "route", "show", "default"], timeout=10)
        if rc == 0 and not route_out.strip():
            return "Limited: no default route (gateway) configured."
        return "Limited connectivity (Wi-Fi connected but internet not confirmed)."

    if rfkill_soft_blocked_wifi():
        return "Wi-Fi is soft blocked (rfkill / airplane mode)."
    if not wifi_radio_enabled():
        return "Wi-Fi radio is disabled."

    if dev and st_num == 20:
        return f"Wi-Fi device '{dev}' unavailable (rfkill/driver/firmware/NM state)."

    rc, route_out, _ = run_cmd(["ip", "route", "show", "default"], timeout=10)
    if rc == 0 and not route_out.strip():
        return "No default route (gateway) configured."

    if nm in ("none", "unknown") and not internet_http_check(timeout=4):
        return "Cannot reach internet (router/ISP/captive portal) or blocked by network policy."

    if nm == "none":
        return "No connectivity (disconnected)."

    return "Intermittent/unknown network issue."

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

    last_net_connected = check_internet_live()
    log(f"Initial internet: connected={last_net_connected} (nmcli={net_connectivity_nmcli()})")

    while True:
        t = now()

        # ========= CPU =========
        cpu_total = psutil.cpu_percent(None)
        if cpu_total >= CPU_TOTAL_THRESHOLD and (t - last_alert_time["cpu"] > COOLDOWN):
            notify("CPU Alert", f"CPU usage is {cpu_total:.1f}%")
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
                f"Total CPU: {cpu_total:.1f}%\n\nTop processes:\n{detail_lines}\n\nLLM suggestion:\n{llm_msg}\n\nChoose an action:",
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

        # ========= NETWORK =========
        connected = check_internet_live()

        if connected != last_net_connected:
            if (not connected) and (t - last_alert_time["net"] > COOLDOWN):
                root_cause = diagnose_network()
                log(f"Network Failure: {root_cause}")
                notify("Network Alert", f"Offline: {root_cause}")

                msg = f"Internet is DOWN.\n\nRoot Cause: {root_cause}\n\nWould you like to attempt a heal?"
                if zenity_yesno("Network Disconnected", msg):
                    choice = zenity_action(
                        "Healing Options",
                        "Select a repair strategy:",
                        ["Restart Networking (Basic)", "Flush DNS Cache", "Open Network Settings", "Ignore"],
                    )

                    if choice == "Restart Networking (Basic)":
                        notify("Network", "Restarting networking...")
                        restart_networking()

                    elif choice == "Flush DNS Cache":
                        notify("Network", "Flushing DNS cache...")
                        subprocess.run(["resolvectl", "flush-caches"], check=False)

                    elif choice == "Open Network Settings":
                        subprocess.Popen(
                            ["gnome-control-center", "network"],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )

                    if wait_for_internet(timeout=35, step=2):
                        notify("Network", "Internet is back online ✅")
                        log("Network restored after healing.")
                    else:
                        notify("Network", "Still offline ❌")
                        log("Network still down after healing.")

                last_alert_time["net"] = t

            elif connected:
                notify("Network", "Internet is back online ✅")
                log("Network restored.")

            last_net_connected = check_internet_live()

        time.sleep(1)

if __name__ == "__main__":
    main()

