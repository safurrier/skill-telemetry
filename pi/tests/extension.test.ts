import assert from "node:assert/strict";
import test from "node:test";

import extension from "../src/index.ts";

test("extension registers only lifecycle handlers", () => {
  const calls: string[] = [];
  extension({
    registerCommand: () => calls.push("command"),
    registerTool: () => calls.push("tool"),
    on: (name: string) => calls.push(name),
  } as never);
  assert.deepEqual(calls, ["session_start", "input", "before_agent_start", "tool_call"]);
});
