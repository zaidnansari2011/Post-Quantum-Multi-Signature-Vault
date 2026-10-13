// A row with actions behind it (phone-ux §6.12): Activity's For you only, the one swipe in the app.
//
// Swiping left reveals the actions (GitHub's "Done": Mark read, Archive). A swipe is invisible to
// screen readers and to anyone who does not know it is there, so every action is also an
// accessibility action of the row itself ("Actions available"), and the inbox still works without
// either: opening an item marks it read, and the header marks them all.
//
// The actions sit beside the row's own target, never inside it (§4.6), each at least 48 high and
// 72 wide.

import { useRef, type ReactNode } from 'react';
import { View } from 'react-native';
import ReanimatedSwipeable, { type SwipeableMethods } from 'react-native-gesture-handler/ReanimatedSwipeable';

import { makeStyles, useTheme } from '../theme/index.ts';
import { Text } from './Text.tsx';
import { Touchable } from './Touchable.tsx';

export type SwipeAction = { key: string; label: string; onPress: () => void; tone?: 'neutral' | 'accent' };

export function SwipeRow({ actions, children }: { actions: SwipeAction[]; children: ReactNode }) {
  const s = useStyles();
  const t = useTheme();
  const ref = useRef<SwipeableMethods | null>(null);
  if (actions.length === 0) return <>{children}</>;
  return (
    <ReanimatedSwipeable
      ref={ref}
      friction={2}
      rightThreshold={40}
      overshootRight={false}
      containerStyle={s.container}
      renderRightActions={() => (
        <View style={s.actions}>
          {actions.map((a) => (
            <Touchable
              key={a.key}
              onPress={() => {
                ref.current?.close();
                a.onPress();
              }}
              accessibilityRole="button"
              accessibilityLabel={a.label}
              ringRadius={0}
              style={({ pressed }) => [
                s.action,
                { backgroundColor: a.tone === 'accent' ? t.color.accent : pressed ? t.color.fillActive : t.color.fill },
              ]}
            >
              <Text role="label" color={a.tone === 'accent' ? t.color.accentText : t.color.text} maxScale={1.4} numberOfLines={2} style={s.label}>
                {a.label}
              </Text>
            </Touchable>
          ))}
        </View>
      )}
    >
      {children}
    </ReanimatedSwipeable>
  );
}

const useStyles = makeStyles((t) => ({
  container: { backgroundColor: t.color.surface },
  actions: { flexDirection: 'row', alignItems: 'stretch' },
  action: { width: 84, minHeight: 48, alignItems: 'center', justifyContent: 'center', paddingHorizontal: t.space[8] },
  label: { textAlign: 'center' },
}));
