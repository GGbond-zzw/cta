# Configuration

Version-controlled, non-secret research configuration belongs here.

Machine-local settings, RQData credentials, and license values must remain in
the local environment and must never be committed.

Phase 1 cache location is configured through ``RQDataConfig.cache_dir`` or the
machine-local ``CTA_RQDATA_CACHE_DIR`` environment variable.  No YAML file is
needed until a version-controlled non-secret setting actually exists.
