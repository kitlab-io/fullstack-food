"""Pin assignments: check what a site file assigns and propose pins for what it leaves blank.

A model lists the signals it needs (`pins` in catalog/models/), a board lists what each of
its pins can do (`pins` in catalog/boards/). Boards without a pin map are not checked.
Pins marked `caution` on the board (strapping pins, pins shared with USB or the serial
bridge) are accepted with a warning when a person assigns them, and never proposed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

SHARED = {"i2c_sda", "i2c_scl", "onewire"}      # one pin serves every device on the bus
OUTPUTS = {"digital_out", "pwm", "led_data"}


@dataclass
class PinReport:
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    proposals: dict[str, dict[str, str]] = field(default_factory=dict)     # device -> signal -> pin
    unassigned: list[str] = field(default_factory=list)                    # signals no clean pin is left for


def unfit(board: dict, pin: str, need: str) -> str | None:
    """Why this pin cannot carry this kind of signal, or None when it can."""
    spec = board["pins"][pin]
    if "reserved" in spec:
        return f"is reserved ({spec['reserved']})"
    if need == "adc":
        if "adc" not in spec:
            return "has no ADC"
        if spec["adc"] == "adc2" and board.get("adc2_blocked_by_wifi"):
            return "is on ADC2, which cannot be read while WiFi is on"
    if need in OUTPUTS and spec.get("input_only"):
        return "is input-only"
    return None


def check_node(node_id: str, board: dict, devices: list) -> PinReport:
    """devices: the node's Device objects, in site-file order."""
    report = PinReport()
    if "pins" not in board:
        return report
    used: dict[str, tuple[str, str, str]] = {}      # pin -> (need, device, signal)
    blank: list[tuple[object, dict]] = []
    wrong: list[tuple[object, dict, str]] = []

    for dev in devices:
        signals = {s["signal"]: s for s in dev.model.get("pins", [])}
        assigned = dev.raw.get("pins", {})
        for signal in assigned:
            if signal not in signals:
                known = ", ".join(signals) or "none"
                report.problems.append(f"device {dev.id}: model {dev.model['id']} has no signal {signal!r} (signals: {known})")
        for signal, spec in signals.items():
            pin = assigned.get(signal)
            if pin is None:
                blank.append((dev, spec))
                continue
            need = spec["needs"]
            if pin not in board["pins"]:
                wrong.append((dev, spec, f"board {board['id']} has no pin {pin}"))
                continue
            reason = unfit(board, pin, need)
            if reason:
                wrong.append((dev, spec, f"{pin} {reason}"))
                continue
            other = used.get(pin)
            if other and not (need in SHARED and other[0] == need):
                wrong.append((dev, spec, f"{pin} is already used by {other[1]} ({other[2]})"))
                continue
            used[pin] = (need, dev.id, signal)
            caution = board["pins"][pin].get("caution")
            if caution:
                report.warnings.append(f"device {dev.id}: {signal} on {pin}: {caution}")

    def free_for(need: str) -> list[str]:
        """Clean pins that fit, those sharing the bus first, then pins that waste no ADC."""
        if need in SHARED:
            bus = [pin for pin, (n, _, _) in used.items() if n == need]
            if bus:
                return bus
        fits = [pin for pin, spec in board["pins"].items()
                if pin not in used and "caution" not in spec and unfit(board, pin, need) is None]
        return sorted(fits, key=lambda pin: need != "adc" and unfit(board, pin, "adc") is None)

    for dev, spec, reason in wrong:     # hints come from what the valid assignments leave free
        options = free_for(spec["needs"])
        hint = f"pins that can: {', '.join(options[:4])}" if options else "no free pin on this board can"
        report.problems.append(f"device {dev.id}: {spec['signal']} ({spec['needs']}): {reason}; {hint}")

    # Signals with the fewest options first, so an ADC input is not left without an ADC pin.
    for dev, spec in sorted(blank, key=lambda item: item[1]["needs"] != "adc"):
        options = free_for(spec["needs"])
        if not options:
            report.unassigned.append(f"device {dev.id}: no free pin on {board['id']} for {spec['signal']} ({spec['needs']})")
            continue
        used[options[0]] = (spec["needs"], dev.id, spec["signal"])
        report.proposals.setdefault(dev.id, {})[spec["signal"]] = options[0]

    if report.unassigned:
        careful = [pin for pin, spec in board["pins"].items() if "caution" in spec and pin not in used]
        report.unassigned.append(
            f"node {node_id}: the build needs more pins than {board['id']} has free. Options: a board with more pins, "
            f"an I2C ADC or expander, or assign one of {', '.join(careful)} by hand after reading its caution")
    return report
