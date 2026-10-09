// New decision (phone-ux §6.16): raise a decision in under a minute, and know who will approve it
// before raising. A modal: a task with a Close, not a place.
//
// Top to bottom: the vault (a row that opens a picker of the vaults you can raise in, the last one
// you used remembered); the type first, because it decides the rest (General, Payment where the
// vault has a treasury, Production access; a Contract with a file is raised on the web); its
// fields; an honest deadline, resolved to the time it shows; and who approves (S14), with the
// separation of duties sentence when it applies.
//
// A General decision raises straight from the bar: the text being signed is on screen above the
// button. A payment goes through "Check this payment" first: amount and address deserve a second
// look, and a payment can't be reversed (D13). Nothing is disabled in advance: pressing shows what
// is missing, under the field (§1.4 rule 6).
//
// After raising, the decision replaces this form, carrying what was entered in memory, and the
// decision screen checks the server stored exactly that (I-5). Raising is not signing: no haptic.

import { useEffect, useMemo, useState } from 'react';
import { KeyboardAvoidingView, Platform, ScrollView, View } from 'react-native';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigation, usePreventRemove } from '@react-navigation/native';

import {
  ActionBar,
  Button,
  ChipGroup,
  ContentWidth,
  Field,
  GroupedValue,
  Icon,
  KeyValue,
  List,
  ListRow,
  NavBar,
  Screen,
  Segmented,
  Sheet,
  Skeleton,
  Text,
  TextArea,
} from '../ui/index.tsx';
import { makeStyles, useTheme } from '../theme/index.ts';
import { useEnrolledSession } from '../session.tsx';
import * as api from '../api/endpoints.ts';
import { ApiError, TransportError } from '../api/client.ts';
import { isOffline } from '../connectivity.ts';
import { formatEth, parseEth } from '../crypto/signing.ts';
import { middleOut } from '../format.ts';
import { OfflineNotice } from '../freshness.tsx';
import { OFFLINE_RAISE } from '../logic/freshness.ts';
import { meQuery, treasuryQuery, vaultQuery, vaultsQuery } from '../queries.ts';
import { describeRaiseRefusal } from '../proposing.ts';
import { ADDRESS_MESSAGES, addressProblem } from '../logic/address.ts';
import { ACCESS_LEVELS, checkFields } from '../logic/decisionTypes.ts';
import {
  defaultDeadline,
  deadlineOptions,
  dueCaption,
  hoursUntil,
  untilOptions,
  utcMinute,
  type DeadlineKey,
} from '../logic/deadline.ts';
import type { RaisedFields } from '../logic/raised.ts';
import { canRaiseIn, ruleSentence, whoApproves } from '../logic/workspace.ts';

type Kind = 'general' | 'payment' | 'access';

/** "Raise again" (S16): the closed decision this one replaces, and what to start from. */
export type AgainFrom = {
  uuid: string;
  title: string;
  vaultId: number;
  vaultName: string;
  kind: Kind;
  text?: string;
  fields?: Record<string, string>;
  payment?: { to: string; valueWei: string };
};

/** The vault last raised in, for the next form opened from the queue (§6.16 "Entry"). */
let lastVault: { id: number; name: string } | null = null;

const TEXT_MAX = 4000;

/** A field rule broken, in the words the web's form uses. */
const ACCESS_PROBLEMS: Record<string, string> = {
  missing: 'This is needed.',
  too_long: "That's too long.",
  line_break: 'Keep it to one line.',
  hidden_character: 'Remove the hidden character.',
  spacing: 'Use single ordinary spaces, with none at either end.',
  quote_mark: "Leave out double quotation marks: the text puts each value in quotes itself.",
  label_in_value: "It can't contain another field's label followed by a colon.",
  datetime: 'Choose when access ends.',
};

