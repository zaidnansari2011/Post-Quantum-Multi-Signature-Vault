// Rows, grouped lists and disclosure (phone-ux §5.7).
//
// Rows, not cards, in every list: a grouped list on `surface` with radius 12 and hairline dividers
// inset 16, rows at least 56pt. A row that opens something carries a chevron in `textMuted`.

import { Children, Fragment, isValidElement, type ReactNode } from 'react';
import { View, type ViewStyle } from 'react-native';

import { makeStyles, useTheme } from '../theme/index.ts';
import { Icon, type IconName } from './Icon.tsx';
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
  /** Two lines of caption before it ellipsises. */
  captionLines?: number;
  /** A sibling control on the right (never inside the row's own target, §4.6). */
  trailing?: ReactNode;
  disabled?: boolean;
  /** A key, fingerprint or hash under the title, in mono: 0/O and 1/l must never be ambiguous. */
  code?: string | null;
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
}: ListRowProps) {
  const t = useTheme();
  const s = useStyles();
  const raised = useRaised();
  const stacked = t.stacked && !!value;
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
      {value && !stacked ? (
        <Text role="body" tone={valueTone} tabular style={s.value}>
          {value}
        </Text>
      ) : null}
      {onPress ? <Icon name="chevron-right" size={16} color={t.color.textMuted} /> : null}
    </>
  );
  const label = accessibilityLabel ?? [title, caption, value].filter(Boolean).join('. ');
  const pressedStyle = { backgroundColor: pressedFill(t, raised) };
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

/** Initials on `fill`, never accent and never a status colour. Square for vaults (§5.7). */
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
  const initials = name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]!.toUpperCase())
    .join('');
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
        {initials || '?'}
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
  rowText: { flex: 1, gap: t.space[2] },
  value: { flexShrink: 1, maxWidth: '62%', textAlign: 'right' },
  kv: { gap: t.space[2], paddingVertical: t.space[4] },
  avatar: { backgroundColor: t.color.fill, alignItems: 'center', justifyContent: 'center' },
  stack: { flexDirection: 'row', alignItems: 'center' },
  stackItem: { borderWidth: 2, borderColor: t.color.surface, borderRadius: 14 },
}));
