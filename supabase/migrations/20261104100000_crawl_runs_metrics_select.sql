-- The dashboard reads crawl_runs.metrics_json for crawler KPIs, but the
-- resumable-crawler migration granted authenticated users only a column list
-- that omitted it, so every dashboard read of crawl_runs failed with a
-- permission error. Coordinator tokens and config stay private.
grant select(metrics_json, current_stage) on public.crawl_runs to authenticated;
