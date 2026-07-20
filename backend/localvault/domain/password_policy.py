from .models import strength_of


class PasswordPolicyError(ValueError):
    pass


def validate_master_password(
    password: str,
    confirmation: str,
    weak_acknowledged: bool,
) -> None:
    """Shared master-password policy.

    LocalVault intentionally has no composition or application-level length
    rule. Whitespace-only values are treated as empty, and weak values require
    an explicit acknowledgement.
    """
    if not password or not password.strip():
        raise PasswordPolicyError("Master password must not be empty")
    if password != confirmation:
        raise PasswordPolicyError("Master password confirmation does not match")
    if strength_of(password) == "weak" and not weak_acknowledged:
        raise PasswordPolicyError("Weak master password acknowledgement is required")
