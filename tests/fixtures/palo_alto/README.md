# Palo Alto PAN-OS TRAFFIC fixtures

Redacted, synthetic samples used by the P2 integration test harness.

- `traffic_end_sample.csv` — 20 sessions of `log_subtype=end`, mix of TCP/UDP,
  distinct dst tuples, including flows with App-ID `ms-office365` for SaaS
  matching and at least one `action=deny`.

All IPs are in RFC 5737 documentation ranges (`192.0.2.0/24`, `198.51.100.0/24`).
No real customer data.

Format reference: PAN-OS 10.x TRAFFIC CSV log fields (see Chunk 1 Task 1.3
field map in the P2 plan).
