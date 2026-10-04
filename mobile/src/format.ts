// Shortening a value for display without hiding it.

/**
 * "0xD491…f3D0": both ends of a long identifier, with the middle left out.
 *
 * The ends are what a person compares against another screen, so both survive; the middle is what
 * nobody reads. A value that shortening would not make shorter comes back whole. Wherever this is
 * shown, the whole value stays one tap away (`Identifier` in ui/index.tsx).
 */
export function middleOut(value: string, head = 6, tail = 4): string {
  if (value.length <= head + tail + 1) return value;
  return `${value.slice(0, head)}…${value.slice(-tail)}`;
}
