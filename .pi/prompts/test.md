Add or update focused tests for the current MemoSight change.

Prefer small tests that exercise the public contract:
- parser, normalizer, validator, schema, backend adapter, or CLI behavior
- success and failure cases when the change touches validation or errors
- no broad fixtures unless the existing tests already use them

Run the targeted pytest file before stopping.
