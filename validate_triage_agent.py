#!/usr/bin/env python3
"""
Validation script for TriageAgent - tests against real workflow failure scenarios.

This script:
1. Creates realistic FailureContext objects
2. Runs TriageAgent analysis with mocked GitHub API
3. Validates output quality and performance
4. Reports results
"""
import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from github_action_triage.agent.analysis.agent import TriageAgent
from github_action_triage.agent.ports import (
    FailureContext,
    FailureSummary,
    RepositoryRef,
    WorkflowRef,
    WorkflowRunFailureEvent,
)


VALIDATION_SCENARIOS = [
    {
        "name": "npm install failure - missing package-lock.json",
        "context": FailureContext(
            event=WorkflowRunFailureEvent(
                installation_id=12345,
                repository=RepositoryRef(owner="test-org", name="test-repo"),
                workflow=WorkflowRef(
                    run_id="123",
                    job_id="456",
                    workflow_name="CI",
                    job_name="build",
                    run_url="https://github.com/test-org/test-repo/actions/runs/123",
                ),
                failure=FailureSummary(
                    conclusion="failure",
                    logs_snippet="npm ERR! code ENOLOCK\nnpm ERR! audit This command requires an existing lockfile.",
                ),
            ),
            job_id=456,
            repository_full_name="test-org/test-repo",
            head_commit_sha="abc123def456",
            branch_ref="refs/heads/main",
            job_html_url="https://github.com/test-org/test-repo/actions/runs/123/job/456",
            logs_url="https://api.github.com/repos/test-org/test-repo/actions/jobs/456/logs",
            logs_excerpt="npm ERR! code ENOLOCK\nnpm ERR! audit This command requires an existing lockfile.\nnpm ERR! A complete log of this run can be found in:\nnpm ERR!     /home/runner/.npm/_logs/2023-01-01T00_00_00_000Z-debug.log",
        ),
        "expected_keywords": ["package-lock.json", "npm install", "lockfile"],
    },
    {
        "name": "Python linting errors - ruff violations",
        "context": FailureContext(
            event=WorkflowRunFailureEvent(
                installation_id=12345,
                repository=RepositoryRef(owner="test-org", name="python-project"),
                workflow=WorkflowRef(
                    run_id="789",
                    job_id="1011",
                    workflow_name="Lint",
                    job_name="ruff-check",
                    run_url="https://github.com/test-org/python-project/actions/runs/789",
                ),
                failure=FailureSummary(
                    conclusion="failure",
                    logs_snippet="ruff check .\nsrc/main.py:45:80: E501 Line too long (92 > 79 characters)",
                ),
            ),
            job_id=1011,
            repository_full_name="test-org/python-project",
            head_commit_sha="def789abc123",
            branch_ref="refs/heads/feature/new-api",
            job_html_url="https://github.com/test-org/python-project/actions/runs/789/job/1011",
            logs_url="https://api.github.com/repos/test-org/python-project/actions/jobs/1011/logs",
            logs_excerpt="ruff check .\nsrc/main.py:45:80: E501 Line too long (92 > 79 characters)\nsrc/utils.py:12:1: F401 [*] `os` imported but unused\nFound 2 errors.",
        ),
        "expected_keywords": ["ruff", "linting", "E501", "F401"],
    },
    {
        "name": "Test failures - pytest assertion errors",
        "context": FailureContext(
            event=WorkflowRunFailureEvent(
                installation_id=12345,
                repository=RepositoryRef(owner="test-org", name="api-service"),
                workflow=WorkflowRef(
                    run_id="321",
                    job_id="654",
                    workflow_name="Test",
                    job_name="pytest",
                    run_url="https://github.com/test-org/api-service/actions/runs/321",
                ),
                failure=FailureSummary(
                    conclusion="failure",
                    logs_snippet="FAILED tests/test_api.py::test_create_user - AssertionError: assert 500 == 201",
                ),
            ),
            job_id=654,
            repository_full_name="test-org/api-service",
            head_commit_sha="xyz123abc456",
            branch_ref="refs/heads/main",
            job_html_url="https://github.com/test-org/api-service/actions/runs/321/job/654",
            logs_url="https://api.github.com/repos/test-org/api-service/actions/jobs/654/logs",
            logs_excerpt="FAILED tests/test_api.py::test_create_user - AssertionError: assert 500 == 201\n    Expected status code 201, got 500\n    Response: {'error': 'Database connection failed'}",
        ),
        "expected_keywords": ["test", "assertion", "500", "database"],
    },
]


def create_mock_github_responses(context: FailureContext):
    """Create mock GitHub API responses for testing."""
    mock_job = {
        "id": int(context.job_id),
        "status": "completed",
        "conclusion": "failure",
        "head_sha": context.head_commit_sha,
        "head_branch": context.branch_ref.replace("refs/heads/", ""),
        "html_url": context.job_html_url,
        "steps": [
            {"name": "Checkout", "status": "completed", "conclusion": "success", "number": 1},
            {"name": "Install deps", "status": "completed", "conclusion": "success", "number": 2},
            {"name": "Run tests", "status": "completed", "conclusion": "failure", "number": 3},
        ],
    }
    
    mock_logs = f"""2024-01-01T00:00:00.0000000Z ##[group]Run tests
2024-01-01T00:00:01.0000000Z {context.logs_excerpt}
2024-01-01T00:00:02.0000000Z ##[error]Process completed with exit code 1."""
    
    return mock_job, mock_logs


