// Inputs (phone-ux §5.8).
//
// A field's label is always visible (never a placeholder standing in for it); the input is 48pt,
// 16pt text (which also stops iOS zooming) on `surface` with a 1pt `borderStrong` edge (3:1; the old
// `rule` edge was 1.3:1). Focus is a 2pt accent edge; an error is a 2pt critical edge and a line
// under the field whose slot is always reserved, so the form never shifts under the thumb.
//
// Selection is the accent everywhere (chips, segments, checkboxes), never the green status colour.

import { useState, type ReactNode } from 'react';
import {
  Platform,
  ScrollView,
  Switch as RNSwitch,
  TextInput,
  View,
  type TextInputProps,
} from 'react-native';

import { fontFamily, makeStyles, useTheme, type Theme } from '../theme/index.ts';
import { IconButton } from './Button.tsx';
import { feedback } from './feedback.ts';
import { Icon } from './Icon.tsx';
import { useAnnounce } from './messages.tsx';
import { pressedFill, useRaised } from './surface.ts';
import { roleStyle, Text } from './Text.tsx';
import { Touchable } from './Touchable.tsx';

function inputBorder(t: Theme, focused: boolean, error: boolean) {
  if (error) return { borderColor: t.color.status.critical.fg, borderWidth: 2 };
  if (focused) return { borderColor: t.color.accent, borderWidth: 2 };
  return { borderColor: t.color.borderStrong, borderWidth: 1 };
}

export type FieldProps = Omit<TextInputProps, 'style'> & {
  label: string;
  /** Under the field; the accessibility hint too. */
  caption?: string | null;
  /** Replaces the caption, in the critical tone, with its icon. */
  error?: string | null;
  /** Hashes and addresses: JetBrains Mono, wrapping. */
  mono?: boolean;
  /** A control beside the label, such as "Forgot password?". */
  labelTrailing?: ReactNode;
  /** An icon button inside the field's right edge. */
  trailing?: ReactNode;
  /**
   * Reserve the error line's height even while there is no error, so a field that validates as
   * you type never shifts under the thumb (§5.8). Fields that only report on submit leave it off.
   */
  validates?: boolean;
  /** A live count on the right of the line under the field: "0 / 255". */
  count?: string | null;
};

/** react-native-web draws a square browser outline inside the 2pt ring; the ring replaces it. */
const NO_WEB_OUTLINE = (Platform.OS === 'web' ? { outlineStyle: 'none' } : {}) as object;

export function Field({
  label,
  caption,
  error,
  mono = false,
  labelTrailing,
  trailing,
  onFocus,
  onBlur,
  multiline,
  validates = false,
  count,
  ...props
}: FieldProps) {
  const t = useTheme();
  const s = useStyles();
  const [focused, setFocused] = useState(false);
  useAnnounce(error);
  const border = inputBorder(t, focused, !!error);
  // The edge thickens by 1pt on focus; the padding gives the point back so the text never moves.
  const pad = t.space[12] - (border.borderWidth - 1);
  return (
    <View style={s.field}>
      <View style={[s.labelRow, labelTrailing ? s.labelRowWithLink : null]}>
        <Text role="caption" tone="muted" nativeID={`${label}-label`}>
          {label}
        </Text>
        {/* The row grows to the link's height: its target must not overlap the input (§4.6). */}
        {labelTrailing}
      </View>
      <View style={[s.inputBox, border, { paddingLeft: pad, paddingRight: trailing ? 0 : pad }]}>
        <TextInput
          {...props}
          multiline={multiline}
          accessibilityLabel={label}
          accessibilityHint={error ?? caption ?? undefined}
          allowFontScaling={!t.emulatedFontScale}
          maxFontSizeMultiplier={2}
          placeholderTextColor={t.color.textSubtle}
          selectionColor={t.color.accent}
          cursorColor={t.color.accent}
          onFocus={(e) => {
            setFocused(true);
            onFocus?.(e);
          }}
          onBlur={(e) => {
            setFocused(false);
            onBlur?.(e);
          }}
          style={[
            roleStyle(t, mono ? 'code' : 'body'),
            mono ? { fontFamily: fontFamily.mono } : null,
            s.input,
            { color: t.color.text },
            NO_WEB_OUTLINE,
          ]}
        />
        {trailing}
      </View>
      {error || caption || validates || count ? (
      <View style={[s.under, count ? s.underRow : null]}>
        {error ? (
          <View style={[s.errorRow, count ? s.flex : null]} accessibilityLiveRegion="polite">
            <Icon name="alert" size={16} color={t.color.status.critical.fg} style={s.errorIcon} />
            <Text role="caption" tone="critical" style={s.flex}>
              {error}
            </Text>
          </View>
        ) : caption ? (
          <Text role="caption" tone="subtle" style={count ? s.flex : null}>
            {caption}
          </Text>
        ) : count ? (
          <View style={s.flex} />
        ) : null}
        {count ? (
          <Text role="caption" tone="muted" tabular>
            {count}
          </Text>
        ) : null}
      </View>
      ) : null}
    </View>
  );
}

