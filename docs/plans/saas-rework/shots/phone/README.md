# Phone screens: the rework against the baseline

Every phone screen in phone-ux §6, beside the baseline shot of the app it replaces
(`../../baseline/app_NN_*.png`, taken before the rework) and the rework shots that show it. The
rework shots are in `../p2`, `../p3` and `../p4b`; each folder's README says how its states were
made and what its audits found. Look in `light_1` or `dark_1` (font scale 1.0) for any shot, and in
`light_2` or `dark_2` (emulated 2.0) for the ones whose large-text layout was worth keeping.

The freshness states (phone-ux §2.6: the offline bar, the cold-start hint, the encrypted cache,
"Checking…") are P2's `f` shots. "none (new)" means the baseline had no such screen.

| phone-ux | Screen | Baseline | Rework shots |
| --- | --- | --- | --- |
| §6.1 | Launch, splash and app lock | none (new) | p3: `l01`, `l02a to l02c` |
| §6.2 | Onboarding (not enrolled) | `app_01_enrol`<br>`app_02_enrol_filled`<br>`app_03_enrol_error`<br>`app_37_account` | p3: `o01 to o05`, `o06`, `o07`, `o08`, `o09` |
| §6.3 | Approvals (tab 1) | `app_04_home_loading`<br>`app_05_home_error`<br>`app_06_home`<br>`app_07_home_full`<br>`app_49_home_after_signing` | p2: `a01`, `a02`, `a03`, `a04`, `a05`, `a06`, `a08`, `a09`, `f03`<br>p3: `a10`<br>p4b: `a13`, `a13b` |
| §6.4 | Waiting on others | none (new) | p2: `a07`<br>p3: `a11`, `a11b`<br>p4b: `a14` |
| §6.5 | Decision screen: shared frame | `app_17_decision_open`<br>`app_46_decision_open_long_text` | p2: `d02d`, `d19`, `d19b` |
| §6.6 | Decision screen: every state | `app_22_decision_approved`<br>`app_23_decision_rejected`<br>`app_24_decision_expired`<br>`app_25_decision_open_past_deadline`<br>`app_26_decision_payment_paid`<br>`app_27_decision_payment_paid_full`<br>`app_28_decision_payment_failed`<br>`app_29_decision_payment_failed_full`<br>`app_30_decision_integrity_failure_simulated`<br>`app_31_decision_integrity_failure_simulated_full`<br>`app_43_decision_open_one_more_needed` | p2: `d01a to d01c`, `d02`, `d02b`, `d02c`, `d03`, `d04`, `d05`, `d06`, `d08`, `d07a`, `d07b`, `d09 to d15`, `d16`, `d17`, `e01 to e03`, `s09a`, `s09`, `s10`, `x01 to x03`, `x04`, `x05`, `x06`, `x07`<br>p3: `d21`, `d23`, `d23b` |
| §6.7 | Evidence sheet: "Checked on this phone" | `app_18_decision_open_signing_detail`<br>`app_19_decision_open_signing_detail_full` | p2: `d02`, `d02b` |
| §6.8 | Approve sheet | `app_20_sheet_approve` | p2: `s01`, `s01b`, `s02` |
| §6.9 | Reject sheet | `app_21_sheet_reject` | p2: `s04`, `s04b`, `s05` |
| §6.10 | Biometric prompt and signing in flight | none (new) | The OS biometric prompt is answered by the harness; signing in flight is in P2's `s` shots |
| §6.11 | The acknowledgement | `app_41_signed_overlay`<br>`app_42_decision_after_signing`<br>`app_44_signed_overlay_threshold_met`<br>`app_45_decision_after_threshold_met`<br>`app_47_rejected_overlay`<br>`app_48_decision_after_rejecting` | p2: `s06 to s08` |
| §6.12 | Activity (tab 2): the inbox and the record | `app_32_activity_all`<br>`app_33_activity_all_full`<br>`app_34_activity_open`<br>`app_35_activity_approved`<br>`app_36_activity_declined` | p3: `ac01 to ac03`<br>p4b: `ac10`, `ac12`, `ac13`, `ac14`, `ac15`, `ac16` |
| §6.13 | Vaults (tab 3) | `app_13_vaults` | p3: `v01` |
| §6.14 | Vault | `app_14_vault_treasury`<br>`app_15_vault_treasury_full`<br>`app_54_vault_new_empty` | p3: `v02 to v05`<br>p4b: `v07` |
| §6.15 | Treasury sheet and treasury change approval | `app_16_vault_treasury_card` | p3: `a10`, `v02 to v05`, `t01 to t09` |
| §6.16 | New decision | `app_08_new_decision_pick_vault`<br>`app_09_new_decision_empty`<br>`app_10_new_decision_filled`<br>`app_11_new_decision_in_treasury`<br>`app_12_new_payment_filled` | p3: `n01 to n07`, `n09`, `n10` |
| §6.17 | New vault (minimal) | `app_50_new_vault_empty`<br>`app_51_sheet_choose_signers`<br>`app_52_sheet_choose_signers_picked`<br>`app_53_new_vault_filled` | p3: `nv01 to nv04` |
| §6.18 | Account (tab 4) | `app_37_account`<br>`app_38_account_full` | p3: `acc01 to acc09`<br>p4b: `ac15`, `acc10 to acc12`, `acc13` |
| §6.19 | Remove this phone | `app_39_sheet_sign_out`<br>`app_40_sheet_revoke` | p2: `s12`, `s12b`, `s13`, `s14`<br>p4b: `acc14` |
| §6.20 | Session ended, device removed, key missing | none (new) | p2: `s11`, `x06`, `x07`, `x08`, `x09` |
| §6.21 | Decision depth features (P4, as R4 and R5 APIs land) | none (new) | p3: `d20`, `d20b`, `d22`, `d22b`, `d24`, `d25`, `d26`<br>p4b: `d27` |
| §6.22 | Workspace and invitations | none (new) | p3: `o09`, `a12`, `v06` |
| §6.23 | Push notifications (R8) | none (new) | A handset check (OWNER-ACTIONS §3.5): a web page receives no push |
