// Web screenshot harness ONLY: every phone component's stories, without the app shell
// (phone-ux §5, §10.1). Opened as `/?gallery=<page>&theme=dark&fontScale=2`; `/?gallery=index`
// lists the pages. Each page renders inside the same providers the app uses, so a story is the
// component as a screen would draw it, in either theme and at an emulated text size.

import { useState, type ReactNode } from 'react';
import { ScrollView, View } from 'react-native';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { ThemeProvider, makeStyles, useTheme, type Scheme } from '../../src/theme/index.ts';
import { ICON_GLYPHS, type IconName } from '../../src/theme/icons.generated.ts';
import { useAppFonts } from '../../src/ui/fonts.ts';
import {
  ActionBar,
  Assurance,
  Avatar,
  AvatarStack,
  Banner,
  Button,
  CheckboxRow,
  ColdStartHint,
  CollapsedBar,
  ChipGroup,
  CodeBlock,
  CodeLine,
  DecisionRow,
  DecisionRowSkeleton,
  DisclosureRow,
  EmptyState,
  Field,
  Icon,
  IconButton,
  Identifier,
  InlineMessage,
  KeyValue,
  List,
  ListRow,
  NavBar,
  OfflineBar,
  PasswordField,
  PaymentCard,
  RootHeader,
  Seal,
  SectionTitle,
  Segmented,
  Sheet,
  SignedOverlay,
  SignedText,
  Skeleton,
  StatusBadge,
  StatusLine,
  Switch,
  Tab,
  Text,
  TextArea,
  TextLink,
  ToastProvider,
  ToastView,
} from '../../src/ui/index.tsx';
import type { PaymentAction } from '../../src/crypto/signing.ts';

const NOW = Date.parse('2026-10-06T12:00:00Z');
const hours = (h: number) => new Date(NOW + h * 3_600_000).toISOString();
const noop = () => {};

const PAYMENT: PaymentAction = {
  kind: 'eth_transfer',
  chain_id: 11155111,
  treasury: '0xD49174b703d6FBC5088b0f01C6E71B5Ef467f3D0',
  to: '0x41Ed9F2C7b1a3E58D0c6a4B97e2F5d1C8A0b8A19',
  value_wei: '250000000000000000',
  data: '0x',
  call_gas: 60000,
  valid_until: 1791132553,
  config_nonce: 3,
};
const SENTENCE =
  'Pay 0.25 ETH from the Operations treasury (0xD49174b703d6FBC5088b0f01C6E71B5Ef467f3D0) on Sepolia to 0x41Ed9F2C7b1a3E58D0c6a4B97e2F5d1C8A0b8A19.';

function Story({ title, children, pad = true }: { title: string; children: ReactNode; pad?: boolean }) {
  const s = useStyles();
  return (
    <View style={s.story}>
      <Text role="label" tone="subtle" style={s.storyTitle}>
        {title}
      </Text>
      <View style={pad ? s.storyBody : null}>{children}</View>
    </View>
  );
}

