import { createHash } from "node:crypto";
import { closeSync, constants, fstatSync, lstatSync, openSync, readSync, realpathSync, statSync, type Stats } from "node:fs";
import { join, resolve } from "node:path";

export type EvidenceConfidence =
  | "observed"
  | "qualified"
  | "candidate"
  | "classified"
  | "unknown";

export type ProvenanceStatus =
  | "provenance-missing"
  | "provenance-denied"
  | "provenance-invalid"
  | "provenance-io-error";

export interface TelemetryEvent {
  schema_version: 1;
  event_name:
    | "agent.skill.activation"
    | "agent.skill.candidate"
    | "agent.skill.execution"
    | "agent.skill.failure";
  agent_system: "pi";
  session_id: string;
  turn_id: string;
  activation_id: string;
  skill_name?: string;
  skill_source: string;
  skill_content_hash?: string;
  trigger: string;
  evidence_type: string;
  evidence_confidence: EvidenceConfidence;
  status: string;
  timestamp: string;
}

export interface SkillRecord {
  name: string;
  canonicalPath: string;
  contentHash: string;
  source: string;
}

export interface CommandRecord {
  name: string;
  source: "skill" | "prompt";
  path?: string;
}

export interface ProvenanceFailure {
  operation: "inventory" | "canonical-read";
  status: ProvenanceStatus;
  skillName?: string;
  skillLookup?: string;
  source: string;
}

export interface Inventory {
  skillsByName: Map<string, SkillRecord>;
  skillsByPath: Map<string, SkillRecord>;
  failedSkillsByPath: Map<string, ProvenanceFailure>;
  commandsByName: Map<string, CommandRecord>;
  provenanceFailures: ProvenanceFailure[];
}

export interface CommandLike {
  name: string;
  source: string;
  sourceInfo?: { path?: string; source?: string };
}

export interface SkillLike {
  name: string;
  filePath: string;
  sourceInfo?: { source?: string };
}

export interface SessionEntryLike {
  type?: string;
  id?: string;
  customType?: string;
  data?: unknown;
  message?: unknown;
}

export const MAX_INVENTORY_RECORDS = 256;
export const MAX_SKILL_BYTES = 256 * 1024;
export const MAX_SKILL_TOTAL_BYTES = 1024 * 1024;
const HASH_CHUNK_BYTES = 64 * 1024;

type InventoryHashFilesystem = {
  lstatSync: typeof lstatSync;
  openSync: typeof openSync;
  fstatSync: typeof fstatSync;
  readSync: typeof readSync;
  closeSync: typeof closeSync;
};

const DIRECT_INVENTORY_HASH_FILESYSTEM: InventoryHashFilesystem = {
  lstatSync,
  openSync,
  fstatSync,
  readSync,
  closeSync,
};

let inventoryHashFilesystem = DIRECT_INVENTORY_HASH_FILESYSTEM;

/** Test-only seam for deterministic descriptor-race regression tests. */
export function setInventoryHashFilesystemForTests(
  overrides?: Partial<InventoryHashFilesystem>,
): void {
  inventoryHashFilesystem = overrides
    ? { ...DIRECT_INVENTORY_HASH_FILESYSTEM, ...overrides }
    : DIRECT_INVENTORY_HASH_FILESYSTEM;
}

const SAFE_IDENTIFIER = /^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$/;
const SAFE_COMMAND_NAME = /^[A-Za-z0-9][A-Za-z0-9._:+-]{0,127}$/;
const SECRET_LIKE = /(?:^|[._+-])(?:sk-(?:proj-|ant-|or-|[A-Za-z0-9_-]{12,})|github_pat_|gh[pousr]_|glpat-|xox[baprs]-|bearer[-_:]|A[KS]IA[0-9A-Z]{12,})/i;

export class ProvenanceError extends Error {
  readonly status: ProvenanceStatus;

  constructor(status: ProvenanceStatus) {
    super(status);
    this.name = "ProvenanceError";
    this.status = status;
  }
}

export function digest(namespace: string, value: string): string {
  return `sha256:${createHash("sha256")
    .update(`skill-telemetry-v1:${namespace}:${value}`)
    .digest("hex")}`;
}

