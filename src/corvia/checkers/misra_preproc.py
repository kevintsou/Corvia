"""MISRA C:2012 preprocessor rules (Rules 20.1-20.14) - placeholder.

This checker deliberately declares NO rules. The Section 20 preprocessor
rules (20.7 parenthesized macro parameters, 20.10/20.11/20.12 # and ##
operators, 20.14 matching #else/#endif files) all require access to
preprocessor tokens, but pycparser only sees the translation unit AFTER
preprocessing - macro definitions, # / ## operators and conditional
directives are gone by then. Declaring those rules here would falsely
advertise coverage that does not exist.

Implementing them would require a raw-source / token-level scanner run
before (or instead of) preprocessing. Until such a scanner exists, this
module stays registered as an inert stub so configurations referencing
"misra-preproc" keep working.
"""

from __future__ import annotations

from corvia.checkers.base import BaseChecker
from corvia.models import Severity
from corvia.registry import CheckerRegistry


class MisraPreprocChecker(BaseChecker):
    checker_id = "misra-preproc"
    description = "MISRA C:2012 Rules 20.x: preprocessor rules (not implementable post-preprocessing; inert stub)"
    default_severity = Severity.INFO
    misra_rules = []


CheckerRegistry.register(MisraPreprocChecker)
