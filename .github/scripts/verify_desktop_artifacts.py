"""Exercise the frozen applications using temporary data and loopback only."""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request


def main():
    root = Path(__file__).resolve().parents[2]
    output = root / "ci-validation"
    output.mkdir(exist_ok=True)
    extension = ".exe" if os.name == "nt" else ""
    agent = root / "dist" / ("ZeuzAgent" + extension)
    edit = root / "dist" / "ZeuzEdit" / ("ZeuzEdit" + extension)
    result = {"platform": sys.platform, "agent": False, "edit": False}
    environment = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_QUICK_CONTROLS_STYLE": "Basic"}
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        programs = directory / "programs"
        programs.mkdir()
        content = "O1000\nG21 G90\nM30\n"
        # Keep the fixture identical on Windows (text mode translates LF to CRLF).
        (programs / "O1000.nc").write_bytes(content.encode("ascii"))
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        configuration = directory / "config.json"
        configuration.write_text(json.dumps({
            "name": "Isolated CI fixture", "programs_dir": str(programs),
            "host": "127.0.0.1", "port": port, "api_token": "ci-fixture-token",
            "pairing_code": "123456", "discovery": False,
            "program_server_host": "", "program_server_port": 5000,
        }))
        process = subprocess.Popen([str(agent), "--config", str(configuration), "--no-tray"],
                                   cwd=directory, env=environment, start_new_session=os.name != "nt")
        try:
            deadline = time.monotonic() + 90
            while True:
                if process.poll() is not None:
                    raise RuntimeError("The packaged Agent quit before serving its API")
                try:
                    request = urllib.request.Request(f"http://127.0.0.1:{port}/v1/programs/content?path=O1000.nc",
                                                     headers={"Authorization": "Bearer ci-fixture-token"})
                    with urllib.request.urlopen(request, timeout=1) as response:
                        preview = json.load(response)
                    assert preview["content"] == content
                    result["agent"] = True
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Packaged Agent did not answer its loopback API")
                    time.sleep(.3)
        finally:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        subprocess.run([str(edit), "--smoke-test"], cwd=output, env=environment,
                       check=True, timeout=90)
        image = output / "zeuzedit-smoke.png"
        assert image.is_file() and image.stat().st_size > 1000
        result["edit"] = True
    (output / "packaged-smoke.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
