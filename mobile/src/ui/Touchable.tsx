// Every tappable thing in the app (phone-ux §4.6).
//
// A wrapper over Pressable that makes the hit area at least 48 x 48 (Material's 48dp covers
// Apple's 44pt): it measures its own visual size and adds hitSlop to make up the difference, at
// most 12 a side. A control drawn smaller than 24 cannot be rescued by slop and fails the harness's
// audit, which is the point: a bare 13pt link with an 8pt slop is a target nobody can hit.
//
// react-native-web ignores hitSlop, so a DOM walk cannot measure the real target. The effective
// size is therefore written to `data-hit-w` / `data-hit-h`, which the web harness audits.
//
// Nothing outside ui/ imports Pressable, and no tappable sits inside another (§4.6): a screen
// reader cannot reach the inner one.

import { forwardRef, useState, type ReactNode } from 'react';
import {
  Platform,
  Pressable,
  View,
  type LayoutChangeEvent,
  type PressableProps,
  type StyleProp,
  type ViewStyle,
} from 'react-native';

import { useTheme } from '../theme/index.ts';

const MIN = 48;
const MAX_SLOP = 12;

export type TouchState = { pressed: boolean; focused: boolean };

export type TouchableProps = Omit<PressableProps, 'hitSlop' | 'style' | 'children'> & {
  style?: StyleProp<ViewStyle> | ((state: TouchState) => StyleProp<ViewStyle>);
  children?: ReactNode | ((state: TouchState) => ReactNode);
  /** The corner radius of the focus ring, which sits 2pt outside the control. */
  ringRadius?: number;
};

export const Touchable = forwardRef<View, TouchableProps>(function Touchable(
  { style, children, onLayout, ringRadius = 10, onFocus, onBlur, ...rest },
  ref,
) {
  const t = useTheme();
  const [size, setSize] = useState<{ w: number; h: number } | null>(null);
  const [focused, setFocused] = useState(false);

  const slopX = size ? Math.min(MAX_SLOP, Math.max(0, (MIN - size.w) / 2)) : 0;
  const slopY = size ? Math.min(MAX_SLOP, Math.max(0, (MIN - size.h) / 2)) : 0;

  const measure = (e: LayoutChangeEvent) => {
    const { width, height } = e.nativeEvent.layout;
    if (!size || Math.abs(size.w - width) > 0.5 || Math.abs(size.h - height) > 0.5) {
      setSize({ w: width, h: height });
    }
    onLayout?.(e);
  };

  // Web only: React Native ignores dataSet, and it is the harness that reads it.
  const audit =
    Platform.OS === 'web' && size
      ? {
          dataSet: {
            hitW: String(Math.round(size.w + slopX * 2)),
            hitH: String(Math.round(size.h + slopY * 2)),
          },
        }
      : {};

  return (
    <Pressable
      ref={ref}
      {...rest}
      {...(audit as object)}
      hitSlop={{ top: slopY, bottom: slopY, left: slopX, right: slopX }}
      onLayout={measure}
      onFocus={(e) => {
        // On native, focus only ever comes from a hardware keyboard or a D-pad. On the web a tap
        // focuses too, so the ring follows :focus-visible there, as a browser's own outline does.
        const target = (e.nativeEvent as unknown as { target?: { matches?: (q: string) => boolean } })
          .target;
        setFocused(Platform.OS !== 'web' || target?.matches?.(':focus-visible') !== false);
        onFocus?.(e);
      }}
      onBlur={(e) => {
        setFocused(false);
        onBlur?.(e);
      }}
      style={({ pressed }) => [
        typeof style === 'function' ? style({ pressed, focused }) : style,
        // react-native-web draws its own outline on focus; the ring below replaces it.
        Platform.OS === 'web' ? ({ outlineStyle: 'none' } as unknown as ViewStyle) : null,
      ]}
    >
      {({ pressed }) => (
        <>
          {typeof children === 'function' ? children({ pressed, focused }) : children}
          {focused ? (
            <View
              pointerEvents="none"
              style={{
                position: 'absolute',
                top: -4,
                left: -4,
                right: -4,
                bottom: -4,
                borderRadius: ringRadius + 4,
                borderWidth: 2,
                borderColor: t.color.focus,
              }}
            />
          ) : null}
        </>
      )}
    </Pressable>
  );
});
