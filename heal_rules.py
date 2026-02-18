import os
import signal

# Never kill these
PROTECTED_NAMES = {
    "systemd", "systemd-journald", "dbus-daemon", "NetworkManager",
    "gnome-shell", "Xorg", "pipewire", "wireplumber",
    "sshd", "cron", "cupsd", "polkitd", "udisksd", "upowerd",
}

def safe_to_kill(proc: dict) -> bool:
    """
    Decide if a process is safe to kill.
    """
    pid = proc.get("pid", -1)
    name = (proc.get("name") or "").lower()
    user = (proc.get("user") or "")

    if pid <= 300:
        return False
    if user == "root":
        return False
    if name in (p.lower() for p in PROTECTED_NAMES):
        return False

    return True


def kill_proc(pid: int):
    """
    Kill process safely.
    """
    try:
        os.kill(pid, signal.SIGTERM)
        return True, "SIGTERM sent"
    except Exception as e:
        return False, str(e)

