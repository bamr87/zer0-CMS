"""The `distribution` check of `zer0 doctor`, ported from the Ruby doctor's
`check_distribution` (rails/lib/zer0_cms/doctor.rb) with the lane it reads:
a leftover per-site LinkedIn publisher is a warning; a site that configures
`distribution.linkedin` gets its settings' errors and warnings and an
unreadable ledger as findings. The environment is ignored on purpose — the
doctor reports what the repository says, the same on every machine.

`findings(root)` returns the doctor's finding shape (lifehacker.dev's
`LH.finding`, fingerprinted `sha1("check_id|rule|file|evidence")[:12]`), for
PLAN G4's Python doctor to include as its `distribution` check.
"""

import hashlib
from pathlib import Path

from ..ledger import Ledger
from .site import Config, ConfigError

CHECK = "distribution"
# The per-site LinkedIn publisher the lane replaced.
VENDORED_LINKEDIN = ("scripts/features/linkedin/posts.py", "scripts/features/linkedin/mcp_server.py")


def finding(severity: str, rule: str, evidence: str, *, file: str = "", line=None) -> dict:
    fingerprint = hashlib.sha1(f"{CHECK}|{rule}|{file}|{evidence}".encode(), usedforsecurity=False).hexdigest()[:12]
    return {
        "check_id": CHECK,
        "severity": severity,
        "file": file,
        "line": line,
        "rule": rule,
        "evidence": evidence,
        "fingerprint": fingerprint,
    }


def findings(root) -> list[dict]:
    root, out = Path(root), []
    vendored = next((rel for rel in VENDORED_LINKEDIN if (root / rel).is_file()), None)
    if vendored:
        out.append(
            finding(
                "warning",
                "vendored-linkedin-publisher",
                "a per-site LinkedIn publisher; manage.py linkedin replaces it",
                file=vendored,
            )
        )
    if not (root / "zer0.json").is_file():
        return out
    try:
        config = Config(root, env={})
    except ConfigError as e:
        return [*out, finding("error", "distribution-config-invalid", str(e), file="zer0.json")]
    if not config.configured:
        return out
    out += [finding("error", "distribution-config-invalid", m, file="zer0.json") for m in config.errors]
    out += [finding("warning", "distribution-config", m, file="zer0.json") for m in config.warnings]
    if not Ledger(config.path(config.ledger)).readable:
        out.append(
            finding("error", "distribution-ledger-unreadable", f"{config.ledger} is not valid JSON", file=config.ledger)
        )
    return out
