"""The three shipped knowledge bases: validity, realistic scenarios, fuzzing."""

import random
import unittest

from expert import ALL_KBS, REPORT_MIN, Session

CHOICES = ("yes", "probably", "no", "unknown")


def consult(key, yes=(), probably=()):
    """Answer yes/probably to the named facts and 'no' to everything else asked."""
    s = Session(ALL_KBS[key])
    while (q := s.next_question()) is not None:
        s.answer(q.fact, "yes" if q.fact in yes else "probably" if q.fact in probably else "no")
    return s


def facts_of(session):
    return {d.fact: cf for d, cf in session.diagnoses()}


def top(session):
    found = session.diagnoses()
    return found[0][0].fact if found else None


class Health(unittest.TestCase):
    def test_every_kb_validates(self):
        for key, kb in ALL_KBS.items():
            with self.subTest(kb=key):
                self.assertEqual(kb.validate(), [])

    def test_every_kb_has_a_decent_size(self):
        for key, kb in ALL_KBS.items():
            with self.subTest(kb=key):
                self.assertGreaterEqual(len(kb.questions), 12)
                self.assertGreaterEqual(len(kb.rules), 12)
                self.assertGreaterEqual(len(kb.diagnoses), 10)

    def test_urgent_diagnoses_exist_and_are_chained(self):
        for key, final in (("car", "unsafe_to_drive"), ("computer", "backup_now")):
            kb = ALL_KBS[key]
            self.assertTrue(kb.diagnosis_for(final).urgent)
            # at least one rule feeds it from an intermediate (derived) fact
            derived = {r.then for r in kb.rules}
            feeders = [r for r in kb.rules if r.then == final]
            self.assertTrue(any(p in derived for r in feeders for p in r.if_all))


class CarScenarios(unittest.TestCase):
    def test_dead_battery(self):
        s = consult("car", yes={"no_start", "slow_or_no_crank", "clicking", "dim_lights"})
        self.assertEqual(top(s), "dead_battery")
        self.assertNotIn("starter_fault", facts_of(s))

    def test_starter_when_lights_stay_bright(self):
        s = consult("car", yes={"no_start", "slow_or_no_crank", "clicking"})
        self.assertEqual(top(s), "starter_fault")
        self.assertNotIn("dead_battery", facts_of(s))

    def test_out_of_fuel(self):
        self.assertEqual(top(consult("car", yes={"no_start", "cranks_normally", "fuel_low"})), "out_of_fuel")

    def test_fuel_pump(self):
        s = consult("car", yes={"no_start", "cranks_normally", "no_pump_hum"})
        self.assertEqual(top(s), "fuel_pump_fault")

    def test_overheating_with_dead_fan_is_unsafe(self):
        s = consult("car", yes={"overheating", "fan_dead"})
        found = facts_of(s)
        self.assertEqual(top(s), "unsafe_to_drive")
        self.assertIn("cooling_fan_fault", found)
        self.assertNotIn("thermostat_or_pump", found)

    def test_overheating_alone_points_at_thermostat_not_unsafe(self):
        found = facts_of(consult("car", yes={"overheating"}))
        self.assertIn("thermostat_or_pump", found)
        self.assertNotIn("unsafe_to_drive", found)

    def test_soft_brakes_are_the_top_warning(self):
        s = consult("car", yes={"brake_soft"})
        self.assertEqual(top(s), "unsafe_to_drive")
        self.assertIn("brake_fluid_air", facts_of(s))

    def test_vibration_only_when_braking_means_discs(self):
        found = facts_of(consult("car", yes={"vibration", "vibration_brake"}))
        self.assertIn("warped_rotors", found)
        self.assertNotIn("wheel_imbalance", found)

    def test_uncertain_answer_lowers_confidence(self):
        sure = facts_of(consult("car", yes={"brake_squeal"}))["worn_brake_pads"]
        unsure = facts_of(consult("car", probably={"brake_squeal"}))["worn_brake_pads"]
        self.assertLess(unsure, sure)

    def test_healthy_car_gets_no_diagnosis(self):
        self.assertEqual(consult("car").diagnoses(), [])


