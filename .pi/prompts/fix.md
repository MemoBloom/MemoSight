Fix the described MemoSight bug end to end.

Before editing:
- reproduce or identify the failing path
- grep callers of the function or CLI surface being changed
- choose the narrowest root-cause fix

After editing, run the smallest meaningful pytest target and report any
remaining risk.