function safeIdentifier(value: string | undefined): string | undefined {
  if (value === undefined) return undefined;
  const candidate = value.trim();
  if (!SAFE_IDENTIFIER.test(candidate)) return undefined;
  if (candidate.includes("..") || candidate.startsWith("/") || candidate.startsWith("~")) {
    return undefined;
  }
  if (SECRET_LIKE.test(candidate)) return undefined;
  return candidate;
}

function safeCommandName(value: string): string | undefined {
  const candidate = value.trim();
  if (!SAFE_COMMAND_NAME.test(candidate) || SECRET_LIKE.test(candidate)) return undefined;
  return candidate;
}

function provenanceStatus(error: unknown): ProvenanceStatus {
  if (error instanceof ProvenanceError) return error.status;
  if (!(error instanceof Error)) throw error;
  const code = (error as NodeJS.ErrnoException).code;
  if (code === "ENOENT" || code === "ENOTDIR") return "provenance-missing";
  if (code === "EACCES" || code === "EPERM") return "provenance-denied";
  if (code === "EINVAL" || code === "ELOOP") return "provenance-invalid";
  return "provenance-io-error";
}

function sameSkillIdentity(before: Stats, after: Stats): boolean {
  return before.dev === after.dev && before.ino === after.ino &&
    (before.mode & constants.S_IFMT) === (after.mode & constants.S_IFMT) &&
    before.uid === after.uid && before.size === after.size;
}

function hashSkillFile(path: string, remainingBytes: number): { contentHash: string; bytes: number } {
  const filesystem = inventoryHashFilesystem;
  const metadata = filesystem.lstatSync(path);
  if (!metadata.isFile() || metadata.isSymbolicLink() || metadata.size > MAX_SKILL_BYTES || metadata.size > remainingBytes) {
    throw new ProvenanceError("provenance-invalid");
  }
  const fd = filesystem.openSync(
    path,
    constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK,
  );
  try {
    const opened = filesystem.fstatSync(fd);
    if (!sameSkillIdentity(metadata, opened) || !opened.isFile() || opened.size > MAX_SKILL_BYTES || opened.size > remainingBytes) {
      throw new ProvenanceError("provenance-invalid");
    }
    const hash = createHash("sha256");
    const chunk = Buffer.allocUnsafe(Math.min(HASH_CHUNK_BYTES, Math.max(opened.size, 1)));
    let offset = 0;
    while (offset < opened.size) {
      const read = filesystem.readSync(
        fd,
        chunk,
        0,
        Math.min(chunk.length, opened.size - offset),
        offset,
      );
      if (read <= 0) throw new ProvenanceError("provenance-io-error");
      hash.update(chunk.subarray(0, read));
      offset += read;
    }
    const completed = filesystem.fstatSync(fd);
    if (!sameSkillIdentity(opened, completed) || opened.mtimeMs !== completed.mtimeMs) {
      throw new ProvenanceError("provenance-invalid");
    }
    return { contentHash: `sha256:${hash.digest("hex")}`, bytes: opened.size };
  } finally {
    filesystem.closeSync(fd);
  }
}

function loadSkillRecord(name: string, path: string, source: string, remainingBytes: number): SkillRecord & { bytes: number } {
  try {
    const declared = lstatSync(path);
    if (declared.isSymbolicLink()) throw new ProvenanceError("provenance-invalid");
    const resolvedPath = realpathSync(path);
    const resolvedStat = statSync(resolvedPath);
    const canonicalPath = resolvedStat.isDirectory()
      ? join(resolvedPath, "SKILL.md")
      : resolvedPath;
    const hashed = hashSkillFile(canonicalPath, remainingBytes);
    return { name, canonicalPath: realpathSync(canonicalPath), contentHash: hashed.contentHash, source, bytes: hashed.bytes };
  } catch (error: unknown) {
    if (error instanceof ProvenanceError) throw error;
    throw new ProvenanceError(provenanceStatus(error));
  }
}

export function emptyInventory(): Inventory {
  return {
    skillsByName: new Map(),
    skillsByPath: new Map(),
    failedSkillsByPath: new Map(),
    commandsByName: new Map(),
    provenanceFailures: [],
  };
}