function Buttons() {
  const s = useStyles();
  return (
    <>
      <Story title="Button: variants">
        <View style={s.col}>
          <Button label="Approve" onPress={noop} full />
          <Button label="Keep editing" variant="secondary" onPress={noop} full />
          <Button label="Sign rejection" variant="danger" onPress={noop} full />
          <Button label="Reject" variant="dangerSecondary" onPress={noop} full />
          <Button label="Cancel" variant="quiet" onPress={noop} full />
        </View>
      </Story>
      <Story title="Button: busy, disabled, content width, icon">
        <View style={s.col}>
          <Button label="Sign with Face ID" onPress={noop} busy full />
          <Button label="Sign with Face ID" onPress={noop} disabled full />
          <View style={s.row}>
            <Button label="Raise a decision" onPress={noop} />
            <Button label="Share" variant="secondary" icon="share" onPress={noop} />
          </View>
        </View>
      </Story>
      <Story title="IconButton and TextLink (48 targets)">
        <View style={s.row}>
          <IconButton icon="chevron-left" label="Go back" onPress={noop} />
          <IconButton icon="more" label="More" onPress={noop} />
          <IconButton icon="copy" label="Copy" onPress={noop} size={20} />
          <IconButton icon="plus" label="New decision" onPress={noop} tone="filled" />
          <TextLink label="Change" onPress={noop} />
          <TextLink label="Show full" onPress={noop} role="caption" />
        </View>
      </Story>
      <Story title="ActionBar: Reject and Approve, 2:3" pad={false}>
        <ActionBar
          secondary={{ label: 'Reject', variant: 'dangerSecondary', onPress: noop }}
          primary={{ label: 'Approve', onPress: noop }}
        />
      </Story>
      <Story title="ActionBar: with an error in its message slot" pad={false}>
        <ActionBar
          message={{ tone: 'warning', text: "Not signed. Q-Vault didn't receive your signature, so nothing changed." }}
          secondary={{ label: 'Reject', variant: 'dangerSecondary', onPress: noop }}
          primary={{ label: 'Approve', onPress: noop }}
        />
      </Story>
      <Story title="ActionBar: a line in place of the buttons" pad={false}>
        <ActionBar line="You raised this, so you can't approve it." />
      </Story>
      <Story title="ActionBar: one primary with its caption" pad={false}>
        <ActionBar caption="Once raised, the text can't be changed." primary={{ label: 'Raise decision', onPress: noop }} />
      </Story>
    </>
  );
}

function Status() {
  const s = useStyles();
  return (
    <>
      <Story title="StatusBadge: the closed vocabulary">
        <View style={s.wrap}>
          <StatusBadge word="Needs your signature" tone="warning" />
          <StatusBadge word="Waiting on 1" tone="neutral" />
          <StatusBadge word="Approved" tone="success" />
          <StatusBadge word="Queued" tone="info" />
          <StatusBadge word="Paid" tone="success" />
          <StatusBadge word="Failed" tone="critical" />
          <StatusBadge word="Rejected" tone="critical" />
          <StatusBadge word="Expired" tone="neutral" />
          <StatusBadge word="Withdrawn" tone="neutral" />
        </View>
      </Story>
      <Story title="StatusLine: due within 24 hours">
        <StatusLine badge={{ word: 'Needs your signature', tone: 'warning' }} when="Today, 18:00" soon />
      </Story>
      <Story title="StatusLine: with the personal line">
        <StatusLine
          badge={{ word: 'Waiting on 1', tone: 'neutral' }}
          when="Tue 6 Oct, 17:00"
          line="You approved 10:24. Waiting on Brij or Chen."
        />
      </Story>
      <Story title="Seal: 10 in rows, 14 on the page, 20 in the acknowledgement">
        <View style={s.col}>
          <Seal filled={1} required={2} size={10} />
          <Seal filled={2} required={3} size={14} />
          <Seal filled={2} required={5} size={14} rejections={1} />
          <Seal filled={3} required={3} size={20} />
          <Seal filled={4} required={12} size={14} />
        </View>
      </Story>
    </>
  );
}

