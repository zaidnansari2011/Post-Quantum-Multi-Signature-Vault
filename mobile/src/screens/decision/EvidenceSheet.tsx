// "Checked on this phone" (phone-ux §6.7): the evidence layers 2 and 3, one tap from the page.
//
// Checks are plain sentences, each with its icon: success for what held, critical for what failed,
// neutral for what is not checked on this phone. A check that did not run is never shown as passed.
// Hashes are the raw values, each copyable and expandable; on a decision that failed its check
// they are only the values that differ, the one this phone derived first.

import { useState } from 'react';
import { Linking, View } from 'react-native';

import {
  Button,
  CODE_ABOUT,
  CodeLine,
  Icon,
  IconButton,
  Identifier,
  KeyValue,
  Segmented,
  Sheet,
  Text,
  TextLink,
} from '../../ui/index.tsx';
import { getApiBaseUrl } from '../../config.ts';
import { copyText } from '../../native/clipboard.ts';
import { makeStyles, useTheme } from '../../theme/index.ts';
import type { ProposalDetail } from '../../api/schemas.ts';
import type { Checked } from '../../checks.ts';
import { paymentText } from '../../crypto/signing.ts';
import type { StoredIdentity } from '../../custody.ts';
import { evidenceChecks, fingerprintGroups, stampWithZone, type CheckLine } from '../../logic/evidence.ts';
import type { Seat } from '../../logic/personalStatus.ts';

export type EvidenceTab = 'checks' | 'hashes';

export function EvidenceSheet({
  visible,
  onClose,
  tab,
  onTab,
  detail,
  checked,
  code,
  identity,
  seat,
  open,
  onReport,
}: {
  visible: boolean;
  onClose: () => void;
  tab: EvidenceTab;
  onTab: (tab: EvidenceTab) => void;
  detail: ProposalDetail;
  checked: Checked;
  /** The decision code from the hash this phone derived; null when it derived none that held. */
  code: string | null;
  identity: StoredIdentity;
  seat: Seat | null;
  open: boolean;
  onReport: () => void;
}) {
  const s = useStyles();
  const [about, setAbout] = useState(false);
  const policy = detail.signing_inputs.policy;
  const lines = evidenceChecks({
    failed: checked.ok ? null : checked.reason,
    isPayment: detail.signing_inputs.action !== undefined,
    M: policy.M,
    N: policy.N,
    seat,
    open,
  });

  const close = () => {
    setAbout(false);
    onClose();
  };

  return (
    <Sheet
      visible={visible}
      onClose={close}
      title={about ? 'About the decision code' : 'Checked on this phone'}
      onBack={about ? () => setAbout(false) : undefined}
      footer={about ? undefined : <Button label="Report a problem" variant="secondary" onPress={onReport} full />}
    >
      {about ? (
        <Text role="body">{CODE_ABOUT}</Text>
      ) : (
        <>
          <Segmented
            label="What was checked"
            value={tab}
            onChange={onTab}
            options={[
              { value: 'checks', label: 'Checks' },
              { value: 'hashes', label: 'Hashes' },
            ]}
          />
          {tab === 'checks' ? (
            <View style={s.checks}>
              {lines.map((line) => (
                <CheckRow key={line.key} line={line} />
              ))}
              <View style={s.footer}>
                <Text role="caption" tone="muted">
                  {'Your key: '}
                  <Text role="code" tone="muted">
                    {fingerprintGroups(identity.fingerprint)}
                  </Text>
                  {', on this phone.'}
                </Text>
                {code ? (
                  <View style={s.codeRow}>
                    <CodeLine code={code} onAbout={() => setAbout(true)} />
                    <IconButton
                      icon="copy"
                      label="Copy the decision code"
                      onPress={() => void copyText(code)}
                      size={18}
                    />
                  </View>
                ) : null}
              </View>
            </View>
          ) : checked.ok ? (
            <Hashes detail={detail} hash={checked.hash} identity={identity} />
          ) : (
            <Differences detail={detail} checked={checked} />
          )}
        </>
      )}
    </Sheet>
  );
}

function CheckRow({ line }: { line: CheckLine }) {
  const open = () => void Linking.openURL(`${getApiBaseUrl()}/ledger/transparency`).catch(() => {});
  const t = useTheme();
  const s = useStyles();
  const icon = line.tone === 'success' ? 'check-circle' : line.tone === 'critical' ? 'alert' : 'info';
  const color =
    line.tone === 'success'
      ? t.color.status.success.fg
      : line.tone === 'critical'
        ? t.color.status.critical.fg
        : t.color.textMuted;
  const spoken = line.tone === 'success' ? 'Passed' : line.tone === 'critical' ? 'Failed' : 'Not checked here';
  return (
    <View style={s.check}>
      <Icon name={icon} size={20} color={color} style={s.checkIcon} />
      <View style={[s.flex, s.checkBody]}>
        <Text role="body" accessibilityLabel={`${spoken}. ${line.text}`}>
          {line.text}
        </Text>
        {line.link ? <TextLink label={line.link.label} onPress={open} accessibilityLabel="Open the transparency log on the web" /> : null}
      </View>
    </View>
  );
}

