# P4b shots: the inbox, the "Notifications are off" line, Remind's next time, rename, the treasury a key is on

Shot on 2026-10-10 by `mobile/tools/web-shots/p4b.py` (390 x 844 at 2x) against a disposable
backend on a copy of the demo database, renamed to the workspace "Northwind" and the vault
"Operations", as P3's are. First screen only. All four folders hold every shot: `light_1` and
`dark_1` at font scale 1.0, `light_2` and `dark_2` at emulated 2.0. Every PNG is a 256-colour
palette image, as P2's and P3's are.

Two audits run on every shot, and the run fails on any finding: touch targets (every target 48 x 48
or larger, none nested) and overflow (nothing past the screen's edge, no container whose content is
wider than it). Each folder: 234 targets, 0 findings, 0 overflowing (`audit_p4b.json`).

**How the states are made.** The inbox is answered in the browser with the server's own copy
(as `notification_copy` writes it), its read state kept for the run, and archiving a security
alert refused with the server's 409, as the server does. The other states rewrite only UNSIGNED
fields of real replies (`remind`, `my_key`, a treasury seat's `key_fingerprint`, `push`). The one
write that reaches the server is a rename it refuses (a right-to-left override in the name), so
nothing is renamed.

**Not shot:** the swipe (Mark read, Archive). react-native-web turns a mouse drag into a press, so
the row opens instead; the same actions are the row's accessibility actions, and the swipe is a
handset check (OWNER-ACTIONS §3.5 item 12). A security alert has no Archive at all.

| Shot | phone-ux | What it shows |
| --- | --- | --- |
| `ac10` | §6.12 | For you: the unread new-device alert pinned in the critical tone with "Not you? Remove that device"; Today and Yesterday groups; unread dots; the Activity tab's dot |
| `ac12` | §6.12 | "Mark all read" and its toast; the dots gone |
| `ac13`, `ac14` | §6.12 | "You're up to date."; the list failed to load (never "up to date") |
| `ac15` | §6.12, §6.18 | "Not you?" opens Other devices with that device's remove sheet open, naming the treasury that holds its key |
| `ac16` | §6.12 | Yours: "You approved", "You rejected" from `my_vote`, whatever the counts |
| `a13`, `a13b` | §6.3 item 5 | Approvals: "Notifications are off" with Turn on and dismiss; Turn on opens Account, Notifications |
| `a14` | §6.4 | Waiting on others: the reminder sent, and when the next may go |
| `d27` | §6.21 | The decision you raised: "Reminded at 17:26. You can remind again tomorrow." over a disabled Remind |
| `acc10` to `acc12` | §6.18 | This phone's name with Change; the rename sheet; a hidden character refused under the field in the server's words |
| `acc13` | §6.18 | Another device's sheet with Rename |
| `acc14` | §6.19 | Remove this phone names the treasury that holds its key, matched by the seat's fingerprint |
| `v07` | §6.14 | Members: "Last signed 4 Oct" from the server; nothing for someone who never voted |