function Rows() {
  return (
    <>
      <Story title="DecisionRow: the queue (one due within 24 hours, a payment)">
        <List>
          <DecisionRow
            title="Rotate the on-call paging credentials"
            vault="Incident response"
            approvals={1}
            required={2}
            expiresAt={hours(6)}
            now={NOW}
            onPress={noop}
          />
          <DecisionRow
            title="Top up the release deployer wallet"
            vault="Operations"
            from="from Gracian"
            amount="0.25 ETH"
            approvals={0}
            required={2}
            expiresAt={hours(53)}
            now={NOW}
            onPress={noop}
          />
          <DecisionRow
            title="Calderwood insurance renewal, 2027, with cover unchanged from 2026 and the first instalment"
            vault="Contracts"
            approvals={0}
            required={3}
            expiresAt={hours(77)}
            now={NOW}
            onPress={noop}
          />
        </List>
      </Story>
      <Story title="DecisionRow: waiting on others, approve on the web, history">
        <List>
          <DecisionRow
            title="Q4 cloud commitment"
            vault="Treasury"
            from="raised by you"
            approvals={1}
            required={2}
            expiresAt={hours(30)}
            variant="waiting"
            now={NOW}
            onPress={noop}
          />
          <DecisionRow
            title="Refund the Northwind deposit"
            vault="Operations"
            amount="0.0025 ETH"
            approvals={0}
            required={2}
            expiresAt={hours(30)}
            variant="web"
            now={NOW}
            onPress={noop}
          />
          <DecisionRow
            title="Duplicate invoice payment"
            vault="Treasury"
            approvals={0}
            required={2}
            expiresAt={hours(-30)}
            variant="outcome"
            outcome={{ word: 'Rejected', tone: 'critical', when: '5 Oct' }}
            now={NOW}
            onPress={noop}
          />
        </List>
      </Story>
      <Story title="DecisionRow: loading">
        <List>
          <DecisionRowSkeleton />
          <DecisionRowSkeleton />
        </List>
      </Story>
      <Story title="ListRow, DisclosureRow, avatars">
        <List>
          <ListRow title="Members" value="4" leading={<AvatarStack names={['Ada Lovelace', 'Brij Mehta', 'Chen Wei', 'Elif Demir']} />} onPress={noop} />
          <DisclosureRow title="Checked on this phone" icon="check-circle" value="A397-71F8" onPress={noop} />
          <ListRow title="Operations" caption="Any 2 of 4 approve. You're an approver." value="2 need you" valueTone="warning" onPress={noop} />
          <ListRow title="Hassan Ali" caption="Approved, on his phone" leading={<Avatar name="Hassan Ali" />} value="09:58" />
          <ListRow title="Board approvals" leading={<Avatar name="Board approvals" square size={32} />} caption="No decisions yet" />
        </List>
      </Story>
      <Story title="KeyValue: one accessibility element per pair">
        <View>
          <KeyValue label="Network" value="Sepolia" />
          <KeyValue label="Payouts today" value="9 of 10 left" />
          <KeyValue label="Nonce" value="0f1e2d3c4b5a69788796a5b4c3d2e1f0" mono />
        </View>
      </Story>
    </>
  );
}

function Values() {
  return (
    <>
      <Story title="Identifier: shortened, with Copy and Show full">
        <Identifier label="Address" value={PAYMENT.treasury} />
      </Story>
      <Story title="Identifier: expanded='always' (a recipient in a signing sheet)">
        <Identifier label="Recipient address" value={PAYMENT.to} expanded="always" />
      </Story>
      <Story title="Identifier: a payload hash">
        <Identifier label="Payload hash" value="a39771f8c6d2e1f0b4a5968778695a4b3c2d1e0f9a8b7c6d5e4f3a2b1c8a5127bf" />
      </Story>
      <Story title="SignedText: the lead, under 180 characters">
        <SignedText text="Rotate the paging integration keys for every production service, and revoke the previous set once the new keys are confirmed working." />
      </Story>
      <Story title="SignedText: long, with an address in it">
        <SignedText text={SENTENCE + ' The treasury pays once two of its three signers approve, and the approvals are valid until 3 Jan 2027.'} />
      </Story>
      <Story title="CodeLine: the quiet line in the approve sheet">
        <CodeLine code="A397-71F8" onAbout={noop} />
      </Story>
      <Story title="CodeBlock: only for a web handoff">
        <CodeBlock code="A397-71F8" />
      </Story>
      <Story title="PaymentCard: on the page">
        <PaymentCard action={PAYMENT} sentence={SENTENCE} />
      </Story>
      <Story title="PaymentCard: in a signing sheet, more than the treasury holds">
        <PaymentCard action={PAYMENT} place="sheet" balanceWei="900000000000000" balanceText="0.0009 ETH" sentence={SENTENCE} />
      </Story>
    </>
  );
}

