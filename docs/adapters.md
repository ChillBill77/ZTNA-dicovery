# Identity Adapter Runbook

Operator guide for the four day-1 identity adapters landed in P3. Each adapter
pushes normalized `IdentityEvent` records to the Redis stream `identity.events`;
the correlator consumes that stream and maintains the in-memory
[`IdentityIndex`](../correlator/src/correlator/pipeline/identity_index.py) from
which `/api/identity/resolve` and the LCD `GroupAggregator` pull bindings.

All adapters auto-discover in `id-ingest` by convention (`*_adapter.py` under
`id-ingest/src/id_ingest/adapters/`). The id-ingest container binds low ports
(516/517/518) directly; Traefik publishes those entrypoints at the stack edge
and forwards to the container unchanged. See
[`traefik/dynamic/tcp-udp.yml`](../traefik/dynamic/tcp-udp.yml) for the router
wiring.

---

## 1. AD Event 4624 — Windows Event Forwarding + Winlogbeat

**Source:** domain controller `Security/4624` logon events forwarded via WEF
to a collector, which ships them as JSON-wrapped syslog.

### Windows side

1. **Set up a Windows Event Forwarding (WEF) collector.**
   - On a dedicated Windows Server: `wecutil qc` to enable Windows Event
     Collector.
   - Create a subscription for Security log event id `4624` (successful logon).
   - Add domain controllers as sources. Verify events arriving in the
     collector's forwarded-events log.

2. **Install Winlogbeat on the collector** and configure it to forward
   subscribed events as syslog to the ztna stack host.

   Minimal `winlogbeat.yml`:

   ```yaml
   winlogbeat.event_logs:
     - name: ForwardedEvents
       event_id: 4624

   output.syslog:
     hosts: ["udp://<stack-host>:516"]
     codec.format:
       string: '%{[@metadata][timestamp]} %{[host][hostname]} winlogbeat[%{[agent][id]}]: %{[json]}'
   ```

   (The adapter's parser expects `ts winlogbeat[pid]: {json}` framing — split
   on the first `": "`.)

### Adapter config

`/etc/flowvis/adapters/ad_4624.yaml`:

```yaml
host: 0.0.0.0
port: 516
# Optional — restrict to WEF collector IPs.
allowed_sources: [10.0.5.11, 10.0.5.12]
```

### Logon-type → confidence mapping

| LogonType | Meaning              | Confidence (default) |
|-----------|----------------------|----------------------|
| 2         | Interactive          | 90                   |
| 3         | Network              | 70                   |
| 10        | RemoteInteractive    | 90                   |
| 11        | CachedInteractive    | 50                   |

TTL defaults to 8 h (28 800 s). Events with `IpAddress=-` are dropped (no
network context to bind to an IP). Customize via
`CONFIDENCE_BY_LOGON_TYPE` in
`id-ingest/src/id_ingest/adapters/ad_4624_adapter.py` if your environment
ranks these differently.

### Validation

```bash
# From the stack host, send a crafted line:
logger --rfc3164 --server localhost --port 516 --udp \
  '{"event_id":4624,"@timestamp":"2026-04-22T12:00:00Z","winlog":{"event_data":{"TargetUserName":"test","TargetDomainName":"CORP","LogonType":"2","IpAddress":"10.0.12.34"}}}'

# Then:
docker compose exec postgres psql -U ztna -d ztna -c \
  "SELECT user_upn, src_ip, confidence FROM identity_events WHERE source='ad_4624' ORDER BY time DESC LIMIT 1;"
```

---

## 2. Entra ID sign-in logs — Microsoft Graph API

**Source:** `GET /auditLogs/signIns` (delta-poll every 60 s).

### Entra side

1. **App Registration** in Entra ID (Azure portal → Entra → App registrations → New).
2. **Application permissions** → Microsoft Graph → `AuditLog.Read.All`
   → admin-consent on behalf of the tenant.
3. **Certificates & secrets** → new client secret; capture the value.

### Stack config (.env)

```bash
ENTRA_TENANT_ID=<your-tenant-guid>
ENTRA_CLIENT_ID=<app-registration-client-id>
ENTRA_CLIENT_SECRET=<generated-secret>
ENTRA_CORP_CIDRS=10.0.0.0/8,192.168.0.0/16
ENTRA_POLL_INTERVAL_S=60
```

### Confidence

- IP in one of `ENTRA_CORP_CIDRS` → **80**
- Otherwise → **40** (Entra sign-in from external IP is a weaker signal)
- `errorCode != 0` sign-ins are dropped.

TTL defaults to 1 h (3 600 s). Adapter tracks a Graph `@odata.deltaLink` so
subsequent polls only fetch new events.

### Throttling

Graph throttles at ~1 000 rps per tenant; `ENTRA_POLL_INTERVAL_S=60` is well
below. Backoff on 429/5xx is implemented as a warning log + skip-this-cycle
(adapter retries on next poll).