function retainFailedCanonicalPath(
  inventory: Inventory,
  path: string,
  failure: ProvenanceFailure,
): void {
  try {
    if (lstatSync(path).isSymbolicLink()) return;
    const resolvedPath = realpathSync(path);
    const canonicalPath = statSync(resolvedPath).isDirectory()
      ? join(resolvedPath, "SKILL.md")
      : resolvedPath;
    if (!lstatSync(canonicalPath).isSymbolicLink() && statSync(canonicalPath).isFile()) {
      inventory.failedSkillsByPath.set(realpathSync(canonicalPath), failure);
    }
  } catch {
    // Missing or denied paths remain fail-closed and are reported if directly read.
  }
}

function addSkill(
  inventory: Inventory,
  rawName: string,
  path: string,
  rawSource: string | undefined,
  remainingBytes: number,
): number {
  const name = safeIdentifier(rawName);
  const source = safeIdentifier(rawSource);
  const skillLookup = digest("pi-failed-skill", rawName.trim());
  if (!name || !source) {
    const failure: ProvenanceFailure = {
      operation: "inventory",
      status: "provenance-invalid",
      ...(name ? { skillName: name } : {}),
      skillLookup,
      source: "pi-provenance",
    };
    inventory.provenanceFailures.push(failure);
    retainFailedCanonicalPath(inventory, path, failure);
    return 0;
  }
  try {
    const record = loadSkillRecord(name, path, source, remainingBytes);
    inventory.skillsByName.set(name, record);
    inventory.skillsByPath.set(record.canonicalPath, record);
    return record.bytes;
  } catch (error: unknown) {
    if (!(error instanceof ProvenanceError)) throw error;
    const failure: ProvenanceFailure = {
      operation: "inventory",
      status: error.status,
      skillName: name,
      skillLookup,
      source,
    };
    inventory.provenanceFailures.push(failure);
    retainFailedCanonicalPath(inventory, path, failure);
    return 0;
  }
}

export function buildInventory(commands: CommandLike[], skills: SkillLike[] = []): Inventory {
  const inventory = emptyInventory();
  let records = 0;
  let remainingBytes = MAX_SKILL_TOTAL_BYTES;
  for (const skill of skills) {
    if (records++ >= MAX_INVENTORY_RECORDS) break;
    remainingBytes -= addSkill(inventory, skill.name, skill.filePath, skill.sourceInfo?.source, remainingBytes);
  }
  for (const command of commands) {
    if (records++ >= MAX_INVENTORY_RECORDS) break;
    if (command.source !== "skill" && command.source !== "prompt") continue;
    const source = command.source;
    const rawName = source === "skill" ? command.name.replace(/^skill:/, "") : command.name;
    const name = safeIdentifier(rawName);
    const commandName = safeCommandName(command.name);
    if (!name || !commandName) {
      // Command inventory is broader than skill telemetry. Ignore unrelated command
      // shapes instead of reporting an unexplained skill provenance failure.
      continue;
    }
    inventory.commandsByName.set(commandName, {
      name,
      source,
      path: command.sourceInfo?.path,
    });
    if (source === "skill" && command.sourceInfo?.path && !inventory.skillsByName.has(name)) {
      remainingBytes -= addSkill(
        inventory, name, command.sourceInfo.path, command.sourceInfo.source, remainingBytes,
      );
    }
  }
  return inventory;
}

export function turnIdFromEntries(sessionId: string, entries: SessionEntryLike[]): string {
  let anchor = "session-root";
  for (const entry of entries) {
    if (
      entry.type === "custom" &&
      entry.customType === "skill-telemetry-v1"
    ) {
      continue;
    }
    if (typeof entry.id === "string") anchor = entry.id;
  }
  return digest("pi-turn", `${sessionId}|${anchor}`);
}

