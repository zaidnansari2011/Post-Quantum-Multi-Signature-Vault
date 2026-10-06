// The tab bar (phone-ux §2.2).
//
// Navy in light mode, part of the app's identity; in dark it becomes the second neutral, so it is
// no longer a separate slab. The tile's own icons: filled when active (the HIG asks for filled
// active tab icons), outline otherwise. Inactive labels are `chrome.textMuted` at full opacity: the
// old 55% opacity measured about 2.9:1, and this is 5.6:1 light and 4.6:1 dark.
//
// The badge counts what this phone can sign, read from the same query as the queue, and is part of
// the tab's spoken name ("Approvals, 3 need your signature").

import { View } from 'react-native';
import type { BottomTabBarProps } from '@react-navigation/bottom-tabs';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { makeStyles, scaleCap, useTheme } from '../theme/index.ts';
import { Icon, type IconName } from './Icon.tsx';
import { Text } from './Text.tsx';
import { Touchable } from './Touchable.tsx';

const ICONS: Record<string, [IconName, IconName]> = {
  Home: ['inbox', 'inbox-fill'],
  Vaults: ['vault', 'vault-fill'],
  Activity: ['pulse', 'pulse-fill'],
  Account: ['user', 'user-fill'],
};

export function TabBar({ state, descriptors, navigation }: BottomTabBarProps) {
  const s = useStyles();
  const insets = useSafeAreaInsets();
  return (
    <View style={[s.bar, { paddingBottom: insets.bottom }]} accessibilityRole="tablist">
      {state.routes.map((route, index) => {
        const { options } = descriptors[route.key];
        const focused = state.index === index;
        const label =
          typeof options.tabBarLabel === 'string' ? options.tabBarLabel : (options.title ?? route.name);
        const onPress = () => {
          const event = navigation.emit({ type: 'tabPress', target: route.key, canPreventDefault: true });
          if (!focused && !event.defaultPrevented) navigation.navigate(route.name);
        };
        return (
          <Tab
            key={route.key}
            label={label}
            icons={ICONS[route.name] ?? ['inbox', 'inbox-fill']}
            focused={focused}
            badge={options.tabBarBadge}
            onPress={onPress}
          />
        );
      })}
    </View>
  );
}

export function Tab({
  label,
  icons,
  focused,
  badge,
  dot,
  onPress,
}: {
  label: string;
  icons: [IconName, IconName];
  focused: boolean;
  badge?: number | string;
  /** Activity's unread dot: a cue, never a number. */
  dot?: boolean;
  onPress: () => void;
}) {
  const t = useTheme();
  const s = useStyles();
  const count = typeof badge === 'number' ? (badge > 99 ? '99+' : String(badge)) : badge;
  const spoken =
    label === 'Approvals' && count
      ? `${label}, ${count} need${count === '1' ? 's' : ''} your signature`
      : dot
        ? `${label}, new updates`
        : label;
  return (
    <Touchable
      onPress={onPress}
      accessibilityRole="tab"
      accessibilityState={{ selected: focused }}
      accessibilityLabel={spoken}
      ringRadius={8}
      style={s.tab}
    >
      <View>
        <Icon
          name={focused ? icons[1] : icons[0]}
          size={24}
          scales={false}
          color={focused ? t.color.chrome.text : t.color.chrome.textMuted}
        />
        {count ? (
          <View style={s.badge}>
            <Text role="label" color={t.color.chrome.badgeText} maxScale={scaleCap.tab} style={s.badgeText} tabular>
              {count}
            </Text>
          </View>
        ) : dot ? (
          <View style={s.dot} />
        ) : null}
      </View>
      <Text
        role="label"
        maxScale={scaleCap.tab}
        color={focused ? t.color.chrome.text : t.color.chrome.textMuted}
        style={focused ? s.labelActive : null}
        numberOfLines={1}
      >
        {label}
      </Text>
    </Touchable>
  );
}

const useStyles = makeStyles((t) => ({
  bar: {
    flexDirection: 'row',
    backgroundColor: t.color.chrome.bg,
    borderTopWidth: 1,
    borderTopColor: t.color.chrome.border,
  },
  tab: { flex: 1, minHeight: 49, alignItems: 'center', justifyContent: 'center', gap: 2, paddingTop: 6, paddingBottom: 4 },
  labelActive: { fontFamily: t.type.bodyStrong.fontFamily },
  badge: {
    position: 'absolute',
    top: -4,
    left: 14,
    minWidth: 18,
    minHeight: 18,
    borderRadius: 9,
    paddingHorizontal: 5,
    backgroundColor: t.color.chrome.badgeBg,
    alignItems: 'center',
    justifyContent: 'center',
  },
  badgeText: { fontFamily: t.type.bodyStrong.fontFamily },
  dot: {
    position: 'absolute',
    top: -1,
    right: -3,
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: t.color.chrome.dot,
  },
}));
