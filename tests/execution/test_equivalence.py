from .workload import Workload, fixed_clock


def test_serial_parallel_and_interrupted_resume_have_identical_business_outputs(tmp_path):
    workloads = [Workload(latency=.001), Workload(latency=.001), Workload(latency=.001, interrupt=True)]
    try:
        with fixed_clock():
            serial, parallel, resumed = workloads
            assert serial.execute(tmp_path / "serial", 1) == 0
            assert parallel.execute(tmp_path / "parallel", 6) == 0
            assert resumed.execute(tmp_path / "resume", 6) == 130
            completed = {r["task_key"]: r["attempt_count"] for r in resumed.store.tasks() if r["status"] == "completed"}
            assert completed and resumed.store.interrupted
            resumed.store.stop.clear()
            assert resumed.execute(tmp_path / "resume", 6) == 0
        expected = serial.outputs()
        assert expected == parallel.outputs() == resumed.outputs()
        assert len(expected["opportunities"]) == 12
        assert expected["signals"] and expected["contacts"]
        ranked = [ranked for item in expected["contacts"] for ranked in item["ranked"]]
        assert len(ranked) >= 12
        assert all(contact["contact"]["email_status"] == "VERIFIED_PUBLIC" for contact in ranked)
        assert all(contact["rank"] == 1 for contact in ranked)
        for row in resumed.store.tasks():
            if row["task_key"] in completed:
                assert row["attempt_count"] == completed[row["task_key"]]
        assert serial.counts() == parallel.counts()
        assert serial.counts()["retries"] == 12
    finally:
        for workload in workloads:
            workload.close()
