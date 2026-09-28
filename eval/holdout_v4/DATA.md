# Data dictionary (generated mechanically from the files in data/)

All times are UTC ISO-8601 unless a column says otherwise. `row_id` is the unique source-row identifier.

## data/store/price_5min.parquet (7350 rows)

`row_id` (VARCHAR), `source_id` (VARCHAR), `source_url` (VARCHAR), `container_sha256` (VARCHAR), `member` (VARCHAR), `member_sha256` (VARCHAR), `line_no` (BIGINT), `published_at_utc` (TIMESTAMP WITH TIME ZONE), `available_at_utc` (TIMESTAMP WITH TIME ZONE), `retrieved_at` (VARCHAR), `parser_version` (VARCHAR), `region` (VARCHAR), `interval_end_utc` (TIMESTAMP WITH TIME ZONE), `interval_start_utc` (TIMESTAMP WITH TIME ZONE), `intervention_record_published` (BOOLEAN), `runno` (BIGINT), `rrp` (DOUBLE), `rop` (DOUBLE), `price_status` (VARCHAR), `unit` (VARCHAR)

## data/store/regionsum_5min.parquet (7350 rows)

`row_id` (VARCHAR), `source_id` (VARCHAR), `source_url` (VARCHAR), `container_sha256` (VARCHAR), `member` (VARCHAR), `member_sha256` (VARCHAR), `line_no` (BIGINT), `published_at_utc` (TIMESTAMP WITH TIME ZONE), `available_at_utc` (TIMESTAMP WITH TIME ZONE), `retrieved_at` (VARCHAR), `parser_version` (VARCHAR), `region` (VARCHAR), `interval_end_utc` (TIMESTAMP WITH TIME ZONE), `interval_start_utc` (TIMESTAMP WITH TIME ZONE), `intervention_record_published` (BOOLEAN), `runno` (BIGINT), `totaldemand_mw` (DOUBLE), `availablegeneration_mw` (DOUBLE), `demandforecast_mw` (DOUBLE), `dispatchablegeneration_mw` (DOUBLE), `netinterchange_mw` (DOUBLE)

## data/store/opdemand_actual.parquet (3410 rows)

`row_id` (VARCHAR), `source_id` (VARCHAR), `source_url` (VARCHAR), `container_sha256` (VARCHAR), `member` (VARCHAR), `member_sha256` (VARCHAR), `line_no` (BIGINT), `published_at_utc` (TIMESTAMP WITH TIME ZONE), `available_at_utc` (TIMESTAMP WITH TIME ZONE), `retrieved_at` (VARCHAR), `parser_version` (VARCHAR), `region` (VARCHAR), `interval_end_utc` (TIMESTAMP WITH TIME ZONE), `interval_start_utc` (TIMESTAMP WITH TIME ZONE), `operational_demand_mw` (DOUBLE), `adjustment_mw` (DOUBLE), `wdr_estimate_mw` (DOUBLE), `revision` (VARCHAR), `unit` (VARCHAR), `definition` (VARCHAR)

## data/store/opdemand_forecast.parquet (149755 rows)

`row_id` (VARCHAR), `source_id` (VARCHAR), `source_url` (VARCHAR), `container_sha256` (VARCHAR), `member` (VARCHAR), `member_sha256` (VARCHAR), `line_no` (BIGINT), `published_at_utc` (TIMESTAMP WITH TIME ZONE), `available_at_utc` (TIMESTAMP WITH TIME ZONE), `retrieved_at` (VARCHAR), `parser_version` (VARCHAR), `region` (VARCHAR), `target_end_utc` (TIMESTAMP WITH TIME ZONE), `target_start_utc` (TIMESTAMP WITH TIME ZONE), `issued_at_utc` (TIMESTAMP WITH TIME ZONE), `run_id` (VARCHAR), `poe10_mw` (DOUBLE), `poe50_mw` (DOUBLE), `poe90_mw` (DOUBLE), `unit` (VARCHAR), `definition` (VARCHAR)

## data/store/scada_5min.parquet (754366 rows)

`row_id` (VARCHAR), `source_id` (VARCHAR), `source_url` (VARCHAR), `container_sha256` (VARCHAR), `member` (VARCHAR), `member_sha256` (VARCHAR), `line_no` (BIGINT), `published_at_utc` (TIMESTAMP WITH TIME ZONE), `available_at_utc` (TIMESTAMP WITH TIME ZONE), `retrieved_at` (VARCHAR), `parser_version` (VARCHAR), `duid` (VARCHAR), `interval_end_utc` (TIMESTAMP WITH TIME ZONE), `scada_mw` (DOUBLE), `unit` (VARCHAR), `reading_time_note` (VARCHAR)

## data/store/duid_region.parquet (23340 rows)

`row_id` (VARCHAR), `source_id` (VARCHAR), `source_url` (VARCHAR), `container_sha256` (VARCHAR), `member` (VARCHAR), `line_no` (BIGINT), `duid` (VARCHAR), `region` (VARCHAR), `valid_from_utc` (TIMESTAMP WITH TIME ZONE), `valid_to_utc` (TIMESTAMP WITH TIME ZONE), `dispatchtype` (VARCHAR), `schedule_type` (VARCHAR), `stationid` (VARCHAR), `parser_version` (VARCHAR)

## data/corpus.sqlite, table `chunks` (document passages)

`chunk_id`, `doc_id`, `title`, `url`, `doc_type`, `publication_date`, `event_region`, `event_date`, `page`, `section`, `text`, `chunk_hash`, `source_sha256`, `instruction_like`

Document types and passage counts: definition 144, market_notice 198, procedure 255
