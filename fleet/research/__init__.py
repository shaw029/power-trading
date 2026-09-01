"""The research tier of the fleet package.

Everything in here assumes the full profile: the whole BM-registered population,
a multi-year window, or a public register pulled in its entirety. That is the
opposite of what the live dashboard can afford — it runs on roughly a gigabyte,
one container, and a cold start on every redeploy — so a single import reaching
in from the presentation tier would not fail loudly, it would quietly push a
working app over its memory limit.

The boundary is the directory, not a list. ``tests/test_profile_boundary.py``
forbids anything under this package from being reachable from the dashboard's
import surface, and it derives both sides from disk, so a module added here is
protected the day it is written rather than the day someone remembers to add it
to a set literal.

``docs/DATA_ARCHITECTURE.md`` explains why the two tiers exist.
"""
