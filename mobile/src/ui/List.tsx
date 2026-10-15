// Rows, grouped lists and disclosure (phone-ux §5.7).
//
// Rows, not cards, in every list: a grouped list on `surface` with radius 12 and hairline dividers
// inset 16, rows at least 56pt. A row that opens something carries a chevron in `textMuted`.

import { Children, Fragment, isValidElement, type ReactNode } from 'react';
import { View, type ViewStyle } from 'react-native';

import { initials } from '../format.ts';
import { makeStyles, useTheme } from '../theme/index.ts';
import { Icon, type IconName } from './Icon.tsx';
import { Switch } from './inputs.tsx';
import { Text, type TextTone } from './Text.tsx';
import { pressedFill, useRaised } from './surface.ts';
import { Touchable } from './Touchable.tsx';

/** A grouped list: rows on `surface`, hairlines between them, inset 16. */
export function List({ children, style }: { children: ReactNode; style?: ViewStyle }) {
  const s = useStyles();
  const rows = Children.toArray(children).filter(isValidElement);
  return (
    <View style={[s.list, style]}>
      {rows.map((row, i) => (
        <Fragment key={row.key ?? i}>
          {i > 0 ? <Divider inset /> : null}
          {row}
        </Fragment>
      ))}
    </View>
  );
}

/**
 * One item of a grouped list rendered by a FlatList (which cannot wrap its rows in one container):
 * the first and last items carry the group's corners and edges, so a long list virtualises and
 * still reads as one group.
 */
export function GroupedItem({
  index,
  total,
  children,
}: {
  index: number;
  total: number;
  children: ReactNode;
}) {
  const s = useStyles();
  return (
    <View style={[s.item, index === 0 && s.itemFirst, index === total - 1 && s.itemLast]}>
      {children}
    </View>
  );
}

/** The hairline between two GroupedItems, inset 16 like a List's. */
export function GroupedSeparator() {
  const s = useStyles();
  return (
    <View style={s.item}>
      <Divider inset />
    </View>
  );
}

export function Divider({ inset = false }: { inset?: boolean }) {
  const s = useStyles();
  return <View style={[s.divider, inset && s.dividerInset]} />;
}

export type ListRowProps = {
  title: string;
  caption?: string | null;
  captionTone?: TextTone;
  /** A value on the right, in `textMuted` unless toned. */
  value?: string | null;
  valueTone?: TextTone;
  leading?: ReactNode;
  icon?: IconName;
  onPress?: () => void;
  accessibilityLabel?: string;
  accessibilityHint?: string;
  /** Two lines of caption before it ellipsises; 0 never cuts it (a switch's explanation). */
  captionLines?: number;
  /** A sibling control on the right (never inside the row's own target, §4.6). */
  trailing?: ReactNode;
  disabled?: boolean;
  /** A key, fingerprint or hash under the title, in mono: 0/O and 1/l must never be ambiguous. */
  code?: string | null;
  /** Decoration inside the row, before its value: Members' avatar stack (§6.14). Not tappable. */
  accessory?: ReactNode;
  /**
   * False for a row whose tap reveals more in place rather than opening something. Defaults to
   * true, except on a row with the `external` icon: a link that leaves the app carries the external
   * icon only, and the chevron (moving within the app) only the rest (handset audit, 14 Oct).
   */
  chevron?: boolean;
  /**
   * A switch for the row (a row with a switch is not itself pressable): inset from the card's right
   * edge like a chevron, and centred on the title's first line however the caption wraps.
   */
  toggle?: { value: boolean; onValueChange: (v: boolean) => void; disabled?: boolean };
};

export function ListRow({
  title,
  caption,
  captionTone = 'muted',
  value,
  valueTone = 'muted',
  leading,
  icon,
  onPress,
  accessibilityLabel,
  accessibilityHint,
  captionLines = 2,
  trailing,
  disabled,
  code,
  accessory,
  chevron = icon !== 'external',
  toggle,
}: ListRowProps) {
  const t = useTheme();
  const s = useStyles();
  const raised = useRaised();
  const stacked = t.stacked && !!value;
  // The title's first line, as `body` is drawn at this text size (capped at the role's maxScale).
  const titleLine = t.type.body.lineHeight * Math.min(Math.max(t.fontScale, 1), t.type.body.maxScale ?? 1);
  const body = (
    <>
      {leading ?? (icon ? <Icon name={icon} size={24} color={t.color.textMuted} /> : null)}
      <View style={s.rowText}>
        <Text role="body">{title}</Text>
        {code ? (
          <Text role="code" tone="muted" selectable>
            {code}
          </Text>
        ) : null}
        {caption ? (
          <Text role="caption" tone={captionTone} numberOfLines={captionLines}>
            {caption}
          </Text>
        ) : null}
        {stacked ? (
          <Text role="body" tone={valueTone} tabular>
            {value}
          </Text>
        ) : null}
      </View>
      {accessory ?? null}
      {value && !stacked ? (
        <Text role="body" tone={valueTone} tabular style={s.value}>
          {value}
        </Text>
      ) : null}
      {onPress && chevron ? <Icon name="chevron-right" size={16} color={t.color.textMuted} /> : null}
    </>
  );
  const label = accessibilityLabel ?? [title, caption, value].filter(Boolean).join('. ');
  const pressedStyle = { backgroundColor: pressedFill(t, raised) };
  if (toggle) {
    // Top-aligned with 16 above and below, so a one-line row is still 56 and the switch's box (the
    // title's line height) sits exactly on the title, however many lines the caption runs to.
    return (
      <View style={[s.row, s.toggleRow]}>
        {leading ?? (icon ? <Icon name={icon} size={24} color={t.color.textMuted} /> : null)}
        <View style={s.rowText}>
          <Text role="body">{title}</Text>
          {caption ? (
            <Text role="caption" tone={captionTone} numberOfLines={captionLines}>
              {caption}
            </Text>
          ) : null}
        </View>
        <View style={[s.toggleBox, { height: titleLine }]}>
          <Switch
            label={title}
            hint={caption ?? undefined}
            value={toggle.value}
            onValueChange={toggle.onValueChange}
            disabled={toggle.disabled}
          />
        </View>
      </View>
    );
  }
  if (!onPress) {
    return (
      <View style={s.rowOuter}>
        <View style={[s.row, s.rowFlex]} accessible accessibilityLabel={label}>
          {body}
        </View>
        {trailing}
      </View>
    );
  }
  return (
    <View style={s.rowOuter}>
      <Touchable
        onPress={onPress}
        disabled={disabled}
        accessibilityRole="button"
        accessibilityLabel={label}
        accessibilityHint={accessibilityHint}
        ringRadius={0}
        style={({ pressed }) => [s.row, s.rowFlex, pressed && pressedStyle]}
      >
        {body}
      </Touchable>
      {trailing}
    </View>
  );
}

