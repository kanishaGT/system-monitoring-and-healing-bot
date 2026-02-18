#!/usr/bin/env python3
import psutil

PROTECTED_NAMES = {
    "systemd", "systemd-journald", "dbus-daemon", "NetworkManager",
    "gnome-shell", "Xorg", "wayland", "pipewire", "wireplumber",
    "sshd", "cron", "cupsd", "polkitd", "udisksd", "upowerd",
    "packagekitd", "unattended-upgrades", "apt", "apt-get", "dpkg",
    "ollama",
}

PROTECTED_PREFIXES = ("kworker", "ksoftirqd", "rcu", "irq", "migration", "watchdog")


def safe_to_kill(proc: dict) -> bool:
    pid = int(proc.get("pid", -1))
    name = (proc.get("name") or "").strip()
    user = (proc.get("user") or "").strip()

    if pid <= 200:
        return False
    if user == "root":
        return False
    if not name:
        return False
    if name in PROTECTED_NAMES:
        return False
    if name.startswith(PROTECTED_PREFIXES):
        return False

    lowered = name.lower()
    if any(x in lowered for x in ["systemd", "dbus", "networkmanager", "gnome-shell", "xorg", "wayland", "pipewire"]):
        return False

    return True


def kill_proc(pid: int):
    """
    terminate -> wait -> kill
    Returns (ok, msg)
    """
    try:
        p = psutil.Process(pid)
        p.terminate()
        try:
            p.wait(timeout=2.5)
            return True, "Closed"
        except psutil.TimeoutExpired:
            pass

        p.kill()
        try:
            p.wait(timeout=2.5)
            return True, "Force closed"
        except psutil.TimeoutExpired:
            return False, "Still running"
    except psutil.NoSuchProcess:
        return True, "Already closed"
    except psutil.AccessDenied:
        return False, "Permission denied"
    except Exception as e:
        return False, str(e)

