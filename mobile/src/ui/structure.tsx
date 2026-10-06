// Screens, bars and sections (phone-ux §5.1).

import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import {
  AccessibilityInfo,
  Platform,
  RefreshControl,
  ScrollView,
  type RefreshControlProps,
  View,
  useWindowDimensions,
  type LayoutChangeEvent,
  type NativeScrollEvent,
  type NativeSyntheticEvent,
  type ViewStyle,
} from 'react-native';
import Animated, { useAnimatedStyle, useReducedMotion, withTiming } from 'react-native-reanimated';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';

import { makeStyles, scaleCap, useTheme } from '../theme/index.ts';
import { IconButton } from './Button.tsx';
import { Icon, type IconName } from './Icon.tsx';
import { Text } from './Text.tsx';

/** The safe-area container on `bg`. The bottom inset belongs to the scroll content, not here. */
export function Screen({
  children,
  edges = ['top'],
}: {
  children: ReactNode;
  edges?: Array<'top' | 'bottom'>;
}) {
  const s = useStyles();
  return (
    <SafeAreaView style={s.screen} edges={edges}>
      {children}
    </SafeAreaView>
  );
}

export type NavAction = { icon: IconName; label: string; onPress: () => void };

/**
 * The bar on a pushed screen (§2.7, §5.1). Back is the platform's glyph in a 48 target; the title
 * is centred on iOS and follows the back button on Android, one line, capped at 1.4x.
 */
export function NavBar({
  onBack,
  title,
  showTitle = true,
  actions = [],
  backIcon,
  backLabel = 'Go back',
}: {
  onBack?: () => void;
  title?: string;
  /** False until the page's own heading has scrolled away (§5.1). */
  showTitle?: boolean;
  actions?: NavAction[];
  /** A modal closes rather than goes back. */
  backIcon?: IconName;
  backLabel?: string;
}) {
  const s = useStyles();
  const centred = Platform.OS === 'ios';
  const back = backIcon ?? (Platform.OS === 'android' ? 'arrow-left' : 'chevron-left');
  return (
    <View style={s.nav}>
      <View style={s.navSide}>
        {onBack ? <IconButton icon={back} label={backLabel} onPress={onBack} /> : null}
      </View>
      <View style={[s.navTitle, centred ? s.navTitleCentred : null]}>
        {title && showTitle ? (
          <Text
            role="titleSm"
            maxScale={scaleCap.navTitle}
            numberOfLines={1}
            accessibilityRole="header"
            align={centred ? 'center' : 'left'}
          >
            {title}
          </Text>
        ) : null}
      </View>
      <View style={[s.navSide, s.navTrailing]}>
        {actions.slice(0, 2).map((a) => (
          <IconButton key={a.label} icon={a.icon} label={a.label} onPress={a.onPress} />
        ))}
      </View>
    </View>
  );
}

/**
 * The headline of a tab root (§5.1): one sentence, an optional line under it, and an optional
 * trailing icon button aligned to the headline's first line. No greeting.
 */
export function RootHeader({
  title,
  lead,
  supporting,
  action,
  onLayout,
}: {
  title: string;
  /** A short line above the headline. Kept for the screens that still have one. */
  lead?: string;
  supporting?: string;
  /** `filled` draws it tinted: the create action is findable, not the loudest thing here. */
  action?: NavAction & { filled?: boolean };
  /** From useCollapsingHeader, so the bar appears when the headline has gone under it. */
  onLayout?: (e: LayoutChangeEvent) => void;
}) {
  const t = useTheme();
  const s = useStyles();
  // Centred on the headline's FIRST line, however the headline wraps or scales.
  const line = t.type.title.lineHeight * Math.min(Math.max(t.fontScale, 1), t.type.title.maxScale ?? 1);
  return (
    <View style={s.rootHeader} onLayout={onLayout}>
      {lead ? (
        <Text role="caption" tone="muted">
          {lead}
        </Text>
      ) : null}
      <View style={s.rootHeadRow}>
        <Text role="title" accessibilityRole="header" style={s.rootTitle}>
          {title}
        </Text>
        {action ? (
          <View style={{ marginTop: (line - 44) / 2, marginBottom: -8 }}>
            <IconButton
              icon={action.icon}
              label={action.label}
              onPress={action.onPress}
              tone={action.filled ? 'tinted' : 'plain'}
            />
          </View>
        ) : null}
      </View>
      {supporting ? (
        <Text role="body" tone="muted">
          {supporting}
        </Text>
      ) : null}
    </View>
  );
}

