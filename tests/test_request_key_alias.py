"""Logical request keys accept both spellings while transport handles stay request ids."""
import argparse
from pathlib import Path

import pytest

from otto.hostctl.cli import build_parser as hostctl_parser
from otto.hostctl.portfolio import prepare_portfolio_request, save_parser
from otto.portfolio.cli import build_parser as portfolio_parser


@pytest.mark.parametrize("flag", ["--request-id", "--request-key"])
@pytest.mark.parametrize("args", [
    ["save", "project.json", "--actor", "owner"],
    ["retire", "{}", "--reason", "done"],
    ["create-pending", "--actor", "owner"],
    ["onboarding", "create", "--actor", "owner", "--title", "T", "--brief", "B"],
    ["onboarding", "reopen", "--actor", "owner", "--project-ref", "{}"],
    ["project-advisor-pair", "--actor", "owner", "--project-ref", "{}",
     "--manager-assignment-ref", "{}", "--manager-generation", "1"],
])
def test_portfolio_logical_mutations_share_request_id_destination(flag, args):
    cli_args = args[:]
    cli_args += [flag, "same-logical-key"]
    parsed = vars(portfolio_parser().parse_args(cli_args))
    assert parsed["request_id"] == "same-logical-key"


@pytest.mark.parametrize("flag", ["--request-id", "--request-key"])
def test_save_forwarder_aliases_to_identical_request_id(flag):
    parsed = save_parser().parse_args(["save", "project.json", flag, "same-logical-key"])
    assert parsed.request_id == "same-logical-key"

    request = argparse.Namespace(portfolio_args=["save", "project.json", flag, "same-logical-key"])
    prepare_portfolio_request(request)
    assert request.portfolio_args == ["save", str(Path("project.json").absolute()),
                                      "--format", "json", "--request-id", "same-logical-key"]


def test_transport_request_status_keeps_request_id_spelling():
    parser = hostctl_parser()
    transport = parser.parse_args(["request-status", "--request-id", "transport-handle"])
    assert transport.request_id == "transport-handle"
    with pytest.raises(SystemExit):
        parser.parse_args(["request-status", "--request-key", "transport-handle"])
