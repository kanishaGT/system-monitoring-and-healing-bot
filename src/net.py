#!/usr/bin/env python3

import subprocess
import time
from datetime import datetime

# ----------------- Helpers -----------------
def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def notify(title, message):
    subprocess.run(
        ["notify-send", title, message],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

def zenity_yesno(title, message):
    r = subprocess.run(
        ["zenity", "--question", "--title", title, "--text", message],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    return r.returncode == 0

def run_cmd(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except Exception as e:
        return 1, "", str(e)
        
#----------------Ethernet-------------------
def get_ethernet_device():
    rc, out, err = run_cmd(["nmcli", "-t", "-f", "DEVICE,TYPE", "device"])
    if rc != 0:
        return ""

    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) >= 2 and parts[1] == "ethernet":
            return parts[0]

    return ""
    
def ethernet_cable_unplugged(dev):
    rc, out, err = run_cmd(["nmcli", "-t", "-f", "DEVICE,STATE", "device"])
    if rc != 0:
        return False

    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) >= 2 and parts[0] == dev:
            state = parts[1].lower()

            # disconnected = cable unplugged
            if state == "unavailable":
                return True

    return False
    
    
def diagnose_ethernet(dev):
    if ethernet_cable_unplugged(dev):
        return "eth_unplugged"

    rc, route_out, _ = run_cmd(["ip", "route", "show", "default"])
    if rc == 0 and not route_out.strip():
        return "eth_no_route"

    r = subprocess.run(["ping", "-c", "1", "8.8.8.8"], stdout=subprocess.DEVNULL)
    if r.returncode != 0:
        return "eth_no_internet"

    return "ok"

# ----------------- Wi-Fi Device -----------------
def get_wifi_device():
    rc, out, err = run_cmd(["nmcli", "-t", "-f", "DEVICE,TYPE", "device"])
    if rc != 0:
        log(f"nmcli device failed: {err}")
        return ""
    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) >= 2 and parts[1] == "wifi":
            return parts[0]
    return ""

def rfkill_soft_blocked_wifi():
    rc, out, err = run_cmd(["rfkill", "list"])
    if rc != 0:
        log(f"rfkill list failed: {err}")
        return False
    txt = out.lower()
    return "wireless lan" in txt and "soft blocked: yes" in txt

def try_unblock_wifi_no_prompt():
    rc, out, err = run_cmd(["rfkill", "unblock", "wifi"])
    if rc == 0:
        return True
    log(f"rfkill unblock failed: {err}")
    return False

def wifi_radio_enabled():
    rc, out, err = run_cmd(["nmcli", "-t", "-f", "WIFI", "radio"])
    if rc != 0:
        log(f"nmcli radio query failed: {err}")
        return True
    return out.strip().lower() != "disabled"

def enable_wifi_radio():
    run_cmd(["nmcli", "radio", "wifi", "on"])

def wifi_state_num_and_reason(dev):
    rc, out, err = run_cmd(["nmcli", "-g", "GENERAL.STATE,GENERAL.REASON", "device", "show", dev])
    if rc != 0:
        return None, "", None, ""
    lines = [l.strip() for l in out.splitlines() if l.strip()]

    def parse_line(s):
        try:
            num = int(s.split()[0])
        except:
            num = None
        txt = ""
        if "(" in s and ")" in s:
            txt = s[s.find("(")+1 : s.rfind(")")]
        return num, txt

    st_num, st_txt = parse_line(lines[0]) if len(lines) >= 1 else (None, "")
    rs_num, rs_txt = parse_line(lines[1]) if len(lines) >= 2 else (None, "")
    return st_num, st_txt, rs_num, rs_txt

def wifi_device_connected(dev):
    st_num, _, _, _ = wifi_state_num_and_reason(dev)
    return st_num == 100

# ----------------- Airplane Mode Check -----------------
def is_airplane_mode_on():
    rc, out, err = run_cmd(["rfkill", "list", "all"])
    if rc != 0:
        log(f"rfkill list failed: {err}")
        return False
    txt = out.lower()
    # If any device is not soft blocked → airplane mode OFF
    if "soft blocked: no" in txt:
        return False
    return True

#interface
def interface_down(dev):
    rc, out, err = run_cmd(["nmcli", "-t", "-f", "DEVICE,STATE", "device"])
    if rc != 0:
        return False

    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) >= 2 and parts[0] == dev:
            state = parts[1].lower()
            # Truly down only if unmanaged or unavailable
            if state in ["unavailable", "unmanaged"]:
                return True

    return False
    
# ----------------- Saved Profiles & Auto-Connect -----------------
def list_saved_wifi_connections():
    rc, out, err = run_cmd(["nmcli", "-t", "-f", "NAME,TYPE", "con", "show"])
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

def get_profile_ssid(profile_name):
    rc, out, err = run_cmd(["nmcli", "-g", "802-11-wireless.ssid", "connection", "show", profile_name])
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

def list_available_wifi_networks(dev):
    run_cmd(["nmcli", "device", "wifi", "rescan", "ifname", dev])
    rc, out, err = run_cmd(["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list", "ifname", dev])
    if rc != 0:
        log(f"nmcli wifi list failed: {err}")
        return []
    nets = []
    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) < 3: continue
        ssid = parts[0].strip()
        if not ssid: continue
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

def connect_wifi_profile(profile_name, dev):
    rc, out, err = run_cmd(["nmcli", "connection", "up", profile_name, "ifname", dev], timeout=40)
    ok = (rc == 0)
    msg = (out or err or "unknown").strip()
    lower = msg.lower()
    if (not ok) and ("password" in lower or "secrets" in lower or "authentication" in lower):
        return False, "MISSING_SECRETS"
    return ok, msg

