// Font loading.
//
// Two families, five faces. That is more bytes than a system-font app would ship, and it is the
// right trade here: the serif/sans split is not decoration, it is how a reader tells the decision
// apart from the apparatus describing it, and a system stack cannot express that distinction on
// both platforms.
//
// The app renders nothing until these resolve. A flash of the fallback face would reflow every
// screen, and on the decision screen that means the sentence someone is reading jumps under their
// eyes at the moment they are deciding whether to sign it.

// Imported per weight, not from the package root. The root barrel re-exports every face the family
// ships -- nine weights in roman and italic -- and Metro bundles an asset it can see a require for,
// so the barrel form put 34 .ttf files into the build when this app uses five. That is around 2MB,
// and it is 2MB in every over-the-air update as well as in the APK.
import { useFonts } from 'expo-font';
import { SourceSerif4_400Regular } from '@expo-google-fonts/source-serif-4/400Regular';
import { SourceSerif4_600SemiBold } from '@expo-google-fonts/source-serif-4/600SemiBold';
import { PublicSans_400Regular } from '@expo-google-fonts/public-sans/400Regular';
import { PublicSans_500Medium } from '@expo-google-fonts/public-sans/500Medium';
import { PublicSans_600SemiBold } from '@expo-google-fonts/public-sans/600SemiBold';

export function useAppFonts(): boolean {
  const [loaded, error] = useFonts({
    SourceSerif4_400Regular,
    SourceSerif4_600SemiBold,
    PublicSans_400Regular,
    PublicSans_500Medium,
    PublicSans_600SemiBold,
  });

  // A font that fails to load must not hold the app hostage -- an approver stuck behind a spinner
  // because a typeface did not decode is a worse failure than one looking at a fallback face.
  return loaded || error != null;
}
