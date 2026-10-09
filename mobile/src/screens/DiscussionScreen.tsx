// A decision's discussion (phone-ux §6.21, R5): the thread, oldest first, pushed over the decision.
//
// Comments are unsigned, and the screen says so at the top: "Not part of what's signed". They are
// set in sans, never the serif that means "this is what you sign", never inside a signing sheet,
// and nothing in them is made a link: a comment saying "the real address is 0x..." is a social
// engineering vector (I-15). A mention is drawn only where the server resolved one.
//
// The phone reads the thread; adding a comment is on the web for now (the API is read only), and
// the page says so with a way there.

import { Linking, View } from 'react-native';
import { useQuery } from '@tanstack/react-query';

import {
  Avatar,
  Banner,
  Button,
  EmptyState,
  NavBar,
  Screen,
  Scroll,
  Skeleton,
  Text,
} from '../ui/index.tsx';
import { makeStyles } from '../theme/index.ts';
import { useEnrolledSession } from '../session.tsx';
import { getApiBaseUrl } from '../config.ts';
import type { Comment } from '../api/schemas.ts';
import { OfflineNotice, useRefreshOnFocus } from '../freshness.tsx';
import { commentsQuery, keys, proposalQuery } from '../queries.ts';
import { whenYouDid } from '../logic/words.ts';

export default function DiscussionScreen({ uuid, title, onBack }: { uuid: string; title?: string; onBack: () => void }) {
  const s = useStyles();
  const { token } = useEnrolledSession();
  const query = useQuery(commentsQuery(token, uuid));
  useRefreshOnFocus([keys.comments(uuid)]);
  const decision = useQuery({ ...proposalQuery(token, uuid), enabled: false });
  const vaultId = decision.data?.proposal.vault_id;
  const webUrl = vaultId ? `${getApiBaseUrl()}/vaults/${vaultId}/proposals/${uuid}#discussion` : null;
  const now = Date.now();
  const comments = query.data?.comments ?? [];

  return (
    <Screen edges={['top', 'bottom']}>
      <NavBar onBack={onBack} title="Discussion" />
      <OfflineNotice at={query.dataUpdatedAt} />
      <Scroll refreshing={query.isRefetching} onRefresh={() => void query.refetch()}>
        <View style={s.stack}>
          <View style={s.head}>
            {title ? (
              <Text role="titleSm" numberOfLines={2}>
                {title}
              </Text>
            ) : null}
            <Text role="caption" tone="muted">
              {"Not part of what's signed. Anyone who can open this decision can read it."}
            </Text>
          </View>

          {query.isLoading ? (
            <View style={s.skeleton}>
              <Skeleton width="40%" height={14} />
              <Skeleton width="90%" height={16} />
              <Skeleton width="40%" height={14} />
              <Skeleton width="75%" height={16} />
            </View>
          ) : query.isError && !query.data ? (
            <Banner
              tone="warning"
              title="Can't load the discussion"
              detail="Check your connection and try again."
              actions={[{ label: 'Try again', onPress: () => void query.refetch() }]}
            />
          ) : comments.length === 0 ? (
            <EmptyState title="No one has commented yet." />
          ) : (
            <View style={s.thread}>
              {comments.map((c) => (
                <CommentRow key={c.id} comment={c} now={now} />
              ))}
            </View>
          )}

          <View style={s.post}>
            <Text role="caption" tone="muted">
              Comments are added on the web for now.
            </Text>
            {webUrl ? (
              <Button label="Comment on the web" variant="secondary" onPress={() => void Linking.openURL(webUrl).catch(() => {})} />
            ) : null}
          </View>
        </View>
      </Scroll>
    </Screen>
  );
}

function CommentRow({ comment, now }: { comment: Comment; now: number }) {
  const s = useStyles();
  const name = comment.author.name ?? 'Someone';
  const when = whenYouDid(comment.created_at, now);
  const spoken = comment.deleted ? `${name}. This comment was deleted.` : `${name}${when ? `, ${when}` : ''}. ${comment.body}`;
  return (
    <View style={s.comment} accessible accessibilityLabel={spoken}>
      <Avatar name={name} />
      <View style={s.flex}>
        <View style={s.byline}>
          <Text role="bodyStrong" style={s.flex} numberOfLines={1}>
            {comment.mine ? `${name} (you)` : name}
          </Text>
          {when ? (
            <Text role="caption" tone="muted" tabular>
              {when}
            </Text>
          ) : null}
        </View>
        {comment.deleted ? (
          <Text role="body" tone="subtle">
            This comment was deleted.
          </Text>
        ) : (
          // Plain text, never links; a resolved mention in the strong weight, not a link either.
          <Text role="body" selectable>
            {(comment.segments ?? [{ text: comment.body, mention: undefined }]).map((part, i) =>
              part.mention ? (
                <Text key={i} role="bodyStrong">
                  {part.text}
                </Text>
              ) : (
                part.text
              ),
            )}
          </Text>
        )}
      </View>
    </View>
  );
}

const useStyles = makeStyles((t) => ({
  flex: { flex: 1 },
  stack: { gap: t.space[24], paddingTop: t.space[8] },
  head: { gap: t.space[4] },
  skeleton: { gap: t.space[12] },
  thread: { gap: t.space[20] },
  comment: { flexDirection: 'row', gap: t.space[12], alignItems: 'flex-start' },
  byline: { flexDirection: 'row', alignItems: 'baseline', gap: t.space[8] },
  post: { gap: t.space[8], alignItems: 'flex-start' },
}));
