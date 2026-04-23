"""Sustained profile — ~20 000 flows/s for 10 minutes.

Each Locust user sends ~100 msgs/s via raw UDP; 200 users → 20k flows/s.
"""

users = 200
spawn_rate = 200
duration_s = 600
scenario = "sustained"
