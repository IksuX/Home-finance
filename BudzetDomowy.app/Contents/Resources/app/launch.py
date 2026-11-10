"""Budżet domowy – start na Windows: uruchamia lokalny serwer (jeśli jeszcze nie działa) i otwiera przeglądarkę."""
import os, sys, threading, time, urllib.request, webbrowser

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


if up():
    webbrowser.open(URL)
    sys.exit(0)

import core
os.makedirs(core.DATA_DIR, exist_ok=True)
log = open(os.path.join(core.DATA_DIR, "program.log"), "a", encoding="utf-8", buffering=1)
sys.stdout = sys.stderr = log      # pythonw nie ma konsoli


def opener():
    for _ in range(80):
        if up():
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
