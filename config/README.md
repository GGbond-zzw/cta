# Configuration

Version-controlled, non-secret research configuration belongs here.

Machine-local settings, RQData credentials, and license values must remain in
the local environment and must never be committed.

Phase 1 cache location is configured through ``RQDataConfig.cache_dir`` or the
machine-local ``CTA_RQDATA_CACHE_DIR`` environment variable.

``product_classification_v1.yaml`` is the deliberately small Phase 5 risk
grouping for RB, CU, and IF. It is not RQData point-in-time sector metadata and
does not decide whether a product belongs to the historical research universe.
Unknown products must be reviewed and added explicitly before sector or chain
caps can allocate them.