function makeEvent(
  sessionId: string,
  turnId: string,
  occurrenceIdentity: string,
  skillName: string | undefined,
  source: string,
  trigger: string,
  evidenceType: string,
  confidence: EvidenceConfidence,
  status: string,
  eventName: TelemetryEvent["event_name"],
  contentHash?: string,
): TelemetryEvent {
  const safeSource = safeIdentifier(source);
  const safeSkillName = safeIdentifier(skillName);
  if (!safeSource || (skillName !== undefined && !safeSkillName)) {
    throw new ProvenanceError("provenance-invalid");
  }
  return {
    schema_version: 1,
    event_name: eventName,
    agent_system: "pi",
    session_id: sessionId,
    turn_id: turnId,
    activation_id: digest(
      "activation",
      [
        sessionId,
        turnId,
        occurrenceIdentity,
        skillName ?? "",
        trigger,
        evidenceType,
        status,
      ].join("|"),
    ),
    ...(safeSkillName ? { skill_name: safeSkillName } : {}),
    skill_source: safeSource,
    ...(contentHash ? { skill_content_hash: contentHash } : {}),
    trigger,
    evidence_type: evidenceType,
    evidence_confidence: confidence,
    status,
    timestamp: new Date().toISOString(),
  };
}

export function provenanceFailureEvent(
  sessionId: string,
  turnId: string,
  occurrenceIdentity: string,
  failure: ProvenanceFailure,
): TelemetryEvent {
  const safeFailureName = safeIdentifier(failure.skillName);
  const safeFailureSource = safeIdentifier(failure.source) ?? "pi-provenance";
  return makeEvent(
    sessionId,
    turnId,
    occurrenceIdentity,
    safeFailureName,
    safeFailureSource,
    failure.operation,
    "provenance-error",
    "unknown",
    failure.status,
    "agent.skill.failure",
  );
}

function lookupSlashCommand(name: string, inventory: Inventory): CommandRecord | undefined {
  return inventory.commandsByName.get(name) ?? inventory.commandsByName.get(`skill:${name}`);
}

export function invokedSkillLookup(text: string, inventory: Inventory): string | undefined {
  const slash = /^\/([^\s]+)(?:\s|$)/.exec(text.trim());
  if (!slash) return undefined;
  const rawName = slash[1];
  const command = lookupSlashCommand(rawName, inventory);
  if (command?.source === "prompt") return undefined;
  const skillName = rawName.startsWith("skill:")
    ? rawName.slice("skill:".length)
    : command?.name ?? rawName;
  return skillName ? digest("pi-failed-skill", skillName.trim()) : undefined;
}

/** A persisted input occurrence contains only its turn and ordinal, never prompt text. */
export function inputOccurrenceIdentity(turnId: string, occurrence: number): string {
  return digest("pi-input-occurrence", `${turnId}|${occurrence}`);
}

export function detectInput(
  text: string,
  sessionId: string,
  turnId: string,
  inventory: Inventory,
  occurrence = 0,
): TelemetryEvent[] {
  const trimmed = text.trim();
  const occurrenceIdentity = inputOccurrenceIdentity(turnId, occurrence);
  const slash = /^\/([^\s]+)(?:\s|$)/.exec(trimmed);
  if (slash) {
    const rawName = slash[1];
    const explicitSkill = rawName.startsWith("skill:")
      ? safeIdentifier(rawName.slice("skill:".length))
      : undefined;
    const command = lookupSlashCommand(rawName, inventory);
    const skill = explicitSkill
      ? inventory.skillsByName.get(explicitSkill)
      : command?.source === "skill"
        ? inventory.skillsByName.get(command.name)
        : undefined;
    if (skill) {
      return [
        makeEvent(
          sessionId,
          turnId,
          occurrenceIdentity,
          skill.name,
          skill.source,
          explicitSkill ? "explicit-command" : "skill-command",
          "explicit-command",
          "observed",
          "loaded",
          "agent.skill.activation",
          skill.contentHash,
        ),
      ];
    }
    if (command?.source === "prompt") {
      return [
        makeEvent(
          sessionId,
          turnId,
          occurrenceIdentity,
          command.name,
          "prompt-command",
          "prompt-command",
          "prompt-expansion",
          "observed",
          "expanded",
          "agent.skill.activation",
        ),
      ];
    }
    const failedLookup = invokedSkillLookup(trimmed, inventory);
    const failure = inventory.provenanceFailures.find(
      (candidate) => candidate.skillLookup === failedLookup,
    );
    if (failure) {
      return [
        provenanceFailureEvent(sessionId, turnId, occurrenceIdentity, failure),
      ];
    }
    return [];
  }

  const normalized = trimmed.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  for (const skill of inventory.skillsByName.values()) {
    const spoken = skill.name.toLowerCase().replace(/[-_]+/g, " ");
    if (spoken.split(" ").length < 2) continue;
    if ([spoken, `run ${spoken}`, `use ${spoken}`].includes(normalized)) {
      return [
        makeEvent(
          sessionId,
          turnId,
          occurrenceIdentity,
          skill.name,
          skill.source,
          "natural-language",
          "natural-language-candidate",
          "candidate",
          "candidate",
          "agent.skill.candidate",
          skill.contentHash,
        ),
      ];
    }
  }
  return [];
}

