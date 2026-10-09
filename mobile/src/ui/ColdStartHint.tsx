// The cold-start hint (phone-ux §2.6): under the headline or skeleton while a first answer is late.
// After 4 s, one caption; after 20 s, "Try again" joins it. Before 4 s, nothing at all: most
// answers arrive by then, and a caption that flashes is noise.

import { View } from 'react-native';

import { COLD_START_CAPTION, type ColdStartStage } from '../logic/freshness.ts';
import { makeStyles } from '../theme/index.ts';
import { Button } from './Button.tsx';
import { Text } from './Text.tsx';

export function ColdStartHint({ stage, onRetry }: { stage: ColdStartStage; onRetry?: () => void }) {
  const s = useStyles();
  if (stage === 'none') return null;
  return (
    <View style={s.hint} accessibilityLiveRegion="polite">
      <Text role="caption" tone="muted">
        {COLD_START_CAPTION}
      </Text>
      {stage === 'retry' && onRetry ? <Button label="Try again" variant="secondary" onPress={onRetry} /> : null}
    </View>
  );
}

const useStyles = makeStyles((t) => ({
  hint: { gap: t.space[12], alignItems: 'flex-start', paddingVertical: t.space[8] },
}));
