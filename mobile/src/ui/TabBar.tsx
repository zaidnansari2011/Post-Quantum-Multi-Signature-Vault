// The tab bar.
//
// Dark, because the product needs a spine. The web client puts its navigation rail on the same
// achromatic dark surface for the same reason: it separates "where you are in the product" from
// "what you are looking at", and it does so without introducing a brand hue that would then be
// competing with the status colours for meaning.
//
// A custom bar rather than the default one, for two reasons. The default renders a coloured active
// tint, and a saturated accent on a navigation control is exactly what rule one forbids -- so the
// active state here is expressed as weight and opacity instead. And the badge on Home carries a
// real count that has to match the queue, which means it needs the query, not a static option.
//
// Motion: the active tab's label and icon settle rather than jump, and there is no haptic. Moving
// between tabs is not an event in the world -- nothing became true because someone looked at their
// history -- so it gets the quietest response the system has.

import Feather from '@expo/vector-icons/Feather';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import type { BottomTabBarProps } from '@react-navigation/bottom-tabs';
import Animated, {
  useAnimatedStyle,
  useDerivedValue,
  useReducedMotion,
  withTiming,
} from 'react-native-reanimated';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { color, motion, space, type } from '../theme.ts';

type IconName = React.ComponentProps<typeof Feather>['name'];

const ICONS: Record<string, IconName> = {
  Home: 'inbox',
  Vaults: 'shield',
  Activity: 'clock',
  Account: 'user',
};

export function TabBar({ state, descriptors, navigation }: BottomTabBarProps) {
  const insets = useSafeAreaInsets();

  return (
    <View style={[s.bar, { paddingBottom: Math.max(space.sm, insets.bottom) }]}>
      {state.routes.map((route, index) => {
        const { options } = descriptors[route.key];
        const focused = state.index === index;
        const label =
          typeof options.tabBarLabel === 'string' ? options.tabBarLabel : options.title ?? route.name;

        function onPress() {
          const event = navigation.emit({ type: 'tabPress', target: route.key, canPreventDefault: true });
          if (!focused && !event.defaultPrevented) navigation.navigate(route.name);
        }

        return (
          <Tab
            key={route.key}
            label={label}
            icon={ICONS[route.name] ?? 'circle'}
            focused={focused}
            badge={options.tabBarBadge}
            onPress={onPress}
          />
        );
      })}
    </View>
  );
}

function Tab({
  label,
  icon,
  focused,
  badge,
  onPress,
}: {
  label: string;
  icon: IconName;
  focused: boolean;
  badge?: number | string;
  onPress: () => void;
}) {
  const reduced = useReducedMotion();
  const active = useDerivedValue(() =>
    reduced ? (focused ? 1 : 0) : withTiming(focused ? 1 : 0, { duration: motion.quick }),
  );

  const animated = useAnimatedStyle(() => ({ opacity: 0.55 + active.value * 0.45 }));

  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="tab"
      accessibilityState={{ selected: focused }}
      accessibilityLabel={label}
      style={s.tab}
      hitSlop={6}
    >
      <Animated.View style={[s.tabInner, animated]}>
        <View>
          <Feather name={icon} size={20} color={focused ? color.chromeInk : color.chromeInk2} />
          {badge ? (
            <View style={s.badge}>
              <Text style={s.badgeText}>{badge}</Text>
            </View>
          ) : null}
        </View>
        <Text style={[s.label, focused && s.labelActive]}>{label}</Text>
      </Animated.View>
    </Pressable>
  );
}

const s = StyleSheet.create({
  bar: {
    flexDirection: 'row',
    backgroundColor: color.chrome,
    borderTopWidth: 1,
    borderTopColor: color.chromeRule,
    paddingTop: space.sm,
  },
  tab: { flex: 1 },
  tabInner: { alignItems: 'center', gap: 4 },
  label: { ...type.micro, fontSize: 11, color: color.chromeInk2 },
  labelActive: { color: color.chromeInk },

  // `waiting` rather than a red dot: work you have not done is not an error, and this app should
  // not greet someone by telling them something is wrong.
  badge: {
    position: 'absolute',
    top: -5,
    right: -10,
    minWidth: 16,
    height: 16,
    borderRadius: 8,
    paddingHorizontal: 4,
    backgroundColor: color.waiting,
    alignItems: 'center',
    justifyContent: 'center',
  },
  badgeText: { fontSize: 10, lineHeight: 13, color: '#FFFFFF', fontWeight: '700' },
});
