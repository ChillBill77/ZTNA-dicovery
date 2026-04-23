"""Identity surge — 1 000 identity events/s for 60 seconds.

FlowSender is expected to be disabled by selecting only the ``IdentitySender``
user class at run time.
"""

users = 100
spawn_rate = 100
duration_s = 120
scenario = "identity_surge"
