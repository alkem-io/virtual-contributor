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

1. Put the guarded fetch executor as well as destination classification in
   `plugins/url_guard.py`, shared by both ingest paths and measured by coverage.
   It permits only HTTP(S), resolves hostnames off the event loop with a
   timeout, denies loopback, link-local, private, reserved, unspecified, and
   multicast addresses, and returns a named refusal category.
2. Disable automatic redirects in the shared executor.  It validates every
   target before requesting it, follows at most five redirects, and gives the
   caller a fresh per-hop credential decision.
3. Match deployment credentials and the private-address exemption by exact
   normalized scheme, hostname, and port.  Rewrite only the `alkem.io` apex or
   the configured deployment origin, never a subdomain or raw suffix; relative
   URLs are not rewritten.
4. Ship the pinned-address DNS-rebinding defence.  Each validated address is
   used as the connection target while the original hostname is preserved in
   both the `Host` header and HTTPX's `sni_hostname` extension.  This maintains
   virtual hosting and TLS certificate validation without re-resolving between
   validation and connect.
5. Stream raw response bytes and stop as soon as either the raw or decoded
   body exceeds the cap; gzip and deflate decoding is bounded before data is
   appended.  Reject an over-cap declared length before reading it.  Unknown
   content types receive only a small magic-byte sniff before rejection.
6. Disable connection reuse between redirect hops with
   `max_keepalive_connections=0`, ensuring a TLS connection verified for one
   hostname cannot be reused for another hostname at the same address.

## Consequences

- The crawler retains its queue and same-domain policy, but now requests every
  page through the same pinned, explicit-redirect executor.  A redirect outside
  the crawl domain or to a refused address is not requested.
- Link fetch failures stay metadata-only and do not alter published result
  envelopes.  Refusal records carry only the link identifier, category, scheme,
  host, and hop count.
- Address pinning is covered with MockTransport assertions for literal connect
  target, Host header, and SNI extension.  This is the shipped design, not the
  validate-then-connect fallback.

Link: workspace spec `workspace#054-ingest-link-ssrf`.