export function detectCanonicalRead(
  inputPath: string,
  cwd: string,
  sessionId: string,
  turnId: string,
  toolCallId: string,
  inventory: Inventory,
): TelemetryEvent | undefined {
  let canonicalPath: string;
  try {
    canonicalPath = realpathSync(resolve(cwd, inputPath));
  } catch (error: unknown) {
    throw new ProvenanceError(provenanceStatus(error));
  }
  const skill = inventory.skillsByPath.get(canonicalPath);
  if (!skill) {
    const failure = inventory.failedSkillsByPath.get(canonicalPath);
    return failure
      ? provenanceFailureEvent(
          sessionId,
          turnId,
          digest("pi-tool-occurrence", toolCallId),
          failure,
        )
      : undefined;
  }
  return makeEvent(
    sessionId,
    turnId,
    digest("pi-tool-occurrence", toolCallId),
    skill.name,
    skill.source,
    "model-read",
    "canonical-file-read",
    "qualified",
    "loaded",
    "agent.skill.execution",
    skill.contentHash,
  );
}

const DIGEST = /^sha256:[a-f0-9]{64}$/;
const EVENT_NAME = /^agent\.(?:skill|runtime)\.[a-z][a-z0-9.-]{0,63}$/;
const TOKEN = /^[a-z][a-z0-9.-]{0,63}$/;
const ISO_DATE_TIME = /^(\d{4})-(\d{2})-(\d{2})T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d+)?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/;
const CONFIDENCE_LEVELS = new Set(["observed", "qualified", "candidate", "classified", "unknown"]);
const REQUIRED_RESTORED_DEDUPE_FIELDS = new Set([
  "schema_version", "event_name", "agent_system", "trigger", "evidence_type",
  "evidence_confidence", "status", "timestamp", "session_id", "turn_id",
  "activation_id", "skill_source",
]);
const RESTORED_DEDUPE_FIELDS = new Set([
  ...REQUIRED_RESTORED_DEDUPE_FIELDS,
  "skill_name", "skill_content_hash", "signal_name", "count",
]);

/**
 * Strict operational subset of persisted SkillEvent v1 records that Pi can use
 * safely for dedupe, occurrence recovery,.
 * Python SkillEvent/its JSON Schema remain the persistence authority: schema-valid
 * records without these Pi-specific IDs are retained by Python but ignored here.
 */
export interface RestoredDedupeCandidate extends TelemetryEvent {}

function safeRestoredIdentifier(value: unknown): value is string {
  return typeof value === "string" && safeIdentifier(value) === value && !/[|\u001f\r\n]/.test(value);
}

function safeRestoredToken(value: unknown): value is string {
  return typeof value === "string" && TOKEN.test(value) && !value.includes("..") &&
    !SECRET_LIKE.test(value) && !/[|\u001f\r\n]/.test(value);
}

function strictIsoDateTime(value: unknown): value is string {
  if (typeof value !== "string") return false;
  const match = ISO_DATE_TIME.exec(value);
  if (!match || Number.isNaN(Date.parse(value))) return false;
  const [year, month, day] = match.slice(1, 4).map(Number);
  const calendar = new Date(Date.UTC(year, month - 1, day));
  return calendar.getUTCFullYear() === year && calendar.getUTCMonth() === month - 1 &&
    calendar.getUTCDate() === day;
}

