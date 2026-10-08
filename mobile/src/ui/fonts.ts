// Font loading (phone-ux §4.2).
//
// Three faces, a job each: Public Sans for the interface, Source Serif 4 for the signed text only,
// JetBrains Mono for hashes, keys and addresses only; plus the icon font outlined from the style
// tile. Source Serif 600 is gone: nothing is bold serif.
//
// Imported per weight, not from the package roots: a root barrel re-exports every face its family
// ships, and Metro bundles every asset it can see a require for. All of these load at runtime
// through expo-font, so they ship over the air.
//
// The app renders nothing until they resolve, since a fallback face would reflow the decision
// under the reader's eyes; a font that fails to load does not hold the app hostage either.

import { useFonts } from 'expo-font';
import { JetBrainsMono_400Regular } from '@expo-google-fonts/jetbrains-mono/400Regular';
import { JetBrainsMono_500Medium } from '@expo-google-fonts/jetbrains-mono/500Medium';
import { PublicSans_400Regular } from '@expo-google-fonts/public-sans/400Regular';
import { PublicSans_500Medium } from '@expo-google-fonts/public-sans/500Medium';
import { PublicSans_600SemiBold } from '@expo-google-fonts/public-sans/600SemiBold';
import { SourceSerif4_400Regular } from '@expo-google-fonts/source-serif-4/400Regular';

export function useAppFonts(): boolean {
  const [loaded, error] = useFonts({
    PublicSans_400Regular,
    PublicSans_500Medium,
    PublicSans_600SemiBold,
    SourceSerif4_400Regular,
    JetBrainsMono_400Regular,
    JetBrainsMono_500Medium,
    QVaultIcons: require('../../assets/fonts/QVaultIcons.ttf'),
  });
  return loaded || error != null;
}
