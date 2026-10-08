version: explain_permission/1
---
A standing payment permission could not be classified by fixed rules. Suggest what kind it looks like.
Answer with one JSON object and nothing else:
{"kind": "fixed_recurring"|"variable_recurring"|"one_time_authority"|"unknown",
 "reason_code": "EXPLAIN_IRREGULAR_RECURRING"|"EXPLAIN_USAGE_BASED"|"EXPLAIN_ONE_OFF"|"EXPLAIN_INSUFFICIENT_DATA"}
