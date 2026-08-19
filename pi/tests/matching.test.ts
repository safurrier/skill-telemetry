import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import {
  closeSync,
  lstatSync,
  mkdtempSync,
  openSync,
  readFileSync,
  readSync,
  renameSync,
  symlinkSync,
  utimesSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

import skillTelemetry from "../src/index.ts";
import {
  buildInventory,
  MAX_INVENTORY_RECORDS,
  MAX_SKILL_BYTES,
  MAX_SKILL_TOTAL_BYTES,
  detectCanonicalRead,
  detectInput,
  digest,
  inputOccurrenceIdentity,
  ProvenanceError,
  provenanceFailureEvent,
  setInventoryHashFilesystemForTests,
  restoredActivationIds,
  restoredDedupeCandidates,
  turnIdFromEntries,
  type CommandLike,
  type SkillLike,
  type TelemetryEvent,
} from "../src/matching.ts";

interface PrivacyCorpus {
  rejected_identifiers: string[];
  rejected_tokens: string[];
  safe_identifiers: string[];
  safe_tokens: string[];
}

const privacyCorpus = JSON.parse(
  readFileSync(
    new URL("./fixtures/privacy-corpus.json", import.meta.url),
    "utf8",
  ),
) as PrivacyCorpus;

const baselineFixtures = JSON.parse(
  readFileSync(new URL("./fixtures/v0.2-legacy-events.json", import.meta.url), "utf8"),
) as {
  explicit_activation: TelemetryEvent;
  prompt_command: TelemetryEvent;
  inventory_failure: TelemetryEvent;
};

interface TestEntry {
  type: string;
  id: string;
  parentId: string | null;
  customType?: string;
  data?: TelemetryEvent;
  message?: { role: string };
}

type Handler = (event: never, context: never) => void;

class FakeExtensionRuntime {
  private readonly handlers = new Map<string, Handler[]>();
  private readonly commands: CommandLike[];
  private nextId = 1;
  private sessionId = "session-a";
  readonly entries: TestEntry[] = [];
  readonly notifications: string[] = [];
  failNextAppend = false;
  readonly pi: ExtensionAPI;

  constructor(commands: CommandLike[]) {
    this.commands = commands;
    this.pi = {
      on: (name: string, handler: Handler) => {
        const existing = this.handlers.get(name) ?? [];
        existing.push(handler);
        this.handlers.set(name, existing);
      },
      getCommands: () => this.commands,
      appendEntry: (customType: string, data: TelemetryEvent) => {
        if (this.failNextAppend) {
          this.failNextAppend = false;
          throw new Error("append failure");
        }
        this.entries.push({
          type: "custom",
          id: this.allocateId(),
          parentId: this.leafId(),
          customType,
          data,
        });
      },
    } as unknown as ExtensionAPI;
  }

  start(sessionId = this.sessionId): void {
    this.sessionId = sessionId;
    this.emit("session_start", { type: "session_start", reason: "resume" });
  }

  input(text: string): void {
    this.emit("input", { type: "input", text, source: "interactive" });
  }

  beforeAgentStart(skills: SkillLike[]): void {
    this.emit("before_agent_start", { systemPromptOptions: { skills } });
  }

  toolCall(path: string, toolCallId = "tool-call-1"): void {
    this.emit("tool_call", {
      toolName: "read",
      toolCallId,
      input: { path },
    });
  }

  appendConversationEntry(role = "assistant"): void {
    this.entries.push({
      type: "message",
      id: this.allocateId(),
      parentId: this.leafId(),
      message: { role },
    });
  }

  telemetryEvents(): TelemetryEvent[] {
    return this.entries
      .filter((entry) => entry.type === "custom" && entry.customType === "skill-telemetry-v1")
      .flatMap((entry) => (entry.data ? [entry.data] : []));
  }

  private emit(name: string, event: object): void {
    const context = {
      cwd: tmpdir(),
      sessionManager: {
        getSessionId: () => this.sessionId,
        getBranch: () => [...this.entries],
      },
      ui: {
        notify: (message: string) => this.notifications.push(message),
      },
    };
    for (const handler of this.handlers.get(name) ?? []) {
      handler(event as never, context as never);
    }
  }

  private allocateId(): string {
    return `entry-${this.nextId++}`;
  }

  private leafId(): string | null {
    return this.entries.at(-1)?.id ?? null;
  }
}

function fixtureCommands(root: string, skillPath: string): CommandLike[] {
  return [
    {
      name: "skill:example-capture",
      source: "skill",
      sourceInfo: { path: skillPath, source: "pi-runtime" },
    },
    {
      name: "example-capture",
      source: "prompt",
      sourceInfo: { path: join(root, "prompt.md"), source: "pi-runtime" },
    },
  ];
}

function fixture() {
  const root = mkdtempSync(join(tmpdir(), "pi-skill-telemetry-"));
  const skillPath = join(root, "SKILL.md");
  const arbitraryPath = join(root, "arbitrary-SKILL.md");
  writeFileSync(skillPath, "---\nname: example-capture\n---\nPrivate-free fixture.\n");
  writeFileSync(arbitraryPath, "not canonical\n");
  const commands = fixtureCommands(root, skillPath);
  const inventory = buildInventory(commands, []);
  return { root, skillPath, arbitraryPath, commands, inventory };
}

test("explicit skill command is observed and contains no absolute path", () => {
  const { inventory } = fixture();
  const [event] = detectInput(
    "/skill:example-capture extra arguments are not retained",
    digest("session", "private"),
    digest("turn", "turn-1"),
    inventory,
  );
  assert.equal(event.evidence_type, "explicit-command");
  assert.equal(event.evidence_confidence, "observed");
  assert.equal(event.turn_id, digest("turn", "turn-1"));
  assert.equal(JSON.stringify(event).includes(tmpdir()), false);
  assert.equal(JSON.stringify(event).includes("extra arguments"), false);
});

test("TypeScript builder stays compatible with the committed Python consumer fixture", () => {
  const root = mkdtempSync(join(tmpdir(), "pi-bridge-"));
  const skillPath = join(root, "SKILL.md");
  writeFileSync(skillPath, "bridge fixture\n");
  const inventory = buildInventory([
    {
      name: "skill:example-capture",
      source: "skill",
      sourceInfo: { path: skillPath, source: "pi-runtime" },
    },
  ]);
  const [event] = detectInput(
    "/skill:example-capture sanitized",
    digest("session", "bridge-session"),
    digest("turn", "bridge-turn"),
    inventory,
  );
  event.timestamp = "2026-07-18T20:10:00Z";
  const fixture = JSON.parse(
    readFileSync(
      new URL(
        "./fixtures/pi-event-v1.json",
        import.meta.url,
      ),
      "utf8",
    ),
  ) as {
    pi_produced_event: TelemetryEvent;
    persistence_valid_but_not_operational: Record<string, unknown>;
  };

  assert.deepEqual(event, fixture.pi_produced_event);
  assert.deepEqual(
    restoredDedupeCandidates([{
      type: "custom",
      customType: "skill-telemetry-v1",
      data: fixture.persistence_valid_but_not_operational,
    }]),
    [],
  );
});

test("prompt command remains distinct from a natural candidate", () => {
  const { inventory } = fixture();
  const session = digest("session", "s");
  const turn = digest("turn", "turn-1");
  const prompt = detectInput("/example-capture", session, turn, inventory)[0];
  const natural = detectInput("run example capture", session, turn, inventory)[0];
  assert.equal(prompt.evidence_type, "prompt-expansion");
  assert.equal(prompt.status, "expanded");
  assert.equal(natural.evidence_type, "natural-language-candidate");
  assert.equal(natural.evidence_confidence, "candidate");
});

test("loose discussion and common one-word names do not become candidates", () => {
  const { inventory } = fixture();
  const session = digest("session", "s");
  const turn = digest("turn", "turn-1");
  assert.deepEqual(
    detectInput("we should discuss example capture metrics", session, turn, inventory),
    [],
  );
  const oneWordPath = join(mkdtempSync(join(tmpdir(), "pi-one-word-")), "SKILL.md");
  writeFileSync(oneWordPath, "one word\n");
  const oneWord = buildInventory([
    {
      name: "skill:write",
      source: "skill",
      sourceInfo: { path: oneWordPath, source: "pi-runtime" },
    },
  ]);
  assert.deepEqual(detectInput("write", session, turn, oneWord), []);
});

test("only provenance-backed canonical SKILL reads qualify", () => {
  const { root, skillPath, arbitraryPath, inventory } = fixture();
  const session = digest("session", "s");
  const turn = digest("turn", "turn-1");
  const canonical = detectCanonicalRead(
    skillPath,
    root,
    session,
    turn,
    "tool-call-1",
    inventory,
  );
  const arbitrary = detectCanonicalRead(
    arbitraryPath,
    root,
    session,
    turn,
    "tool-call-2",
    inventory,
  );
  assert.equal(canonical?.evidence_type, "canonical-file-read");
  assert.equal(canonical?.evidence_confidence, "qualified");
  assert.equal(arbitrary, undefined);
});

test("resume keeps later activations while duplicate delivery stays deduplicated", () => {
  const { commands } = fixture();
  const runtime = new FakeExtensionRuntime(commands);
  skillTelemetry(runtime.pi);

  runtime.start("session-a");
  runtime.input("/skill:example-capture");
  runtime.input("/skill:example-capture");
  assert.equal(runtime.telemetryEvents().length, 1);

  runtime.appendConversationEntry();
  runtime.start("session-a");
  runtime.input("/skill:example-capture");
  assert.equal(runtime.telemetryEvents().length, 2);
  assert.notEqual(
    runtime.telemetryEvents()[0].activation_id,
    runtime.telemetryEvents()[1].activation_id,
  );
  assert.notEqual(runtime.telemetryEvents()[0].turn_id, runtime.telemetryEvents()[1].turn_id);

  runtime.start("session-fork");
  runtime.input("/skill:example-capture");
  assert.equal(runtime.telemetryEvents().length, 3);
  assert.notEqual(
    runtime.telemetryEvents()[1].activation_id,
    runtime.telemetryEvents()[2].activation_id,
  );
});

test("repeated same-skill input events retain distinct content-free occurrences", () => {
  const { commands } = fixture();
  const runtime = new FakeExtensionRuntime(commands);
  skillTelemetry(runtime.pi);

  runtime.start("session-a");
  runtime.input("/skill:example-capture first invocation");
  runtime.input("/skill:example-capture second invocation");

  const events = runtime.telemetryEvents();
  assert.equal(events.length, 2);
  assert.notEqual(events[0].activation_id, events[1].activation_id);
});

test("session_start restores same-turn ordinals while preserving only an exact replay", () => {
  const { commands } = fixture();
  const runtime = new FakeExtensionRuntime(commands);
  skillTelemetry(runtime.pi);

  runtime.start("session-a");
  runtime.input("/skill:example-capture first input");
  runtime.start("session-a");
  runtime.input("/skill:example-capture second input");
  runtime.input("/skill:example-capture second input");

  const events = runtime.telemetryEvents();
  assert.equal(events.length, 2);
  assert.notEqual(events[0].activation_id, events[1].activation_id);

  runtime.start("session-fork");
  runtime.input("/skill:example-capture fork input");
  assert.equal(runtime.telemetryEvents().length, 3);
});

test("input activation IDs exclude prompt arguments at a fixed turn and ordinal", () => {
  const { commands } = fixture();
  const first = new FakeExtensionRuntime(commands);
  const second = new FakeExtensionRuntime(commands);
  skillTelemetry(first.pi);
  skillTelemetry(second.pi);
  first.start("privacy-session");
  second.start("privacy-session");
  first.input("/skill:example-capture first private argument");
  second.input("/skill:example-capture second private argument");

  assert.equal(first.telemetryEvents()[0].activation_id, second.telemetryEvents()[0].activation_id);
  assert.equal(JSON.stringify(first.telemetryEvents()[0]).includes("first private argument"), false);
  assert.equal(JSON.stringify(second.telemetryEvents()[0]).includes("second private argument"), false);
});

test("operationally unsafe restored records fail closed without rewriting history", () => {
  const valid = structuredClone(baselineFixtures.explicit_activation) as unknown as Record<string, unknown>;
  const invalidRecords: Record<string, unknown>[] = [
    { ...valid, event_name: "agent.skill.a..b" },
    { ...valid, trigger: "explicit..command" },
    { ...valid, skill_source: "../private" },
    { ...valid, timestamp: "2026-02-30T00:00:00Z" },
    { ...valid, timestamp: "2026-08-19" },
    { ...valid, status: "loaded\u001fdelimiter" },
    { ...valid, count: 0 },
    { ...valid, count: "1" },
    { ...valid, agent_system: "unknown" },
    { ...valid, agent_system: "claude" },
    { ...valid, evidence_confidence: "certain" },
    { ...valid, extra: "unknown" },
    (() => { const { timestamp: _timestamp, ...missing } = valid; return missing; })(),
    { ...valid, trigger: `github_pat_${"a".repeat(36)}` },
  ];
  for (const data of invalidRecords) {
    assert.deepEqual([...restoredActivationIds([{
      type: "custom", customType: "skill-telemetry-v1", data,
    }])], []);
  }
});

test("safe operational candidates with bounded optional fields remain restorable", () => {
  const event = { ...baselineFixtures.explicit_activation, signal_name: "skill-usage", count: 1 };
  assert.deepEqual([...restoredActivationIds([{
    type: "custom", customType: "skill-telemetry-v1", data: event,
  }])], [event.activation_id]);
});

test("malformed restored telemetry cannot influence dedupe or compatibility", () => {
  const { commands } = fixture();
  const runtime = new FakeExtensionRuntime(commands);
  runtime.entries.push({
    type: "custom", id: "malformed", parentId: null, customType: "skill-telemetry-v1",
    data: { activation_id: digest("activation", "safe") } as TelemetryEvent,
  });
  skillTelemetry(runtime.pi);
  runtime.start("session-a");
  runtime.input("/skill:example-capture");
  assert.equal(runtime.telemetryEvents().length, 2);
});

test("secret-like restored event metadata cannot influence dedupe", () => {
  const { commands, inventory } = fixture();
  const session = digest("pi-session", "session-a");
  const turn = turnIdFromEntries(session, []);
  const [unsafe] = detectInput("/skill:example-capture", session, turn, inventory);
  unsafe.trigger = `github_pat_${"a".repeat(36)}`;
  const runtime = new FakeExtensionRuntime(commands);
  runtime.entries.push({
    type: "custom", id: "unsafe", parentId: null, customType: "skill-telemetry-v1", data: unsafe,
  });
  skillTelemetry(runtime.pi);
  runtime.start("session-a");
  runtime.input("/skill:example-capture");
  assert.equal(runtime.telemetryEvents().length, 2);
});

test("an append failure retries its ordinal without corrupting the next identity", () => {
  const { commands } = fixture();
  const runtime = new FakeExtensionRuntime(commands);
  skillTelemetry(runtime.pi);
  runtime.start("session-a");
  runtime.failNextAppend = true;
  runtime.input("/skill:example-capture retryable input");
  assert.equal(runtime.telemetryEvents().length, 0);
  runtime.input("/skill:example-capture retryable input");
  runtime.input("/skill:example-capture next input");
  const events = runtime.telemetryEvents();
  const session = digest("pi-session", "session-a");
  const turn = turnIdFromEntries(session, []);
  const retry = detectInput(
    "/skill:example-capture retryable input", session, turn, buildInventory(commands), 0,
  )[0];
  const successor = detectInput(
    "/skill:example-capture next input", session, turn, buildInventory(commands), 1,
  )[0];
  assert.equal(events.length, 2);
  assert.equal(events[0].activation_id, retry.activation_id);
  assert.equal(events[1].activation_id, successor.activation_id);
});

test("append failure followed by distinct inputs remains contiguous across two resumes", () => {
  const { commands } = fixture();
  const runtime = new FakeExtensionRuntime(commands);
  skillTelemetry(runtime.pi);

  runtime.start("session-a");
  runtime.failNextAppend = true;
  runtime.input("/skill:example-capture failed ordinal zero");
  runtime.input("/skill:example-capture persisted ordinal zero");
  runtime.start("session-a");
  runtime.input("/skill:example-capture persisted ordinal one");
  runtime.start("session-a");
  runtime.input("/skill:example-capture persisted ordinal two");

  const events = runtime.telemetryEvents();
  assert.equal(events.length, 3);
  assert.equal(new Set(events.map((event) => event.activation_id)).size, 3);
  const session = digest("pi-session", "session-a");
  const turn = turnIdFromEntries(session, []);
  for (const [ordinal, text] of [
    "persisted ordinal zero",
    "persisted ordinal one",
    "persisted ordinal two",
  ].entries()) {
    assert.equal(
      events[ordinal]?.activation_id,
      detectInput(`/skill:example-capture ${text}`, session, turn, buildInventory(commands), ordinal)[0]
        ?.activation_id,
    );
  }
});

test("deferred failure append lifecycle remains contiguous across two resumes", () => {
  const { skillPath } = fixture();
  const runtime = new FakeExtensionRuntime([]);
  skillTelemetry(runtime.pi);

  runtime.start("session-a");
  runtime.failNextAppend = true;
  runtime.input("/skill:example-capture failed ordinal zero");
  runtime.beforeAgentStart([{ name: "example-capture", filePath: skillPath }]);
  runtime.input("/skill:example-capture persisted ordinal zero");
  runtime.beforeAgentStart([{ name: "example-capture", filePath: skillPath }]);
  runtime.start("session-a");
  runtime.input("/skill:example-capture persisted ordinal one");
  runtime.beforeAgentStart([{ name: "example-capture", filePath: skillPath }]);
  runtime.start("session-a");
  runtime.input("/skill:example-capture persisted ordinal two");
  runtime.beforeAgentStart([{ name: "example-capture", filePath: skillPath }]);

  const failures = runtime.telemetryEvents();
  assert.equal(failures.length, 3);
  const session = digest("pi-session", "session-a");
  const turn = turnIdFromEntries(session, []);
  const failure = {
    operation: "inventory" as const,
    status: "provenance-invalid" as const,
    skillName: "example-capture",
    source: "pi-provenance",
  };
  for (const ordinal of [0, 1, 2]) {
    assert.equal(
      failures[ordinal]?.activation_id,
      provenanceFailureEvent(session, turn, inputOccurrenceIdentity(turn, ordinal), failure).activation_id,
    );
  }
});

test("July 18 dogfood: candidate and canonical read share one logical turn", () => {
  const { skillPath, commands } = fixture();
  const runtime = new FakeExtensionRuntime(commands);
  skillTelemetry(runtime.pi);

  runtime.start("session-a");
  runtime.input("run example capture");
  runtime.appendConversationEntry("user");
  runtime.appendConversationEntry("assistant");
  runtime.toolCall(skillPath);

  const [candidate, loaded] = runtime.telemetryEvents();
  assert.equal(candidate.evidence_type, "natural-language-candidate");
  assert.equal(loaded.evidence_type, "canonical-file-read");
  assert.equal(candidate.session_id, loaded.session_id);
  assert.equal(candidate.turn_id, loaded.turn_id);
});

test("July 18 dogfood: unrelated invalid command is skipped without provenance failure", () => {
  const { skillPath } = fixture();
  const inventory = buildInventory([
    {
      name: "skill:example-capture",
      source: "skill",
      sourceInfo: { path: skillPath, source: "pi-runtime" },
    },
    {
      name: "skill:unrelated/private-command",
      source: "skill",
      sourceInfo: { path: skillPath, source: "pi-runtime" },
    },
  ]);

  assert.equal(inventory.provenanceFailures.length, 0);
  assert.equal(inventory.skillsByName.has("example-capture"), true);
});

test("resume restores only telemetry activation IDs", () => {
  const activation = digest("activation", "same");
  const entries = [
    {
      type: "custom",
      customType: "skill-telemetry-v1",
      data: {
        schema_version: 1,
        event_name: "agent.skill.activation",
        agent_system: "pi",
        session_id: digest("session", "safe"),
        turn_id: digest("turn", "safe"),
        activation_id: activation,
        skill_name: "example-capture",
        skill_source: "pi-runtime",
        trigger: "explicit-command",
        evidence_type: "explicit-command",
        evidence_confidence: "observed",
        status: "loaded",
        timestamp: "2026-08-19T00:00:00.000Z",
      },
    },
    { type: "custom", customType: "another-extension", data: { activation_id: "ignore" } },
  ];
  assert.deepEqual([...restoredActivationIds(entries)], [activation]);
});

test("turn identity ignores telemetry entries but advances with conversation", () => {
  const session = digest("session", "s");
  const initial = turnIdFromEntries(session, []);
  const afterTelemetry = turnIdFromEntries(session, [
    {
      type: "custom",
      id: "telemetry-1",
      customType: "skill-telemetry-v1",
      data: { activation_id: digest("activation", "a") },
    },
  ]);
  const afterConversation = turnIdFromEntries(session, [
    {
      type: "message",
      id: "message-1",
      message: { role: "assistant" },
    },
  ]);
  assert.equal(initial, afterTelemetry);
  assert.notEqual(initial, afterConversation);
});

test("inventory provenance failure is deferred until the failed skill is invoked", () => {
  const missingPath = join(tmpdir(), "missing-private-skill", "SKILL.md");
  const runtime = new FakeExtensionRuntime([
    {
      name: "skill:example-capture",
      source: "skill",
      sourceInfo: { path: missingPath, source: "pi-runtime" },
    },
  ]);
  skillTelemetry(runtime.pi);

  runtime.start();
  assert.equal(runtime.telemetryEvents().length, 0);
  assert.equal(runtime.notifications.length, 0);
  runtime.input("/skill:example-capture");

  const [failure] = runtime.telemetryEvents();
  assert.equal(failure.event_name, "agent.skill.failure");
  assert.equal(failure.evidence_confidence, "unknown");
  assert.equal(failure.status, "provenance-missing");
  assert.equal(JSON.stringify(failure).includes(missingPath), false);
  assert.equal(runtime.notifications.length, 1);
  assert.equal(runtime.notifications[0].includes(missingPath), false);
});

test("deferred missing-source failures restore semantic occurrences across an unchanged anchor", () => {
  const { skillPath } = fixture();
  const runtime = new FakeExtensionRuntime([]);
  skillTelemetry(runtime.pi);
  runtime.start();
  runtime.input("/skill:example-capture first input");
  runtime.beforeAgentStart([{ name: "example-capture", filePath: skillPath }]);

  runtime.start("session-a");
  runtime.input("/skill:example-capture distinct later input");
  runtime.beforeAgentStart([{ name: "example-capture", filePath: skillPath }]);

  const failures = runtime.telemetryEvents();
  assert.equal(failures.length, 2);
  assert.equal(failures[0]?.event_name, "agent.skill.failure");
  assert.equal(failures[0]?.status, "provenance-invalid");
  assert.equal(failures[0]?.skill_name, "example-capture");
  assert.equal(failures[0]?.skill_source, "pi-provenance");
  assert.notEqual(failures[0]?.activation_id, failures[1]?.activation_id);
  assert.equal(runtime.notifications.length, 2);
});

test("deferred provenance append failure retries before allocating its successor", () => {
  const { skillPath } = fixture();
  const runtime = new FakeExtensionRuntime([]);
  skillTelemetry(runtime.pi);
  runtime.start();
  runtime.failNextAppend = true;
  runtime.input("/skill:example-capture retryable input");
  runtime.beforeAgentStart([{ name: "example-capture", filePath: skillPath }]);
  assert.equal(runtime.telemetryEvents().length, 0);

  runtime.input("/skill:example-capture retryable input");
  runtime.beforeAgentStart([{ name: "example-capture", filePath: skillPath }]);
  runtime.input("/skill:example-capture next input");
  runtime.beforeAgentStart([{ name: "example-capture", filePath: skillPath }]);

  const failures = runtime.telemetryEvents();
  assert.equal(failures.length, 2);
  assert.notEqual(failures[0]?.activation_id, failures[1]?.activation_id);
});

test("command-derived skill without source cannot qualify activation", () => {
  const { skillPath } = fixture();
  const runtime = new FakeExtensionRuntime([
    {
      name: "skill:example-capture",
      source: "skill",
      sourceInfo: { path: skillPath },
    },
  ]);
  skillTelemetry(runtime.pi);
  runtime.start();
  runtime.input("/skill:example-capture");

  const events = runtime.telemetryEvents();
  assert.equal(events.length, 1);
  assert.equal(events[0].event_name, "agent.skill.failure");
  assert.equal(events[0].status, "provenance-invalid");
  assert.equal(events[0].skill_name, "example-capture");
  assert.equal(events[0].skill_source, "pi-provenance");
  assert.equal(events.some((event) => event.evidence_type === "explicit-command"), false);
});

test("extension append path rejects secret-like skill names and sources without echo", () => {
  const { skillPath } = fixture();
  for (const secretLike of [
    ...privacyCorpus.rejected_identifiers,
    ...privacyCorpus.rejected_tokens,
  ]) {
    for (const field of ["name", "source"] as const) {
      const runtime = new FakeExtensionRuntime([]);
      skillTelemetry(runtime.pi);
      runtime.start();
      const invokedName = field === "name" ? secretLike : "example-capture";
      runtime.input(`/skill:${invokedName}`);
      runtime.beforeAgentStart([
        {
          name: field === "name" ? secretLike : "example-capture",
          filePath: skillPath,
          sourceInfo: { source: field === "source" ? secretLike : "pi-runtime" },
        },
      ]);

      const [failure] = runtime.telemetryEvents();
      assert.equal(runtime.telemetryEvents().length, 1);
      assert.equal(failure.event_name, "agent.skill.failure");
      assert.equal(failure.status, "provenance-invalid");
      assert.equal(JSON.stringify(runtime.entries).includes(secretLike), false);
      assert.equal(runtime.notifications.join("\n").includes(secretLike), false);
    }
  }
});

test("unrelated ambient invalid sources stay silent while the invoked safe skill loads", () => {
  const root = mkdtempSync(join(tmpdir(), "pi-dogfood-precision-"));
  const writingPath = join(root, "writing-SKILL.md");
  const ambientPath = join(root, "ambient-SKILL.md");
  writeFileSync(writingPath, "writing skill\n");
  writeFileSync(ambientPath, "ambient skill\n");
  const runtime = new FakeExtensionRuntime([
    {
      name: "skill:example-writing",
      source: "skill",
      sourceInfo: { path: writingPath, source: "auto" },
    },
  ]);
  skillTelemetry(runtime.pi);

  runtime.start();
  runtime.input("/skill:example-writing");
  runtime.beforeAgentStart([
    {
      name: "ambient-plugin-skill",
      filePath: ambientPath,
      sourceInfo: { source: "plugin:ambient/source" },
    },
  ]);

  const [activation] = runtime.telemetryEvents();
  assert.equal(runtime.telemetryEvents().length, 1);
  assert.equal(activation.event_name, "agent.skill.activation");
  assert.equal(activation.skill_name, "example-writing");
  assert.equal(activation.skill_source, "auto");
  assert.equal(runtime.notifications.length, 0);

  runtime.input("/skill:ambient-plugin-skill");
  runtime.beforeAgentStart([
    {
      name: "ambient-plugin-skill",
      filePath: ambientPath,
      sourceInfo: { source: "plugin:ambient/source" },
    },
  ]);

  const failure = runtime.telemetryEvents().at(-1);
  assert.equal(runtime.telemetryEvents().length, 2);
  assert.equal(failure?.event_name, "agent.skill.failure");
  assert.equal(failure?.skill_name, "ambient-plugin-skill");
  assert.equal(failure?.skill_source, "pi-provenance");
  assert.equal(JSON.stringify(failure).includes("plugin:ambient/source"), false);
  assert.equal(runtime.notifications.length, 1);
});

test("canonical read of a failed skill emits one scoped content-free failure", () => {
  const root = mkdtempSync(join(tmpdir(), "pi-failed-read-"));
  const skillPath = join(root, "SKILL.md");
  const unsafeSource = "plugin:ambient/source";
  writeFileSync(skillPath, "failed provenance skill\n");
  const runtime = new FakeExtensionRuntime([]);
  skillTelemetry(runtime.pi);

  runtime.start();
  runtime.beforeAgentStart([
    {
      name: "ambient-plugin-skill",
      filePath: skillPath,
      sourceInfo: { source: unsafeSource },
    },
  ]);
  assert.equal(runtime.telemetryEvents().length, 0);

  runtime.toolCall(skillPath, "failed-read-1");
  runtime.toolCall(skillPath, "failed-read-1");

  const [failure] = runtime.telemetryEvents();
  assert.equal(runtime.telemetryEvents().length, 1);
  assert.equal(failure.event_name, "agent.skill.failure");
  assert.equal(failure.evidence_type, "provenance-error");
  assert.equal(failure.trigger, "inventory");
  assert.equal(failure.status, "provenance-invalid");
  assert.equal(failure.skill_name, "ambient-plugin-skill");
  assert.equal(failure.skill_source, "pi-provenance");
  assert.equal(JSON.stringify(failure).includes(skillPath), false);
  assert.equal(JSON.stringify(failure).includes(unsafeSource), false);
  assert.equal(runtime.notifications.length, 1);
});

test("unsafe Pi provenance is emitted only as a content-free failure", () => {
  const unsafeSource = privacyCorpus.rejected_identifiers[0];
  const event = provenanceFailureEvent(
    digest("session", "safe"),
    digest("turn", "safe"),
    digest("occurrence", "safe"),
    {
      operation: "inventory",
      status: "provenance-invalid",
      skillName: unsafeSource,
      source: unsafeSource,
    },
  );

  assert.equal(event.event_name, "agent.skill.failure");
  assert.equal(event.skill_name, undefined);
  assert.equal(event.skill_source, "pi-provenance");
  assert.equal(JSON.stringify(event).includes(unsafeSource), false);
});

test("shared privacy corpus keeps safe Pi provenance identifiers available", () => {
  const { skillPath } = fixture();
  for (const source of [...privacyCorpus.safe_identifiers, ...privacyCorpus.safe_tokens]) {
    const inventory = buildInventory(
      [],
      [{ name: "example-capture", filePath: skillPath, sourceInfo: { source } }],
    );
    assert.equal(inventory.provenanceFailures.length, 0);
    assert.equal(inventory.skillsByName.get("example-capture")?.source, source);
  }
});

test("Pi inventory hashes a bounded regular skill in fixed-size chunks", () => {
  const root = mkdtempSync(join(tmpdir(), "telemetry-bounded-"));
  const exact = join(root, "exact.md");
  writeFileSync(exact, "a".repeat(MAX_SKILL_BYTES));
  const inventory = buildInventory([], [{ name: "bounded-skill", filePath: exact, sourceInfo: { source: "pi-runtime" } }]);
  assert.equal(inventory.skillsByName.has("bounded-skill"), true);

  const oversized = join(root, "oversized.md");
  writeFileSync(oversized, "b".repeat(MAX_SKILL_BYTES + 1));
  const failed = buildInventory([], [{ name: "oversized-skill", filePath: oversized, sourceInfo: { source: "pi-runtime" } }]);
  assert.equal(failed.skillsByName.size, 0);
  assert.equal(detectInput("/oversized-skill", "session", "turn", failed)[0]?.event_name, "agent.skill.failure");
});

test("Pi inventory caps aggregate skill bytes and ambient records without retaining content", () => {
  const root = mkdtempSync(join(tmpdir(), "telemetry-bounded-"));
  const skills: SkillLike[] = Array.from({ length: 5 }, (_, index) => {
    const path = join(root, `skill-${index}.md`);
    writeFileSync(path, "x".repeat(MAX_SKILL_TOTAL_BYTES / 4));
    return { name: `skill-${index}`, filePath: path, sourceInfo: { source: "pi-runtime" } };
  });
  const inventory = buildInventory(
    Array.from({ length: MAX_INVENTORY_RECORDS + 10 }, (_, index) => ({ name: `prompt-${index}`, source: "prompt" })),
    skills,
  );
  assert.equal(inventory.skillsByName.size, 4);
  assert.ok(inventory.commandsByName.size <= MAX_INVENTORY_RECORDS);
});

test("Pi inventory rejects a FIFO without blocking", () => {
  const root = mkdtempSync(join(tmpdir(), "pi-skill-fifo-"));
  const fifo = join(root, "SKILL.md");
  execFileSync("mkfifo", [fifo]);
  const inventory = buildInventory([], [
    { name: "fifo-skill", filePath: fifo, sourceInfo: { source: "pi-runtime" } },
  ]);
  assert.equal(inventory.skillsByName.size, 0);
  assert.equal(inventory.provenanceFailures[0]?.status, "provenance-invalid");
});

test("Pi inventory rejects a same-size replacement after lstat and closes its descriptor", () => {
  const root = mkdtempSync(join(tmpdir(), "pi-skill-race-"));
  const skillPath = join(root, "SKILL.md");
  const replacement = join(root, "replacement.md");
  writeFileSync(skillPath, "before\n");
  writeFileSync(replacement, "after!\n");
  let closed = 0;
  setInventoryHashFilesystemForTests({
    openSync(path, flags) {
      renameSync(replacement, path.toString());
      return openSync(path, flags);
    },
    closeSync(fd) {
      closed += 1;
      closeSync(fd);
    },
  });
  try {
    const inventory = buildInventory([], [
      { name: "race-skill", filePath: skillPath, sourceInfo: { source: "pi-runtime" } },
    ]);
    const [failure] = detectInput("/race-skill", "session", "turn", inventory);
    assert.equal(inventory.skillsByName.size, 0);
    assert.equal(failure?.status, "provenance-invalid");
    assert.equal(closed, 1);
    assert.equal(JSON.stringify(failure).includes(skillPath), false);
    assert.equal(JSON.stringify(failure).includes("after!"), false);
  } finally {
    setInventoryHashFilesystemForTests();
  }
});

test("Pi inventory rejects a same-size mutation during hashing", () => {
  const root = mkdtempSync(join(tmpdir(), "pi-skill-race-"));
  const skillPath = join(root, "SKILL.md");
  writeFileSync(skillPath, "original\n");
  const before = lstatSync(skillPath);
  let mutated = false;
  const mutateDuringRead = ((
    fd: number,
    buffer: NodeJS.ArrayBufferView,
    offset: number,
    length: number,
    position: number | bigint | null,
  ): number => {
    const read = readSync(fd, buffer, offset, length, position);
    if (read > 0 && !mutated) {
      mutated = true;
      writeFileSync(skillPath, "changed!\n");
      utimesSync(skillPath, before.atime, new Date(before.mtimeMs + 1_000));
    }
    return read;
  }) as typeof readSync;
  setInventoryHashFilesystemForTests({ readSync: mutateDuringRead });
  try {
    const inventory = buildInventory([], [
      { name: "race-skill", filePath: skillPath, sourceInfo: { source: "pi-runtime" } },
    ]);
    const [failure] = detectInput("/race-skill", "session", "turn", inventory);
    assert.equal(mutated, true);
    assert.equal(inventory.skillsByName.size, 0);
    assert.equal(failure?.status, "provenance-invalid");
    assert.equal(JSON.stringify(failure).includes(skillPath), false);
    assert.equal(JSON.stringify(failure).includes("changed!"), false);
  } finally {
    setInventoryHashFilesystemForTests();
  }
});

test("Pi inventory opens a FIFO replacement without blocking and closes its descriptor", () => {
  const root = mkdtempSync(join(tmpdir(), "pi-skill-race-"));
  const skillPath = join(root, "SKILL.md");
  const fifo = join(root, "replacement.fifo");
  writeFileSync(skillPath, "regular\n");
  execFileSync("mkfifo", [fifo]);
  let closed = 0;
  setInventoryHashFilesystemForTests({
    openSync(path, flags) {
      renameSync(fifo, path.toString());
      return openSync(path, flags);
    },
    closeSync(fd) {
      closed += 1;
      closeSync(fd);
    },
  });
  try {
    const inventory = buildInventory([], [
      { name: "fifo-race", filePath: skillPath, sourceInfo: { source: "pi-runtime" } },
    ]);
    assert.equal(inventory.skillsByName.size, 0);
    assert.equal(inventory.provenanceFailures[0]?.status, "provenance-invalid");
    assert.equal(closed, 1);
  } finally {
    setInventoryHashFilesystemForTests();
  }
});

test("Pi inventory rejects symlink and non-regular skill records", () => {
  const root = mkdtempSync(join(tmpdir(), "telemetry-bounded-"));
  const target = join(root, "target.md");
  writeFileSync(target, "safe");
  const linked = join(root, "linked.md");
  symlinkSync(target, linked);
  const inventory = buildInventory([], [
    { name: "linked-skill", filePath: linked, sourceInfo: { source: "pi-runtime" } },
    { name: "directory-skill", filePath: root, sourceInfo: { source: "pi-runtime" } },
  ]);
  assert.equal(inventory.skillsByName.size, 0);
  assert.equal(inventory.provenanceFailures.length, 2);
});

test("unresolvable canonical read throws a precise provenance error", () => {
  const { root, inventory } = fixture();
  assert.throws(
    () =>
      detectCanonicalRead(
        "missing/SKILL.md",
        root,
        digest("session", "s"),
        digest("turn", "turn-1"),
        "tool-call-1",
        inventory,
      ),
    (error: unknown) =>
      error instanceof ProvenanceError && error.status === "provenance-missing",
  );
});