---

## 3. Cisco ISE RADIUS Accounting — LiveLogs syslog

**Source:** ISE Policy Service Node RADIUS Accounting Start/Stop events.

### ISE side

1. **Administration → System → Logging → Logging Targets** → add
   `<stack-host>:517/udp` (plain syslog).
2. **Administration → System → Logging → Logging Categories** →
   `RADIUS Accounting` → set severity `INFO`, targets includes the one above.
3. **Keep both Start and Stop** forwarded — the adapter distinguishes by
   `Acct-Status-Type` and emits `event_type=nac-auth-stop` (TTL 0) on Stop so
   the `IdentityIndex` invalidates the prior binding.

### Adapter config

`/etc/flowvis/adapters/cisco_ise.yaml`:

```yaml
host: 0.0.0.0
port: 517
allowed_sources: [10.0.100.10, 10.0.100.11]   # PSN IPs
```

### Confidence

Fixed at **95** (802.1X is the strongest binding available). TTL comes from
the `Session-Timeout` RADIUS attribute if present, otherwise defaults to 12 h.

### Sample line the parser expects

```
<14>2026-04-22T12:10:00Z ise01 CISE_RADIUS_Accounting … UserName=alice, Framed-IP-Address=10.0.12.34, Calling-Station-ID=AA-BB-CC-DD-EE-FF, Acct-Status-Type=Start, Session-Timeout=3600, Acct-Session-Id=ABCDEF01
```

Fields consumed: `UserName`, `Framed-IP-Address`, `Calling-Station-ID` (MAC),
`Acct-Status-Type`, `Session-Timeout` (optional), `Acct-Session-Id`.

---

## 4. Aruba ClearPass — CEF syslog

**Source:** ClearPass Policy Manager Session logs in CEF format.

### ClearPass side

1. **Administration → External Servers → Syslog Export Servers** → add
   `<stack-host>:518/udp`, format `CEF`.
2. **Administration → External Servers → Syslog Export Filters** → add a
   filter subscribing to **Session Logs**, attach to the syslog server.
3. Verify **Filter → Data Filter** selects at least the fields listed below.

### Adapter config

`/etc/flowvis/adapters/aruba_clearpass.yaml`:

```yaml
host: 0.0.0.0
port: 518
allowed_sources: [10.0.100.30]
```

### Fields consumed

| CEF key          | Meaning                                          |
|------------------|--------------------------------------------------|
| `src`            | Framed IP assigned to the endpoint               |
| `suser`          | Authenticated user (UPN)                         |
| `smac`           | Station MAC                                      |
| `cs2Label`/`cs2` | Paired: when `cs2Label=Session-Timeout`, `cs2` is the TTL in seconds |
| `externalId`     | ClearPass session id (used as `raw_id`)          |

Confidence fixed at **95**. `Accounting-Stop` events (name contains "Stop")
emit `event_type=nac-auth-stop` and TTL 0, invalidating the prior binding.

---

## Troubleshooting

1. **No rows in `identity_events`.** Check Traefik access log for the
   identity entrypoints (`docker compose logs traefik | grep ad-syslog`);
   then `docker compose logs id-ingest` for parse errors. Confirm the source
   IP matches `allowed_sources` in the adapter YAML if set.

2. **Unknown-user ratio > 50 % sustained.** Either an identity adapter is
   silent (check its healthcheck in `/api/adapters`), or the flow ingress
   includes IPs not in any identity binding (e.g., servers with no logged-in
   user). Inspect:

   ```sql
   SELECT src_ip, COUNT(*) FROM flows
   WHERE src_ip NOT IN (SELECT DISTINCT src_ip FROM identity_events
                        WHERE time > now() - INTERVAL '1 hour')
   GROUP BY src_ip ORDER BY 2 DESC LIMIT 20;
   ```

3. **Group enrichment missing.** `group-sync` worker may be disabled — the
   worker only runs when either `AD_LDAP_URL` or `ENTRA_TENANT_ID` is set.
   Check `docker compose logs id-ingest | grep group-sync` and
   `GET /api/stats` → `group_sync_age_seconds` (None = never run).

4. **Confidence distribution sanity check.**

   ```sql
   SELECT source, confidence, COUNT(*)
   FROM identity_events
   WHERE time > now() - INTERVAL '15 minutes'
   GROUP BY 1, 2 ORDER BY 1, 2;
   ```

   ISE/ClearPass entries should cluster at 95; AD at 70–90; Entra at 40 or 80
   based on your `ENTRA_CORP_CIDRS`.

5. **Traefik TCP/UDP routers not picking up the change.** The file provider
   hot-reloads on change but the container must have the config volume
   mounted (`./traefik/dynamic:/etc/traefik/dynamic:ro`). Verify with
   `docker compose exec traefik cat /etc/traefik/dynamic/tcp-udp.yml`.