function Inputs() {
  const s = useStyles();
  const [text, setText] = useState('Rotate the on-call paging credentials');
  const [chip, setChip] = useState<string>('In 3 days');
  const [seg, setSeg] = useState<'all' | 'open' | 'decided'>('all');
  const [on, setOn] = useState(true);
  const [picked, setPicked] = useState(true);
  return (
    <>
      <Story title="Field: label, caption, the reserved error slot">
        <View>
          <Field label="Title" value={text} onChangeText={setText} caption="Shown in every list." />
          <Field label="Email" value="ada@" onChangeText={noop} error="Enter your email." />
          <Field label="Recipient" value="0x41Ed9F2C7b1a3E58D0c6a4B97e2F5d1C8A0b8A19" onChangeText={noop} mono multiline />
          <PasswordField label="Password" value="hunter2-hunter2" onChangeText={noop} labelTrailing={<TextLink label="Forgot password?" onPress={noop} role="caption" />} />
        </View>
      </Story>
      <Story title="TextArea: the signed text, in the serif, counting near the limit">
        <TextArea label="What everyone signs" value={'Renew the Calderwood Mutual policy. '.repeat(108)} onChangeText={noop} caption="Signed exactly as written." />
      </Story>
      <Story title="ChipGroup: deadlines (40 visual, 48 targets, 8 apart)">
        <ChipGroup
          label="Deadline"
          value={chip}
          onChange={setChip}
          options={['Today', 'Tomorrow', 'In 3 days', 'In a week', 'No deadline'].map((v) => ({ value: v, label: v }))}
        />
      </Story>
      <Story title="Segmented">
        <Segmented
          label="Show"
          value={seg}
          onChange={setSeg}
          options={[
            { value: 'all', label: 'All' },
            { value: 'open', label: 'Open' },
            { value: 'decided', label: 'Decided' },
          ]}
        />
      </Story>
      <Story title="CheckboxRow and Switch: accent, never the status green">
        <List>
          <CheckboxRow label="Brij Mehta" caption="brij@qvault.demo" checked={picked} onToggle={() => setPicked((v) => !v)} />
          <CheckboxRow label="Chen Wei" caption="chen@qvault.demo" checked={false} onToggle={noop} />
        </List>
        <View style={[s.row, s.top]}>
          <Text role="body" style={s.flex}>
            Require Face ID to open Q-Vault
          </Text>
          <Switch value={on} onValueChange={setOn} label="Require Face ID to open Q-Vault" />
        </View>
      </Story>
    </>
  );
}

function Messages() {
  const s = useStyles();
  return (
    <>
      <Story title="Banner: page-level only">
        <View style={s.col}>
          <Banner tone="critical" title="Don't act on this decision" detail="Its contents don't match the code everyone signs. Nothing has been signed, and this phone won't sign it." actions={[{ label: 'Copy a report', onPress: noop }]} />
          <Banner tone="warning" title="Can't load this decision." detail="Check your connection." actions={[{ label: 'Try again', onPress: noop }]} />
          <Banner tone="success" title="Signed on this device." />
          <Banner tone="info" title="Queued" detail="The treasury pays at its next check." />
          <Banner tone="neutral" title="This vault is not available to you." />
        </View>
      </Story>
      <Story title="InlineMessage: where the action was">
        <View style={s.col}>
          <InlineMessage tone="critical" text="Set a screen lock to sign with this phone." />
          <InlineMessage tone="warning" text="Face ID is locked. Unlock your phone with its PIN, then try again." />
          <InlineMessage tone="neutral" text="Face ID was cancelled. Nothing was signed." />
          <InlineMessage tone="success" text="Key held on this device" />
        </View>
      </Story>
      <Story title="Toast: background confirmations only">
        <ToastView text="Link copied" inline />
      </Story>
      <Story title="EmptyState: one sentence, one line, one button">
        <EmptyState title="Nothing is open in this vault." detail="Decisions raised here appear first." action={<Button label="Raise a decision" onPress={noop} />} />
      </Story>
      <Story title="Skeleton: after 150ms, breathing">
        <View style={s.col}>
          <Skeleton width="80%" height={16} />
          <Skeleton width="55%" height={12} />
          <Skeleton height={64} radius={12} />
        </View>
      </Story>
      <Story title="Assurance: holds, then fails">
        <View style={s.col}>
          <Assurance ok>
            <KeyValue label="Payload hash" value="a39771f8…8a5127bf" mono />
          </Assurance>
          <Assurance ok={false}>
            <KeyValue label="Derived on this phone" value="a39771f8…8a5127bf" mono />
            <KeyValue label="Server stated" value="0be4d1c2…77e0aa31" mono />
          </Assurance>
        </View>
      </Story>
    </>
  );
}

