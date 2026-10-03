"""Minimal ACP client for the trial: spawn an agent over stdio, send one prompt,
auto-approve permission requests (logging each), record every session update,
and print a JSON summary. Usage: trial_client.py LABEL WORKDIR PROMPT -- CMD..."""
import asyncio, json, sys, time
from typing import Any
from acp import PROTOCOL_VERSION, Client, RequestError, connect_to_agent
from acp.schema import (AgentMessageChunk, AllowedOutcome, ClientCapabilities,
    DeniedOutcome, Implementation, RequestPermissionResponse, TextContentBlock)

class TrialClient(Client):
    def __init__(self, log):
        self.log, self.text, self.perms, self.kinds, self.usage = log, [], [], {}, None

    def _rec(self, kind, obj):
        self.log.write(json.dumps({"t": round(time.time(), 3), "kind": kind,
            "data": obj.model_dump(mode="json", by_alias=True, exclude_none=True)
            if hasattr(obj, "model_dump") else obj}) + "\n")

    async def request_permission(self, session_id, tool_call, options, **kw):
        self._rec("permission", {"tool_call": tool_call.model_dump(mode="json", by_alias=True, exclude_none=True),
                                 "options": [o.model_dump(mode="json", by_alias=True) for o in options]})
        pick = next((o for o in options if o.kind in ("allow_once", "allow_always")), None)
        self.perms.append({"title": tool_call.title, "picked": pick.kind if pick else None})
        if pick is None:
            return RequestPermissionResponse(outcome=DeniedOutcome(outcome="cancelled"))
        return RequestPermissionResponse(outcome=AllowedOutcome(outcome="selected", option_id=pick.option_id))

    async def session_update(self, session_id, update, **kw):
        k = getattr(update, "session_update", type(update).__name__)
        self.kinds[k] = self.kinds.get(k, 0) + 1
        self._rec("update", update)
        if isinstance(update, AgentMessageChunk) and isinstance(update.content, TextContentBlock):
            self.text.append(update.content.text)
        if k == "usage_update":
            self.usage = update.model_dump(mode="json", by_alias=True, exclude_none=True)

    async def ext_method(self, method, params): raise RequestError.method_not_found(method)
    async def ext_notification(self, method, params): pass

async def main():
    sep = sys.argv.index("--")
    label, workdir, prompt = sys.argv[1:4]
    cmd = sys.argv[sep + 1:]
    t0 = time.time()
    log = open(f"{label}.jsonl", "w")
    proc = await asyncio.create_subprocess_exec(*cmd, cwd=workdir, stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=open(f"{label}.stderr", "w"))
    client = TrialClient(log)
    conn = connect_to_agent(client, proc.stdin, proc.stdout)
    out = {"label": label, "cmd": cmd}
    try:
        init = await asyncio.wait_for(conn.initialize(protocol_version=PROTOCOL_VERSION,
            client_capabilities=ClientCapabilities(),
            client_info=Implementation(name="acp-trial", title="ACP trial", version="0.1")), 120)
        out["agent"] = init.agent_info.model_dump(exclude_none=True) if init.agent_info else None
        sess = await asyncio.wait_for(conn.new_session(mcp_servers=[], cwd=workdir), 120)
        resp = await asyncio.wait_for(conn.prompt(session_id=sess.session_id,
            prompt=[TextContentBlock(type="text", text=prompt)]), 600)
        out["stop_reason"] = resp.stop_reason
        out["prompt_usage"] = resp.usage.model_dump(mode="json", exclude_none=True) if resp.usage else None
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"[:500]
    out.update(seconds=round(time.time() - t0, 1), final_text="".join(client.text)[-400:],
               permissions=client.perms, update_kinds=client.kinds, usage_update=client.usage)
    if proc.returncode is None:
        proc.terminate()
        try: await asyncio.wait_for(proc.wait(), 10)
        except asyncio.TimeoutError: proc.kill()
    print(json.dumps(out, indent=1))

asyncio.run(main())
