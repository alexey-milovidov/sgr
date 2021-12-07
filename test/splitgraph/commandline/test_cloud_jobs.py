import os
import re
from test.splitgraph.commandline.http_fixtures import (
    ACCESS_TOKEN,
    GQL_ENDPOINT,
    STORAGE_ENDPOINT,
    gql_job_logs,
    gql_job_status,
    gql_upload,
    job_log_callback,
)
from test.splitgraph.conftest import RESOURCES
from unittest.mock import PropertyMock, patch

import httpretty
import pytest
import requests
from click.testing import CliRunner
from splitgraph.commandline.cloud import _deduplicate_items, logs_c, status_c, upload_c


@httpretty.activate(allow_net_connect=False)
def test_job_status_yaml():
    runner = CliRunner(mix_stderr=False)
    httpretty.register_uri(
        httpretty.HTTPretty.POST,
        GQL_ENDPOINT + "/",
        body=gql_job_status(),
    )

    with patch(
        "splitgraph.cloud.RESTAPIClient.access_token",
        new_callable=PropertyMock,
        return_value=ACCESS_TOKEN,
    ), patch("splitgraph.cloud.get_remote_param", return_value=GQL_ENDPOINT):
        result = runner.invoke(
            status_c,
            [
                "-f",
                os.path.join(RESOURCES, "repositories_yml", "repositories.yml"),
            ],
            catch_exceptions=False,
        )
        assert result.exit_code == 0

        assert (
            result.stdout
            == """Repository            Task ID         Started              Finished             Manual    Status
--------------------  --------------  -------------------  -------------------  --------  --------
otheruser/somerepo_2
someuser/somerepo_1   somerepo1_task  2020-01-01 00:00:00                       False     STARTED
someuser/somerepo_2   somerepo2_task  2021-01-01 00:00:00  2021-01-01 01:00:00  False     SUCCESS
"""
        )


@httpretty.activate(allow_net_connect=False)
def test_job_status_explicit_repos():
    runner = CliRunner(mix_stderr=False)
    httpretty.register_uri(
        httpretty.HTTPretty.POST,
        GQL_ENDPOINT + "/",
        body=gql_job_status(),
    )

    with patch(
        "splitgraph.cloud.RESTAPIClient.access_token",
        new_callable=PropertyMock,
        return_value=ACCESS_TOKEN,
    ), patch("splitgraph.cloud.get_remote_param", return_value=GQL_ENDPOINT):
        result = runner.invoke(
            status_c,
            ["someuser/somerepo_1", "otheruser/somerepo_2"],
            catch_exceptions=False,
        )
        assert result.exit_code == 0

        assert (
            result.stdout
            == """Repository            Task ID         Started              Finished    Manual    Status
--------------------  --------------  -------------------  ----------  --------  --------
someuser/somerepo_1   somerepo1_task  2020-01-01 00:00:00              False     STARTED
otheruser/somerepo_2
"""
        )


@httpretty.activate(allow_net_connect=False)
def test_job_logs():
    runner = CliRunner(mix_stderr=False)
    httpretty.register_uri(
        httpretty.HTTPretty.POST,
        GQL_ENDPOINT + "/",
        body=gql_job_logs(),
    )

    httpretty.register_uri(
        httpretty.HTTPretty.GET,
        re.compile(re.escape(STORAGE_ENDPOINT + "/") + ".*"),
        body=job_log_callback,
    )

    with patch(
        "splitgraph.cloud.RESTAPIClient.access_token",
        new_callable=PropertyMock,
        return_value=ACCESS_TOKEN,
    ), patch("splitgraph.cloud.get_remote_param", return_value=GQL_ENDPOINT):
        result = runner.invoke(
            logs_c,
            ["someuser/somerepo_1", "sometask"],
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        assert result.stdout == "Logs for /someuser/somerepo_1/sometask\n"

        with pytest.raises(requests.exceptions.HTTPError, match="404 Client Error: Not Found"):
            runner.invoke(logs_c, ["someuser/somerepo_1", "notfound"], catch_exceptions=False)


def test_deduplicate_items():
    assert _deduplicate_items(["item", "otheritem", "otheritem"]) == [
        "item",
        "otheritem_000",
        "otheritem_001",
    ]
    assert _deduplicate_items(["otheritem", "item"]) == ["otheritem", "item"]


@httpretty.activate(allow_net_connect=False)
@pytest.mark.parametrize("success", (True, False))
def test_csv_upload(success):
    gql_upload_cb, file_upload_cb = gql_upload(
        namespace="someuser",
        repository="somerepo_1",
        final_status="SUCCESS" if success else "FAILURE",
    )

    runner = CliRunner(mix_stderr=False)
    httpretty.register_uri(
        httpretty.HTTPretty.POST,
        GQL_ENDPOINT + "/",
        body=gql_upload_cb,
    )

    httpretty.register_uri(
        httpretty.HTTPretty.PUT,
        re.compile(re.escape(STORAGE_ENDPOINT + "/") + ".*"),
        body=file_upload_cb,
    )

    httpretty.register_uri(
        httpretty.HTTPretty.GET,
        re.compile(re.escape(STORAGE_ENDPOINT + "/") + ".*"),
        body=job_log_callback,
    )

    with patch(
        "splitgraph.cloud.RESTAPIClient.access_token",
        new_callable=PropertyMock,
        return_value=ACCESS_TOKEN,
    ), patch("splitgraph.cloud.get_remote_param", return_value=GQL_ENDPOINT), patch(
        "splitgraph.commandline.cloud.GQL_POLL_TIME", 0
    ):
        # Also patch out the poll frequency so that we don't wait between calls to the job
        # status endpoint.
        result = runner.invoke(
            upload_c,
            [
                "someuser/somerepo_1",
                os.path.join(RESOURCES, "ingestion", "csv", "base_df.csv"),
                os.path.join(RESOURCES, "ingestion", "csv", "patch_df.csv"),
            ],
        )

        if success:
            assert result.exit_code == 0
            assert "(STARTED) Loading someuser/somerepo_1, task ID ingest_task" in result.stdout
            assert "(SUCCESS) Loading someuser/somerepo_1, task ID ingest_task" in result.stdout
            assert (
                "See the repository at http://www.example.com/someuser/somerepo_1/-/tables"
                in result.stdout
            )
        else:
            assert result.exit_code == 1
            assert "(FAILURE) Loading someuser/somerepo_1, task ID ingest_task" in result.stdout
            # Check we got the job logs
            assert "Logs for /someuser/somerepo_1/ingest_task" in result.stdout