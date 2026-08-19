import type {
  ExtensionAPI,
  ExtensionContext,
  Skill,
  SlashCommandInfo,
} from "@earendil-works/pi-coding-agent";

import {
  buildInventory,
  detectCanonicalRead,
  detectInput,
  digest,
  inputOccurrenceIdentity,
  inputSemanticKey,
  invokedSkillLookup,
  restoredDedupeCandidates,
  restoredInputState,
  ProvenanceError,
  provenanceFailureEvent,
  turnIdFromEntries,
  type Inventory,
  type ProvenanceFailure,
  type TelemetryEvent,
} from "./matching.ts";

export default function skillTelemetry(pi: ExtensionAPI): void {
  let inventory: Inventory = buildInventory([]);
  let seen = new Set<string>();
  let inputOccurrences = new Map<string, number>();
  let lastInput:
    | { turn: string; text: string; occurrenceKey: string; occurrence: number }
    | undefined;
  let activeTurn: { session: string; turn: string } | undefined;
  let activeInvocation:
    | { skillLookup: string; inputText: string }
    | undefined;
  let appendFailureReported = false;
  let provenanceFailureReported = false;

  const sessionId = (rawSessionId: string): string => digest("pi-session", rawSessionId);

  const notifyWarning = (ctx: ExtensionContext, message: string): void => {
    ctx.ui.notify(message, "warning");
  };

  type EmitOutcome = "appended" | "current-seen" | "failed";

  const emit = (
    event: TelemetryEvent,
    ctx: ExtensionContext,
  ): EmitOutcome => {
    if (seen.has(event.activation_id)) return "current-seen";
    try {
      pi.appendEntry("skill-telemetry-v1", event);
      seen.add(event.activation_id);
      return "appended";
    } catch (error: unknown) {
      if (!(error instanceof Error)) throw error;
      if (!appendFailureReported) {
        notifyWarning(
          ctx,
          "Skill telemetry could not append its private session entry; agent usage continues.",
        );
        appendFailureReported = true;
      }
      return "failed";
    }
  };

  const reportProvenanceFailure = (
    event: TelemetryEvent,
    ctx: ExtensionContext,
  ): EmitOutcome => {
    const result = emit(event, ctx);
    if (provenanceFailureReported) return result;
    notifyWarning(
      ctx,
      "Skill telemetry could not verify one or more provenance records; no activation was inferred and no path content was recorded.",
    );
    provenanceFailureReported = true;
    return result;
  };

  const privateContext = (ctx: ExtensionContext): { session: string; turn: string } => {
    const session = sessionId(ctx.sessionManager.getSessionId());
    return {
      session,
      turn: turnIdFromEntries(session, ctx.sessionManager.getBranch()),
    };
  };

  const currentTurn = (ctx: ExtensionContext): { session: string; turn: string } => {
    const currentSession = sessionId(ctx.sessionManager.getSessionId());
    if (activeTurn?.session === currentSession) return activeTurn;
    return privateContext(ctx);
  };

  const refreshInventory = (
    commands: SlashCommandInfo[],
    skills: Skill[] = [],
  ): void => {
    inventory = buildInventory(commands, skills);
  };

  const reportInvokedProvenanceFailure = (ctx: ExtensionContext): void => {
    if (!activeInvocation) return;
    const failure = inventory.provenanceFailures.find(
      (candidate) => candidate.skillLookup === activeInvocation?.skillLookup,
    );
    if (!failure) return;
    const { session, turn } = currentTurn(ctx);
    // The concrete failure is available only after before_agent_start refreshes
    // inventory. Derive its semantic key now, rather than persisting an
    // unreconstructable invocation placeholder, so resume restores this ordinal.
    const template = provenanceFailureEvent(
      session,
      turn,
      inputOccurrenceIdentity(turn, 0),
      failure,
    );
    const occurrenceKey = inputSemanticKey(turn, template);
    const previousInput = lastInput;
    const replay = previousInput?.turn === turn &&
      previousInput.occurrenceKey === occurrenceKey &&
      previousInput.text === activeInvocation.inputText;
    const occurrence = replay && previousInput
      ? previousInput.occurrence
      : inputOccurrences.get(occurrenceKey) ?? 0;
    if (!replay) {
      lastInput = {
        turn,
        text: activeInvocation.inputText,
        occurrenceKey,
        occurrence,
      };
    }
    const outcome = reportProvenanceFailure(
      provenanceFailureEvent(session, turn, inputOccurrenceIdentity(turn, occurrence), failure),
      ctx,
    );
    if (outcome === "appended") {
      inputOccurrences.set(
        occurrenceKey,
        Math.max(inputOccurrences.get(occurrenceKey) ?? 0, occurrence + 1),
      );
    }
  };

  pi.on("session_start", (_event, ctx) => {
    const { session, turn } = privateContext(ctx);
    const preserveReplay = activeTurn?.session === session && activeTurn.turn === turn;
    const restored = restoredDedupeCandidates(ctx.sessionManager.getBranch());
    const restoredInputs = restoredInputState(restored);
    seen = new Set(restored.map((event) => event.activation_id));
    inputOccurrences = restoredInputs.occurrences;
    if (!preserveReplay) lastInput = undefined;
    activeTurn = undefined;
    activeInvocation = undefined;
    appendFailureReported = false;
    provenanceFailureReported = false;
    refreshInventory(pi.getCommands());
  });

  pi.on("input", (event, ctx) => {
    if (event.source === "extension") return;
    activeTurn = privateContext(ctx);
    const { session, turn } = activeTurn;
    refreshInventory(pi.getCommands());
    const skillLookup = invokedSkillLookup(event.text, inventory);
    const detectedEvents = detectInput(event.text, session, turn, inventory);
    const occurrenceKey = detectedEvents.length > 0
      ? inputSemanticKey(turn, detectedEvents[0])
      : undefined;
    // Pi's input event has no delivery ID.  A byte-for-byte transient replay in
    // an unchanged logical turn is therefore the same delivery; distinct text
    // uses the next content-free ordinal.  Raw text never reaches a digest or
    // persisted value.
    const previousInput = lastInput;
    const replay = occurrenceKey !== undefined && previousInput?.turn === turn &&
      previousInput.occurrenceKey === occurrenceKey &&
      previousInput.text === event.text;
    const occurrence = occurrenceKey !== undefined && replay && previousInput
      ? previousInput.occurrence
      : occurrenceKey === undefined
        ? 0
        : inputOccurrences.get(occurrenceKey) ?? 0;
    if (occurrenceKey !== undefined && !replay) {
      lastInput = { turn, text: event.text, occurrenceKey, occurrence };
    }
    activeInvocation = skillLookup
      ? { skillLookup, inputText: event.text }
      : undefined;
    for (const detected of detectInput(event.text, session, turn, inventory, occurrence)) {
      const outcome = detected.event_name === "agent.skill.failure"
        ? reportProvenanceFailure(detected, ctx)
        : emit(detected, ctx);
      // A current-format ordinal becomes unavailable only after appendEntry()
      // succeeds. Failed writes leave it
      // available for a successor or retry, while current-seen is an ordinary
      // replay of an already persisted ordinal.
      if (occurrenceKey !== undefined && outcome === "appended") {
        inputOccurrences.set(
          occurrenceKey,
          Math.max(inputOccurrences.get(occurrenceKey) ?? 0, occurrence + 1),
        );
      }
    }
  });

  pi.on("before_agent_start", (event, ctx) => {
    refreshInventory(pi.getCommands(), event.systemPromptOptions.skills ?? []);
    reportInvokedProvenanceFailure(ctx);
  });

  pi.on("tool_call", (event, ctx) => {
    if (event.toolName !== "read" || typeof event.input.path !== "string") return;
    const { session, turn } = currentTurn(ctx);
    try {
      const detected = detectCanonicalRead(
        event.input.path,
        ctx.cwd,
        session,
        turn,
        event.toolCallId,
        inventory,
      );
      if (detected?.event_name === "agent.skill.failure") {
        reportProvenanceFailure(detected, ctx);
      } else if (detected) {
        emit(detected, ctx);
      }
    } catch (error: unknown) {
      if (!(error instanceof ProvenanceError)) throw error;
      const failure: ProvenanceFailure = {
        operation: "canonical-read",
        status: error.status,
        source: "pi-provenance",
      };
      reportProvenanceFailure(
        provenanceFailureEvent(
          session,
          turn,
          digest("pi-tool-occurrence", event.toolCallId),
          failure,
        ),
        ctx,
      );
    }
  });
}
