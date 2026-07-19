"""
Tests del sistema de métricas Prometheus y logging.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unifi_agent.api.metrics import metrics_router, record_request, record_diagnostic
from unifi_agent.core.logging import setup_logging, JSONFormatter


class TestMetricsEndpoint:
    def test_metrics_returns_200(self):
        app = FastAPI()
        app.include_router(metrics_router)
        client = TestClient(app)
        r = client.get("/metrics")
        assert r.status_code == 200

    def test_metrics_content_type(self):
        app = FastAPI()
        app.include_router(metrics_router)
        client = TestClient(app)
        r = client.get("/metrics")
        assert "text/plain" in r.headers["content-type"]

    def test_metrics_contain_app_info(self):
        app = FastAPI()
        app.include_router(metrics_router)
        client = TestClient(app)
        r = client.get("/metrics")
        assert b"unifi_agent_http_requests_total" in r.content or b"# HELP" in r.content


class TestMetricsHelpers:
    def test_record_request_no_crash(self):
        record_request("GET", "/test", 200, 0.1)

    def test_record_diagnostic_no_crash(self):
        record_diagnostic("success", 5.0)


class TestLoggingSetup:
    def test_setup_text_format(self, tmp_path):
        log_file = str(tmp_path / "test.log")
        logger = setup_logging(log_level="DEBUG", log_file=log_file, log_format="text")
        logger.info("Test message")
        assert os.path.exists(log_file)

    def test_setup_json_format(self, tmp_path):
        log_file = str(tmp_path / "test_json.log")
        logger = setup_logging(log_level="DEBUG", log_file=log_file, log_format="json")
        logger.info("Test JSON message")
        assert os.path.exists(log_file)

    def test_json_formatter(self):
        import logging
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="test.py",
            lineno=1, msg="test msg", args=(), exc_info=None,
        )
        output = formatter.format(record)
        assert '"level": "INFO"' in output
        assert '"message": "test msg"' in output
