// A payment, Apple Pay style: the amount, then the recipient on its network (phone-ux §5.12).
//
// Read ONLY from `signing_inputs.action` (I-2), which `verifyProposalIntegrity`'s payment_text
// check has proven equal to the signed sentence: that proof is why the card can stand in for the
// sentence, with the sentence itself one tap away. Names never lead the address: a server-held
// label is unsigned, and a compromised server could call an attacker's address "Hassan".
//
// On a page the recipient is shortened in the middle with "Show full"; in a signing sheet it is
// always whole, grouped in fours with its ends emphasised (§1.4 rule 8).

import { useState } from 'react';
import { View } from 'react-native';

import { NETWORKS, formatEth, type PaymentAction } from '../crypto/signing.ts';
import { makeStyles, useTheme } from '../theme/index.ts';
import { Icon } from './Icon.tsx';
import { Identifier } from './Identifier.tsx';
import { SignedText } from './SignedText.tsx';
import { Text } from './Text.tsx';
import { Touchable } from './Touchable.tsx';

export function PaymentCard({
  action,
  sentence,
  place = 'page',
  balanceWei,
  balanceText,
}: {
  action: PaymentAction;
  /** The verbatim signed sentence (`signing_inputs.action_text`), behind "Show the signed sentence". */
  sentence?: string;
  /** 'sheet' shows the recipient in full, always (§1.4 rule 8). */
  place?: 'page' | 'sheet';
  /** Open decisions only: the treasury's balance, for the "more than it holds" line. */
  balanceWei?: string | null;
  balanceText?: string | null;
}) {
  const t = useTheme();
  const s = useStyles();
  const [open, setOpen] = useState(false);
  const amount = formatEth(action.value_wei);
  const network = NETWORKS[action.chain_id] ?? `chain ${action.chain_id}`;
  const short =
    balanceWei != null && /^\d+$/.test(balanceWei) && BigInt(action.value_wei) > BigInt(balanceWei);

  return (
    <View>
      <View style={s.card}>
        <Text role="figure" tabular selectable accessibilityLabel={amount.replace(/ETH$/, 'ether')}>
          {amount}
        </Text>
        {place === 'sheet' ? (
          <View style={s.to}>
            <Text role="body" tone="muted">
              to
            </Text>
            <Identifier label="Recipient address" value={action.to} expanded="always" showLabel={false} />
            <Text role="body" tone="muted">{`on ${network}`}</Text>
          </View>
        ) : (
          <View style={s.toRow}>
            <Text role="body" tone="muted" style={s.toWord}>
              to
            </Text>
            <View style={s.flex}>
              <Identifier label="Recipient address" value={action.to} showLabel={false} />
            </View>
          </View>
        )}
        {place === 'page' ? (
          <Text role="body" tone="muted">{`on ${network}`}</Text>
        ) : null}
        {short ? (
          <View style={s.warn}>
            <Icon name="warning" size={16} color={t.color.status.warning.fg} />
            <Text role="caption" tone="warning" style={s.flex}>
              {`More than the treasury holds${balanceText ? ` (${balanceText})` : ''}. It can be approved, but it won't be paid until the treasury is topped up.`}
            </Text>
          </View>
        ) : null}
      </View>
      {sentence ? (
        <>
          <Touchable
            onPress={() => setOpen((v) => !v)}
            accessibilityRole="button"
            accessibilityState={{ expanded: open }}
            accessibilityLabel={open ? 'Hide the signed sentence' : 'Show the signed sentence'}
            ringRadius={8}
            style={({ pressed }) => [s.disclosure, pressed && s.pressed]}
          >
            <Text role="body" tone="link" style={s.flex}>
              {open ? 'Hide the signed sentence' : 'Show the signed sentence'}
            </Text>
            <Icon name={open ? 'chevron-down' : 'chevron-right'} size={16} color={t.color.link} />
          </Touchable>
          {open ? <SignedText text={sentence} size="decision" /> : null}
        </>
      ) : null}
    </View>
  );
}

const useStyles = makeStyles((t) => ({
  flex: { flex: 1 },
  card: {
    backgroundColor: t.color.surface,
    borderWidth: 1,
    borderColor: t.color.border,
    borderRadius: t.radius.card,
    padding: t.space[16],
    gap: t.space[8],
  },
  to: { gap: t.space[4] },
  toRow: { flexDirection: 'row', alignItems: 'flex-start', gap: t.space[8] },
  toWord: { paddingTop: t.space[12] - 2 },
  warn: { flexDirection: 'row', gap: t.space[8], alignItems: 'flex-start', marginTop: t.space[4] },
  disclosure: {
    minHeight: 44,
    flexDirection: 'row',
    alignItems: 'center',
    gap: t.space[8],
    borderRadius: 8,
    marginTop: t.space[4],
  },
  pressed: { backgroundColor: t.color.fill },
}));