export default function NewDecisionScreen({
  vaultId: initialVaultId,
  vaultName: initialVaultName,
  again,
  onClose,
  onRaised,
}: {
  vaultId?: number | null;
  vaultName?: string | null;
  again?: AgainFrom;
  onClose: () => void;
  onRaised: (uuid: string, raised: RaisedFields) => void;
}) {
  const s = useStyles();
  const t = useTheme();
  const { token, identity } = useEnrolledSession();
  const queryClient = useQueryClient();
  const navigation = useNavigation();

  const vaults = useQuery(vaultsQuery(token));
  const me = useQuery(meQuery(token));
  const raisable = (vaults.data?.vaults ?? []).filter((v) => canRaiseIn(v.role, me.data?.workspace));
  const [chosen, setChosen] = useState<{ id: number; name: string } | null>(
    initialVaultId != null
      ? { id: initialVaultId, name: initialVaultName ?? '' }
      : again
        ? { id: again.vaultId, name: again.vaultName }
        : lastVault,
  );
  // With one vault to choose from, it is the vault.
  const vault = chosen ?? (raisable.length === 1 ? { id: raisable[0]!.vault_id, name: raisable[0]!.name } : null);
  const vaultSummary = (vaults.data?.vaults ?? []).find((v) => v.vault_id === vault?.id);
  const detail = useQuery({ ...vaultQuery(token, vault?.id ?? 0), enabled: vault !== null });
  const treasury = useQuery({ ...treasuryQuery(token, vault?.id ?? 0), enabled: vault !== null });
  const hasTreasury = !!treasury.data?.treasury;

  const [kind, setKind] = useState<Kind>(again?.kind ?? 'general');
  const [title, setTitle] = useState(again ? again.title : '');
  const [text, setText] = useState(again?.text ?? '');
  const [amount, setAmount] = useState(again?.payment ? formatEth(again.payment.valueWei).replace(/ ETH$/, '') : '');
  const [to, setTo] = useState(again?.payment?.to ?? '');
  const [toChecked, setToChecked] = useState(!!again?.payment);
  const [person, setPerson] = useState(again?.fields?.person ?? '');
  const [system, setSystem] = useState(again?.fields?.system ?? '');
  const [level, setLevel] = useState<string>(again?.fields?.level ?? 'read');
  const [untilKey, setUntilKey] = useState<DeadlineKey>('tomorrow');
  const [reason, setReason] = useState(again?.fields?.reason ?? '');
  const [reference, setReference] = useState(again?.fields?.reference ?? '');
  const [deadline, setDeadline] = useState<DeadlineKey>(defaultDeadline(again?.kind ?? 'general'));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [barMessage, setBarMessage] = useState<{ tone: 'neutral' | 'warning' | 'critical'; text: string } | null>(null);
  const [picking, setPicking] = useState(false);
  const [reviewing, setReviewing] = useState(false);
  const [discard, setDiscard] = useState<{ action: unknown } | null>(null);
  const [raised, setRaised] = useState(false);
  // Where to go once the form may be left: the new decision, or wherever Discard was taking it.
  const [leaving, setLeaving] = useState<{ uuid: string; fields: RaisedFields } | { action: unknown } | null>(null);

  const now = Date.now();
  const effectiveKind: Kind = kind === 'payment' && !hasTreasury && treasury.isSuccess ? 'general' : kind;
  const options = deadlineOptions(now, effectiveKind);
  const chosenDeadline = options.find((o) => o.value === deadline) ?? options.find((o) => o.value === defaultDeadline(effectiveKind))!;
  const untils = untilOptions(now);
  const until = untils.find((o) => o.value === untilKey) ?? untils[0]!;

  const normalisedAmount = amount.trim().replace(',', '.');
  const valueWei = parseEth(normalisedAmount);
  const balanceWei = treasury.data?.status?.balance_wei ?? null;
  const overBalance = valueWei !== null && balanceWei !== null && BigInt(valueWei) > BigInt(balanceWei);

  const dirty =
    !raised &&
    (title.trim() !== (again?.title ?? '') ||
      text.trim() !== (again?.text ?? '') ||
      amount.trim() !== '' ||
      to.trim() !== (again?.payment?.to ?? '') ||
      person.trim() !== (again?.fields?.person ?? '') ||
      system.trim() !== (again?.fields?.system ?? '') ||
      reason.trim() !== (again?.fields?.reason ?? ''));
  // Leaving with something typed asks first: Back, a swipe, the hardware back (§2.3).
  usePreventRemove(dirty, ({ data }) => setDiscard({ action: data.action }));
  // Only once the guard above has let go (`dirty` is false), so leaving never asks twice.
  useEffect(() => {
    if (!leaving || dirty) return;
    if ('uuid' in leaving) onRaised(leaving.uuid, leaving.fields);
    else navigation.dispatch(leaving.action as never);
  }, [leaving, dirty, navigation, onRaised]);

  const accessFields = (): Record<string, string> => {
    const f: Record<string, string> = {
      person: person.trim(),
      system: system.trim(),
      level,
      until: utcMinute(until.at!),
      reason: reason.trim(),
    };
    if (reference.trim()) f.reference = reference.trim();
    return f;
  };

  const who = useMemo(() => {
    const d = detail.data?.vault;
    if (!d) return null;
    return whoApproves(d.members, d.threshold_m, d.separation_of_duties, identity.userId);
  }, [detail.data, identity.userId]);

  /** What is missing, said under each field; empty when the form can go. */
  const validate = (): Record<string, string> => {
    const e: Record<string, string> = {};
    if (!vault) e.vault = 'Choose the vault this decision is for.';
    if (effectiveKind === 'general') {
      if (!title.trim()) e.title = 'Give this decision a title.';
      if (!text.trim()) e.text = 'Write what everyone signs.';
      else if (text.trim().length > TEXT_MAX) e.text = `Keep it to ${TEXT_MAX.toLocaleString('en-GB')} characters.`;
    } else if (effectiveKind === 'payment') {
      if (valueWei === null || valueWei === '0') e.amount = 'Enter an amount in ETH, like 0.25.';
      const problem = addressProblem(to);
      if (problem) e.to = ADDRESS_MESSAGES[problem];
    } else {
      const problem = checkFields('access', accessFields());
      if (problem && problem.field) e[problem.field] = ACCESS_PROBLEMS[problem.code] ?? 'Check this.';
      else if (problem) e.person = 'Check these fields.';
    }
    return e;
  };

  const titleFor = (): string => {
    if (title.trim()) return title.trim();
    if (effectiveKind === 'payment' && valueWei) return `Pay ${formatEth(valueWei)} to ${middleOut(to.trim())}`;
    if (effectiveKind === 'access') return `Production access for ${person.trim()} to ${system.trim()}`;
    return title.trim();
  };

  const raise = useMutation({
    mutationFn: async () => {
      const typed = effectiveKind === 'access' ? { type: 'access', fields: accessFields() } : null;
      const result = await api.createProposal({
        token,
        vaultId: vault!.id,
        title: titleFor(),
        actionText: effectiveKind === 'general' ? text.trim() : '',
        expiresInHours: hoursUntil(chosenDeadline.at, Date.now()),
        payment: effectiveKind === 'payment' ? { to: to.trim(), valueWei: valueWei! } : null,
        typed,
        raisedAgainFrom: again?.uuid ?? null,
      });
      const raisedFields: RaisedFields =
        effectiveKind === 'payment'
          ? { kind: 'payment', to: to.trim(), valueWei: valueWei!, treasury: treasury.data?.treasury?.address ?? null }
          : typed
            ? { kind: 'typed', type: typed.type, fields: typed.fields }
            : { kind: 'general', text: text.trim() };
      return { uuid: result.proposal.proposal_uuid, raisedFields };
    },
    onSuccess: ({ uuid, raisedFields }) => {
      lastVault = vault;
      setRaised(true);
      setReviewing(false);
      void queryClient.invalidateQueries({ queryKey: ['proposals'] });
      void queryClient.invalidateQueries({ queryKey: ['vaults'] });
      if (vault) void queryClient.invalidateQueries({ queryKey: ['vault', vault.id] });
      setLeaving({ uuid, fields: raisedFields });
    },
    onError: (err) => {
      setReviewing(false);
      if (err instanceof TransportError && isOffline()) {
        setBarMessage({ tone: 'neutral', text: OFFLINE_RAISE });
        return;
      }
      if (err instanceof ApiError && err.code === 'fields_invalid') {
        // The server's own sentence for the field it named (the web form's words).
        setErrors({ person: err.message });
        return;
      }
      const refusal = describeRaiseRefusal(err);
      setBarMessage({ tone: 'warning', text: refusal.detail ? `${refusal.title} ${refusal.detail}` : refusal.title });
    },
  });

  const submit = () => {
    setBarMessage(null);
    const e = validate();
    setErrors(e);
    if (Object.keys(e).length > 0) return;
    if (effectiveKind === 'payment') setReviewing(true);
    else raise.mutate();
  };

  const kinds: Array<{ value: Kind; label: string }> = [
    { value: 'general', label: 'General' },
    ...(hasTreasury ? [{ value: 'payment' as const, label: 'Payment' }] : []),
    { value: 'access', label: 'Access' },
  ];

  return (
    <Screen>
      <NavBar onBack={onClose} backIcon="x" backLabel="Close" title={again ? 'Raise again' : 'New decision'} />
      <OfflineNotice at={undefined} />

      <KeyboardAvoidingView style={s.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView
          style={s.flex}
          contentContainerStyle={s.content}
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
        >
          <ContentWidth style={s.stack}>
            <View style={s.group}>
              <List>
                <ListRow
                  icon="vault"
                  title={vault ? vault.name || vaultSummary?.name || 'Vault' : 'Choose a vault'}
                  caption={
                    vaultSummary
                      ? ruleSentence(vaultSummary.threshold_m, vaultSummary.signer_count)
                      : vault
                        ? null
                        : 'Only vaults where you can raise decisions'
                  }
                  captionTone={errors.vault ? 'critical' : 'muted'}
                  onPress={raisable.length > 1 || !vault ? () => setPicking(true) : undefined}
                  accessibilityHint={raisable.length > 1 ? 'Changes the vault' : undefined}
                />
              </List>
              {errors.vault ? <Text role="caption" tone="critical">{errors.vault}</Text> : null}
              {again ? (
                <Text role="caption" tone="muted">
                  {`Replaces "${again.title}". Signatures don't carry over.`}
                </Text>
              ) : null}
            </View>

            <View style={s.group}>
              <Segmented label="Type" options={kinds} value={effectiveKind} onChange={(k) => {
                setKind(k);
                setErrors({});
                setDeadline(defaultDeadline(k));
              }} />
              <Text role="caption" tone="muted">
                Contracts with a file are raised on the web.
              </Text>
            </View>

            {effectiveKind === 'general' ? (
              <View>
                <Field
                  label="Title"
                  value={title}
                  onChangeText={setTitle}
                  placeholder="Rotate the on-call paging credentials"
                  autoCapitalize="sentences"
                  maxLength={255}
                  error={errors.title}
                />
                <TextArea
                  label="What everyone signs"
                  value={text}
                  onChangeText={setText}
                  placeholder="Say exactly what approving authorises."
                  autoCapitalize="sentences"
                  error={errors.text}
                  caption="Signed exactly as written. It can't be edited once anyone has signed."
                />
              </View>
            ) : effectiveKind === 'payment' ? (
              <View>
                <Field
                  label="Amount"
                  value={amount}
                  onChangeText={setAmount}
                  placeholder="0.25"
                  keyboardType="decimal-pad"
                  maxLength={40}
                  error={errors.amount}
                  caption={
                    overBalance
                      ? "More than the treasury holds. It can be approved, but the treasury can't pay until it's topped up."
                      : treasury.data?.status?.balance
                        ? `${treasury.data.status.balance} in the treasury`
                        : null
                  }
                  trailing={
                    <View style={s.suffix}>
                      <Text role="body" tone="muted">
                        ETH
                      </Text>
                    </View>
                  }
                />
                <Field
                  label="To"
                  value={to}
                  onChangeText={(v) => {
                    setTo(v);
                    setToChecked(false);
                  }}
                  onBlur={() => {
                    setToChecked(true);
                    const problem = to.trim() ? addressProblem(to) : null;
                    setErrors((e) => ({ ...e, to: problem ? ADDRESS_MESSAGES[problem] : '' }));
                  }}
                  placeholder="0x…"
                  autoCapitalize="none"
                  autoCorrect={false}
                  maxLength={64}
                  mono
                  multiline
                  error={errors.to || null}
                />
                {toChecked && to.trim() && !addressProblem(to) ? (
                  <View style={s.grouped} accessible accessibilityLabel={`Address as entered: ${to.trim()}`}>
                    <Text role="caption" tone="muted">
                      Check it, in fours:
                    </Text>
                    <GroupedValue value={to.trim()} />
                  </View>
                ) : null}
                <Field
                  label="Title (optional)"
                  value={title}
                  onChangeText={setTitle}
                  placeholder={valueWei ? `Pay ${formatEth(valueWei)} to ${to.trim() ? middleOut(to.trim()) : '…'}` : 'Pay the supplier'}
                  autoCapitalize="sentences"
                  maxLength={255}
                />
              </View>
            ) : (
              <View>
                <Field
                  label="Person"
                  value={person}
                  onChangeText={setPerson}
                  placeholder="Elif Kaya"
                  autoCapitalize="words"
                  maxLength={80}
                  error={errors.person}
                />
                <Field
                  label="System"
                  value={system}
                  onChangeText={setSystem}
                  placeholder="prod-db"
                  autoCapitalize="none"
                  maxLength={80}
                  error={errors.system}
                />
                <View style={s.group}>
                  <Text role="caption" tone="muted">
                    Access
                  </Text>
                  <ChipGroup
                    label="Access"
                    value={level}
                    onChange={setLevel}
                    options={Object.entries(ACCESS_LEVELS).map(([value, [label]]) => ({ value, label }))}
                  />
                </View>
                <View style={s.group}>
                  <Text role="caption" tone="muted">
                    Until
                  </Text>
                  <ChipGroup
                    label="Until"
                    value={untilKey}
                    onChange={setUntilKey}
                    options={untils.map((o) => ({ value: o.value, label: o.label }))}
                  />
                  <Text role="caption" tone="muted">
                    {`${dueCaption(until.at, now).replace(/^Due/, 'Ends')}, written as ${utcMinute(until.at!)} UTC in what everyone signs.`}
                  </Text>
                </View>
                <Field
                  label="Reason"
                  value={reason}
                  onChangeText={setReason}
                  placeholder="Investigate incident 2214."
                  autoCapitalize="sentences"
                  maxLength={280}
                  error={errors.reason}
                />
                <Field
                  label="Reference (optional)"
                  value={reference}
                  onChangeText={setReference}
                  placeholder="INC-2214"
                  autoCapitalize="characters"
                  maxLength={80}
                  error={errors.reference}
                />
                <Field
                  label="Title (optional)"
                  value={title}
                  onChangeText={setTitle}
                  placeholder={person.trim() && system.trim() ? `Production access for ${person.trim()} to ${system.trim()}` : 'Production access'}
                  autoCapitalize="sentences"
                  maxLength={255}
                  caption="The text everyone signs is written from these fields."
                />
              </View>
            )}

            <View style={s.group}>
              <Text role="caption" tone="muted">
                Needs an answer by
              </Text>
              <ChipGroup
                label="Needs an answer by"
                value={chosenDeadline.value}
                onChange={setDeadline}
                options={options.map((o) => ({ value: o.value, label: o.label }))}
              />
              <Text role="caption" tone="muted">
                {dueCaption(chosenDeadline.at, now)}
              </Text>
            </View>

            {vault ? (
              detail.data ? (
                <View style={s.who} accessible accessibilityLabel={`Who approves. ${who?.line ?? ''}`}>
                  <Icon name="members" size={20} color={who?.cannotPass ? t.color.status.warning.fg : t.color.textMuted} />
                  <Text role="body" tone={who?.cannotPass ? 'warning' : 'muted'} style={s.flex}>
                    {who?.line}
                  </Text>
                </View>
              ) : (
                <Skeleton width="80%" height={16} />
              )
            ) : null}
          </ContentWidth>
        </ScrollView>

        <ActionBar
          message={barMessage}
          caption={effectiveKind === 'general' ? "Once raised, the text can't be changed." : null}
          primary={{
            label: effectiveKind === 'payment' ? 'Review payment' : 'Raise decision',
            onPress: submit,
            busy: raise.isPending && !reviewing,
          }}
        />
      </KeyboardAvoidingView>

      <Sheet visible={picking} onClose={() => setPicking(false)} title="Choose a vault">
        {vaults.isLoading ? (
          <Skeleton width="60%" height={16} />
        ) : raisable.length === 0 ? (
          <Text role="body" tone="muted">
            {"You can't raise decisions in any of your vaults. Their owners and approvers can."}
          </Text>
        ) : (
          <List>
            {raisable.map((v) => (
              <ListRow
                key={v.vault_id}
                title={v.name}
                caption={ruleSentence(v.threshold_m, v.signer_count)}
                leading={
                  vault?.id === v.vault_id ? (
                    <Icon name="check" size={20} color={t.color.accent} />
                  ) : (
                    <View style={s.checkSpace} />
                  )
                }
                accessibilityLabel={`${v.name}${vault?.id === v.vault_id ? ', chosen' : ''}`}
                onPress={() => {
                  setChosen({ id: v.vault_id, name: v.name });
                  setErrors((e) => ({ ...e, vault: '' }));
                  setPicking(false);
                }}
              />
            ))}
          </List>
        )}
      </Sheet>

      <Sheet
        visible={reviewing}
        onClose={() => !raise.isPending && setReviewing(false)}
        dismissible={!raise.isPending}
        title="Check this payment"
        footer={
          <>
            <Button label="Request payment" onPress={() => raise.mutate()} busy={raise.isPending} full />
            <Button label="Edit" variant="quiet" onPress={() => setReviewing(false)} disabled={raise.isPending} full />
          </>
        }
      >
        {valueWei ? (
          <View style={s.stack}>
            <Text role="figure" tabular accessibilityLabel={`${formatEth(valueWei).replace(/ETH$/, 'ether')}`}>
              {formatEth(valueWei)}
            </Text>
            <View style={s.grouped}>
              <Text role="body" tone="muted">
                to
              </Text>
              <GroupedValue value={to.trim()} />
              <Text role="body" tone="muted">
                on Sepolia
              </Text>
            </View>
            <KeyValue
              label="From"
              value={`${vault?.name ?? ''} treasury. ${vaultSummary ? ruleSentence(vaultSummary.threshold_m, vaultSummary.signer_count) : ''}`.trim()}
            />
            <KeyValue label="Due" value={dueCaption(chosenDeadline.at, now).replace(/^Due /, '')} />
            <Text role="body" tone="muted">
              {"Once requested, this can't be changed. To change it, withdraw it and raise a new one."}
            </Text>
          </View>
        ) : null}
      </Sheet>

      <Sheet
        visible={discard !== null}
        onClose={() => setDiscard(null)}
        title={again ? 'Discard this?' : 'Discard this decision?'}
        footer={
          <>
            <Button
              label="Discard"
              variant="danger"
              onPress={() => {
                const action = discard?.action;
                setDiscard(null);
                setRaised(true);
                if (action) setLeaving({ action });
              }}
              full
            />
            <Button label="Keep editing" variant="secondary" onPress={() => setDiscard(null)} full />
          </>
        }
      >
        <Text role="body">{"What you've entered here is lost. Nothing has been raised."}</Text>
      </Sheet>
    </Screen>
  );
}

const useStyles = makeStyles((t) => ({
  flex: { flex: 1 },
  content: { paddingHorizontal: t.layout.gutter, paddingBottom: t.space[32], paddingTop: t.space[8] },
  stack: { gap: t.space[16] },
  group: { gap: t.space[8] },
  who: { flexDirection: 'row', gap: t.space[8], alignItems: 'flex-start' },
  suffix: { paddingHorizontal: t.space[12], justifyContent: 'center' },
  grouped: { gap: t.space[4] },
  checkSpace: { width: 20 },
}));
