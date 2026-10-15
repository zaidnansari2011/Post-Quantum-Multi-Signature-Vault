// Treasury approvals (phone-ux §6.18): which key treasuries hold for you, the password key the web
// uses or this phone's (D37). This is where "Approve treasury payments on this phone" lands, from
// the Approvals group and from a payment the phone can't sign (§6.3, §6.6 row 7): it then opens with
// this phone's key chosen, and says honestly that it applies at the next treasury update.

import { useState } from 'react';
import { View } from 'react-native';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  ActionBar,
  Button,
  Icon,
  InlineMessage,
  List,
  ListRow,
  NavBar,
  Screen,
  Scroll,
  Sheet,
  Skeleton,
  Text,
} from '../../ui/index.tsx';
import { makeStyles, useTheme } from '../../theme/index.ts';
import { useEnrolledSession } from '../../session.tsx';
import * as api from '../../api/endpoints.ts';
import { keys, meQuery } from '../../queries.ts';
import { useApprovals } from '../../approvals.ts';
import { capitalise, countWord } from '../../logic/words.ts';

type Choice = 'password' | 'device';

const CONSEQUENCE =
  "This applies to the next treasury set up or updated. Treasuries that already hold your other key keep it until they're updated.";

export default function TreasuryApprovalsScreen({ onBack, fromPayment }: { onBack: () => void; fromPayment?: boolean }) {
  const s = useStyles();
  const t = useTheme();
  const { token } = useEnrolledSession();
  const queryClient = useQueryClient();
  const me = useQuery(meQuery(token));
  const queue = useApprovals();
  const current: Choice | null = me.data?.my_key ? (me.data.my_key.custody === 'device' ? 'device' : 'password') : null;
  const [choice, setChoice] = useState<Choice | null>(fromPayment ? 'device' : null);
  const [confirming, setConfirming] = useState(false);
  const picked = choice ?? current;
  const waiting = Object.values(queue.seats).filter((seat) => seat?.kind === 'password').length;

  const save = useMutation({
    mutationFn: (custody: Choice) => api.setSigningChoice({ token, custody }),
    onSuccess: () => {
      setConfirming(false);
      setChoice(null);
      void queryClient.invalidateQueries({ queryKey: keys.me });
    },
  });

  const option = (value: Choice, title: string, caption: string | null) => (
    <ListRow
      key={value}
      title={title}
      caption={caption}
      leading={
        picked === value ? <Icon name="check" size={20} color={t.color.accent} /> : <View style={s.checkSpace} />
      }
      accessibilityLabel={`${title}${picked === value ? ', chosen' : ''}`}
      onPress={() => setChoice(value)}
    />
  );

  return (
    <Screen>
      <NavBar onBack={onBack} title="Treasury approvals" />
      <Scroll>
        <View style={s.stack}>
          {fromPayment && waiting > 0 ? (
            <Text role="body">
              {`${capitalise(countWord(waiting))} ${waiting === 1 ? 'payment is' : 'payments are'} waiting for your password key. After an owner updates the treasury, they come to this phone.`}
            </Text>
          ) : null}
          <Text role="titleSm" accessibilityRole="header">
            Which key should treasuries hold for you?
          </Text>
          {me.isLoading ? (
            <Skeleton width="100%" height={112} radius={12} />
          ) : !me.data?.my_key ? (
            <Text role="body" tone="muted">
              This Q-Vault has no treasuries, so there is nothing to choose.
            </Text>
          ) : (
            <List>
              {option('password', 'Password key on the web', null)}
              {option('device', "This phone's key", 'Payments are then approved only from this phone.')}
            </List>
          )}
          <Text role="body" tone="muted">
            {CONSEQUENCE}
          </Text>
          {me.data?.my_key && !me.data.my_key.usable ? (
            <InlineMessage tone="critical" text="The key chosen now can't sign. Choose again." />
          ) : null}
        </View>
      </Scroll>

      {picked && current && picked !== current ? (
        <ActionBar
          primary={{
            label: picked === 'device' ? "Use this phone's key" : 'Use my password key',
            onPress: () => setConfirming(true),
          }}
        />
      ) : null}

      <Sheet
        visible={confirming}
        onClose={() => !save.isPending && setConfirming(false)}
        dismissible={!save.isPending}
        title={picked === 'device' ? "Use this phone's key?" : 'Use your password key?'}
        footer={
          <>
            {save.isError ? <InlineMessage tone="warning" text="Q-Vault didn't make the change. Try again." /> : null}
            <Button
              label={picked === 'device' ? "Use this phone's key" : 'Use my password key'}
              onPress={() => picked && save.mutate(picked)}
              busy={save.isPending}
              full
            />
            <Button label="Cancel" variant="quiet" onPress={() => setConfirming(false)} disabled={save.isPending} full />
          </>
        }
      >
        <Text role="body">{CONSEQUENCE}</Text>
      </Sheet>
    </Screen>
  );
}

const useStyles = makeStyles((t) => ({
  stack: { gap: t.space[16], paddingTop: t.space[8] },
  checkSpace: { width: 20 },
}));
