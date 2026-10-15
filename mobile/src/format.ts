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

/**
 * The letters on an avatar, as the web draws them (qvault/ui.py initials): the first letters of the
 * first and last words ("QA Brij" is QB, "Ada Byron Lovelace" AL), one for a one-word name, and
 * "?" for none. Two letters, so two people who share a first name aren't both "Q".
 */
export function initials(name: string): string {
  const words = name.split(/\s+/).filter(Boolean);
  if (words.length === 0) return '?';
  const ends = words.length > 1 ? [words[0]!, words[words.length - 1]!] : words;
  return ends.map((w) => w[0]!.toUpperCase()).join('');
}
