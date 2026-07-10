"""NeuroProof audit certificate + append-only proof ledger (v0).

This module promotes the previously *spec-only* "NeuroProof certificate / proof
ledger" line item (status doc §1, §9) to a concrete, independently verifiable v0.
It implements exactly the acceptance criteria the status doc names as the bar:

    "those names remain future/spec-only until there is a certificate schema,
    frozen input/query/rule digests, an independent checker, ledger storage,
    replay policy, and tamper/replay tests."

WHAT THIS CERTIFIES (and what it does NOT)
------------------------------------------
A :class:`NeuroProofCertificateV1` certifies a narrow, mechanical property:

    *Given these frozen inputs, this frozen reproducible query, this frozen
    rule/ruleset, and this named backend + corpus version, the recorded audit
    verdict is reproducible and untampered.*

It is an **AUDIT** certificate, not a proof of empirical truth. Mirroring status
doc §9, this layer does **NOT**:

* prove empirical truth — the wrapped status is editorial, not ground-truth;
* replace human / PI judgment;
* validate paper extraction (extraction confidence is never laundered into the
  association probability — that contract lives in :mod:`society.uncertainty`);
* turn a low-evidence claim false (``unresolved`` != ``rejected``).

The certificate freezes *what was claimed and on what frozen basis*, and lets an
independent checker confirm the basis was not altered after the fact. A passing
certificate means "this verdict, on this basis, is replayable and tamper-evident",
never "this verdict is correct".

DESIGN
------
* Pure stdlib (``hashlib``, ``json``, ``dataclasses``, ``pathlib``). No DB, no deps.
* Hashing is deterministic: canonical, sorted-key, compact JSON (mirrors
  :func:`society.cards.fingerprint`) so rebuilding from the same inputs yields the
  same content hash (replay determinism).
* The independent checker (:func:`verify_certificate`) RECOMPUTES the content hash
  from the frozen fields and compares; it never trusts the stored hash.
* :class:`ProofLedger` is append-only JSONL with a backward hash chain: each line
  carries the previous line's content hash, so :meth:`ProofLedger.verify_chain`
  detects reordering, in-place edits, and *interior* deletions (any line removed
  from the middle breaks the link to its successor).

  LIMITATION — a self-contained backward chain canNOT detect tail-truncation or a
  total wipe: dropping the last line (or N trailing lines) leaves a shorter but
  still internally consistent prefix that verifies ``ok=True``, and an emptied file
  verifies as "chain intact, 0 entries". Detecting truncation requires an EXTERNAL
  anchor — the expected entry count and/or the expected last content-hash — which a
  caller can persist elsewhere and pass to :meth:`ProofLedger.verify_chain` via the
  opt-in ``expected_len`` / ``expected_tip`` parameters.

This module is service-tier-free and safe to import inside ``autoresearch``.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)

CERTIFICATE_SCHEMA = "neuroproof-certificate-v1"

#: The empty-chain sentinel: the ``prev_content_hash`` of the first ledger line.
GENESIS_PREV_HASH = "0" * 64

#: Default ledger location, under the repo runs/ dir. Injectable everywhere.
DEFAULT_LEDGER_PATH = Path("runs") / "ledger" / "neuroproof_ledger.jsonl"


class LedgerCorruptionError(Exception):
    """Raised when a ledger line is undecodable JSON in a position that is NOT the
    last line.

    A torn/truncated FINAL line is a benign crash-mid-append artifact: the writer
    died before its newline landed, so we drop it and keep the ledger readable and
    appendable. An undecodable line *before* the final one cannot be explained by a
    torn write — it is genuine corruption (or tampering), so we surface it as this
    typed, informative error instead of leaking a bare ``json.JSONDecodeError``.

    Carries ``line_index`` (0-based index of the offending line among non-blank
    lines) so callers can locate the damage.
    """

    def __init__(self, line_index: int, message: str = "") -> None:
        self.line_index = line_index
        detail = message or (
            f"undecodable JSON at ledger line index {line_index} (not the final "
            "line — genuine corruption, not a torn write)"
        )
        super().__init__(detail)


def _utc_now() -> str:
    """ISO-8601 UTC timestamp (matches ``society.cards._utc_now``)."""
    return datetime.now(timezone.utc).isoformat()


def _canonical(payload: Any) -> str:
    """Canonical JSON string: sorted keys, compact separators, ``default=str``.

    Byte-for-byte compatible with :func:`society.cards.fingerprint` so society and
    proof-ledger digests are directly comparable.
    """
    return json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))


def _digest(payload: Any) -> str:
    """SHA-256 hex digest over the canonical JSON encoding of ``payload``."""
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _report_to_dict(report: Any) -> dict[str, Any]:
    """Best-effort plain-dict view of a ``neuroclaim_compile`` result.

    Accepts a Pydantic ``NeuroClaimReportV1`` (``model_dump``) or an already-plain
    mapping, without importing the service tier or coupling to the model type.
    """
    if hasattr(report, "model_dump"):
        return dict(report.model_dump(mode="json"))
    if isinstance(report, dict):
        return dict(report)
    raise TypeError(
        "build_certificate expects a NeuroClaimReportV1 or a plain dict; "
        f"got {type(report)!r}"
    )


@dataclass(frozen=True)
class NeuroProofCertificateV1:
    """A tamper-evident, replayable audit certificate over one compile result.

    Every field below the ``content_hash`` is a *frozen* part of the audit basis.
    ``content_hash`` is a SHA-256 over the canonical encoding of all of them. The
    certificate does NOT certify empirical truth (see module docstring); it certifies
    that the recorded ``status``/``verdict_basis`` were produced from this exact frozen
    input/query/rule/backend basis and have not been altered.

    Frozen digests:

    * ``input_digest`` — over the claim text, scope, formalized claim, and the
      caller-supplied extra inputs that fed the compile.
    * ``query_digest`` — over the report's ``reproducible_query`` (the literal,
      re-runnable backend call + args).
    * ``ruleset_digest`` — over the structural typecheck rule outcome / ruleset id,
      i.e. the rule basis that could have emitted ``ill_typed``.
    * ``content_hash`` — over the whole frozen certificate body, recomputed and
      checked independently by :func:`verify_certificate`.
    """

    schema_version: str = CERTIFICATE_SCHEMA
    certificate_id: str = ""
    claim_id: str = ""
    claim_text: str = ""

    # The audit verdict being frozen (editorial, NOT ground-truth).
    status: str = ""
    verdict_basis: str = ""

    # Frozen digests over the audit basis.
    input_digest: str = ""
    query_digest: str = ""
    ruleset_digest: str = ""

    # Named backend + corpus version identifiers (the evidence basis identity).
    backend: str = ""
    corpus_version: str = ""

    # Honesty banner, frozen into the hash so it cannot be quietly dropped.
    certifies: str = (
        "Given these frozen inputs/query/rules/backend+corpus, this audit verdict "
        "is reproducible and untampered. This does NOT certify empirical truth; "
        "status is editorial, not ground-truth."
    )
    status_not_ground_truth: bool = True

    generated_at: str = field(default_factory=_utc_now)

    # The content hash over everything above. Excluded from the hash itself.
    content_hash: str = ""

    def hashable_body(self) -> dict[str, Any]:
        """The frozen *audit basis* fields the ``content_hash`` is computed over.

        Excludes ``content_hash`` (a hash cannot cover itself) and the two metadata
        fields that are NOT part of the audit basis: ``generated_at`` (wall-clock
        time of issuance) and ``certificate_id`` (a derived/assigned label). Holding
        these out is what makes the replay criterion hold: rebuilding a certificate
        from the same inputs/query/rules/backend+corpus yields the SAME content hash
        regardless of when it was issued.
        """
        body = asdict(self)
        for meta in ("content_hash", "generated_at", "certificate_id"):
            body.pop(meta, None)
        return body

    def compute_hash(self) -> str:
        """Recompute the content hash from the frozen body (does not mutate)."""
        return _digest(self.hashable_body())


def build_certificate(
    report: Any,
    *,
    certificate_id: str | None = None,
    corpus_version: str = "",
    extra_inputs: dict[str, Any] | None = None,
) -> NeuroProofCertificateV1:
    """Construct a :class:`NeuroProofCertificateV1` from a compile result.

    Args:
        report: a ``NeuroClaimReportV1`` (or a plain dict view of one) produced by
            :func:`society.compile.neuroclaim_compile`.
        certificate_id: optional stable id; defaults to a content-derived slug over
            the claim id + input digest (deterministic for replay).
        corpus_version: the evidence corpus version identifier (e.g. the Neurosynth
            release the backend ran against). Frozen as part of the evidence identity.
        extra_inputs: optional additional caller inputs to fold into ``input_digest``
            (e.g. profile names, run flags) so the frozen basis is complete.

    The result satisfies ``verify_certificate(...).ok is True`` immediately.
    """
    data = _report_to_dict(report)

    claim_id = str(data.get("claim_id", ""))
    claim_text = str(data.get("claim_text", ""))
    status = str(data.get("status", ""))
    verdict_basis = str(data.get("verdict_basis", ""))
    backend = str(data.get("backend", ""))

    # input_digest: the claim + scope + formalized claim + any caller extras.
    input_payload = {
        "claim_id": claim_id,
        "claim_text": claim_text,
        "scope": data.get("scope"),
        "formalized_claim": data.get("formalized_claim"),
        "extra_inputs": extra_inputs or {},
    }
    input_digest = _digest(input_payload)

    # query_digest: the literal, re-runnable backend call recorded in the report.
    query_digest = _digest(data.get("reproducible_query", {}))

    # ruleset_digest: the structural typecheck basis (what could emit ill_typed).
    ruleset_digest = _digest(data.get("typecheck", {}))

    cert_id = certificate_id or (
        "neuroproof:"
        + hashlib.sha256(f"{claim_id}|{input_digest}".encode("utf-8")).hexdigest()[:16]
    )

    draft = NeuroProofCertificateV1(
        certificate_id=cert_id,
        claim_id=claim_id,
        claim_text=claim_text,
        status=status,
        verdict_basis=verdict_basis,
        input_digest=input_digest,
        query_digest=query_digest,
        ruleset_digest=ruleset_digest,
        backend=backend,
        corpus_version=corpus_version,
    )
    content_hash = draft.compute_hash()
    # dataclass is frozen; rebuild with the hash set.
    return NeuroProofCertificateV1(**{**asdict(draft), "content_hash": content_hash})


@dataclass(frozen=True)
class VerificationResult:
    """The outcome of the independent certificate checker."""

    ok: bool
    reason: str = ""


def verify_certificate(cert: NeuroProofCertificateV1) -> VerificationResult:
    """Independent checker: recompute the hash and compare. Never trusts the stored one.

    Returns pass/fail with a reason. A pass means the certificate's frozen basis is
    internally consistent and untampered — NOT that the wrapped verdict is empirically
    true (see module docstring).
    """
    if cert.schema_version != CERTIFICATE_SCHEMA:
        return VerificationResult(
            ok=False,
            reason=f"unknown certificate schema {cert.schema_version!r}",
        )
    if not cert.content_hash:
        return VerificationResult(ok=False, reason="missing content_hash")
    recomputed = cert.compute_hash()
    if recomputed != cert.content_hash:
        return VerificationResult(
            ok=False,
            reason=(
                "content hash mismatch — frozen field tampered "
                f"(stored={cert.content_hash[:12]}..., recomputed={recomputed[:12]}...)"
            ),
        )
    return VerificationResult(ok=True, reason="content hash matches frozen basis")


# --------------------------------------------------------------------------- #
# Append-only, hash-chained ledger.
# --------------------------------------------------------------------------- #


def _cert_from_record(record: dict[str, Any]) -> NeuroProofCertificateV1:
    """Rebuild a certificate from a stored ledger ``certificate`` mapping."""
    field_names = {f for f in NeuroProofCertificateV1.__dataclass_fields__}
    kwargs = {k: v for k, v in record.items() if k in field_names}
    return NeuroProofCertificateV1(**kwargs)


@dataclass
class ChainVerification:
    """The outcome of verifying a whole ledger chain."""

    ok: bool
    n_entries: int = 0
    reason: str = ""
    failed_index: int | None = None


class ProofLedger:
    """An append-only, hash-chained JSONL store of NeuroProof certificates.

    Each line is a JSON object::

        {"prev_content_hash": <hash of previous line's cert>,
         "certificate": <NeuroProofCertificateV1 as dict>}

    The first line links to :data:`GENESIS_PREV_HASH`. The chain makes reordering,
    in-place edits, and *interior* deletions detectable: :meth:`verify_chain`
    re-checks every certificate independently AND that each ``prev_content_hash``
    matches the prior line's certificate hash.

    A self-contained backward chain canNOT, on its own, detect tail-truncation (the
    last N lines removed) or a total wipe — a shorter valid prefix still verifies.
    Callers who have persisted an external anchor (expected entry count and/or
    expected last content-hash) can pass it to :meth:`verify_chain` via the opt-in
    ``expected_len`` / ``expected_tip`` parameters to catch truncation.

    The ledger never mutates or deletes prior lines — :meth:`append` only ever
    appends. The backing path is injectable (default :data:`DEFAULT_LEDGER_PATH`).
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else DEFAULT_LEDGER_PATH

    # -- reads -------------------------------------------------------------- #

    def _read_records(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with self.path.open("r", encoding="utf-8") as fh:
            raw_lines = [stripped for stripped in (ln.strip() for ln in fh) if stripped]

        records: list[dict[str, Any]] = []
        last_idx = len(raw_lines) - 1
        for idx, line in enumerate(raw_lines):
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                if idx == last_idx:
                    # Torn/truncated final line: a crash mid-append left a
                    # non-newline-terminated fragment. Treat it as a torn write —
                    # drop it so the ledger stays readable AND appendable (the next
                    # append rebuilds on the last intact certificate).
                    logger.warning(
                        "ProofLedger %s: dropping torn final line "
                        "(crash-mid-append artifact): %s",
                        self.path,
                        exc,
                    )
                    continue
                # An undecodable line in the MIDDLE of the file cannot be a torn
                # write — it is genuine corruption. Surface it as a typed error
                # rather than leaking a bare JSONDecodeError that would block all
                # reads and appends.
                raise LedgerCorruptionError(idx, message=str(exc)) from exc
        return records

    def last_hash(self) -> str:
        """The content hash of the last appended certificate, or genesis if empty."""
        records = self._read_records()
        if not records:
            return GENESIS_PREV_HASH
        return str(records[-1].get("certificate", {}).get("content_hash", GENESIS_PREV_HASH))

    def __len__(self) -> int:
        return len(self._read_records())

    def read_all(self) -> list[NeuroProofCertificateV1]:
        """Return every stored certificate, in append order."""
        return [_cert_from_record(r["certificate"]) for r in self._read_records()]

    # -- writes ------------------------------------------------------------- #

    def append(self, cert: NeuroProofCertificateV1) -> dict[str, Any]:
        """Append one certificate as a new chained line. Never mutates prior lines.

        The certificate must itself verify (we refuse to ledger a tampered cert).
        Returns the written record.
        """
        check = verify_certificate(cert)
        if not check.ok:
            raise ValueError(f"refusing to append an invalid certificate: {check.reason}")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Physically drop a torn (non-newline-terminated, undecodable) final line so
        # the new record lands on its own line instead of being concatenated onto the
        # crash-mid-append fragment. _read_records() already ignores such a tail
        # logically; this keeps the on-disk bytes consistent with what reads see.
        self._truncate_torn_final_line()
        record = {
            "prev_content_hash": self.last_hash(),
            "certificate": asdict(cert),
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(_canonical(record) + "\n")
        return record

    def _truncate_torn_final_line(self) -> None:
        """If the file's last line is a torn (undecodable) write, truncate it off.

        Only the final line is ever treated as torn; an undecodable interior line is
        genuine corruption and is left untouched here (it surfaces as
        :class:`LedgerCorruptionError` on read). A blank/newline-terminated file is a
        no-op.
        """
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as fh:
            raw_lines = fh.readlines()
        if not raw_lines:
            return
        last = raw_lines[-1]
        stripped = last.strip()
        if not stripped:
            return
        try:
            json.loads(stripped)
        except json.JSONDecodeError:
            # Torn final line: rewrite the file without it. Prior lines are intact
            # (any interior corruption would have raised before we got here).
            kept = "".join(raw_lines[:-1])
            if kept and not kept.endswith("\n"):
                kept += "\n"
            self.path.write_text(kept, encoding="utf-8")

    # -- integrity ---------------------------------------------------------- #

    def verify_chain(
        self,
        *,
        expected_len: int | None = None,
        expected_tip: str | None = None,
    ) -> ChainVerification:
        """Re-check every certificate and the hash links between consecutive lines.

        Detects: a tampered frozen field (cert hash mismatch), a broken/forged link
        (``prev_content_hash`` not matching the prior cert), and reordering/interior
        deletion (the link sequence no longer matches).

        A self-contained backward chain canNOT detect tail-truncation or a total wipe
        on its own: a shorter valid prefix (or an emptied file) still verifies. To
        catch that, a caller who has persisted an EXTERNAL anchor can pass it:

        * ``expected_len`` — the entry count the ledger is expected to have. If the
          actual count differs (e.g. truncated to a shorter prefix, or wiped to 0),
          the result is ``ok=False``.
        * ``expected_tip`` — the content hash of the certificate that is expected to
          be last. If the actual tip differs (including an empty ledger, whose tip is
          :data:`GENESIS_PREV_HASH`), the result is ``ok=False``.

        With neither argument supplied, behavior is unchanged (back-compatible): the
        chain is verified purely on its own internal consistency.
        """
        records = self._read_records()
        prev_hash = GENESIS_PREV_HASH
        for idx, record in enumerate(records):
            cert_record = record.get("certificate")
            if not isinstance(cert_record, dict):
                return ChainVerification(
                    ok=False,
                    n_entries=len(records),
                    reason=f"line {idx}: missing certificate object",
                    failed_index=idx,
                )
            cert = _cert_from_record(cert_record)
            cert_check = verify_certificate(cert)
            if not cert_check.ok:
                return ChainVerification(
                    ok=False,
                    n_entries=len(records),
                    reason=f"line {idx}: {cert_check.reason}",
                    failed_index=idx,
                )
            link = str(record.get("prev_content_hash", ""))
            if link != prev_hash:
                return ChainVerification(
                    ok=False,
                    n_entries=len(records),
                    reason=(
                        f"line {idx}: broken hash chain — prev_content_hash "
                        f"{link[:12]}... != expected {prev_hash[:12]}... "
                        "(reordering, deletion, or edit detected)"
                    ),
                    failed_index=idx,
                )
            prev_hash = cert.content_hash

        n_entries = len(records)
        # The internal chain is consistent. Now apply any EXTERNAL truncation anchors
        # the caller persisted — these are what catch tail-truncation / total wipe,
        # which a self-contained backward chain cannot see on its own.
        if expected_len is not None and n_entries != expected_len:
            return ChainVerification(
                ok=False,
                n_entries=n_entries,
                reason=(
                    f"truncation detected — {n_entries} entries present but "
                    f"expected_len={expected_len} (tail-truncation or wipe)"
                ),
                failed_index=None,
            )
        if expected_tip is not None and prev_hash != expected_tip:
            return ChainVerification(
                ok=False,
                n_entries=n_entries,
                reason=(
                    "truncation detected — ledger tip "
                    f"{prev_hash[:12]}... != expected_tip {expected_tip[:12]}... "
                    "(tail-truncation or wipe)"
                ),
                failed_index=None,
            )
        return ChainVerification(ok=True, n_entries=n_entries, reason="chain intact")


def append_certificates(
    ledger: ProofLedger, certs: Iterable[NeuroProofCertificateV1]
) -> int:
    """Convenience: append many certificates in order; returns the count appended."""
    n = 0
    for cert in certs:
        ledger.append(cert)
        n += 1
    return n
