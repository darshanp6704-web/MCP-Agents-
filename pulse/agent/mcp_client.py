import os
import json
import queue
import logging
import threading
import subprocess
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

class McpClient:
    """
    Spawns an MCP server as a subprocess and acts as an MCP client host.
    Communicates using JSON-RPC 2.0 over standard inputs/outputs (stdio).
    Exposes a call_tool interface for simple orchestrator integration.
    """
    def __init__(self, command: str, args: List[str], env_file: Optional[str] = None):
        self.command = command
        self.args = args
        self.env_file = env_file
        self.process: Optional[subprocess.Popen] = None
        self.response_queue = queue.Queue()
        self.req_id = 1
        self.running = False

    def start(self) -> None:
        # 1. Load environment variables from the configured env file
        env = os.environ.copy()
        if self.env_file:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            full_env_path = os.path.join(base_dir, self.env_file) if not os.path.isabs(self.env_file) else self.env_file
            
            if os.path.exists(full_env_path):
                logger.info(f"Loading environment settings from {full_env_path}")
                with open(full_env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            # Remove potential surrounding quotes from values
                            val = v.strip().strip('"').strip("'")
                            env[k.strip()] = val
            else:
                logger.warning(f"Configured env file not found at {full_env_path}. Defaulting to process environment.")

        # 2. Spawn MCP subprocess
        logger.info(f"Starting MCP Server subprocess: {self.command} {' '.join(self.args)}")
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        
        self.process = subprocess.Popen(
            [self.command] + self.args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=base_dir,
            text=True,
            bufsize=1
        )
        self.running = True

        # 3. Start communication background reader threads
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

        # 4. Perform standard MCP handshake (initialize)
        self._handshake()

    def _read_stdout(self) -> None:
        """Reads JSON-RPC responses from server stdout."""
        while self.running and self.process and self.process.stdout:
            line = self.process.stdout.readline()
            if not line:
                break
            line = line.strip()
            if line:
                try:
                    msg = json.loads(line)
                    self.response_queue.put(msg)
                except Exception:
                    # Ignore lines that are not valid JSON-RPC payloads (e.g. server debugging noise printed to stdout)
                    logger.debug(f"Non-JSON message on stdout: {line}")

    def _read_stderr(self) -> None:
        """Reads error output and logs from server stderr."""
        while self.running and self.process and self.process.stderr:
            line = self.process.stderr.readline()
            if not line:
                break
            line = line.strip()
            if line:
                logger.info(f"[MCP Server log] {line}")

    def _send_request(self, method: str, params: Dict[str, Any], has_id: bool = True) -> int:
        """Helper to format and write a JSON-RPC message to subprocess stdin."""
        if not self.process or not self.process.stdin:
            raise RuntimeError("Subprocess is not running or stdin is closed.")

        req_id = self.req_id if has_id else None
        if has_id:
            self.req_id += 1

        payload: Dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params
        }
        if req_id is not None:
            payload["id"] = req_id

        self.process.stdin.write(json.dumps(payload) + "\n")
        self.process.stdin.flush()
        return req_id if req_id is not None else -1

    def _handshake(self) -> None:
        """Executes the standard Model Context Protocol client-server handshake."""
        # A. Send initialize request
        init_id = self._send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {
                "name": "pulse-agent-client",
                "version": "1.0.0"
            }
        })

        # B. Wait for initialize response
        try:
            while True:
                resp = self.response_queue.get(timeout=10)
                if resp.get("id") == init_id:
                    logger.info("MCP initialize handshake completed successfully.")
                    break
        except queue.Empty:
            raise TimeoutError("Handshake timeout waiting for MCP initialize response.")

        # C. Send initialized notification (no ID)
        self._send_request("notifications/initialized", {}, has_id=False)

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Calls a tool exposed by the MCP server and returns the parsed result."""
        req_id = self._send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments
        })

        try:
            while True:
                # 30-second timeout for long operations like Docs appending or drafts creation
                resp = self.response_queue.get(timeout=30)
                if resp.get("id") == req_id:
                    if "error" in resp:
                        err_msg = resp["error"].get("message", "Unknown MCP Server Error")
                        raise RuntimeError(f"MCP Tool call '{tool_name}' failed: {err_msg}")
                        
                    result = resp.get("result", {})
                    # Standard tool outputs wrap results in an array under "content"
                    content_list = result.get("content", [])
                    if content_list and content_list[0].get("type") == "text":
                        text_val = content_list[0].get("text", "")
                        try:
                            # Our servers return tools responses serialized as JSON strings in the text content
                            return json.loads(text_val)
                        except json.JSONDecodeError:
                            return {"raw_text": text_val}
                            
                    return result
        except queue.Empty:
            raise TimeoutError(f"Timeout waiting for MCP response to tool '{tool_name}'")

    def stop(self) -> None:
        """Gracefully terminates the MCP subprocess."""
        self.running = False
        if self.process:
            logger.info("Terminating MCP Server subprocess...")
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning("MCP Subprocess did not exit gracefully. Killing process.")
                self.process.kill()
            self.process = None