/**
 * Restored custom entries are untrusted Pi history. This is deliberately not a
 * second schema-v1 validator: it admits only RestoredDedupeCandidate records
 * whose additional IDs and source are needed for safe local state. All unsafe,
 * malformed, or non-operational history remains byte-for-byte untouched and
 * contributes no IDs.
 */
export function restoredDedupeCandidates(entries: SessionEntryLike[]): RestoredDedupeCandidate[] {
  const restored: RestoredDedupeCandidate[] = [];
  for (const entry of entries) {
    if (entry.type !== "custom" || entry.customType !== "skill-telemetry-v1") continue;
    if (typeof entry.data !== "object" || entry.data === null || Array.isArray(entry.data)) continue;
    const data = entry.data as Record<string, unknown>;
    if (
      Object.keys(data).some((field) => !RESTORED_DEDUPE_FIELDS.has(field)) ||
      [...REQUIRED_RESTORED_DEDUPE_FIELDS].some((field) => !Object.hasOwn(data, field)) ||
      data.schema_version !== 1 || data.agent_system !== "pi" ||
      typeof data.event_name !== "string" || !EVENT_NAME.test(data.event_name) ||
      data.event_name.includes("..") || SECRET_LIKE.test(data.event_name) ||
      !safeRestoredToken(data.trigger) || !safeRestoredToken(data.evidence_type) ||
      !safeRestoredToken(data.status) || !CONFIDENCE_LEVELS.has(data.evidence_confidence as string) ||
      !strictIsoDateTime(data.timestamp) ||
      !DIGEST.test(data.session_id as string) || !DIGEST.test(data.turn_id as string) ||
      !DIGEST.test(data.activation_id as string) || !safeRestoredIdentifier(data.skill_source) ||
      (Object.hasOwn(data, "skill_name") && !safeRestoredIdentifier(data.skill_name)) ||
      (Object.hasOwn(data, "skill_content_hash") && !DIGEST.test(data.skill_content_hash as string)) ||
      (Object.hasOwn(data, "signal_name") && !safeRestoredIdentifier(data.signal_name)) ||
      (Object.hasOwn(data, "count") && (typeof data.count !== "number" || !Number.isInteger(data.count) || data.count < 1 || data.count > 1_000_000))
    ) continue;
    restored.push(data as unknown as RestoredDedupeCandidate);
  }
  return restored;
}

export function restoredActivationIds(entries: SessionEntryLike[]): Set<string> {
  return new Set(restoredDedupeCandidates(entries).map((event) => event.activation_id));
}

function inputOccurrenceKey(turnId: string, event: TelemetryEvent): string {
  return [
    turnId, event.event_name, event.skill_name ?? "", event.skill_source,
    event.trigger, event.evidence_type, event.status,
  ].join("\u001f");
}

function activationForInputOccurrence(event: TelemetryEvent, occurrence: number): string {
  return digest("activation", [
    event.session_id,
    event.turn_id,
    inputOccurrenceIdentity(event.turn_id, occurrence),
    event.skill_name ?? "",
    event.trigger,
    event.evidence_type,
    event.status,
  ].join("|"));
}

export interface RestoredInputState {
  occurrences: Map<string, number>;
  activationIds: Set<string>;
}

/** Restore contiguous current-format input ordinals and their recognized IDs. */
export function restoredInputState(events: TelemetryEvent[]): RestoredInputState {
  const occurrences = new Map<string, number>();
  const activationIds = new Set<string>();
  for (const event of events) {
    const key = inputOccurrenceKey(event.turn_id, event);
    const ordinal = occurrences.get(key) ?? 0;
    if (event.activation_id === activationForInputOccurrence(event, ordinal)) {
      occurrences.set(key, ordinal + 1);
      activationIds.add(event.activation_id);
    }
  }
  return { occurrences, activationIds };
}

/** Restore contiguous current-format input ordinals per turn and semantic family. */
export function restoredInputOccurrences(events: TelemetryEvent[]): Map<string, number> {
  return restoredInputState(events).occurrences;
}

export function inputSemanticKey(turnId: string, event: TelemetryEvent): string {
  return inputOccurrenceKey(turnId, event);
}

