// Banner, inline message, empty state and skeleton (phone-ux §5.10).
//
// The error tone rule: connectivity is neutral or warning, never critical. Critical is for integrity
// failures, refusals and money that failed to move. A page banner is only for page-level states;
// an action's error goes where the action was, as an InlineMessage.

import { useEffect, useState, type ReactNode } from 'react';
import { AccessibilityInfo, Platform, View, type DimensionValue, type ViewStyle } from 'react-native';
import Animated, {
  cancelAnimation,
  Easing,
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withRepeat,
  withTiming,
} from 'react-native-reanimated';

import { makeStyles, useTheme, type Tone } from '../theme/index.ts';
import { Button, type ButtonProps } from './Button.tsx';
import { Icon, type IconName } from './Icon.tsx';
import { Text } from './Text.tsx';

const TONE_ICON: Record<Tone, IconName> = {
  success: 'check-circle',
  warning: 'warning',
  critical: 'alert',
  info: 'info',
  neutral: 'info',
};

/** Speak a message once when it appears: a live region on Android, an announcement on iOS. */
export function useAnnounce(text: string | null | undefined) {
  useEffect(() => {
    if (text && Platform.OS === 'ios') AccessibilityInfo.announceForAccessibility(text);
  }, [text]);
}

export function Banner({
  tone,
  title,
  detail,
  actions = [],
}: {
  tone: Tone;
  title: string;
  detail?: string | null;
  /** Up to two, drawn as secondary buttons. */
  actions?: Array<Pick<ButtonProps, 'label' | 'onPress'>>;
}) {
  const t = useTheme();
  const s = useStyles();
  const palette = t.color.status[tone];
  useAnnounce(tone === 'critical' ? `${title}. ${detail ?? ''}` : null);
  return (
    <View
      style={[s.banner, { backgroundColor: palette.bg, borderColor: palette.border }]}
      accessibilityRole={tone === 'critical' ? 'alert' : undefined}
      accessibilityLiveRegion={tone === 'critical' ? 'assertive' : 'polite'}
    >
      <View style={s.bannerHead}>
        <Icon name={TONE_ICON[tone]} size={20} color={palette.fg} />
        <View style={s.bannerText}>
          <Text role="bodyStrong" color={palette.fg}>
            {title}
          </Text>
          {detail ? (
            <Text role="body" tone="text">
              {detail}
            </Text>
          ) : null}
        </View>
      </View>
      {actions.length ? (
        <View style={s.bannerActions}>
          {actions.slice(0, 2).map((a) => (
            <Button key={a.label} label={a.label} onPress={a.onPress} variant="secondary" />
          ))}
        </View>
      ) : null}
    </View>
  );
}

/** One line in the tone's colour, with its icon, where the action was. Announced on appearance. */
export function InlineMessage({ tone, text }: { tone: Tone; text: string }) {
  const t = useTheme();
  const s = useStyles();
  const fg = tone === 'neutral' ? t.color.textMuted : t.color.status[tone].fg;
  useAnnounce(text);
  return (
    <View style={s.inline} accessibilityLiveRegion="polite" accessible accessibilityLabel={text}>
      <Icon name={TONE_ICON[tone]} size={16} color={fg} style={s.inlineIcon} />
      <Text role="caption" color={fg} style={s.inlineText}>
        {text}
      </Text>
    </View>
  );
}

/** One sentence, at most one line under it, at most one button. No illustration. */
export function EmptyState({
  title,
  detail,
  action,
}: {
  title: string;
  detail?: string;
  action?: ReactNode;
}) {
  const s = useStyles();
  return (
    <View style={s.empty}>
      <Text role="titleSm" align="center">
        {title}
      </Text>
      {detail ? (
        <Text role="body" tone="muted" align="center" style={s.emptyDetail}>
          {detail}
        </Text>
      ) : null}
      {action ? <View style={s.emptyAction}>{action}</View> : null}
    </View>
  );
}

/**
 * A placeholder in the shape of what is coming. It appears only after 150ms, so a fast answer never
 * flashes one, then breathes between 0.55 and 1 over 1.6s; it holds still under reduced motion.
 * It is the only looping motion in the app (§7.1).
 */
export function Skeleton({
  width = '100%',
  height = 16,
  radius = 6,
  style,
}: {
  width?: DimensionValue;
  height?: number;
  radius?: number;
  style?: ViewStyle;
}) {
  const t = useTheme();
  const reduced = useReducedMotion();
  const [shown, setShown] = useState(false);
  const breath = useSharedValue(0.55);

  useEffect(() => {
    const at = setTimeout(() => setShown(true), t.motion.skeletonDelay);
    return () => clearTimeout(at);
  }, [t.motion.skeletonDelay]);

  useEffect(() => {
    if (!shown || reduced) return;
    breath.value = withRepeat(
      withTiming(1, { duration: t.motion.skeletonBreath / 2, easing: Easing.inOut(Easing.sin) }),
      -1,
      true,
    );
    return () => cancelAnimation(breath);
  }, [shown, reduced, breath, t.motion.skeletonBreath]);

  const animated = useAnimatedStyle(() => ({ opacity: reduced ? 0.55 : breath.value }));
  return (
    <Animated.View
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
      style={[
        { width, height, borderRadius: radius, backgroundColor: t.color.fillHover },
        style,
        shown ? animated : { opacity: 0 },
      ]}
    />
  );
}

const useStyles = makeStyles((t) => ({
  banner: { borderWidth: 1, borderRadius: t.radius.card, padding: t.space[16], gap: t.space[12] },
  bannerHead: { flexDirection: 'row', gap: t.space[12], alignItems: 'flex-start' },
  bannerText: { flex: 1, gap: t.space[4] },
  bannerActions: { flexDirection: 'row', flexWrap: 'wrap', gap: t.space[8], paddingLeft: 32 },
  inline: { flexDirection: 'row', alignItems: 'flex-start', gap: t.space[8] },
  inlineIcon: { marginTop: 1 },
  inlineText: { flex: 1 },
  empty: { alignItems: 'center', paddingVertical: t.space[40], paddingHorizontal: t.space[16], gap: t.space[8] },
  emptyDetail: { maxWidth: 320 },
  emptyAction: { marginTop: t.space[8] },
}));
