import subprocess
import time
import signal
import sys

# full path to venv python
venv_python = "/home/kanisha/psutil-env/bin/python"

monitor = subprocess.Popen([venv_python, "monitor_bot.py"])
net = subprocess.Popen([venv_python, "net.py"])
disk = subprocess.Popen([venv_python, "disk.py"])
def shutdown(sig, frame):
    print("Stopping bot...")
    monitor.terminate()
    net.terminate()
    disk.terminate()
    sys.exit(0)

signal.signal(signal.SIGTERM, shutdown)
signal.signal(signal.SIGINT, shutdown)

while True:
    time.sleep(3600)
