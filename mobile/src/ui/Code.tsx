// The decision code (phone-ux §5.11): a quiet line by default, a comparison block for a web handoff.
//
// The value is `decisionCode()` of the hash THIS PHONE derived. The phone is the main surface, so
// most approvals have no web page open beside them: telling every signer to "check this matches
// the web" would be noise. The block appears only when the decision was opened from the web's
// "Approve on your phone" link, when the web dialog is known to be open.
//
// It is a consistency check, never described as a proof (I-11).

import { Share, View } from 'react-native';

import { spokenCode } from '../logic/decisionCode.ts';
import { makeStyles, scaleCap } from '../theme/index.ts';
import { IconButton } from './Button.tsx';
import { Text } from './Text.tsx';

/** "Code A397-71F8", with the info button that explains it. */
export function CodeLine({ code, onAbout }: { code: string; onAbout: () => void }) {
  const s = useStyles();
  return (
    <View style={s.line}>
      <Text role="caption" tone="muted" accessibilityLabel={`Decision code: ${spokenCode(code)}`}>
        {'Code '}
        <Text role="code" tone="muted" maxScale={scaleCap.badge}>
          {code}
        </Text>
      </Text>
      <IconButton icon="info" label="About the decision code" onPress={onAbout} size={18} />
    </View>
  );
}

/** What the info button opens. Its copy is the copy deck's `code.about`. */
export const CODE_ABOUT =
  "This code is worked out on this phone from what you sign. If the same decision is open on the web, its code should match. If it doesn't, don't sign; tell your admin.";

/** The comparison block, for a decision opened from the web's handoff link only. */
export function CodeBlock({ code }: { code: string }) {
  const s = useStyles();
  return (
    <View style={s.block}>
      <Text role="caption" tone="muted">
        Decision code
      </Text>
      <View style={s.blockRow}>
        <Text
          role="codeDisplay"
          maxScale={scaleCap.badge}
          numberOfLines={1}
          accessibilityLabel={`Decision code: ${spokenCode(code)}`}
          style={s.flex}
        >
          {code}
        </Text>
        <IconButton icon="copy" label="Copy the decision code" onPress={() => void Share.share({ message: code })} size={20} />
      </View>
      <Text role="body">Check this matches the code on your web page.</Text>
      <Text role="caption" tone="subtle">
        {"If it's different, don't sign. Tell your admin."}
      </Text>
    </View>
  );
}

const useStyles = makeStyles((t) => ({
  flex: { flex: 1 },
  line: { flexDirection: 'row', alignItems: 'center', gap: t.space[4] },
  block: {
    backgroundColor: t.color.fill,
    borderRadius: t.radius.card,
    padding: t.space[16],
    gap: t.space[4],
  },
  blockRow: { flexDirection: 'row', alignItems: 'center', gap: t.space[8] },
}));
