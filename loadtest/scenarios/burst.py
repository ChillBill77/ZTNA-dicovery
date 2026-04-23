"""Burst profile — 50 000 flows/s for 60 s, then 10 000 flows/s for the rest.

Step-down is driven by a LoadTestShape (to be wired up in locustfile.py; for
now this module carries the numbers the shape will consume).
"""

users = 500
spawn_rate = 500
duration_s = 180
scenario = "burst"
