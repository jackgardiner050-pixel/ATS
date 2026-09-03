# Security Notes

**Last reviewed:** 2026-09-02

---

## Credential-store filenames audit

**Reviewed on droplet:** `/root/.secrets/` directory contains credential files for backup and service authentication.

**Filenames found:**
- `restic_b2.env` — Backblaze B2 (S3-compatible backup storage) credentials
- `restic_pass` — restic backup password/encryption key

**Assessment:** All filenames are **generic** and do not leak sensitive specifics (no account numbers, real names, account identifiers, or resource-specific details in the names themselves). The names describe their purpose only.

---

## Git-history redaction status

**Redaction scope:** commit `38416bf` contains early infrastructure setup comments with:
- Droplet IP address (46.101.59.177, since decommissioned)
- SSH port reference
- Credential file paths (no values)

**Assessment:** Low risk. The values — droplet IP, SSH port, file paths — are infrastructure specifics, not credential values themselves. The commit is in history, not HEAD.

**Decision:** Git-history redaction of this commit is **deferred by decision**. If any of the credential-store filenames later prove more revealing than their current generic labels, revisit and consider full history redaction / rebase.

---

## References

- Credentials stored on droplet: `/root/.secrets/` (not committed to this repo)
- Droplet backup: restic + Backblaze B2 (documented in infrastructure scripts, not here)
- Protocol lock: `docs/OBSERVATION_PROTOCOL.md` (contains all locked inputs including universe)