/** A password field with the eye (§5.8): "Show password" / "Hide password", 48 target. */
export function PasswordField(props: Omit<FieldProps, 'secureTextEntry' | 'trailing'>) {
  const [shown, setShown] = useState(false);
  return (
    <Field
      {...props}
      secureTextEntry={!shown}
      autoCapitalize="none"
      autoCorrect={false}
      textContentType="password"
      autoComplete="password"
      trailing={
        <IconButton
          icon={shown ? 'eye-off' : 'eye'}
          label={shown ? 'Hide password' : 'Show password'}
          onPress={() => setShown((v) => !v)}
          size={20}
        />
      }
    />
  );
}

/**
 * The decision text (§5.8): set in the serif it will be signed in, 5 lines tall and growing to 12,
 * with a live count once it nears the 4,000-character limit.
 */
export function TextArea({
  label,
  caption,
  error,
  value,
  maxLength = 4000,
  countFrom = 3800,
  ...props
}: Omit<FieldProps, 'mono' | 'multiline'> & { value: string; countFrom?: number }) {
  const t = useTheme();
  const s = useStyles();
  const [focused, setFocused] = useState(false);
  useAnnounce(error);
  const border = inputBorder(t, focused, !!error);
  const pad = t.space[12] - (border.borderWidth - 1);
  const line = roleStyle(t, 'decision').lineHeight as number;
  const count = value.length >= countFrom ? `${value.length.toLocaleString('en-GB')} of ${maxLength.toLocaleString('en-GB')}` : null;
  return (
    <View style={s.field}>
      <Text role="caption" tone="muted">
        {label}
      </Text>
      <TextInput
        {...props}
        value={value}
        maxLength={maxLength}
        multiline
        textAlignVertical="top"
        accessibilityLabel={label}
        accessibilityHint={error ?? caption ?? undefined}
        allowFontScaling={!t.emulatedFontScale}
        placeholderTextColor={t.color.textSubtle}
        selectionColor={t.color.accent}
        cursorColor={t.color.accent}
        onFocus={(e) => {
          setFocused(true);
          props.onFocus?.(e);
        }}
        onBlur={(e) => {
          setFocused(false);
          props.onBlur?.(e);
        }}
        style={[
          roleStyle(t, 'decision'),
          s.textarea,
          border,
          NO_WEB_OUTLINE,
          {
            color: t.color.text,
            paddingHorizontal: pad,
            minHeight: line * 5 + t.space[24],
            maxHeight: line * 12 + t.space[24],
          },
        ]}
      />
      <View style={[s.under, s.underRow]}>
        {error ? (
          <View style={[s.errorRow, s.flex]} accessibilityLiveRegion="polite">
            <Icon name="alert" size={16} color={t.color.status.critical.fg} style={s.errorIcon} />
            <Text role="caption" tone="critical" style={s.flex}>
              {error}
            </Text>
          </View>
        ) : (
          <Text role="caption" tone="subtle" style={s.flex}>
            {caption ?? ''}
          </Text>
        )}
        {count ? (
          <Text role="caption" tone={value.length >= maxLength ? 'critical' : 'muted'} tabular>
            {count}
          </Text>
        ) : null}
      </View>
    </View>
  );
}

