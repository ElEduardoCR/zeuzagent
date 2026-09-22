"""Present the selected Pi library through Agent's existing mobile contract."""
import base64
from pathlib import Path
from urllib.parse import urlencode

from .dnc_proxy import DNCEndpoint, ZeuzDNCProxy
from .library import LibraryError, ChangeTracker


class RemoteProgramLibrary:
    def __init__(self, host, port):
        self.endpoint = DNCEndpoint(host, port)
        self.proxy = ZeuzDNCProxy()
        self.tracker = ChangeTracker()

    def request(self, method, path, body=None):
        status, payload = self.proxy.forward(method, path, body, self.endpoint)
        if status >= 300:
            error = LibraryError(payload.get("error", "No se pudo contactar el servidor"))
            error.status = status
            raise error
        return payload

    def list(self, path=""):
        return self.request("GET", "/api/workshop/programs?" + urlencode({"path": path}))

    def read(self, path):
        return self.request("GET", "/api/workshop/content?" + urlencode({"path": path}))

    def read_bytes(self, path):
        value = self.request("GET", "/api/workshop/bytes?" + urlencode({"path": path}))
        return Path(path).name, base64.b64decode(value["data"], validate=True)

    def write(self, path, content, expected_modified=None):
        return self.request("PUT", "/api/workshop/content", {"path": path, "content": content, "expected_modified": expected_modified})

    def create(self, directory, name, kind="file"):
        return self.request("POST", "/api/workshop/programs", {"directory": directory, "name": name, "kind": kind})

    def delete(self, path):
        return self.request("DELETE", "/api/workshop/content?" + urlencode({"path": path}))

    def search(self, query):
        folders, results, visited = [""], [], set()
        while folders and len(visited) < 1000 and len(results) < 300:
            folder = folders.pop()
            if folder in visited:
                continue
            visited.add(folder)
            for entry in self.list(folder)["entries"]:
                if query.casefold() in entry["name"].casefold():
                    results.append(entry)
                if entry["kind"] == "directory":
                    folders.append(entry["path"])
        return results[:300]