/**
 * Collapses a tab root's headline into a 48pt bar once it has scrolled under the top (§5.1, the
 * large-title pattern): `onScroll` goes on the list, `<CollapsedBar>` sits above it.
 */
export function useCollapsingHeader() {
  const [collapsed, setCollapsed] = useState(false);
  const last = useRef(false);
  // Where the headline's bottom edge passes under the 48pt bar: measured, so it holds at 2x text.
  const threshold = useRef(56);
  const onHeaderLayout = useCallback((e: LayoutChangeEvent) => {
    const { y, height } = e.nativeEvent.layout;
    threshold.current = Math.max(0, y + height - 48);
  }, []);
  const onScroll = useCallback((e: NativeSyntheticEvent<NativeScrollEvent>) => {
    const next = e.nativeEvent.contentOffset.y > threshold.current;
    if (next !== last.current) {
      last.current = next;
      setCollapsed(next);
    }
  }, []);
  return { collapsed, onScroll, onHeaderLayout, scrollEventThrottle: 16 };
}

export function CollapsedBar({
  title,
  visible,
  action,
}: {
  title: string;
  visible: boolean;
  action?: NavAction;
}) {
  const t = useTheme();
  const s = useStyles();
  const reduced = useReducedMotion();
  const style = useAnimatedStyle(() => ({
    opacity: withTiming(visible ? 1 : 0, { duration: reduced ? 0 : t.motion.popover }),
  }));
  return (
    <Animated.View
      style={[s.collapsed, style]}
      pointerEvents={visible ? 'box-none' : 'none'}
      accessibilityElementsHidden={!visible}
      importantForAccessibility={visible ? 'auto' : 'no-hide-descendants'}
      aria-hidden={!visible}
    >
      <View style={s.navSide} />
      <View style={[s.navTitle, Platform.OS === 'ios' ? s.navTitleCentred : null]}>
        <Text
          role="titleSm"
          maxScale={scaleCap.navTitle}
          numberOfLines={1}
          align={Platform.OS === 'ios' ? 'center' : 'left'}
        >
          {title}
        </Text>
      </View>
      <View style={[s.navSide, s.navTrailing]}>
        {/* Only while shown: a hidden duplicate of the header's button would be a second target
            for the same action, reachable by a screen reader but not by a finger. */}
        {action && visible ? (
          <IconButton icon={action.icon} label={action.label} onPress={action.onPress} />
        ) : null}
      </View>
    </Animated.View>
  );
}

/** A scrolling page with pull to refresh on every one of them (§5.1). */
export function Scroll({
  children,
  padded = true,
  footerSpace = 0,
  refreshing,
  onRefresh,
  onScroll,
  scrollEventThrottle,
}: {
  children: ReactNode;
  padded?: boolean;
  /** Extra bottom padding, for a screen with a pinned action bar over it. */
  footerSpace?: number;
  refreshing?: boolean;
  onRefresh?: () => void;
  onScroll?: (e: NativeSyntheticEvent<NativeScrollEvent>) => void;
  scrollEventThrottle?: number;
}) {
  const s = useStyles();
  const insets = useSafeAreaInsets();
  const t = useTheme();
  return (
    <ScrollView
      style={s.scroll}
      contentContainerStyle={[
        padded ? s.scrollContent : null,
        { paddingBottom: t.space[32] + footerSpace + insets.bottom },
      ]}
      showsVerticalScrollIndicator={false}
      onScroll={onScroll}
      scrollEventThrottle={scrollEventThrottle}
      keyboardShouldPersistTaps="handled"
      refreshControl={onRefresh ? <ThemedRefresh refreshing={!!refreshing} onRefresh={onRefresh} /> : undefined}
    >
      <ContentWidth>{children}</ContentWidth>
    </ScrollView>
  );
}

/**
 * Pull to refresh in the theme's colours.
 *
 * Every other prop is passed through: a ScrollView clones its `refreshControl` and hands it the
 * scroll view itself as children (Android and the web wrap the list in the control), so a wrapper
 * that dropped them would render no list at all.
 */