/** Layer 3, when every check held: the values themselves. */
function Hashes({ detail, hash, identity }: { detail: ProposalDetail; hash: string; identity: StoredIdentity }) {
  const s = useStyles();
  const inputs = detail.signing_inputs;
  const action = inputs.action;
  const payout = detail.payout;
  const raised = stampWithZone(inputs.created_at);
  const due = stampWithZone(detail.expires_at);
  return (
    <View style={s.hashes}>
      <Identifier label="Payload hash, worked out on this phone" value={hash} />
      <Identifier label="Nonce" value={inputs.nonce} />
      {inputs.file_sha256 ? <Identifier label="Attached file SHA-256" value={inputs.file_sha256} /> : null}
      <KeyValue label="Algorithm" value={identity.algId} />
      <Identifier label="This phone's key" value={identity.fingerprint} />
      {action ? <Identifier label="Treasury" value={action.treasury} /> : null}
      {detail.execution?.digest ? <Identifier label="Treasury digest" value={detail.execution.digest} /> : null}
      {payout?.tx_hash ? <Identifier label="Transaction" value={payout.tx_hash} /> : null}
      {payout?.block_number != null ? (
        <KeyValue label="Block" value={payout.block_number.toLocaleString('en-GB')} />
      ) : null}
      {payout?.gas_used != null ? <KeyValue label="Gas" value={payout.gas_used.toLocaleString('en-GB')} /> : null}
      {detail.votes.length > 0 ? (
        <KeyValue label="Signatures">
          {detail.votes.map((v, i) => (
            <Text key={`${v.signer_id}-${i}`} role="body">
              {`${v.signer_name ?? 'Someone'}, ${v.custody === 'device' ? 'phone key' : 'password key on the server'}`}
            </Text>
          ))}
        </KeyValue>
      ) : null}
      {payout?.reason ? <KeyValue label="Payout reason, as the server gave it" value={payout.reason} /> : null}
      {raised ? <KeyValue label="Raised" value={raised} /> : null}
      {due ? <KeyValue label="Due" value={due} /> : null}
    </View>
  );
}

/** Layer 3 on a decision that failed: only what differs, this phone's value first. */
function Differences({ detail, checked }: { detail: ProposalDetail; checked: Extract<Checked, { ok: false }> }) {
  const s = useStyles();
  const inputs = detail.signing_inputs;
  switch (checked.reason) {
    case 'display_policy':
      return (
        <View style={s.hashes}>
          <KeyValue label="Rule that would be signed" value={`${inputs.policy.M} of ${inputs.policy.N}`} tone="critical" />
          <KeyValue label="Rule sent to show you" value={`${detail.required_m} of ${detail.required_n}`} />
        </View>
      );
    case 'display_text':
      return (
        <View style={s.hashes}>
          <KeyValue label="Text that would be signed" value={inputs.action_text} tone="critical" />
          <KeyValue label="Text sent to show you" value={detail.action_text} />
        </View>
      );
    case 'payment_text':
      return (
        <View style={s.hashes}>
          <KeyValue
            label="What the payment says, worked out on this phone"
            value={inputs.action ? paymentText(inputs.action) : null}
            tone="critical"
          />
          <KeyValue label="Wording sent with it" value={inputs.action_text} />
        </View>
      );
    default:
      return (
        <View style={s.hashes}>
          <Identifier label="Worked out on this phone" value={checked.actual} />
          <Identifier label="Stated by the server" value={checked.expected} />
        </View>
      );
  }
}

const useStyles = makeStyles((t) => ({
  flex: { flex: 1 },
  checks: { gap: t.space[12] },
  check: { flexDirection: 'row', gap: t.space[12], alignItems: 'flex-start' },
  checkIcon: { marginTop: 2 },
  checkBody: { gap: t.space[4], alignItems: 'flex-start' },
  footer: {
    gap: t.space[4],
    marginTop: t.space[8],
    paddingTop: t.space[12],
    borderTopWidth: 1,
    borderTopColor: t.color.border,
  },
  codeRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  hashes: { gap: t.space[8] },
}));
