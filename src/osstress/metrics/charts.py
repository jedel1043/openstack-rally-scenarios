"""Rally ``add_output`` chart builders for host metrics."""

from typing import Any

from metrics.snapshot import HostMetricsSnapshot


def build_rally_output_charts(
    host_snapshots: dict[str, list[HostMetricsSnapshot]],
) -> list[dict[str, Any]]:
    """Build Rally ``add_output`` chart data for **multiple hosts**.

    *host_snapshots* is a mapping of ``host_label -> [snap0, snap1, ...]``
    where each list contains the four chronological snapshots collected by
    the scenario plugin (baseline, mid_pre_trigger, post_trigger, final).

    Every chart contains one series **per host** so their resource usage
    can be compared side-by-side in the Rally HTML report.

    Returns a list of *complete* output dicts suitable for
    ``self.add_output(complete=...)``.
    """
    charts: list[dict[str, Any]] = []
    host_labels = sorted(host_snapshots.keys())

    # ---- Memory usage — one series per host --------------------------------
    mem_series: list[list[Any]] = []
    for hlabel in host_labels:
        points: list[list[Any]] = []
        for idx, snap in enumerate(host_snapshots[hlabel]):
            if snap.memory:
                mem_total = snap.memory.mem_total_kb
                mem_used_pct = round(snap.memory.mem_used_kb / mem_total * 100, 2) if mem_total else 0.0
                points.append([idx, mem_used_pct])
        if points:
            mem_series.append(["%s Memory Used %%" % hlabel, points])
    if mem_series:
        charts.append(
            {
                "title": "Host Memory Usage (%) — All Hosts",
                "description": (
                    "Percentage of memory in use at each sample point, "
                    "one series per host"
                ),
                "chart_plugin": "Lines",
                "data": mem_series,
                "label": "Memory %",
                "axis_label": "Sample",
            }
        )

    # ---- CPU busy % — one series per host ----------------------------------
    cpu_series: list[list[Any]] = []
    for hlabel in host_labels:
        snaps = host_snapshots[hlabel]
        points = []
        for idx in range(1, len(snaps)):
            b_cpu = snaps[idx - 1].cpu
            a_cpu = snaps[idx].cpu
            if b_cpu and a_cpu:
                usage = b_cpu.usage_pct(a_cpu)
                points.append([idx, usage["busy_pct"]])
        if points:
            cpu_series.append(["%s CPU Busy %%" % hlabel, points])
    if cpu_series:
        charts.append(
            {
                "title": "Host CPU Busy (%) — All Hosts",
                "description": (
                    "CPU busy percentage between consecutive sample points, "
                    "one series per host"
                ),
                "chart_plugin": "Lines",
                "data": cpu_series,
                "label": "CPU %",
                "axis_label": "Sample",
            }
        )

    # ---- Disk I/O sectors read — one series per host -----------------------
    io_read_series: list[list[Any]] = []
    io_write_series: list[list[Any]] = []
    for hlabel in host_labels:
        snaps = host_snapshots[hlabel]
        rd_points: list[list[Any]] = []
        wr_points: list[list[Any]] = []
        for idx in range(1, len(snaps)):
            b_io = snaps[idx - 1].io
            a_io = snaps[idx].io
            if b_io and a_io:
                delta = b_io.diff(a_io)
                rd_points.append([idx, delta["sectors_read"]])
                wr_points.append([idx, delta["sectors_written"]])
        if rd_points:
            io_read_series.append(["%s Sectors Read" % hlabel, rd_points])
        if wr_points:
            io_write_series.append(["%s Sectors Written" % hlabel, wr_points])
    combined_io = io_read_series + io_write_series
    if combined_io:
        charts.append(
            {
                "title": "Host Disk I/O (sectors) — All Hosts",
                "description": (
                    "Sectors read/written between consecutive sample points, "
                    "one series per host"
                ),
                "chart_plugin": "Lines",
                "data": combined_io,
                "label": "Sectors",
                "axis_label": "Sample",
            }
        )

    # ---- Network throughput — one series per host --------------------------
    net_rx_series: list[list[Any]] = []
    net_tx_series: list[list[Any]] = []
    for hlabel in host_labels:
        snaps = host_snapshots[hlabel]
        rx_points: list[list[Any]] = []
        tx_points: list[list[Any]] = []
        for idx in range(1, len(snaps)):
            b_net = snaps[idx - 1].net
            a_net = snaps[idx].net
            if b_net and a_net:
                delta = b_net.diff(a_net)
                rx_points.append([idx, delta["rx_bytes"]])
                tx_points.append([idx, delta["tx_bytes"]])
        if rx_points:
            net_rx_series.append(["%s RX Bytes" % hlabel, rx_points])
        if tx_points:
            net_tx_series.append(["%s TX Bytes" % hlabel, tx_points])
    if net_rx_series:
        charts.append(
            {
                "title": "Host Network RX (bytes) — All Hosts",
                "description": (
                    "Bytes received between consecutive sample points, "
                    "one series per host"
                ),
                "chart_plugin": "Lines",
                "data": net_rx_series,
                "label": "Bytes",
                "axis_label": "Sample",
            }
        )
    if net_tx_series:
        charts.append(
            {
                "title": "Host Network TX (bytes) — All Hosts",
                "description": (
                    "Bytes transmitted between consecutive sample points, "
                    "one series per host"
                ),
                "chart_plugin": "Lines",
                "data": net_tx_series,
                "label": "Bytes",
                "axis_label": "Sample",
            }
        )

    # ---- Raw snapshot table — one row per (host, sample) -------------------
    table_rows: list[list[str]] = []
    for hlabel in host_labels:
        for snap in host_snapshots[hlabel]:
            d = snap.to_dict()
            mem = d.get("memory") or {}
            io_data = d.get("io") or {}
            net_data = d.get("net") or {}
            table_rows.append(
                [
                    hlabel,
                    snap.label,
                    str(round(mem["mem_used_kb"] / mem["mem_total_kb"] * 100, 2) if mem.get("mem_total_kb") else "N/A"),
                    str(mem.get("mem_total_kb", "N/A")),
                    str(io_data.get("reads_completed", "N/A")),
                    str(io_data.get("writes_completed", "N/A")),
                    str(io_data.get("ios_in_progress", "N/A")),
                    str(net_data.get("rx_bytes", "N/A")),
                    str(net_data.get("tx_bytes", "N/A")),
                ]
            )
    if table_rows:
        charts.append(
            {
                "title": "Host Metrics Snapshots — All Hosts",
                "description": "Raw metrics captured at each sample point per host",
                "chart_plugin": "Table",
                "data": {
                    "cols": [
                        "Host",
                        "Sample",
                        "Memory Used %",
                        "Memory Total (kB)",
                        "Disk Reads",
                        "Disk Writes",
                        "IOs In Progress",
                        "Net RX Bytes",
                        "Net TX Bytes",
                    ],
                    "rows": table_rows,
                },
            }
        )

    return charts