class ComputerScenarios(unittest.TestCase):
    def test_dead_outlet(self):
        s = consult("computer", yes={"no_power", "outlet_dead"})
        self.assertEqual(top(s), "outlet_problem")
        self.assertNotIn("psu_fault", facts_of(s))

    def test_psu(self):
        self.assertEqual(top(consult("computer", yes={"no_power"})), "psu_fault")

    def test_beeps_mean_reseat_ram(self):
        s = consult("computer", yes={"no_display", "beep_codes"})
        self.assertEqual(top(s), "memory_gpu_seating")
        self.assertNotIn("video_output_fault", facts_of(s))

    def test_failing_disk_triggers_backup_warning(self):
        s = consult("computer", yes={"boot_fail", "disk_noise"})
        found = facts_of(s)
        self.assertEqual([d.fact for d, _ in s.diagnoses()][:2], ["backup_now", "disk_failing"])
        self.assertIn("backup_now", found)
        self.assertNotIn("os_corrupted", found)

    def test_boot_failure_without_noise_is_the_os(self):
        self.assertEqual(top(consult("computer", yes={"boot_fail"})), "os_corrupted")

    def test_slow_hdd(self):
        self.assertEqual(top(consult("computer", yes={"slow", "disk_100", "hdd_old"})), "slow_hdd")

    def test_driver(self):
        self.assertEqual(top(consult("computer", yes={"bsod", "recent_driver"})), "driver_issue")

    def test_dust(self):
        found = facts_of(consult("computer", yes={"overheats", "dusty"}))
        self.assertIn("dust_overheat", found)
        self.assertNotIn("cooling_hw", found)


class NetworkScenarios(unittest.TestCase):
    def test_isp_outage(self):
        s = consult("network", yes={"no_internet", "others_also", "modem_light_red"})
        found = facts_of(s)
        self.assertEqual(top(s), "isp_outage")
        self.assertNotIn("router_restart", found)
        self.assertNotIn("device_network_issue", found)

    def test_router_restart_when_wan_light_is_fine(self):
        s = consult("network", yes={"no_internet", "others_also", "router_old_uptime"})
        self.assertEqual(top(s), "router_restart")

    def test_only_my_device(self):
        self.assertEqual(top(consult("network", yes={"no_internet"})), "device_network_issue")

    def test_dhcp(self):
        self.assertEqual(top(consult("network", yes={"no_internet", "ip_169"})), "dhcp_problem")

    def test_dns(self):
        self.assertEqual(top(consult("network", yes={"no_internet", "dns_fail"})), "dns_problem")

    def test_bandwidth_sharing(self):
        found = facts_of(consult("network", yes={"slow_net", "many_users", "slow_all_devices"}))
        self.assertIn("bandwidth_saturated", found)
        self.assertNotIn("isp_slow", found)

    def test_cable_fixes_slowness_means_wifi(self):
        self.assertEqual(top(consult("network", yes={"slow_net", "wired_ok"})), "wifi_interference")

    def test_single_site(self):
        self.assertEqual(top(consult("network", yes={"one_site"})), "site_specific")


class Fuzz(unittest.TestCase):
    RUNS = 600

    def run_random(self, key, seed):
        rng = random.Random(seed)
        kb = ALL_KBS[key]
        s = Session(kb)
        asked = 0
        while (q := s.next_question()) is not None:
            s.answer(q.fact, rng.choice(CHOICES))
            asked += 1
            self.assertLessEqual(asked, len(kb.questions))
        return s

    def test_random_sessions_are_well_formed(self):
        for key in ALL_KBS:
            for seed in range(self.RUNS):
                s = self.run_random(key, seed)
                found = s.diagnoses()
                order = [(not d.urgent, -cf) for d, cf in found]
                self.assertEqual(order, sorted(order))  # safety first, then certainty
                for _, cf in found:
                    self.assertGreaterEqual(cf, REPORT_MIN)
                    self.assertLessEqual(cf, 1.0)
                # every reported diagnosis can be explained
                for d, _ in found:
                    self.assertTrue(s.explain(d.fact).rules)

    def test_every_diagnosis_is_reachable(self):
        for key, kb in ALL_KBS.items():
            seen = set()
            for seed in range(4000):
                seen |= {d.fact for d, _ in self.run_random(key, seed).diagnoses()}
            missing = {d.fact for d in kb.diagnoses} - seen
            self.assertFalse(missing, f"{key}: never reached {missing}")

    def test_undo_is_the_inverse_of_answer(self):
        rng = random.Random(7)
        for key, kb in ALL_KBS.items():
            s = Session(kb)
            snapshots = []
            while (q := s.next_question()) is not None:
                snapshots.append((dict(s.evidence), q.fact))
                s.answer(q.fact, rng.choice(CHOICES))
            for evidence, fact in reversed(snapshots):
                s.undo()
                self.assertEqual(s.evidence, evidence)
                self.assertEqual(s.next_question().fact, fact)


if __name__ == "__main__":
    unittest.main()
