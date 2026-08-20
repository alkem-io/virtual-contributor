# 20. Shared outbound URL guard for ingestion fetches

Date: 2026-08-20

## Status

Accepted.

## Context

The space-ingest link fetcher accepts member-authored URLs and embeds successful
responses into a knowledge base.  It previously lacked destination validation,
delegated redirects to the HTTP client, buffered full response bodies before its
size check, and used a suffix comparison when deciding whether to rewrite an
Alkemio URI to the deployment host.  The latter could turn a lookalike host into
an authenticated request to the deployment.

The website crawler had a separate partial destination check.  Keeping separate
copies would make the two outbound HTTP paths drift again, while putting the new
logic in the ingest-space client would leave it outside the repository's
coverage measurement.

## Decision

1. Put destination classification in `plugins/url_guard.py`, shared by both
   ingest paths.  It permits only HTTP(S), resolves hostnames off the event
   loop with a timeout, denies loopback, link-local, private, reserved,
   unspecified, and multicast addresses, and returns a named refusal category.
2. Disable automatic redirects in the space link fetcher.  Its explicit loop
   validates every target before requesting it, follows at most five redirects,
   and computes credentials anew for every validated target.
3. Match deployment credentials by exact normalized hostname.  Rewrite only
   `alkem.io` itself or a true subdomain, never a raw suffix; relative URLs are
   not rewritten.
4. Ship the pinned-address DNS-rebinding defence.  Each validated address is
   used as the connection target while the original hostname is preserved in
   both the `Host` header and HTTPX's `sni_hostname` extension.  This maintains
   virtual hosting and TLS certificate validation without re-resolving between
   validation and connect.
5. Stream response bytes and stop as soon as the cap is exceeded; reject an
   over-cap declared length before reading it.

## Consequences

- The crawler retains its current queue and redirect semantics; only its base
  URL classification is shared.  Redirect hardening there remains follow-up
  work.
- Link fetch failures stay metadata-only and do not alter published result
  envelopes.  Refusal records carry only the link identifier, category, scheme,
  host, and hop count.
- Address pinning is covered with MockTransport assertions for literal connect
  target, Host header, and SNI extension.  This is the shipped design, not the
  validate-then-connect fallback.

Link: workspace spec `workspace#054-ingest-link-ssrf`.
