// The approve and reject sheets (phone-ux §6.8, §6.9): the last thing read before the key is used.
//
// They render ONLY the frozen snapshot (src/signingSheet.ts, I-6): a refetch that lands while a
// sheet is open never changes what it shows. Nothing here signs. The sign button reports the reason
// typed; the decision screen confirms the snapshot and calls flows.ts.
//
// Approve, block budget: title, what you sign, one consequence sentence, the button. The quiet code
// line sits above the button (the comparison block instead, for a web handoff), and a file the phone
// has not opened adds one line. Reject: title, the reason (required, chips above the field, never
// autofocused), what you're rejecting, the consequence, the button. No code in the reject sheet: a
// rejection authorises nothing to happen.
//
// The consequence and the code sit in the fixed footer, so a long decision scrolls under them and
// the person never signs without the consequence in view. At large text (1.6x and up) a footer that
// tall would leave no room for what is signed, so they close the scrolling body instead, in the
// same order (§6.8's screen-reader order: what you sign, consequence, code, button).

import { useEffect, useRef, useState } from 'react';
import { Linking, View } from 'react-native';

import {
  Button,
  Chip,
  CODE_ABOUT,
  CodeBlock,
  CodeLine,
  Field,
  InlineMessage,
  PaymentCard,
  Sheet,
  SignedText,
  Text,
  TextLink,
} from '../../ui/index.tsx';
import { makeStyles, useTheme } from '../../theme/index.ts';
import { REASON_MAX, type SigningProblem, type Snapshot } from '../../signingSheet.ts';

