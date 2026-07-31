"""iPhone MOV -> MP4 converter core.

This package is the GUI-reusable core: a caller (the CLI today, a GUI later)
constructs an :class:`~converter.decisions.Options`, probes a file with
:func:`~converter.probe.probe`, builds a plan with
:func:`~converter.decisions.plan_conversion`, and runs it with
:func:`~converter.convert.convert`.
"""

from .probe import MediaInfo, probe
from .decisions import Options, ConversionPlan, OutputFormat, Action, plan_conversion
from .convert import convert, build_command

__all__ = [
    "MediaInfo",
    "probe",
    "Options",
    "ConversionPlan",
    "OutputFormat",
    "Action",
    "plan_conversion",
    "convert",
    "build_command",
]
