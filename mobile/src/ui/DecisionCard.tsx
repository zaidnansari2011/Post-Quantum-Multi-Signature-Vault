// A decision, as it appears in a list.
//
// The old row carried a title, a vault name, and three chips: "2/3 approved", "1 rejected" and the
// status word. Three chips is a row that has given up deciding what matters -- and none of the
// three answered the question someone scanning a queue is actually asking, which is "how long have
// I got, and how close is this to done".
//
// What is here now, in reading order:
//
//   1. The quorum, as marks, and the deadline. Both are state, both are scannable without reading.
//   2. The decision itself, set in the serif, given the most room. It is the only thing on the
//      card a person has to actually read.
//   3. The vault, quiet, at the bottom -- context for the decision, not a headline.
//
// The status word is gone from the open-queue case entirely: every decision in that queue is open,
// so printing "open" on each one is a column of the same word. It returns only in history, where
// the outcome is the point.

import { StyleSheet, Text, View } from 'react-native';

import { Card, Row, Seal } from './index.tsx';
import { color, space, statusTone, type } from '../theme.ts';
import { expiryPhrase, urgencyOf, whenPhrase } from '../time.ts';
import type { ProposalSummary } from '../api/schemas.ts';

export function DecisionCard({
  proposal,
  onPress,
  showOutcome = false,
}: {
  proposal: ProposalSummary;
  onPress: () => void;
  /** History mode: lead with what was decided rather than with what is still needed. */
  showOutcome?: boolean;
}) {
  const urgency = urgencyOf(proposal.expires_at);
  const expiry = expiryPhrase(proposal.expires_at);
  const complete = proposal.approvals >= proposal.required_m;

  return (
    <Card onPress={onPress} accessibilityLabel={proposal.title}>
      <Row style={{ justifyContent: 'space-between' }} gap={space.md}>
        <Seal filled={proposal.approvals} required={proposal.required_m} />
        {showOutcome ? (
          <Text style={[s.outcome, { color: outcomeColor(proposal.status) }]}>
            {outcomeWord(proposal.status)}
          </Text>
        ) : expiry ? (
          <Text style={[s.expiry, { color: expiryColor(urgency) }]}>{expiry}</Text>
        ) : null}
      </Row>

      <Text style={s.title} numberOfLines={3}>
        {proposal.title}
      </Text>

      <Row style={{ justifyContent: 'space-between' }} gap={space.sm}>
        <Text style={s.vault} numberOfLines={1}>
          {proposal.vault_name ?? `Vault ${proposal.vault_id}`}
        </Text>
        {showOutcome ? (
          <Text style={s.when}>{whenPhrase(proposal.expires_at)}</Text>
        ) : proposal.rejections > 0 ? (
          <Text style={s.rejected}>
            {proposal.rejections} rejected
          </Text>
        ) : complete ? (
          <Text style={s.readyText}>Threshold met</Text>
        ) : null}
      </Row>
    </Card>
  );
}

function expiryColor(urgency: ReturnType<typeof urgencyOf>): string {
  // Only a real deadline earns a colour. A decision with four days left is not a warning, and
  // tinting it would spend the attention the six-hour case needs.
  switch (urgency) {
    case 'expired':
    case 'critical':
      return color.broken;
    case 'soon':
      return color.waiting;
    default:
      return color.ink3;
  }
}

function outcomeColor(status: string): string {
  const t = statusTone(status);
  return t === 'sealed' ? color.sealed : t === 'broken' ? color.broken : color.ink3;
}

function outcomeWord(status: string): string {
  switch (status) {
    case 'approved':
      return 'Approved';
    case 'rejected':
      return 'Rejected';
    case 'expired':
      return 'Expired';
    case 'open':
      return 'Open';
    default:
      return status;
  }
}

const s = StyleSheet.create({
  title: { ...type.decisionSm },
  vault: { ...type.meta, flex: 1 },
  when: { ...type.meta },
  expiry: { ...type.micro, fontSize: 12.5 },
  outcome: { ...type.micro, fontSize: 12.5 },
  rejected: { ...type.micro, color: color.broken },
  readyText: { ...type.micro, color: color.sealed },
});
