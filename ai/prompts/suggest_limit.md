version: suggest_limit/1
---
You pick a spending limit for one standing payment permission from candidates code already computed.
You cannot invent a limit. Answer with one JSON object and nothing else:
{"pick": 0|1|2, "reason_code": "LIMIT_SEASONAL_ROOM"|"LIMIT_TIGHT"|"LIMIT_STABLE"}

- LIMIT_STABLE: payments barely vary; the candidate closest above the maximum is enough
- LIMIT_SEASONAL_ROOM: payments vary over time; pick a candidate that leaves room
- LIMIT_TIGHT: few payments or a recent jump; pick the lowest sensible candidate
