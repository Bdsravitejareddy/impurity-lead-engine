from impurity_leads.execution.stages import run_post_crawl_stages


def test_post_crawl_stages_return_ordered_metrics_and_isolate_failure():
    events = []

    def ok():
        events.append("contact")
        return {"status": "COMPLETED", "processed": 2, "sources": 3, "links": 1}

    def broken():
        events.append("targeted")
        raise TimeoutError("provider unavailable")

    def later():
        events.append("opportunity")
        return {"status": "COMPLETED", "selected": 1}

    result = run_post_crawl_stages([
        ("contact_research", ok),
        ("targeted_research", broken),
        ("opportunity_evidence", later),
    ])
    assert events == ["contact", "targeted", "opportunity"]
    assert result.status == "PARTIAL"
    assert [stage.name for stage in result.stages] == ["contact_research", "targeted_research", "opportunity_evidence"]
    assert result.stages[0].processed == 2
    assert result.stages[1].status == "FAILED"
    assert result.stages[1].error == "TimeoutError"
    assert result.stages[2].metrics["selected"] == 1


def test_empty_post_crawl_pipeline_is_completed():
    result = run_post_crawl_stages([])
    assert result.status == "COMPLETED"
    assert result.stages == ()