export function ThemedRefresh({
  refreshing,
  onRefresh,
  ...rest
}: { refreshing: boolean; onRefresh: () => void } & Omit<RefreshControlProps, 'refreshing' | 'onRefresh'>) {
  const t = useTheme();
  return (
    <RefreshControl
      {...rest}
      refreshing={refreshing}
      onRefresh={onRefresh}
      tintColor={t.color.textMuted}
      colors={[t.color.accent]}
      progressBackgroundColor={t.color.surfaceRaised}
    />
  );
}

/** Content capped at 600pt and centred on a tablet or in landscape (§4.4). */
export function ContentWidth({ children, style }: { children: ReactNode; style?: ViewStyle }) {
  const { width } = useWindowDimensions();
  const t = useTheme();
  const wide = width > t.layout.maxContent + 2 * t.layout.gutter;
  return (
    <View style={[wide && { width: '100%', maxWidth: t.layout.maxContent, alignSelf: 'center' }, style]}>
      {children}
    </View>
  );
}

/** A section title, with an optional count after it and an optional trailing control. */
export function SectionTitle({
  title,
  count,
  trailing,
}: {
  title: string;
  count?: number;
  trailing?: ReactNode;
}) {
  const s = useStyles();
  return (
    <View style={s.sectionTitle}>
      <Text role="titleSm" accessibilityRole="header" style={s.sectionTitleText}>
        {title}
        {count !== undefined ? (
          <Text role="titleSm" tone="subtle" tabular>
            {`  ${count}`}
          </Text>
        ) : null}
      </Text>
      {trailing}
    </View>
  );
}

/** A titled group: 24 above it, 16 between its title and its first row (§4.4). */
export function Section({
  title,
  count,
  trailing,
  children,
  first = false,
}: {
  title?: string;
  count?: number;
  trailing?: ReactNode;
  children: ReactNode;
  first?: boolean;
}) {
  const t = useTheme();
  return (
    <View style={{ marginTop: first ? 0 : t.space[24] }}>
      {title ? <SectionTitle title={title} count={count} trailing={trailing} /> : null}
      {children}
    </View>
  );
}

/**
 * The offline bar (§2.6): neutral, never red, under the header of every screen while offline. It is
 * announced once when it appears.
 */
export function OfflineBar({ since }: { since: string | null }) {
  const s = useStyles();
  const text = since ? `Offline. Showing what was here at ${since}.` : 'Offline.';
  useEffect(() => {
    if (Platform.OS === 'ios') AccessibilityInfo.announceForAccessibility(text);
  }, [text]);
  return (
    <View style={s.offline} accessibilityLiveRegion="polite" accessibilityRole="text">
      <Icon name="info" size={16} />
      <Text role="caption" tone="muted" style={{ flex: 1 }}>
        {text}
      </Text>
    </View>
  );
}

const useStyles = makeStyles((t) => ({
  screen: { flex: 1, backgroundColor: t.color.bg },
  scroll: { flex: 1, backgroundColor: t.color.bg },
  scrollContent: { paddingHorizontal: t.layout.gutter },

  nav: {
    flexDirection: 'row',
    alignItems: 'center',
    minHeight: 48,
    paddingHorizontal: t.space[4],
  },
  navSide: { minWidth: 48, flexDirection: 'row', alignItems: 'center' },
  navTrailing: { justifyContent: 'flex-end' },
  navTitle: { flex: 1, paddingHorizontal: t.space[4] },
  navTitleCentred: { alignItems: 'center' },

  rootHeader: { gap: t.space[4], paddingTop: t.space[16], paddingBottom: t.space[16] },
  rootHeadRow: { flexDirection: 'row', alignItems: 'flex-start', gap: t.space[12] },
  rootTitle: { flex: 1 },

  collapsed: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    zIndex: 10,
    flexDirection: 'row',
    alignItems: 'center',
    minHeight: 48,
    paddingHorizontal: t.space[4],
    backgroundColor: t.color.bg,
    borderBottomWidth: 1,
    borderBottomColor: t.color.border,
  },

  sectionTitle: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    minHeight: 24,
    marginBottom: t.space[16],
    gap: t.space[12],
  },
  sectionTitleText: { flexShrink: 1 },

  offline: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: t.space[8],
    minHeight: 36,
    paddingHorizontal: t.layout.gutter,
    backgroundColor: t.color.fill,
    borderBottomWidth: 1,
    borderBottomColor: t.color.border,
  },
}));