export function SigningSheet({
  snapshot,
  visible,
  busy,
  problem,
  reasonMissing,
  onConfirm,
  onCancel,
  onReasonChange,
  onOpenWeb,
  balanceWei,
  balanceText,
}: {
  /** Kept by the caller while the sheet animates out, so it never flashes to another state. */
  snapshot: Snapshot | null;
  visible: boolean;
  busy: boolean;
  /** An inline failure (§6.6): the sheet stays open so a retry is one tap. */
  problem: SigningProblem | null;
  /** The reason was empty on submit: said under the field, and no prompt was shown. */
  reasonMissing: boolean;
  onConfirm: (reason: string) => void;
  onCancel: () => void;
  onReasonChange: () => void;
  onOpenWeb: () => void;
  /** The treasury's balance now, for the card's "more than the treasury holds" line. Not signed, and
   * not part of the snapshot: a warning only, never a reason the sheet shows something else. */
  balanceWei?: string | null;
  balanceText?: string | null;
}) {
  const s = useStyles();
  const t = useTheme();
  const [reason, setReason] = useState('');
  const [about, setAbout] = useState(false);
  const [showAll, setShowAll] = useState(false);
  // The reject sheet's text, collapsed to three lines: "Show all" only when it is longer than that.
  // Measured from a hidden full-length copy (onLayout works everywhere; onTextLayout does not on the
  // web harness), so a short decision shows no control that does nothing.
  const [fullHeight, setFullHeight] = useState(0);
  const [clampedHeight, setClampedHeight] = useState(0);
  const opened = useRef<string | null>(null);

  // A new sheet starts empty: no reason, the text collapsed, the code page closed.
  const key = snapshot ? `${snapshot.kind}:${snapshot.uuid}:${snapshot.contentKey}` : null;
  useEffect(() => {
    if (visible && key !== opened.current) {
      opened.current = key;
      setReason('');
      setAbout(false);
      setShowAll(false);
      setFullHeight(0);
      setClampedHeight(0);
    }
    if (!visible) opened.current = null;
  }, [visible, key]);

  if (!snapshot) return null;
  const m = snapshot.model;
  const action = snapshot.detail.signing_inputs.action;
  const approve = snapshot.kind === 'approve';

  if (about) {
    return (
      <Sheet visible={visible} onClose={onCancel} dismissible={!busy} title="About the decision code" onBack={() => setAbout(false)}>
        <Text role="body">{CODE_ABOUT}</Text>
      </Sheet>
    );
  }

  const what = action ? (
    // The recipient in full, never collapsed, in a signing sheet (§1.4 rule 8).
    <PaymentCard
      action={action}
      place="sheet"
      sentence={m.signedText}
      balanceWei={approve ? balanceWei : null}
      balanceText={approve ? balanceText : null}
    />
  ) : approve ? (
    <SignedText text={m.signedText} size="decision" />
  ) : (
    <View style={s.collapsible}>
      <View style={s.measured}>
        <View onLayout={(e) => setClampedHeight(e.nativeEvent.layout.height)}>
          <SignedText text={m.signedText} size="decision" numberOfLines={showAll ? undefined : 3} />
        </View>
        <View
          style={s.ghost}
          pointerEvents="none"
          accessibilityElementsHidden
          importantForAccessibility="no-hide-descendants"
          aria-hidden
          onLayout={(e) => setFullHeight(e.nativeEvent.layout.height)}
        >
          <SignedText text={m.signedText} size="decision" />
        </View>
      </View>
      {showAll || fullHeight > clampedHeight + 1 ? (
        <TextLink label={showAll ? 'Show less' : 'Show all'} onPress={() => setShowAll((v) => !v)} />
      ) : null}
    </View>
  );

  const consequence = (
    <>
      <Text role="body">{m.consequence}</Text>
      {m.code ? (
        m.code.form === 'block' ? (
          <CodeBlock code={m.code.value} />
        ) : (
          <CodeLine code={m.code.value} onAbout={() => setAbout(true)} />
        )
      ) : null}
    </>
  );
  const inBody = t.stacked;

  return (
    <Sheet
      visible={visible}
      onClose={onCancel}
      dismissible={!busy}
      title={m.title}
      footer={
        <>
          {inBody ? null : consequence}
          {problem?.text ? (
            <View style={s.problem}>
              <InlineMessage tone={problem.tone} text={problem.text} />
              {problem.action === 'settings' ? (
                <TextLink label="Open settings" onPress={() => void Linking.openSettings().catch(() => {})} />
              ) : null}
            </View>
          ) : null}
          <Button
            label={m.button}
            variant={approve ? 'primary' : 'danger'}
            onPress={() => onConfirm(reason)}
            busy={busy}
            full
          />
          <Button label="Cancel" variant="quiet" onPress={onCancel} disabled={busy} full />
        </>
      }
    >
      {approve ? null : (
        <View>
          <View style={s.chips} accessibilityLabel="Quick reasons">
            {m.chips.map((chip) => (
              <Chip
                key={chip}
                label={chip}
                selected={reason === chip}
                disabled={busy}
                onPress={() => {
                  setReason(chip);
                  onReasonChange();
                }}
              />
            ))}
          </View>
          <Field
            label="Reason"
            caption={m.reasonCaption}
            error={reasonMissing ? m.reasonMissing : null}
            count={`${Array.from(reason).length} / ${REASON_MAX}`}
            value={reason}
            onChangeText={(v: string) => {
              setReason(v);
              onReasonChange();
            }}
            maxLength={REASON_MAX}
            editable={!busy}
            multiline
          />
        </View>
      )}
      {what}
      {m.attachment ? (
        <View style={s.attachment}>
          <InlineMessage tone="warning" text="This includes a file you haven't opened. Read it before approving." />
          <TextLink label="Read it on the web" onPress={onOpenWeb} />
        </View>
      ) : null}
      {inBody ? consequence : null}
    </Sheet>
  );
}

const useStyles = makeStyles((t) => ({
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: t.space[8], marginBottom: t.space[16] },
  collapsible: { gap: t.space[4], alignItems: 'flex-start' },
  measured: { alignSelf: 'stretch' },
  // Same width as the shown copy, out of the flow and invisible: only its height is read.
  ghost: { position: 'absolute', left: 0, right: 0, top: 0, opacity: 0 },
  attachment: { gap: t.space[4], alignItems: 'flex-start' },
  problem: { gap: t.space[4], alignItems: 'flex-start' },
}));