async def mock_get_installation_client(ctx):
    """Mock GitHub client - always returns None (tools handle this)."""
    return None


async def validate_scenario(scenario: dict) -> dict:
    """Run validation for a single scenario."""
    print(f"\n{'='*80}")
    print(f"Validating: {scenario['name']}")
    print(f"{'='*80}")
    
    start_time = time.time()
    
    mock_job, mock_logs = create_mock_github_responses(scenario["context"])
    
    async def get_job_mock(ctx, job_id):
        return mock_job
    
    async def get_job_logs_mock(ctx, job_id):
        return mock_logs
    
    try:
        with patch("github_action_triage.agent.analysis.tools.github._get_installation_client", mock_get_installation_client):
            from github_action_triage.agent.analysis.tools import github
            
            # Temporarily replace the tool functions
            original_get_job = github.get_job
            original_get_job_logs = github.get_job_logs
            
            github.get_job = get_job_mock
            github.get_job_logs = get_job_logs_mock
            
            try:
                agent = TriageAgent()
                proposal = await agent.diagnose_and_propose(scenario["context"])
            finally:
                github.get_job = original_get_job
                github.get_job_logs = original_get_job_logs
        
        execution_time = time.time() - start_time
        
        print(f"\n✓ Analysis completed in {execution_time:.2f}s")
        print(f"\nIssue Title: {proposal.issue_title}")
        print(f"Fix Effort: {proposal.fix_effort}")
        print(f"\nIdentified Issue:\n{proposal.identified_issue}")
        print(f"\nRemediation Plan:\n{proposal.remediation_plan[:200]}...")
        
        validation_result = {
            "name": scenario["name"],
            "success": True,
            "execution_time": execution_time,
            "proposal": {
                "issue_title": proposal.issue_title,
                "identified_issue": proposal.identified_issue,
                "fix_effort": proposal.fix_effort,
                "has_remediation_plan": bool(proposal.remediation_plan),
                "has_job_metadata": bool(proposal.job_metadata),
                "involved_files_count": len(proposal.involved_files),
            },
            "validations": {
                "execution_time_ok": execution_time < 300,
                "has_issue_title": bool(proposal.issue_title),
                "title_length_ok": len(proposal.issue_title) < 80,
                "has_identified_issue": bool(proposal.identified_issue),
                "has_remediation_plan": bool(proposal.remediation_plan),
                "valid_fix_effort": proposal.fix_effort in ["small", "medium", "large"],
                "keywords_present": any(
                    keyword.lower() in proposal.identified_issue.lower() 
                    or keyword.lower() in proposal.remediation_plan.lower()
                    for keyword in scenario.get("expected_keywords", [])
                ),
            },
        }
        
        all_passed = all(validation_result["validations"].values())
        if all_passed:
            print(f"\n✓ All validations passed")
        else:
            print(f"\n✗ Some validations failed:")
            for check, passed in validation_result["validations"].items():
                if not passed:
                    print(f"  - {check}: FAILED")
        
        return validation_result
        
    except Exception as e:
        execution_time = time.time() - start_time
        print(f"\n✗ Analysis failed after {execution_time:.2f}s: {e}")
        return {
            "name": scenario["name"],
            "success": False,
            "execution_time": execution_time,
            "error": str(e),
        }


async def main():
    """Run all validation scenarios."""
    print("=" * 80)
    print("TriageAgent Validation Suite")
    print("=" * 80)
    
    results = []
    for scenario in VALIDATION_SCENARIOS:
        result = await validate_scenario(scenario)
        results.append(result)
    
    print("\n" + "=" * 80)
    print("Validation Summary")
    print("=" * 80)
    
    successful = sum(1 for r in results if r.get("success", False))
    total = len(results)
    
    print(f"\nScenarios: {successful}/{total} passed")
    
    for result in results:
        if result.get("success"):
            validations = result.get("validations", {})
            passed = sum(1 for v in validations.values() if v)
            total_checks = len(validations)
            print(f"\n✓ {result['name']}")
            print(f"  Execution time: {result['execution_time']:.2f}s")
            print(f"  Validations: {passed}/{total_checks} passed")
        else:
            print(f"\n✗ {result['name']}")
            print(f"  Error: {result.get('error', 'Unknown')}")
    
    output_file = Path("validation_results.json")
    with output_file.open("w") as f:
        json.dump(results, f, indent=2)
    
    print(f"\n✓ Detailed results written to {output_file}")
    
    if successful == total:
        print("\n✓✓✓ ALL VALIDATIONS PASSED ✓✓✓")
        return 0
    else:
        print(f"\n✗✗✗ {total - successful} VALIDATION(S) FAILED ✗✗✗")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
