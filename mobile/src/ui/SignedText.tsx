// The text a person signs, in the serif (phone-ux §1.4 rule 7, §6.5).
//
// Serif means "this is what you sign" and nothing else uses it. Up to 180 characters it is the
// page's lead (decisionHero, 22/30); longer, or at 1.3x text and above, it steps down to decision
// (18/28) so a long decision does not fill the screen twice over. Ethereum addresses inside it are
// set in mono, wrapping in groups of four: a display treatment of the same characters, never a
// summary of them.

import { useTheme } from '../theme/index.ts';
import { GroupedValue } from './Identifier.tsx';
import { Text } from './Text.tsx';

const ADDRESS = /(0x[0-9a-fA-F]{40})/g;
const LONG = 180;

export function SignedText({
  text,
  size = 'auto',
  tone = 'text',
}: {
  text: string;
  /** 'auto' picks hero or reading size by length and font scale; sheets always use 'decision'. */
  size?: 'auto' | 'decision';
  tone?: 'text' | 'muted';
}) {
  const t = useTheme();
  const hero = size === 'auto' && text.length <= LONG && t.fontScale < t.breakpoints.decisionStepDown;
  const parts = text.split(ADDRESS);
  return (
    <Text role={hero ? 'decisionHero' : 'decision'} tone={tone} selectable>
      {parts.map((part, i) =>
        i % 2 === 1 ? (
          <GroupedValue key={i} value={part} emphasiseEnds={false} />
        ) : (
          part
        ),
      )}
    </Text>
  );
}
