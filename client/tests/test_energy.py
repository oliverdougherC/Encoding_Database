import os
import tempfile
import unittest
from unittest import mock

from client import energy


class EnergyCollectorTests(unittest.TestCase):
    def test_collect_powercap_snapshot_labels_domains(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            pkg = os.path.join(root, "intel-rapl:0")
            dram = os.path.join(root, "intel-rapl:0:0")
            os.makedirs(pkg, exist_ok=True)
            os.makedirs(dram, exist_ok=True)
            with open(os.path.join(pkg, "name"), "w", encoding="utf-8") as handle:
                handle.write("package-0")
            with open(os.path.join(pkg, "energy_uj"), "w", encoding="utf-8") as handle:
                handle.write("1000000")
            with open(os.path.join(pkg, "max_energy_range_uj"), "w", encoding="utf-8") as handle:
                handle.write("4000000")
            with open(os.path.join(dram, "name"), "w", encoding="utf-8") as handle:
                handle.write("dram")
            with open(os.path.join(dram, "energy_uj"), "w", encoding="utf-8") as handle:
                handle.write("250000")
            with open(os.path.join(dram, "max_energy_range_uj"), "w", encoding="utf-8") as handle:
                handle.write("4000000")

            with mock.patch.object(energy, "_LINUX", True):
                snapshots = energy.collect_powercap_snapshot(root=root)

        self.assertEqual(
            [(item.domain, item.domainType) for item in snapshots],
            [
                ("rapl:intel-rapl:0:package-0", "cpu-package"),
                ("rapl:intel-rapl:0:0:dram", "dram"),
            ],
        )

    def test_collect_powercap_snapshot_reports_explicit_unsupported(self) -> None:
        with tempfile.TemporaryDirectory() as root, mock.patch.object(energy, "_LINUX", True):
            snapshots = energy.collect_powercap_snapshot(root=root)

        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0].state, "unsupported")
        self.assertEqual(snapshots[0].reason, "powercap_no_energy_domains")

    def test_finalize_energy_measurement_marks_counter_wrap(self) -> None:
        start = energy.EnergySnapshot(
            domain="rapl:intel-rapl:0:package-0",
            domainType="cpu-package",
            source="linux-powercap-rapl",
            collectorVersion="sysfs-v1",
            counterUnit="microjoule",
            counterValue=900.0,
            counterMax=1000.0,
        )
        end = energy.EnergySnapshot(
            domain="rapl:intel-rapl:0:package-0",
            domainType="cpu-package",
            source="linux-powercap-rapl",
            collectorVersion="sysfs-v1",
            counterUnit="microjoule",
            counterValue=100.0,
            counterMax=1000.0,
        )

        record = energy.finalize_energy_measurement(start, end, frame_count=100)

        self.assertEqual(record["counterState"], "wrapped")
        self.assertEqual(record["deltaJoules"], 0.0002)
        self.assertEqual(record["joulesPerFrame"], 0.000002)

    def test_finalize_energy_measurement_marks_counter_reset_without_wrap_range(self) -> None:
        start = energy.EnergySnapshot(
            domain="gpu-board:0",
            domainType="gpu-board",
            source="nvml-total-energy",
            collectorVersion="pynvml",
            counterUnit="millijoule",
            counterValue=500.0,
        )
        end = energy.EnergySnapshot(
            domain="gpu-board:0",
            domainType="gpu-board",
            source="nvml-total-energy",
            collectorVersion="pynvml",
            counterUnit="millijoule",
            counterValue=100.0,
        )

        record = energy.finalize_energy_measurement(start, end)

        self.assertEqual(record["counterState"], "reset")
        self.assertIsNone(record["deltaJoules"])
        self.assertEqual(record["reason"], "energy_counter_decreased_without_wrap_range")

    def test_collect_nvml_snapshot_without_selected_device_is_explicitly_unsupported(self) -> None:
        snapshots = energy.collect_nvml_snapshot(device_indexes=[])

        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0].domain, "gpu-board")
        self.assertEqual(snapshots[0].state, "unsupported")
        self.assertEqual(snapshots[0].reason, "nvml_device_not_selected")


if __name__ == "__main__":
    unittest.main()
