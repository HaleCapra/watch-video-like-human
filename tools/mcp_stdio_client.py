#!/usr/bin/env python3
"""A very small MCP client over stdio, standard library only - for the tests and the smoke run.

It speaks the wire format itself (one JSON-RPC message per line), so what it checks is what any
agent's MCP client will see, not what one SDK's client makes of it.

    with McpStdio([sys.executable, "server/mcp_server.py", "--root", work]) as client:
        names = client.tool_names()
        payload, is_error, raw = client.call("about", {})
"""

import json
import queue
import subprocess
import threading

PROTOCOL = "2025-06-18"


class McpError(Exception):
    pass


class McpStdio:
    def __init__(self, command, cwd=None, env=None, start_timeout=60):
        self.command = [str(c) for c in command]
        self.proc = subprocess.Popen(self.command, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE)
        self.lines = queue.Queue()
        self.errors = []
        self.next_id = 0
        threading.Thread(target=self._pump_out, daemon=True).start()
        threading.Thread(target=self._pump_err, daemon=True).start()
        self.server = self.request("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                                                  "clientInfo": {"name": "wvlh-test-client", "version": "1"}},
                                   timeout=start_timeout)
        self.notify("notifications/initialized")

    def _pump_out(self):
        for line in iter(self.proc.stdout.readline, b""):
            self.lines.put(line)
        self.lines.put(None)

    def _pump_err(self):
        for line in iter(self.proc.stderr.readline, b""):
            self.errors.append(line.decode("utf-8", "replace").rstrip())

    def stderr_text(self):
        return "\n".join(self.errors[-40:])

    def _send(self, message):
        self.proc.stdin.write((json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8"))
        self.proc.stdin.flush()

    def notify(self, method, params=None):
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self._send(message)

    def request(self, method, params=None, timeout=120):
        self.next_id += 1
        wanted = self.next_id
        message = {"jsonrpc": "2.0", "id": wanted, "method": method}
        if params is not None:
            message["params"] = params
        self._send(message)
        while True:
            try:
                line = self.lines.get(timeout=timeout)
            except queue.Empty:
                raise McpError("no answer to %s within %s s\n%s" % (method, timeout, self.stderr_text()))
            if line is None:
                raise McpError("the server ended (exit %s) while %s was waiting\n%s"
                               % (self.proc.poll(), method, self.stderr_text()))
            line = line.strip()
            if not line:
                continue
            try:
                answer = json.loads(line.decode("utf-8"))
            except ValueError:
                raise McpError("the server wrote something that is not JSON on stdout: %r" % line[:300])
            if answer.get("id") == wanted and ("result" in answer or "error" in answer):
                if "error" in answer:
                    raise McpError("%s: %s" % (method, json.dumps(answer["error"])))
                return answer["result"]
            if "method" in answer and "id" in answer:        # a request from the server: we offer nothing
                self._send({"jsonrpc": "2.0", "id": answer["id"],
                            "error": {"code": -32601, "message": "not supported by this client"}})

    def tools(self):
        return self.request("tools/list", {})["tools"]

    def tool_names(self):
        return sorted(tool["name"] for tool in self.tools())

    def call(self, name, arguments=None, timeout=900):
        """(payload, is_error, raw). payload is the structured result, or the text when there is none."""
        try:
            raw = self.request("tools/call", {"name": name, "arguments": arguments or {}}, timeout=timeout)
        except McpError as exc:                               # a protocol-level refusal (unknown tool, bad arguments)
            return {"protocol_error": str(exc)}, True, None
        text = "\n".join(part.get("text", "") for part in raw.get("content") or [] if part.get("type") == "text")
        payload = raw.get("structuredContent")
        if payload is None:
            try:
                payload = json.loads(text)
            except ValueError:
                payload = {"text": text}
        if isinstance(payload, dict) and set(payload) == {"result"} and isinstance(payload["result"], dict):
            payload = payload["result"]
        if raw.get("isError") and isinstance(payload, dict):
            payload.setdefault("text", text)
        return payload, bool(raw.get("isError")), raw

    def close(self):
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self.proc.kill()                                  # the process this object started, nothing else
            self.proc.wait(timeout=20)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False
