from brain_researcher.services.agent.codegen.benchmark_scoring import (
    CodegenBenchmarkSignals,
    load_codegen_benchmark_policy,
    score_codegen_benchmark,
)


def test_load_codegen_benchmark_policy_reads_default_file():
    policy = load_codegen_benchmark_policy()

    assert policy["version"] == 1
    assert policy["weights"]["failure_detection"] > 0


def test_failed_regression_scores_higher_when_covered():
    base = {
        "failure_modes_identified": 2,
        "failure_modes_expected": 2,
        "verification_evidence_present": True,
        "tests_ran": True,
        "tests_added_or_updated": 1,
        "negative_tests_added": 1,
        "backward_checks": 1,
        "backward_checks_expected": 1,
        "domain_checks": 1,
        "domain_checks_expected": 1,
    }

    happy = score_codegen_benchmark(
        CodegenBenchmarkSignals(case_type="happy_path", **base)
    )
    regression = score_codegen_benchmark(
        CodegenBenchmarkSignals(
            case_type="failed_regression",
            failed_case_covered=True,
            **base,
        )
    )

    assert regression.total_score > happy.total_score


def test_silent_failure_penalty_hits_score_hard():
    strong = score_codegen_benchmark(
        CodegenBenchmarkSignals(
            case_type="failed_regression",
            failed_case_covered=True,
            failure_modes_identified=1,
            failure_modes_expected=1,
            verification_evidence_present=True,
            tests_ran=True,
            tests_added_or_updated=1,
            negative_tests_added=1,
            backward_checks=1,
            backward_checks_expected=1,
            domain_checks=1,
            domain_checks_expected=1,
        )
    )
    penalized = score_codegen_benchmark(
        CodegenBenchmarkSignals(
            case_type="failed_regression",
            failed_case_covered=True,
            failure_modes_identified=1,
            failure_modes_expected=1,
            verification_evidence_present=True,
            tests_ran=True,
            tests_added_or_updated=1,
            negative_tests_added=1,
            backward_checks=1,
            backward_checks_expected=1,
            domain_checks=1,
            domain_checks_expected=1,
            silent_failure=True,
            claimed_success_without_evidence=True,
        )
    )

    assert penalized.total_score < strong.total_score
    assert penalized.penalties["silent_failure"] > 0
    assert penalized.penalties["claimed_success_without_evidence"] > 0
