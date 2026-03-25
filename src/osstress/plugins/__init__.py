"""OsStress Rally scenario plugins.

This sub-package contains all Rally scenario plugins provided by the
OsStress project:

* :mod:`split_run` — split-run stress testing with host-level metrics.
* :mod:`find_limits` — auto-stepping load test to find service limits.

Rally discovers these automatically when ``--plugin-paths`` points to the
parent ``osstress`` directory, because Rally's ``load_plugins`` walks
subdirectories recursively.
"""