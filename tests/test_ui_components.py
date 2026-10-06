"""The component macros in templates/ui/ keep their contracts (rework S7, plan section 6).

Each test renders a macro the way a screen will and checks the part of its contract a screen relies
on: the closed status vocabulary, labels tied to their controls, loading that keeps the label, the
quorum drawn as discrete marks, and the two different empty states of a table.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta, timezone

import pytest

from qvault import ui


def render(app, source: str, **context) -> str:
    with app.test_request_context("/"):
        return app.jinja_env.from_string(source).render(**context)


# ------------------------------------------------------------------------------ status (S6)


@pytest.mark.parametrize(
    "key, word, tone",
    [
        ("needs_you", "Needs your signature", "warning"),
        ("approved", "Approved", "success"),
        ("rejected", "Rejected", "critical"),
        ("expired", "Expired", "neutral"),
        ("withdrawn", "Withdrawn", "neutral"),
        ("queued", "Queued", "info"),
        ("paid", "Paid", "success"),
        ("failed", "Failed", "critical"),
    ],
)
def test_each_status_always_has_the_same_word_and_tone(app, key, word, tone):
    html = render(app, '{% from "ui/status.html" import status %}{{ status(k) }}', k=key)
    assert f'class="q-badge q-badge--{tone}"' in html
    assert f">{word}</span>" in html


def test_waiting_names_how_many_approvals_are_still_needed(app):
    """Neutral, not info: the S6 tone map after the R1.1 critique (pending, but nothing for the
    viewer to do). Changed in R2 from the info tone the foundation shipped with."""
    html = render(app, '{% from "ui/status.html" import status %}{{ status("waiting", 2) }}')
    assert "q-badge--neutral" in html and ">Waiting on 2<" in html


def test_a_status_outside_the_vocabulary_fails_the_render_instead_of_inventing_one(app):
    with pytest.raises(ValueError, match="vocabulary"):
        render(app, '{% from "ui/status.html" import status %}{{ status("open") }}')
    with pytest.raises(ValueError, match="count"):
        ui.status_of("waiting")


def test_a_badge_takes_only_one_of_the_five_tones(app):
    html = render(app, '{% from "ui/status.html" import badge %}{{ badge("ML-DSA-65", "info") }}')
    assert 'class="q-badge q-badge--info"' in html
    with pytest.raises(ValueError, match="tones"):
        render(app, '{% from "ui/status.html" import badge %}{{ badge("x", "purple") }}')


# ------------------------------------------------------------------------------ the quorum


@pytest.mark.parametrize("approved, required, filled", [(0, 2, 0), (1, 2, 1), (2, 2, 2), (3, 2, 2)])
def test_the_quorum_is_one_mark_per_needed_approval_filling_to_the_threshold(
    app, approved, required, filled
):
    html = render(
        app,
        '{% from "ui/status.html" import quorum %}{{ quorum(a, r) }}',
        a=approved,
        r=required,
    )
    assert html.count('class="q-mark-dot') == required
    assert html.count("q-mark-dot is-on") == filled
    assert f'aria-label="{approved} of {required} approvals"' in html
    # A count of people, never a progress bar.
    assert "<progress" not in html and "width:" not in html and "%" not in html


# ------------------------------------------------------------------------------ buttons


def test_a_loading_button_keeps_its_label_and_cannot_be_pressed_twice(app):
    html = render(
        app,
        '{% from "ui/buttons.html" import button %}'
        '{{ button("Approve & sign", "primary", type="submit", loading=True) }}',
    )
    assert "<span>Approve &amp; sign</span>" in html
    assert 'aria-busy="true"' in html and " disabled" in html
    assert 'class="q-btn q-btn--primary"' in html


def test_a_button_with_an_href_is_a_link(app):
    html = render(
        app,
        '{% from "ui/buttons.html" import button %}'
        '{{ button("New vault", "secondary", href="/vaults/new") }}',
    )
    assert html.startswith('<a class="q-btn q-btn--secondary" href="/vaults/new"')


def test_an_icon_button_is_named_for_screen_readers(app):
    html = render(
        app, '{% from "ui/buttons.html" import icon_button %}{{ icon_button("close", "Close") }}'
    )
    assert 'aria-label="Close"' in html and 'aria-hidden="true"' in html


# ------------------------------------------------------------------------------ forms


def test_a_field_ties_its_label_caption_and_error_to_the_input(app):
    html = render(
        app,
        '{% from "ui/forms.html" import field %}'
        '{{ field("email", "Email", type="email", caption="We never share it.",'
        ' error=["Enter an email address."]) }}',
    )
    assert '<label class="q-field__label" for="f-email">Email</label>' in html
    assert 'id="f-email" name="email" type="email"' in html
    assert 'aria-describedby="f-email-cap f-email-err"' in html
    assert 'aria-invalid="true"' in html
    assert 'id="f-email-cap"' in html and 'id="f-email-err"' in html
    assert "Enter an email address." in html


def test_a_field_without_an_error_is_not_marked_invalid(app):
    html = render(app, '{% from "ui/forms.html" import field %}{{ field("title", "Title") }}')
    assert "aria-invalid" not in html and "aria-describedby" not in html


def test_a_select_marks_the_current_option(app):
    html = render(
        app,
        '{% from "ui/forms.html" import select %}'
        '{{ select("m", "Approvals needed", [(1, "1"), (2, "2"), (3, "3")], selected="2") }}',
    )
    assert '<option value="2" selected>' in html
    assert html.count(" selected") == 1


def test_a_switch_is_a_checkbox_with_the_switch_role(app):
    html = render(
        app,
        '{% from "ui/forms.html" import switch, checkbox %}'
        '{{ switch("sod", "The person who raises a decision can also approve it", checked=True) }}'
        '{{ checkbox("agree", "I understand") }}',
    )
    assert (
        'class="q-sw" type="checkbox" id="f-sod" name="sod" value="1" role="switch" checked' in html
    )
    assert 'class="q-cb" type="checkbox" id="f-agree"' in html


def test_a_radio_group_has_a_legend_and_checks_the_selected_option(app):
    html = render(
        app,
        '{% from "ui/forms.html" import radio_group %}'
        '{{ radio_group("choice", "Decision",'
        ' [("approve", "Approve"), ("reject", "Reject", "Ends it")], selected="reject") }}',
    )
    assert "<legend>Decision</legend>" in html
    assert re.search(r'value="reject"\s+checked', html)
    assert not re.search(r'value="approve"\s+checked', html)


# ------------------------------------------------------------------------------ data


def test_a_hash_keeps_both_ends_and_copies_the_whole_value(app):
    value = "a" * 4 + "0123456789abcdef" * 3 + "z" * 4
    html = render(
        app, '{% from "ui/data.html" import hash %}{{ hash(v, "payload hash") }}', v=value
    )
    assert f'data-copy="{value}"' in html and f'title="{value}"' in html
    shown = re.search(r'class="q-hash__v"[^>]*>([^<]+)<', html).group(1)
    assert shown == f"{value[:8]}…{value[-6:]}"
    assert 'aria-label="Copy payload hash"' in html


def test_a_short_value_is_not_truncated():
    assert ui.middle_truncate("abc123") == "abc123"


COLUMNS = [
    {"key": "title", "label": "Decision", "sortable": True},
    {"key": "amount", "label": "Amount", "numeric": True},
    {"key": "actions", "label": "Actions", "hide_label": True},
]


def test_an_empty_table_and_a_filtered_out_table_say_different_things(app):
    source = (
        '{% from "ui/data.html" import data_table %}'
        "{% call data_table(cols, False, filtered=f, empty_title='No decisions yet', "
        "empty_action={'label': 'New decision', 'href': '/new'}, clear_href='/list') %}"
        "{% endcall %}"
    )
    empty = render(app, source, cols=COLUMNS, f=False)
    filtered = render(app, source, cols=COLUMNS, f=True)
    assert 'data-empty="empty"' in empty and "No decisions yet" in empty and 'href="/new"' in empty
    assert 'data-empty="no-results"' in filtered and "No results" in filtered
    assert 'href="/list"' in filtered and "No decisions yet" not in filtered
    assert 'colspan="3"' in empty


def test_the_sorted_column_says_so_and_sorting_is_a_link(app):
    html = render(
        app,
        '{% from "ui/data.html" import data_table %}'
        "{% macro by(key) %}/list?sort={{ key }}{% endmacro %}"
        "{% call data_table(cols, True, sort='title', descending=True, sort_href=by) %}"
        "<tr><td>a</td><td>1</td><td></td></tr>{% endcall %}",
        cols=COLUMNS,
    )
    assert re.search(
        r'<th scope="col"\s+aria-sort="descending"><a class="q-sort" href="/list\?sort=title">',
        html,
    )
    assert '<th scope="col" class="is-num">Amount</th>' in html
    assert '<span class="visually-hidden">Actions</span>' in html
    assert "<tr><td>a</td>" in html


def test_a_key_value_panel_is_a_description_list(app):
    html = render(
        app,
        '{% from "ui/data.html" import kv_panel %}'
        '{{ kv_panel([("Rule", "Any 2 of 3")], "Details") }}',
    )
    assert "<dt>Rule</dt><dd>Any 2 of 3</dd>" in html and ">Details</h2>" in html


def test_a_time_carries_a_machine_readable_utc_stamp_and_the_absolute_time(app):
    moment = datetime(2026, 10, 4, 9, 58, 42)
    html = render(app, '{% from "ui/data.html" import reltime %}{{ reltime(t) }}', t=moment)
    assert 'datetime="2026-10-04T09:58:42Z"' in html
    assert 'title="Sun 4 Oct 2026, 09:58 UTC"' in html
    assert ">Sun 4 Oct 2026, 09:58 UTC</time>" in html


def test_an_aware_time_is_converted_to_utc():
    moment = datetime(2026, 10, 4, 10, 58, tzinfo=timezone(timedelta(hours=1)))
    assert ui.iso_utc(moment) == "2026-10-04T09:58:00Z"
    assert ui.iso_utc(datetime(2026, 1, 1, tzinfo=UTC)) == "2026-01-01T00:00:00Z"


# ------------------------------------------------------------------------------ navigation


def test_tabs_are_links_and_the_current_one_is_marked(app):
    html = render(
        app,
        '{% from "ui/navigation.html" import tabs %}'
        "{{ tabs([{'key': 'decisions', 'label': 'Decisions', 'href': '?tab=decisions', 'count': 3},"
        " {'key': 'members', 'label': 'Members', 'href': '?tab=members'}],"
        " 'members', 'Vault sections') }}",
    )
    assert '<nav class="q-tabs" aria-label="Vault sections">' in html
    assert '<a class="q-tab" href="?tab=members" aria-current="page">' in html
    assert '<a class="q-tab" href="?tab=decisions">' in html
    assert '<span class="q-count">3</span>' in html


def test_a_page_header_has_one_title_labelled_facts_and_one_action(app):
    html = render(
        app,
        '{% from "ui/navigation.html" import page_header %}'
        '{% from "ui/status.html" import status %}'
        "{{ page_header('Treasury', status=status('approved'), facts=[('Rule', 'Any 2 of 3')],"
        " action={'label': 'New decision', 'href': '/new'}) }}",
    )
    assert html.count("<h1") == 1 and ">Treasury</h1>" in html
    assert "q-badge--success" in html
    assert '<div class="q-fact"><dt>Rule</dt><dd>Any 2 of 3</dd></div>' in html
    assert html.count("q-btn--primary") == 1


def test_the_breadcrumb_marks_the_last_item_as_the_current_page(app):
    html = render(
        app,
        '{% from "ui/navigation.html" import breadcrumbs %}'
        "{{ breadcrumbs([('Vaults', '/vaults/'), ('Treasury', '/vaults/1')]) }}",
    )
    assert '<a href="/vaults/">Vaults</a>' in html
    assert '<span aria-current="page">Treasury</span>' in html
    assert 'href="/vaults/1"' not in html


# ------------------------------------------------------------------------------ feedback and menus


def test_a_dialog_is_a_native_dialog_labelled_by_its_title(app):
    html = render(
        app,
        '{% from "ui/feedback.html" import dialog %}'
        "{% call(part) dialog('reject', 'Reject this decision?') %}"
        "{% if part == 'body' %}Rejecting ends it for everyone."
        "{% else %}<button>Reject</button>{% endif %}"
        "{% endcall %}",
    )
    assert '<dialog class="q-dialog" id="reject" aria-labelledby="reject-title">' in html
    assert 'id="reject-title">Reject this decision?</h2>' in html
    assert '<div class="q-dlg__bd">Rejecting ends it for everyone.</div>' in html
    assert '<div class="q-dlg__ft"><button>Reject</button></div>' in html


def test_a_critical_banner_is_an_alert_and_an_info_banner_is_not(app):
    critical = render(
        app,
        '{% from "ui/feedback.html" import banner %}{{ banner("critical", "Tamper detected") }}',
    )
    info = render(app, '{% from "ui/feedback.html" import banner %}{{ banner("info", "Queued") }}')
    assert 'role="alert"' in critical and 'role="status"' in info


def test_an_empty_state_says_the_fact_then_the_next_step(app):
    html = render(
        app,
        '{% from "ui/feedback.html" import empty_state %}'
        "{{ empty_state('No vaults yet', 'A vault holds the people who approve together.',"
        " {'label': 'New vault', 'href': '/vaults/new'}) }}",
    )
    assert "No vaults yet" in html and 'href="/vaults/new"' in html


def test_a_toast_can_be_dismissed_and_names_its_tone(app):
    html = render(
        app,
        '{% from "ui/feedback.html" import toast %}{{ toast("Signature recorded", "success") }}',
    )
    assert 'data-toast data-tone="success"' in html
    assert 'data-toast-close aria-label="Dismiss"' in html


def test_a_menu_action_that_changes_state_is_a_csrf_protected_post(app):
    html = render(
        app, '{% from "ui/menus.html" import menu_post %}{{ menu_post("Sign out", "/logout") }}'
    )
    assert '<form method="post" action="/logout">' in html
    assert 'name="csrf_token"' in html
    assert '<button class="q-menu__i" type="submit">' in html


def test_an_avatar_stack_shows_three_and_counts_the_rest(app):
    html = render(
        app,
        '{% from "ui/avatars.html" import avatar_stack %}'
        '{{ avatar_stack(["Ada", "Brij", "Chen", "Dee", "Eve"]) }}',
    )
    assert html.count('class="q-av"') == 3
    assert ">+2</span>" in html
    assert 'aria-label="Ada, Brij, Chen, Dee, Eve"' in html
