"""WTForms form definitions (CSRF-protected via Flask-WTF)."""

from __future__ import annotations

from flask_wtf import FlaskForm
from flask_wtf.file import FileField
from wtforms import (
    DateTimeLocalField,
    IntegerField,
    PasswordField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Email, EqualTo, Length, NumberRange, Optional


class RegisterForm(FlaskForm):
    display_name = StringField("Full name", validators=[DataRequired(), Length(max=255)])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=8, max=1024)])
    confirm = PasswordField(
        "Confirm password",
        validators=[DataRequired(), EqualTo("password", message="Passwords must match")],
    )
    submit = SubmitField("Create account")


class LoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Log in")


class VaultForm(FlaskForm):
    name = StringField("Vault name", validators=[DataRequired(), Length(max=255)])
    description = TextAreaField("Description", validators=[Optional(), Length(max=2000)])
    threshold_m = IntegerField(
        "Approval threshold (M signatures required)",
        validators=[DataRequired(), NumberRange(min=1, max=50)],
        default=2,
    )
    submit = SubmitField("Create vault")


class AddMemberForm(FlaskForm):
    email = StringField("Member email", validators=[DataRequired(), Email(), Length(max=255)])
    role = SelectField(
        "Role", choices=[("signer", "Signer"), ("viewer", "Viewer")], default="signer"
    )
    submit = SubmitField("Add member")


class ProposalForm(FlaskForm):
    title = StringField("Title", validators=[DataRequired(), Length(max=255)])
    action_text = TextAreaField(
        "Action / description", validators=[DataRequired(), Length(max=4000)]
    )
    deadline = DateTimeLocalField(
        "Deadline (optional)", format="%Y-%m-%dT%H:%M", validators=[Optional()]
    )
    file = FileField("Attach a file (optional)")
    submit = SubmitField("Create proposal")
