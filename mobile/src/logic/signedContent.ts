// Signed content never changes under the reader (phone-ux I-16, §2.6).
//
// A decision's signed content is fixed when it is raised, so two fetches of the same decision in
// one run of the app must carry the same `signing_inputs` and derive the same payload hash. If a
// later fetch differs, the server (or something between) changed what the person is reading while
// they read it: the decision is shown as tampered ("The text changed while you were reading it"),
// never quietly re-rendered, and an open signing sheet closes before any prompt.
//
// The memory is per process and sticky: once a decision has changed, it stays changed for the run,
// even if a third fetch brings the first version back.
//
// No React Native import: tools/signing_probe.ts runs it under Node.

/** Object keys sorted at every depth, so two equal values always serialise the same. */
function stable(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stable).join(',')}]`;
  if (value !== null && typeof value === 'object') {
    const entries = Object.keys(value as Record<string, unknown>)
      .sort()
      .map((k) => `${JSON.stringify(k)}:${stable((value as Record<string, unknown>)[k])}`);
    return `{${entries.join(',')}}`;
  }
  return JSON.stringify(value) ?? 'undefined';
}

/** The content a fetch commits to: the signed inputs and the hash this phone derived from them. */
export function signedContentKey(signingInputs: unknown, derivedHash: string): string {
  return `${derivedHash}|${stable(signingInputs)}`;
}

/** True when a later fetch's signed content differs from an earlier one's. */
export function detectSignedContentChange(earlier: string | null | undefined, later: string): boolean {
  return earlier !== null && earlier !== undefined && earlier !== later;
}

export type Seen = 'first' | 'same' | 'changed';

/** What this run has seen of each decision's signed content. */
export class SignedContentMemory {
  private readonly first = new Map<string, string>();
  private readonly changed = new Set<string>();

  see(uuid: string, key: string): Seen {
    if (this.changed.has(uuid)) return 'changed';
    const earlier = this.first.get(uuid);
    if (earlier === undefined) {
      this.first.set(uuid, key);
      return 'first';
    }
    if (detectSignedContentChange(earlier, key)) {
      this.changed.add(uuid);
      return 'changed';
    }
    return 'same';
  }

  hasChanged(uuid: string): boolean {
    return this.changed.has(uuid);
  }

  /** A different person enrolled, or this phone was removed: nothing from before applies. */
  clear(): void {
    this.first.clear();
    this.changed.clear();
  }
}
