"""Budżet domowy – start na Windows: uruchamia lokalny serwer (jeśli jeszcze nie działa) i otwiera przeglądarkę."""
import json, os, sys, threading, time, urllib.request, webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
URL = "http://127.0.0.1:8765/"
_direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))      # bez systemowego proxy


def up():
    try:
        _direct.open(URL + "api/state", timeout=1).close()
        return True
    except Exception:
        return False


def alert(msg):
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, msg, "Budżet domowy", 0x10)
    except Exception:
        pass


import re


def own_version():
    with open(os.path.join(HERE, "core.py"), encoding="utf-8") as f:
        return re.search(r'^VERSION = "([^"]+)"', f.read(), re.M).group(1)


def running_version():
    try:
        return json.loads(_direct.open(URL + "api/state", timeout=2).read()).get("version")
    except Exception:
        return None


RESTART = os.environ.get("BUDZET_RESTART")      # nowa wersja uruchomiona przez poprzednią – przeglądarka sama się odświeży
if not RESTART and up():
    if running_version() == own_version():
        webbrowser.open(URL)
        sys.exit(0)
    try:      # w tle działa inna wersja – zamykamy ją i startujemy tę
        _direct.open(urllib.request.Request(URL + "api/quit", data=b"{}", method="POST",
                                            headers={"Content-Type": "application/json", "Origin": URL.rstrip("/")}), timeout=3).close()
    except Exception:
        pass
    for _ in range(40):
        if not up():
            break
        time.sleep(0.25)

import core
os.makedirs(core.DATA_DIR, exist_ok=True)
log = open(os.path.join(core.DATA_DIR, "program.log"), "a", encoding="utf-8", buffering=1)
sys.stdout = sys.stderr = log      # pythonw nie ma konsoli


def opener():
    for _ in range(80):
        if up():
            if not RESTART:
                webbrowser.open(URL)
            return
        time.sleep(0.25)
    alert("Program nie odpowiada. Szczegóły są w pliku program.log w folderze " + core.DATA_DIR)


threading.Thread(target=opener, daemon=True).start()
try:
    import server
    server.main()
except OSError as e:
    alert(f"Nie udało się uruchomić programu ({e}). Możliwe, że port 8765 zajmuje inny program.\n\nSzczegóły: {core.DATA_DIR}\\program.log")
    raise
