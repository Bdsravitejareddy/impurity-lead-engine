from datetime import datetime, timedelta, timezone

from impurity_leads.opportunity_rescore import rescore_stale_opportunities

NOW = datetime(2026, 11, 4, tzinfo=timezone.utc)
RUN_START = NOW - timedelta(hours=1)


class Query:
    def __init__(self, client, table):
        self.client, self.table, self.filters, self.window, self.payload = client, table, [], None, None
    def select(self, columns):
        return self
    def eq(self, column, value):
        self.filters.append(lambda row: row.get(column) == value)
        return self
    def lt(self, column, value):
        self.filters.append(lambda row: row.get(column) is not None and row[column] < value)
        return self
    def in_(self, column, values):
        self.filters.append(lambda row: row.get(column) in values)
        return self
    def range(self, start, end):
        self.window = (start, end)
        return self
    def update(self, payload):
        self.payload = payload
        return self
    def execute(self):
        rows = [row for row in self.client.data[self.table] if all(check(row) for check in self.filters)]
        if self.payload is not None:
            self.client.updates.append((self.table, rows[0]["id"], self.payload))
            rows[0].update(self.payload)
        elif self.window:
            rows = rows[self.window[0]:self.window[1] + 1]
        return type("Result", (), {"data": rows})()


class Client:
    def __init__(self, opportunities, signals, companies=()):
        self.data = {"opportunities": opportunities, "signals": signals, "companies": list(companies)}
        self.updates = []
    def table(self, name):
        return Query(self, name)


def opportunity(id, company="c1", molecule="m1", score=92, priority="HOT", qualified=NOW - timedelta(days=3)):
    return {"id": id, "company_id": company, "molecule_id": molecule, "score": score, "priority": priority,
            "status": "new", "last_qualified_at": qualified.isoformat()}


def signal(kind, weight, company="c1", molecule="m1", n=0, source="trial", days_ago=400):
    return {"id": f"{kind}{n}{company}{molecule}", "company_id": company, "molecule_id": molecule, "source_type": source,
            "signal_type": kind, "source_url": f"https://x/{n}", "evidence_text": "e", "event_date": (NOW - timedelta(days=days_ago)).isoformat(),
            "discovered_at": NOW.isoformat(), "base_weight": weight, "confidence": 1.0, "fingerprint": f"{kind}{n}{company}{molecule}", "metadata_json": {}}


def test_old_rule_hot_from_filings_alone_is_demoted_below_the_dashboard_threshold():
    # Five filings summed to a HOT score under the old rules.
    client = Client([opportunity("o1")], [signal("regulatory_application", 22, n=n) for n in range(5)])
    result = rescore_stale_opportunities(client, qualified_before=RUN_START, now=NOW)
    assert client.updates == [("opportunities", "o1", {"score": 35 + 3, "priority": "REVIEW", "rationale": "regulatory application",
                                                      "likely_need_type": ["regulatory_application"], "decision_maker_role": []})]
    assert client.data["opportunities"][0]["score"] < 50
    assert result["lapsed"] == 1 and result["rescored"] == 1


def test_pair_requalified_in_this_run_is_left_alone():
    client = Client([opportunity("o1", qualified=NOW)], [signal("regulatory_application", 22)])
    result = rescore_stale_opportunities(client, qualified_before=RUN_START, now=NOW)
    assert client.updates == [] and result["evaluated"] == 0


def test_high_without_impurity_evidence_becomes_review_and_unchanged_scores_are_not_written():
    stale_high = opportunity("o1", score=70, priority="HIGH")
    current = opportunity("o2", molecule="m2", score=0, priority="HOT")
    signals = [signal("phase_iii", 18), signal("regulatory_application", 22), signal("method_validation", 30, source="job"),
               signal("direct_impurity_rfq", 40, molecule="m2")]
    client = Client([stale_high, current], signals)
    first = rescore_stale_opportunities(client, qualified_before=RUN_START, now=NOW)
    assert {id: payload["priority"] for _, id, payload in client.updates} == {"o1": "REVIEW", "o2": "HOT"}
    assert first["demoted"] == 1
    client.updates.clear()
    second = rescore_stale_opportunities(client, qualified_before=RUN_START, now=NOW)
    assert client.updates == [] and second["unchanged"] == 2


def test_vendor_company_lapses_and_pairs_without_signals_are_reported_not_guessed():
    vendor = Client([opportunity("o1"), opportunity("o2", company="c2")],
                    [signal("stability", 30), signal("impurity_vendor_exclusion", -100, molecule=None)])
    result = rescore_stale_opportunities(vendor, qualified_before=RUN_START, now=NOW)
    assert [(id, payload["score"]) for _, id, payload in vendor.updates] == [("o1", 0)]
    assert result["without_signals"] == 1


def test_dry_run_reports_without_writing():
    client = Client([opportunity("o1")], [signal("regulatory_application", 22)])
    result = rescore_stale_opportunities(client, qualified_before=None, now=NOW, apply=False)
    assert client.updates == [] and result["rescored"] == 1 and result["changes"][0]["after_score"] == 25


def test_rescore_stage_skips_without_credentials_and_cli_defaults_to_dry_run(monkeypatch, capsys):
    from impurity_leads import cli, opportunity_rescore
    from impurity_leads.config import Settings

    assert opportunity_rescore.run_stale_opportunity_rescore(Settings(), qualified_before=None)["status"] == "SKIPPED"
    calls = []
    monkeypatch.setattr(cli, "load_settings", lambda: Settings())
    monkeypatch.setattr(opportunity_rescore, "run_stale_opportunity_rescore",
                        lambda settings, **kwargs: calls.append(kwargs) or {"status": "COMPLETED"})
    assert cli.main(["rescore-opportunities"]) == 0
    assert cli.main(["rescore-opportunities", "--apply"]) == 0
    assert calls == [{"qualified_before": None, "apply": False}, {"qualified_before": None, "apply": True}]


def test_signals_on_a_soft_merged_twin_count_for_the_surviving_company():
    # The cleanup merged a duplicate "Accord Healthcare" row into the one holding the
    # opportunity; the signals stayed on the duplicate and were read as "no signals".
    companies = [{"id": "accord", "merged_into_company_id": None}, {"id": "accord-dup", "merged_into_company_id": "accord"}]
    signals = [signal("impurity_characterization", 38, company="accord-dup"), signal("phase_iii", 18, company="accord-dup", n=1)]
    client = Client([opportunity("o1", company="accord", score=90)], signals, companies)
    result = rescore_stale_opportunities(client, qualified_before=RUN_START, now=NOW)
    assert result["without_signals"] == 0
    assert result["evaluated"] == 1
    assert client.data["opportunities"][0]["score"] == 38 + 18 + 3  # plus the 400-day urgency bonus


def test_rescore_runs_before_the_soft_merge_column_exists():
    class NoMergeColumn(Client):
        def table(self, name):
            if name == "companies":
                raise RuntimeError("column companies.merged_into_company_id does not exist")
            return super().table(name)

    client = NoMergeColumn([opportunity("o1")], [signal("impurity_characterization", 38)])
    assert rescore_stale_opportunities(client, qualified_before=RUN_START, now=NOW)["without_signals"] == 0
