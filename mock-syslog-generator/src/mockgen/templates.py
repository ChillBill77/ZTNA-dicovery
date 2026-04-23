from __future__ import annotations

import random
from datetime import UTC, datetime


PAN_FIELDS = (
    "1,{ts},001801000000,TRAFFIC,end,2560,{ts},"
    "{src},{dst},,,allow-all,,,{app},vsys1,trust,untrust,ae1,ae2,,,,,"
    "{sport},{dport},,,0x400000,tcp,allow,{bytes},{pkts}"
)

FGT_FIELDS = (
    '<189>date={date} time={time} devname="fw02" logid="0000000013" '
    'type="traffic" subtype="forward" eventtype="forward" level="notice" vd="root" '
    'srcip={src} srcport={sport} dstip={dst} dstport={dport} proto=6 action="close" '
    'sentbyte={sent} rcvdbyte={rcvd} sentpkt={spkt} rcvdpkt={rpkt} '
    'appcat="Collaboration" app="{app}" status="close" hostname="{fqdn}"'
)

APPS_PAN = ["ms-office365", "ms-teams", "github", "salesforce", "zoom", "slack"]
APPS_FGT = ["SharePoint", "Teams", "GitHub", "Salesforce", "Zoom", "Slack"]
FQDNS = [
    "outlook.office365.com", "teams.microsoft.com", "api.github.com",
    "login.salesforce.com", "zoom.us", "wss-mobile.slack.com",
]


def pan_line() -> str:
    now = datetime.now(UTC).strftime("%Y/%m/%d %H:%M:%S")
    return PAN_FIELDS.format(
        ts=now,
        src=f"10.0.0.{random.randint(1, 250)}",
        dst=f"52.97.1.{random.randint(1, 250)}",
        sport=random.randint(10000, 60000),
        dport=random.choice([443, 80, 22, 53]),
        app=random.choice(APPS_PAN),
        bytes=random.randint(500, 50000),
        pkts=random.randint(1, 100),
    )


def fgt_line() -> str:
    now = datetime.now(UTC)
    sent = random.randint(500, 50000)
    rcvd = random.randint(500, 50000)
    return FGT_FIELDS.format(
        date=now.strftime("%Y-%m-%d"),
        time=now.strftime("%H:%M:%S"),
        src=f"10.0.1.{random.randint(1, 250)}",
        dst=f"52.97.2.{random.randint(1, 250)}",
        sport=random.randint(10000, 60000),
        dport=random.choice([443, 80, 22, 53]),
        sent=sent, rcvd=rcvd,
        spkt=random.randint(1, 100), rpkt=random.randint(1, 100),
        app=random.choice(APPS_FGT),
        fqdn=random.choice(FQDNS),
    )
