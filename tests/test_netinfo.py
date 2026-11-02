from backend.netinfo import default_gateway

ROUTE = """Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT
eth0\t00000000\t01015A0A\t0003\t0\t0\t0\t00000000\t0\t0\t0
eth0\t00015A0A\t00000000\t0001\t0\t0\t0\t00FFFFFF\t0\t0\t0
"""


def test_default_gateway_parses_proc_route(tmp_path):
    f = tmp_path / "route"
    f.write_text(ROUTE)
    assert default_gateway(f) == "10.90.1.1"


def test_default_gateway_missing_file(tmp_path):
    assert default_gateway(tmp_path / "nope") is None