/** A single-select chip: 40 visual with a 48 target, accent when selected, with its check. */
export function Chip({
  label,
  selected,
  onPress,
  disabled,
}: {
  label: string;
  selected: boolean;
  onPress: () => void;
  disabled?: boolean;
}) {
  const t = useTheme();
  const s = useStyles();
  return (
    <Touchable
      onPress={() => {
        if (!selected) feedback.selection();
        onPress();
      }}
      disabled={disabled}
      accessibilityRole="radio"
      accessibilityState={{ selected, checked: selected, disabled: !!disabled }}
      accessibilityLabel={label}
      ringRadius={t.radius.control}
      style={({ pressed }) => [
        s.chip,
        selected
          ? { backgroundColor: t.color.accentSubtle, borderColor: t.color.accentBorder }
          : { backgroundColor: pressed ? t.color.fill : t.color.surface, borderColor: t.color.borderStrong },
        disabled && { backgroundColor: t.color.fillDisabled, borderColor: t.color.borderDisabled },
      ]}
    >
      {selected ? <Icon name="check" size={16} color={t.color.accentFg} /> : null}
      <Text role="body" tone={disabled ? 'disabled' : selected ? 'accentFg' : 'text'} maxScale={1.6}>
        {label}
      </Text>
    </Touchable>
  );
}

/** A radiogroup of chips, 8 apart so their targets never overlap (§4.6). */
export function ChipGroup<T extends string | number | null>({
  options,
  value,
  onChange,
  label,
  disabled,
}: {
  options: Array<{ value: T; label: string }>;
  value: T;
  onChange: (value: T) => void;
  /** The group's accessible name. */
  label: string;
  disabled?: boolean;
}) {
  const s = useStyles();
  return (
    <View style={s.chips} accessibilityRole="radiogroup" accessibilityLabel={label}>
      {options.map((o) => (
        <Chip
          key={String(o.value)}
          label={o.label}
          selected={o.value === value}
          onPress={() => onChange(o.value)}
          disabled={disabled}
        />
      ))}
    </View>
  );
}

/**
 * A segmented control: 40 high on a `fill` track, the selected segment on `surface`. At large text
 * it becomes a scrolling row of chips, which can grow (§5.8).
 */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: Array<{ value: T; label: string }>;
  value: T;
  onChange: (value: T) => void;
  label: string;
}) {
  const t = useTheme();
  const s = useStyles();
  if (t.stacked) {
    return (
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={[s.chips, s.chipScroller]}
      >
        {options.map((o) => (
          <Chip key={o.value} label={o.label} selected={o.value === value} onPress={() => onChange(o.value)} />
        ))}
      </ScrollView>
    );
  }
  return (
    <View style={s.segmented} accessibilityRole="tablist" accessibilityLabel={label}>
      {options.map((o) => {
        const active = o.value === value;
        return (
          <Touchable
            key={o.value}
            onPress={() => {
              if (!active) feedback.selection();
              onChange(o.value);
            }}
            accessibilityRole="tab"
            accessibilityState={{ selected: active }}
            accessibilityLabel={o.label}
            ringRadius={8}
            style={({ pressed }) => [
              s.segment,
              active ? s.segmentActive : pressed ? { backgroundColor: t.color.fillHover } : null,
            ]}
          >
            <Text role="body" tone={active ? 'text' : 'muted'} maxScale={1.6} numberOfLines={1}>
              {o.label}
            </Text>
          </Touchable>
        );
      })}
    </View>
  );
}

/** A 24pt box, accent when checked (§5.8). The row around it is the target. */
export function Checkbox({ checked }: { checked: boolean }) {
  const t = useTheme();
  const s = useStyles();
  return (
    <View
      style={[
        s.checkbox,
        checked
          ? { backgroundColor: t.color.accent, borderColor: t.color.accent }
          : { borderColor: t.color.borderStrong, backgroundColor: t.color.surface },
      ]}
    >
      {checked ? <Icon name="check" size={18} color={t.color.accentText} /> : null}
    </View>
  );
}