function Structure() {
  const t = useTheme();
  const s = useStyles();
  const names = Object.keys(ICON_GLYPHS) as IconName[];
  return (
    <>
      <Story title="NavBar: back, title, overflow" pad={false}>
        <NavBar onBack={noop} title="Operations" actions={[{ icon: 'more', label: 'More', onPress: noop }]} />
      </Story>
      <Story title="RootHeader: headline, supporting line, the plus">
        <RootHeader
          title="Three decisions need your signature"
          supporting="One is due today."
          action={{ icon: 'plus', label: 'New decision', onPress: noop, filled: true }}
        />
      </Story>
      <Story title="SectionTitle with a count and a link">
        <SectionTitle title="Open" count={7} trailing={<TextLink label="See all" onPress={noop} />} />
      </Story>
      <Story title="CollapsedBar: the headline once it has scrolled away" pad={false}>
        <View style={s.collapsedFrame}>
          <CollapsedBar title="3 need your signature" visible action={{ icon: 'plus', label: 'New decision', onPress: noop }} />
        </View>
      </Story>
      <Story title="OfflineBar" pad={false}>
        <OfflineBar since="09:40" />
      </Story>
      <Story title="ColdStartHint: the caption at 4 s, and Try again at 20 s">
        <ColdStartHint stage="hint" />
        <ColdStartHint stage="retry" onRetry={noop} />
      </Story>
      <Story title="Tab bar: filled when active, badge and unread dot" pad={false}>
        <View style={s.tabbar}>
          <Tab label="Approvals" icons={['inbox', 'inbox-fill']} focused badge={3} onPress={noop} />
          <Tab label="Activity" icons={['pulse', 'pulse-fill']} focused={false} dot onPress={noop} />
          <Tab label="Vaults" icons={['vault', 'vault-fill']} focused={false} onPress={noop} />
          <Tab label="Account" icons={['user', 'user-fill']} focused={false} onPress={noop} />
        </View>
      </Story>
      <Story title={`Icons: the style tile's set, ${names.length} glyphs at 24`}>
        <View style={s.wrap}>
          {names.map((n) => (
            <View key={n} style={s.icon}>
              <Icon name={n} size={24} color={t.color.text} />
              <Text role="label" tone="subtle" numberOfLines={1} maxScale={1}>
                {n}
              </Text>
            </View>
          ))}
        </View>
      </Story>
    </>
  );
}

function SheetPage() {
  return (
    <>
      <Story title="Behind the sheet">
        <SignedText text="Rotate the paging integration keys for every production service." />
      </Story>
      <Sheet
        visible
        onClose={noop}
        title="Approve this payment"
        footer={
          <>
            <CodeLine code="A397-71F8" onAbout={noop} />
            <Button label="Sign with Face ID" onPress={noop} full />
            <Button label="Cancel" variant="quiet" onPress={noop} full />
          </>
        }
      >
        <PaymentCard action={PAYMENT} place="sheet" sentence={SENTENCE} />
        <Text role="body">
          Yours will be approval 2 of 2; the treasury pays once 2 approve, and you can't withdraw it.
        </Text>
      </Sheet>
    </>
  );
}