def auto_connect_best_saved_visible(dev, max_tries=10):
    visible = list_available_wifi_networks(dev)
    saved_items = get_saved_wifi_profiles_with_ssid()

    if not visible:
        return False, "No visible Wi-Fi networks found."

    if not saved_items:
        return False, "No saved Wi-Fi profiles found."

    # Map SSID -> profiles
    ssid_to_profiles = {}
    for it in saved_items:
        ssid_to_profiles.setdefault(it["ssid"], []).append(it["profile"])

    # Only networks that are visible + saved
    candidates = [n for n in visible if n["ssid"] in ssid_to_profiles]

    if not candidates:
        return False, "No visible networks match saved Wi-Fi profiles."

    # 🔥 Sort by strongest signal first
    candidates.sort(key=lambda x: x.get("signal", 0), reverse=True)

    # 🔥 Disconnect ethernet first (important!)
    subprocess.call(["nmcli", "device", "disconnect", "enp1s0"])

    tried = 0
    errors = []

    for n in candidates:
        ssid = n["ssid"]

        for profile in ssid_to_profiles.get(ssid, []):
            ok, msg = connect_wifi_profile(profile, dev)
            tried += 1

            if ok:
                return True, f"Connected to '{ssid}' using profile '{profile}'"

            errors.append(f"{profile}: {msg}")

            if msg == "MISSING_SECRETS":
                return False, f"Wi-Fi password not stored for '{profile}'"

            if tried >= max_tries:
                return False, "Reached max connection attempts.\n" + "\n".join(errors)

    return False, "All saved profiles failed:\n" + "\n".join(errors)
# ----------------- Diagnose Root Cause -----------------
def diagnose_network(dev):
    if is_airplane_mode_on():  # <-- new check
        return "rfkill"
    if not wifi_radio_enabled():
        return "radio_disabled"
    st_num, st_txt, rs_num, rs_txt = wifi_state_num_and_reason(dev)
    
    if interface_down(dev):   # <-- 100 = connected
        return "interface_down"
    rc, route_out, _ = run_cmd(["ip", "route", "show", "default"])
    if rc == 0 and not route_out.strip(): 
        return "no_route"
    r = subprocess.run(["ping", "-c", "1", "8.8.8.8"], stdout=subprocess.DEVNULL)
    if r.returncode != 0: 
        return "no_internet"
    return "ok"

# ----------------- Root-Cause → Action Mapping -----------------
def get_action_for_cause(cause, dev):
    actions_map = {
        "rfkill": {"msg": "Wi-Fi is blocked (airplane mode). Unblock?", "func": try_unblock_wifi_no_prompt},
        "radio_disabled": {"msg": "Wi-Fi radio is disabled. Enable Wi-Fi?", "func": enable_wifi_radio},
        "interface_down": {"msg": "Wi-Fi interface is down. Bring it up?", "func": lambda: run_cmd(["nmcli", "device", "connect", dev])[0:2]},
        "no_route": {"msg": "No gateway/default route. Try best saved Wi-Fi?", "func": lambda: auto_connect_best_saved_visible(dev)},
        "no_internet": {"msg": "Cannot reach internet. Try best saved Wi-Fi?", "func": lambda: auto_connect_best_saved_visible(dev)},
        "eth_unplugged": {"msg": "Ethernet cable is unplugged. Please check cable connection.","func": lambda: (False, "Cable unplugged")},
		"eth_no_route": {"msg": "Ethernet connected but no gateway. Check router?","func": lambda: (False, "No default route")},
		"eth_no_internet": {"msg": "Ethernet has no internet access. Check ISP?","func": lambda: auto_connect_best_saved_visible(dev)},
    }
    return actions_map.get(cause)

# ----------------- Main Loop -----------------
def main():
    dev = get_wifi_device()
    eth_dev = get_ethernet_device()
    if not dev:
        notify("Network", "No Wi-Fi device found ❌")
        return
    log(f"Wi-Fi device detected: {dev}")

    last_cause = None

    while True:
        # Log Airplane Mode separately
        if is_airplane_mode_on():
            log("Airplane Mode is ON ✈️")
        else:
            log("Airplane Mode is OFF")

        cause = "ok"

		# Prefer Ethernet first
        if eth_dev:
            cause = diagnose_ethernet(eth_dev)

		# If Ethernet OK or not present, check WiFi
        if cause == "ok" and dev:
            cause = diagnose_network(dev)

        if cause == "ok":
            if last_cause != "ok":
                notify("Network", "Internet is back ✅")
                log("Network OK")
            last_cause = "ok"
        else:
            if cause != last_cause:
                action = get_action_for_cause(cause, dev)
                if action:
                    if zenity_yesno("Network Action", action["msg"]):
                        result = action["func"]()
                        if isinstance(result, tuple)and len(result) == 2:
                            ok, msg = result
                            if ok: notify("Network", f"Action successful ✅: {msg}")
                            else: notify("Network", f"Action failed ❌: {msg}")
                        elif isinstance(result, bool):
                            if result:
                                notify("Network", "Action successful ✅")
                            else:
                                notify("Network", "Action failed ❌")
                        else:
                            notify("Network", "Action executed ✅")
                    else:
                        log("User declined action")
            last_cause = cause

        time.sleep(5)  # check every 5 seconds

if __name__ == "__main__":
    main()