/** A row that opens a sheet: "Checked on this phone", "Details", "Members" (§5.7). */
export function DisclosureRow(props: ListRowProps & { onPress: () => void }) {
  return <ListRow accessibilityHint="Opens more detail" {...props} />;
}

/**
 * A label above its value. The pair is one accessibility element: "Network, Sepolia".
 */
export function KeyValue({
  label,
  value,
  children,
  mono = false,
  tone = 'text',
}: {
  label: string;
  value?: string | null;
  children?: ReactNode;
  mono?: boolean;
  tone?: TextTone;
}) {
  const s = useStyles();
  if (children) {
    return (
      <View style={s.kv}>
        <Text role="caption" tone="muted">
          {label}
        </Text>
        {children}
      </View>
    );
  }
  return (
    <View style={s.kv} accessible accessibilityLabel={`${label}, ${value ?? 'none'}`}>
      <Text role="caption" tone="muted">
        {label}
      </Text>
      <Text role={mono ? 'code' : 'body'} tone={tone} selectable={mono}>
        {value ?? '—'}
      </Text>
    </View>
  );
}

/** Initials on `fillActive`, never accent and never a status colour. Square for vaults (§5.7). */
export function Avatar({
  name,
  size = 24,
  square = false,
}: {
  name: string;
  size?: 24 | 32;
  square?: boolean;
}) {
  const s = useStyles();
  const letters = initials(name);
  return (
    <View
      style={[
        s.avatar,
        { width: size, height: size, borderRadius: square ? 6 : size / 2 },
      ]}
      accessible={false}
      importantForAccessibility="no"
    >
      <Text role="label" tone="muted" maxScale={1}>
        {letters}
      </Text>
    </View>
  );
}

/** Up to three avatars with a 2pt ring, then "+2". */
export function AvatarStack({ names }: { names: string[] }) {
  const s = useStyles();
  const shown = names.slice(0, 3);
  const more = names.length - shown.length;
  return (
    <View style={s.stack} accessibilityLabel={`${names.length} people`}>
      {shown.map((n, i) => (
        <View key={`${n}-${i}`} style={[s.stackItem, i > 0 && { marginLeft: -6 }]}>
          <Avatar name={n} />
        </View>
      ))}
      {more > 0 ? (
        <Text role="caption" tone="muted" style={{ marginLeft: 4 }}>
          {`+${more}`}
        </Text>
      ) : null}
    </View>
  );
}

const useStyles = makeStyles((t) => ({
  list: {
    backgroundColor: t.color.surface,
    borderRadius: t.radius.card,
    // A hairline in both themes: white on the near-white page is 1.05:1, so the group would
    // otherwise have no edge (§4.5, flat with a hairline).
    borderWidth: 1,
    borderColor: t.color.border,
    overflow: 'hidden',
  },
  divider: { height: 1, backgroundColor: t.color.border },
  item: {
    backgroundColor: t.color.surface,
    borderLeftWidth: 1,
    borderRightWidth: 1,
    borderColor: t.color.border,
    overflow: 'hidden',
  },
  itemFirst: {
    borderTopWidth: 1,
    borderTopLeftRadius: t.radius.card,
    borderTopRightRadius: t.radius.card,
  },
  itemLast: {
    borderBottomWidth: 1,
    borderBottomLeftRadius: t.radius.card,
    borderBottomRightRadius: t.radius.card,
  },
  dividerInset: { marginLeft: t.layout.gutter },
  rowOuter: { flexDirection: 'row', alignItems: 'center' },
  row: {
    minHeight: 56,
    flexDirection: 'row',
    alignItems: 'center',
    gap: t.space[12],
    paddingHorizontal: t.layout.gutter,
    paddingVertical: t.space[12],
  },
  rowFlex: { flex: 1 },
  toggleRow: { alignItems: 'flex-start', paddingVertical: t.space[16] },
  // Overflows its box evenly when the platform switch is taller than the line.
  toggleBox: { justifyContent: 'center', alignItems: 'flex-end', minWidth: 48 },
  rowText: { flex: 1, gap: t.space[2] },
  value: { flexShrink: 1, maxWidth: '62%', textAlign: 'right' },
  kv: { gap: t.space[2], paddingVertical: t.space[4] },
  // `fillActive`, not `fill`: on the dark page `fill` was almost the page itself (handset audit).
  avatar: { backgroundColor: t.color.fillActive, alignItems: 'center', justifyContent: 'center' },
  stack: { flexDirection: 'row', alignItems: 'center' },
  stackItem: { borderWidth: 2, borderColor: t.color.surface, borderRadius: 14 },
}));