function OverlayPage() {
  return (
    <>
      <Story title="Behind the acknowledgement">
        <SignedText text="Commit to the Q4 reserved-capacity plan." />
      </Story>
      <SignedOverlay
        visible
        mark="tick"
        sealed
        headline="Decision approved"
        line="Yours was the approval that met the rule."
        filled={2}
        required={2}
        next={{ caption: '2 more need your signature', onPress: noop }}
        onDone={noop}
      />
    </>
  );
}

export const PAGES: Record<string, { title: string; render: () => ReactNode }> = {
  buttons: { title: 'Buttons, icon buttons, links, action bar', render: () => <Buttons /> },
  status: { title: 'Status badge, status line, seal', render: () => <Status /> },
  rows: { title: 'Decision rows, list rows, key values, avatars', render: () => <Rows /> },
  values: { title: 'Identifier, signed text, decision code, payment card', render: () => <Values /> },
  inputs: { title: 'Fields, text area, chips, segmented, checkbox, switch', render: () => <Inputs /> },
  messages: { title: 'Banner, inline message, toast, empty state, skeleton, assurance', render: () => <Messages /> },
  structure: { title: 'Nav bar, root header, section title, offline bar, tab bar, icons', render: () => <Structure /> },
  sheet: { title: 'Sheet', render: () => <SheetPage /> },
  overlay: { title: 'Acknowledgement', render: () => <OverlayPage /> },
};

function Page({ name }: { name: string }) {
  const s = useStyles();
  const t = useTheme();
  const page = PAGES[name];
  return (
    <ScrollView nativeID="gallery-scroll" style={s.page} contentContainerStyle={s.pageContent}>
      <View style={s.pageHead}>
        <Text role="titleSm" accessibilityRole="header">
          {page ? page.title : 'Gallery'}
        </Text>
        <Text role="caption" tone="muted">{`${t.scheme}, text at ${t.fontScale}x`}</Text>
      </View>
      {page ? (
        page.render()
      ) : (
        <View>
          {Object.entries(PAGES).map(([key, p]) => (
            <Text key={key} role="body">{`?gallery=${key}  ${p.title}`}</Text>
          ))}
        </View>
      )}
    </ScrollView>
  );
}

export default function Gallery({ name, scheme, fontScale }: { name: string; scheme?: Scheme; fontScale?: number }) {
  const fonts = useAppFonts();
  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <ThemeProvider scheme={scheme} fontScale={fontScale}>
        <SafeAreaProvider>
          <ToastProvider>{fonts ? <Page name={name} /> : null}</ToastProvider>
        </SafeAreaProvider>
      </ThemeProvider>
    </GestureHandlerRootView>
  );
}

const useStyles = makeStyles((t) => ({
  flex: { flex: 1 },
  page: { flex: 1, backgroundColor: t.color.bg },
  pageContent: { paddingVertical: t.space[16], gap: t.space[4] },
  pageHead: { paddingHorizontal: t.layout.gutter, gap: t.space[2] },
  story: { marginTop: t.space[20] },
  storyTitle: { paddingHorizontal: t.layout.gutter, marginBottom: t.space[8] },
  storyBody: { paddingHorizontal: t.layout.gutter },
  col: { gap: t.space[12] },
  row: { flexDirection: 'row', alignItems: 'center', gap: t.space[8], flexWrap: 'wrap' },
  wrap: { flexDirection: 'row', flexWrap: 'wrap', gap: t.space[8] },
  top: { marginTop: t.space[12] },
  tabbar: { flexDirection: 'row', backgroundColor: t.color.chrome.bg, paddingVertical: t.space[4] },
  collapsedFrame: { height: 48 },
  icon: { width: 80, alignItems: 'center', gap: t.space[4], paddingVertical: t.space[4] },
}));
