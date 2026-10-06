// The style tile's icons, drawn from the phone's icon font (phone-ux §2.2).
//
// tools/icons_from_tile.ts outlines the tile's 1.5 strokes into assets/fonts/QVaultIcons.ttf, so a
// glyph here is the same drawing the web uses, at any size, in any colour, with no native module.
// Icons are decorative by default: the control around one carries its accessible name.

import { Text as RNText, type TextStyle } from 'react-native';

import { fontFamily, useTheme } from '../theme/index.ts';
import { ICON_GLYPHS, type IconName } from '../theme/icons.generated.ts';

export type { IconName };

export function Icon({
  name,
  size = 20,
  color,
  style,
  scales = true,
}: {
  name: IconName;
  size?: number;
  /** Grows with the text size, up to 1.5x; off where the container is fixed (the tab bar). */
  scales?: boolean;
  /** A theme colour; defaults to the muted text colour. */
  color?: string;
  style?: TextStyle;
}) {
  const t = useTheme();
  const px = Math.round(size * (scales ? Math.min(Math.max(t.fontScale, 1), 1.5) : 1));
  return (
    <RNText
      accessible={false}
      importantForAccessibility="no"
      aria-hidden
      allowFontScaling={false}
      selectable={false}
      style={[
        {
          fontFamily: fontFamily.icons,
          fontSize: px,
          lineHeight: px,
          width: px,
          height: px,
          color: color ?? t.color.textMuted,
          textAlign: 'center',
          includeFontPadding: false,
        },
        style,
      ]}
    >
      {ICON_GLYPHS[name]}
    </RNText>
  );
}