/** A row that toggles a checkbox: the whole row is the target and the checkbox its state. */
export function CheckboxRow({
  label,
  caption,
  checked,
  onToggle,
}: {
  label: string;
  caption?: string | null;
  checked: boolean;
  onToggle: () => void;
}) {
  const s = useStyles();
  const t = useTheme();
  const raised = useRaised();
  return (
    <Touchable
      onPress={onToggle}
      accessibilityRole="checkbox"
      accessibilityState={{ checked }}
      accessibilityLabel={caption ? `${label}, ${caption}` : label}
      ringRadius={0}
      style={({ pressed }) => [s.checkRow, pressed && { backgroundColor: pressedFill(t, raised) }]}
    >
      <View style={s.flex}>
        <Text role="body">{label}</Text>
        {caption ? (
          <Text role="caption" tone="muted">
            {caption}
          </Text>
        ) : null}
      </View>
      <Checkbox checked={checked} />
    </Touchable>
  );
}

/** The platform switch, in the accent when on (§5.8). */
export function Switch({
  value,
  onValueChange,
  label,
  disabled,
}: {
  value: boolean;
  onValueChange: (v: boolean) => void;
  label: string;
  disabled?: boolean;
}) {
  const t = useTheme();
  return (
    <RNSwitch
      value={value}
      onValueChange={onValueChange}
      disabled={disabled}
      accessibilityLabel={label}
      trackColor={{ true: t.color.accent, false: t.color.borderStrong }}
      thumbColor={t.color.surface}
      ios_backgroundColor={t.color.borderStrong}
      // react-native-web's own default thumb is teal; selection is never a status green.
      {...({ activeThumbColor: t.color.surface } as object)}
    />
  );
}

const useStyles = makeStyles((t) => ({
  flex: { flex: 1 },
  // One field-to-field rhythm everywhere: 16 below each field, whatever it carries.
  field: { gap: t.space[8], paddingBottom: t.space[16] },
  labelRowWithLink: { minHeight: 44, marginVertical: -t.space[8] },
  labelRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', minHeight: 18 },
  inputBox: {
    minHeight: 48,
    borderRadius: t.radius.control,
    backgroundColor: t.color.surface,
    flexDirection: 'row',
    alignItems: 'center',
  },
  input: { flex: 1, paddingVertical: t.space[12], minHeight: 46 },
  under: { minHeight: 18 },
  underRow: { flexDirection: 'row', gap: t.space[12], alignItems: 'flex-start' },
  errorRow: { flexDirection: 'row', gap: t.space[4], alignItems: 'flex-start' },
  errorIcon: { marginTop: 1 },
  textarea: {
    borderRadius: t.radius.control,
    backgroundColor: t.color.surface,
    paddingVertical: t.space[12],
  },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: t.space[8] },
  chip: {
    minHeight: 40,
    paddingHorizontal: t.space[12],
    borderRadius: t.radius.control,
    borderWidth: 1,
    flexDirection: 'row',
    alignItems: 'center',
    gap: t.space[4],
  },
  segmented: {
    flexDirection: 'row',
    backgroundColor: t.color.fill,
    borderRadius: t.radius.control,
    padding: 2,
    gap: 2,
    minHeight: 40,
  },
  chipScroller: { flexWrap: 'nowrap', paddingRight: t.layout.gutter },
  segment: {
    // Sized to their labels and sharing the rest, so "Approved" is never cut to "Approv…".
    flexGrow: 1,
    flexBasis: 'auto',
    minHeight: 36,
    borderRadius: 8,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: t.space[8],
  },
  segmentActive: {
    // In dark, `surface` is darker than the `fill` track and the selection would look sunken;
    // dark surfaces step lighter (§4.5), so the selected segment takes `fillActive` there.
    backgroundColor: t.scheme === 'dark' ? t.color.fillActive : t.color.surface,
    borderWidth: 1,
    borderColor: t.color.border,
  },
  checkbox: {
    width: 24,
    height: 24,
    borderRadius: t.radius.badge,
    borderWidth: 1.5,
    alignItems: 'center',
    justifyContent: 'center',
  },
  checkRow: {
    minHeight: 56,
    flexDirection: 'row',
    alignItems: 'center',
    gap: t.space[12],
    paddingHorizontal: t.layout.gutter,
    paddingVertical: t.space[8],
  },
}));
