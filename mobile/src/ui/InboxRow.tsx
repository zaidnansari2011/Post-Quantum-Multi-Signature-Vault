// One item of Activity's For you (phone-ux §6.12): who, what, when, and whether it is new.
//
//   (•) (AO)  Brij approved "Top up the release deployer wallet"     2h
//             It needs one more approval.
//
// A 24 avatar (the actor; a square vault avatar when the system acted), the server's sentence with
// its first line strong, a relative time, and an 8pt unread dot at the leading edge, which is also
// said ("Unread"), never colour alone (§8.5). A security alert is the row on `surface` with a 3pt
// critical accent at its leading edge and the critical shield: not a full critical slab with a
// salmon title, which was garish in dark (handset audit, 14 Oct). The shield says "security", so
// no tag repeats it; the screen reader still hears "Security".
//
// The copy is the server's, unsigned, so it is sans and never carries an action that signs (I-12):
// the row opens a screen, and its only sibling is "Not you? Remove that device", which opens a
// sheet that asks for the phone's lock before it removes anything (§6.18).

import { View, type AccessibilityActionEvent } from 'react-native';

import { makeStyles, useTheme } from '../theme/index.ts';
import { Icon } from './Icon.tsx';
import { Avatar } from './List.tsx';
import { Text } from './Text.tsx';
import { Touchable } from './Touchable.tsx';
import { TextLink } from './Button.tsx';

export type InboxRowProps = {
  title: string;
  body: string;
  /** "2h", "Yesterday", "4 Oct". */
  when: string;
  unread: boolean;
  security: boolean;
  /** Whose initials lead the row; null when the system acted (the vault's square avatar). */
  actor: string | null;
  vault: string | null;
  /** False when there is no screen to open: the tap only marks it read. */
  opens: boolean;
  onPress: () => void;
  /** "Not you? Remove that device", beside the row, never inside it (§4.6). */
  onRemoveDevice?: (() => void) | null;
  /** The swipe's actions again, for screen readers. */
  actions?: Array<{ key: string; label: string; onPress: () => void }>;
};

export function InboxRow({
  title,
  body,
  when,
  unread,
  security,
  actor,
  vault,
  opens,
  onPress,
  onRemoveDevice,
  actions = [],
}: InboxRowProps) {
  const t = useTheme();
  const s = useStyles();
  const label = [unread ? 'Unread' : null, security ? 'Security' : null, title, body, when, vault]
    .filter(Boolean)
    .join('. ');
  const onAction = (e: AccessibilityActionEvent) => actions.find((a) => a.key === e.nativeEvent.actionName)?.onPress();
  return (
    <View style={s.wrap}>
      {security ? <View style={[s.accent, { backgroundColor: t.color.status.critical.fg }]} /> : null}
      <Touchable
        onPress={onPress}
        accessibilityRole="button"
        accessibilityLabel={label}
        accessibilityHint={opens ? 'Opens it and marks it read' : 'Marks it read'}
        accessibilityActions={actions.map((a) => ({ name: a.key, label: a.label }))}
        onAccessibilityAction={onAction}
        ringRadius={0}
        style={({ pressed }) => [s.row, pressed && s.pressed]}
      >
        <View style={s.lead}>
          <View style={[s.dot, unread ? { backgroundColor: security ? t.color.status.critical.fg : t.color.accent } : null]} />
          {security ? (
            <View style={s.securityIcon}>
              <Icon name="shield" size={20} color={t.color.status.critical.fg} />
            </View>
          ) : (
            <Avatar name={actor ?? vault ?? 'Q-Vault'} square={actor === null} />
          )}
        </View>
        <View style={s.text}>
          <View style={s.top}>
            <Text role="bodyStrong" numberOfLines={3} style={s.title}>
              {title}
            </Text>
            <Text role="caption" tone="muted" tabular numberOfLines={1}>
              {when}
            </Text>
          </View>
          {body ? (
            <Text role="body" tone="muted" numberOfLines={4}>
              {body}
            </Text>
          ) : null}
          {vault && !security ? (
            <Text role="caption" tone="subtle" numberOfLines={1}>
              {vault}
            </Text>
          ) : null}
        </View>
      </Touchable>
      {onRemoveDevice ? (
        <View style={s.sibling}>
          <TextLink label="Not you? Remove that device" onPress={onRemoveDevice} tone="critical" />
        </View>
      ) : null}
    </View>
  );
}

const useStyles = makeStyles((t) => ({
  wrap: { backgroundColor: t.color.surface },
  accent: { position: 'absolute', left: 0, top: 0, bottom: 0, width: 3 },
  row: {
    flexDirection: 'row',
    gap: t.space[8],
    paddingLeft: t.space[8],
    paddingRight: t.layout.gutter,
    paddingVertical: t.space[12],
  },
  pressed: { backgroundColor: t.color.fill },
  lead: { flexDirection: 'row', alignItems: 'center', gap: t.space[4], alignSelf: 'flex-start', paddingTop: 2 },
  dot: { width: 8, height: 8, borderRadius: 4 },
  securityIcon: { width: 24, height: 24, alignItems: 'center', justifyContent: 'center' },
  text: { flex: 1, gap: t.space[2] },
  top: { flexDirection: 'row', alignItems: 'flex-start', gap: t.space[8] },
  title: { flex: 1 },
  sibling: { paddingLeft: 52, paddingBottom: t.space[4], marginTop: -t.space[8], alignItems: 'flex-start' },
}));
