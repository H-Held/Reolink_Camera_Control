"""Exception hierarchy for the Reolink library."""


class ReolinkError(Exception):
    """Base exception for all Reolink errors."""


class ReolinkAuthError(ReolinkError):
    """Login or token failure."""


class ReolinkCommandError(ReolinkError):
    """The camera rejected a command."""


class ReolinkConnectionError(ReolinkError):
    """Network or transport error."""


class ReolinkAudioError(ReolinkError):
    """Audio conversion or push failure."""
