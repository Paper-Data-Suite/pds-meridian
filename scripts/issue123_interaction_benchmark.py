"""#123 Slice 11H: controlled, reproducible *controller* interaction measurements.

Compare a pair of actual legacy and named read-only Meridian controllers against
exactly the same selected synthetic records and injected read-only domain loaders.
This is NOT an installed data/authorization benchmark, nor a general latency claim.
"""

from __future__ import annotations

import argparse
import json
import platform
import re
import sys
import tempfile
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path
from statistics import median
from time import perf_counter_ns
from types import SimpleNamespace
from typing import Any, cast

from pds_core.academic_catalog import CatalogAcademicPeriod
from pds_core.class_metadata import ClassMetadata
from pds_core.rosters import Roster

from meridian.grade_items_workflow import GradeItemsReview
from meridian.menu_grade_items import GradeItemsMenuDependencies, _review_one_grade_item
from meridian.menu_proficiency import (
    AcademicPeriodProficiencyPresentation,
    GradeItemProficiencyPresentation,
    PlanningReadinessPresentation,
    ProficiencyMenuDependencies,
    _review_grade_item,
)
from meridian.menu_teacher_named_review import (
    run_named_grade_item_proficiency,
    run_named_grade_item_review,
)
from meridian.teacher_navigation_choices import TeacherChoice
from meridian.teacher_navigation_context import (
    TeacherNavigationContext,
    TeacherNavigationReaders,
)
from meridian.teacher_navigation_domain import TeacherAcademicChoiceCatalog
from meridian.teacher_session import TeacherSessionContext

CLASS = "english_12_pd2"
GRADE_ITEM = "grade_essay_1"
STUDENT = "student_07"
STANDARD = "urn:synthetic:ELA:W.NW.11-12.3.D"
SCHOOL_YEAR = "2026-2027"
REPORT_SCHEMA = "pds.meridian.issue123.slice11h.controller_benchmark.v1"
RAW_SCOPE_PATTERN = re.compile(
    r"\b(?:class|grade item|student|standard|work|policy|period|snapshot|"
    r"review|publication)\s+id\b|sha256|cache key|digest|revision\s*:",
    re.I,
)


@dataclass
class Script:
    answers: list[str]
    calls: list[tuple[str, str]] = field(default_factory=list)

    def __call__(self, prompt: str = "") -> str:
        if not self.answers:
            raise AssertionError(f"Unexpected input prompt: {prompt!r}")
        answer = self.answers.pop(0)
        self.calls.append((prompt, answer))
        return answer


@dataclass
class CoreReaders:
    root: Path
    reads: Counter[str] = field(default_factory=Counter)

    def workspace(self) -> Path:
        self.reads["workspace"] += 1
        return self.root

    def year(self, root: Path) -> str:
        self.reads["year"] += 1
        assert root == self.root
        return SCHOOL_YEAR

    def metadata(self, root: Path, class_id: str) -> ClassMetadata:
        self.reads["metadata"] += 1
        assert root == self.root and class_id == CLASS
        return cast(
            ClassMetadata, SimpleNamespace(class_id=CLASS, school_year=SCHOOL_YEAR)
        )

    def roster(self, root: Path, class_id: str) -> Roster:
        self.reads["roster"] += 1
        assert root == self.root and class_id == CLASS
        return cast(Roster, SimpleNamespace(class_id=CLASS, students=()))

    def periods(self, root: Path, year: str) -> tuple[CatalogAcademicPeriod, ...]:
        self.reads["periods"] += 1
        assert root == self.root and year == SCHOOL_YEAR
        return ()


@dataclass
class Catalog:
    reads: Counter[str] = field(default_factory=Counter)

    def options(
        self, *, scope: str, selected: Mapping[str, str]
    ) -> tuple[TeacherChoice, ...]:
        self.reads[scope] += 1
        if scope == "class":
            assert not selected
            return (TeacherChoice((CLASS,), "English 12 · Period 2", "2026–2027"),)
        assert selected["class"] == CLASS
        if scope == "grade_item":
            return (
                TeacherChoice(
                    (GRADE_ITEM,),
                    "Active essay",
                    "Current · Unit 1",
                    witness="revision:1",
                ),
                TeacherChoice(
                    ("grade_archived",),
                    "Archived assessment",
                    "Archived",
                    witness="revision:1",
                ),
            )
        if scope == "student":
            assert selected.get("grade_item", GRADE_ITEM) == GRADE_ITEM
            values = []
            for number in range(1, 30):
                name = "Alex Rivera" if number in (7, 21) else f"Student {number:02d}"
                values.append(
                    TeacherChoice(
                        (f"student_{number:02d}",),
                        name,
                        f"English 12 · seat {number:02d}",
                        witness="roster:1",
                    )
                )
            return tuple(values)
        if scope == "standard":
            assert selected["student"] == STUDENT
            return (
                TeacherChoice(
                    (STANDARD,),
                    "Narrative writing",
                    "Selected proficiency",
                    witness="result:1",
                ),
            )
        raise AssertionError(f"Unexpected catalog scope: {scope}")


@dataclass
class Domain:
    root: Path
    reads: Counter[str] = field(default_factory=Counter)

    def review(self, root: Path, class_id: str) -> GradeItemsReview:
        self.reads["grade_item_review"] += 1
        assert root == self.root and class_id == CLASS
        row = SimpleNamespace(
            grade_item_id=GRADE_ITEM,
            title="Active essay",
            status="active",
            selection_state="current",
            purpose="standards_proficiency",
            selected_revision=1,
            latest_persisted_revision=1,
            memberships=(),
        )
        return cast(GradeItemsReview, SimpleNamespace(class_id=CLASS, items=(row,)))

    def proficiency(
        self,
        root: Path,
        class_id: str,
        grade_item_id: str,
        student_id: str,
        standard_id: str,
    ) -> GradeItemProficiencyPresentation:
        self.reads["proficiency_explanation"] += 1
        assert (root, class_id, grade_item_id, student_id, standard_id) == (
            self.root,
            CLASS,
            GRADE_ITEM,
            STUDENT,
            STANDARD,
        )
        return GradeItemProficiencyPresentation(
            class_id=CLASS,
            grade_item_id=GRADE_ITEM,
            grade_item_title="Active essay",
            student_id=STUDENT,
            standard_id=STANDARD,
            result_revision=1,
            result_sha256="a" * 64,
            policy_title="Synthetic policy",
            scale_title="Synthetic scale",
            status="calculated",
            proficiency_label="Meeting",
            performance_count=1,
            native_state_count=0,
            excluded_count=0,
        )


def _unused_period(*_args: Any) -> AcademicPeriodProficiencyPresentation:
    raise AssertionError("Unrelated period read in paired benchmark")


def _unused_planning(*_args: Any) -> PlanningReadinessPresentation:
    raise AssertionError("Unrelated planning read in paired benchmark")


def one_workload(mode: str, root: Path, *, pairs: int = 2) -> dict[str, Any]:
    """Measure the same ordered four reads, with a fresh session per workload."""
    if mode not in {"legacy", "named"} or pairs < 1:
        raise ValueError("Unsupported workload")
    core, catalog, domain = CoreReaders(root), Catalog(), Domain(root)
    typed_catalog = cast(TeacherAcademicChoiceCatalog, catalog)
    navigation = TeacherNavigationContext(
        session=TeacherSessionContext(),
        readers=TeacherNavigationReaders(
            workspace_resolver=core.workspace,
            active_year_loader=core.year,
            class_metadata_loader=core.metadata,
            roster_loader=core.roster,
            period_lister=core.periods,
        ),
    )
    stream = StringIO()
    all_calls: list[tuple[str, str]] = []
    grade_deps = GradeItemsMenuDependencies(
        workspace_resolver=core.workspace, review_loader=domain.review
    )
    proficiency_deps = ProficiencyMenuDependencies(
        workspace_resolver=core.workspace,
        grade_item_loader=domain.proficiency,
        academic_period_loader=_unused_period,
        planning_loader=_unused_planning,
    )
    started = perf_counter_ns()
    for number in range(pairs):
        if mode == "legacy":
            item_inputs = [CLASS, GRADE_ITEM, ""]
            proficiency_inputs = [CLASS, GRADE_ITEM, STUDENT, STANDARD, "B"]
        else:
            item_inputs = (["1"] if number == 0 else []) + ["1", ""]
            proficiency_inputs = ["1", "1", "1", ""]
        grade_script = Script(item_inputs)
        proficiency_script = Script(proficiency_inputs)
        if mode == "legacy":
            _review_one_grade_item(
                dependencies=grade_deps,
                input_fn=grade_script,
                output=stream,
                clear_fn=lambda: None,
            )
            _review_grade_item(
                deps=proficiency_deps,
                input_fn=proficiency_script,
                output=stream,
                clear_fn=lambda: None,
            )
        else:
            run_named_grade_item_review(
                navigation=navigation,
                catalog=typed_catalog,
                review_loader=domain.review,
                input_fn=grade_script,
                output=stream,
                clear_fn=lambda: None,
            )
            run_named_grade_item_proficiency(
                navigation=navigation,
                catalog=typed_catalog,
                load_proficiency=domain.proficiency,
                input_fn=proficiency_script,
                output=stream,
                clear_fn=lambda: None,
            )
        if grade_script.answers or proficiency_script.answers:
            raise AssertionError(
                "A controller failed to complete its scripted workflow"
            )
        all_calls.extend(grade_script.calls)
        all_calls.extend(proficiency_script.calls)
    elapsed = perf_counter_ns() - started
    if domain.reads != {"grade_item_review": pairs, "proficiency_explanation": pairs}:
        raise AssertionError(f"Mismatched domain work: {domain.reads}")
    if mode == "named":
        if navigation.session.active_class_id != CLASS:
            raise AssertionError("Named route failed to retain the exact class")
        if navigation.session.active_student_id != STUDENT:
            raise AssertionError("Named route did not retain the exact student")
        if "Current proficiency: Meeting" not in stream.getvalue():
            raise AssertionError("Named route did not reach the expected result")
        if "could not" in stream.getvalue().casefold():
            raise AssertionError("Named route reported a hidden failure")
    else:
        if "Current proficiency: Meeting" not in stream.getvalue():
            raise AssertionError("Legacy route did not reach the expected result")
    return {
        "mode": mode,
        "paired_grade_item_and_proficiency_reviews": pairs,
        "completed_domain_reads": dict(sorted(domain.reads.items())),
        "inputs": len(all_calls),
        "technical_id_prompts": sum(
            bool(RAW_SCOPE_PATTERN.search(p)) for p, _ in all_calls
        ),
        "repeated_class_id_prompts": max(
            0, sum(bool(re.search(r"\bClass ID\b", p, re.I)) for p, _ in all_calls) - 1
        ),
        "catalog_reads_total": sum(catalog.reads.values()),
        "catalog_reads_by_scope": dict(sorted(catalog.reads.items())),
        "core_reader_calls": dict(sorted(core.reads.items())),
        "elapsed_ns": elapsed,
    }


def _percentile(sorted_values: list[int], *, numerator: int, denominator: int) -> int:
    index = (len(sorted_values) * numerator + denominator - 1) // denominator - 1
    return sorted_values[max(index, 0)]


def benchmark(*, repeats: int = 21, pairs: int = 2, warmups: int = 3) -> dict[str, Any]:
    if not 1 <= repeats <= 101 or not 1 <= pairs <= 10 or not 0 <= warmups <= 20:
        raise ValueError("Benchmark settings exceed safe bounds")
    with tempfile.TemporaryDirectory(prefix="meridian123_slice11h_") as temporary:
        root = Path(temporary).resolve()
        for _ in range(warmups):
            one_workload("legacy", root, pairs=pairs)
            one_workload("named", root, pairs=pairs)
        samples: dict[str, list[dict[str, Any]]] = {"legacy": [], "named": []}
        # Alternate order to reduce systematic warm-cache and scheduler bias.
        for index in range(repeats):
            for mode in ("legacy", "named") if index % 2 == 0 else ("named", "legacy"):
                samples[mode].append(one_workload(mode, root, pairs=pairs))
    values: dict[str, dict[str, Any]] = {}
    for mode in ("legacy", "named"):
        rows = samples[mode]
        fields = (
            "inputs",
            "technical_id_prompts",
            "repeated_class_id_prompts",
            "catalog_reads_total",
            "catalog_reads_by_scope",
            "core_reader_calls",
            "completed_domain_reads",
        )
        for field_name in fields:
            if any(row[field_name] != rows[0][field_name] for row in rows):
                raise AssertionError(f"Non-deterministic {mode} {field_name}")
        timings = sorted(row["elapsed_ns"] for row in rows)
        values[mode] = {
            **{field_name: rows[0][field_name] for field_name in fields},
            "latency_median_ns": int(median(timings)),
            "latency_p95_ns": _percentile(timings, numerator=95, denominator=100),
            "latency_min_ns": timings[0],
            "latency_max_ns": timings[-1],
        }
    return {
        "schema": REPORT_SCHEMA,
        "comparison": (
            "same Grade Item review + selected Grade Item proficiency read, repeated"
        ),
        "paired_repetitions_per_sample": pairs,
        "measured_samples_per_mode": repeats,
        "unmeasured_warmup_pairs_per_mode": warmups,
        "runtime": {
            "python": platform.python_version(),
            "os": platform.system(),
            "arch": platform.machine(),
        },
        "scope": (
            "real legacy/named controllers; synthetic injected Core/catalog/domain "
            "read adapters; source-tree Python, not installed-wheel "
            "or full academic E2E"
        ),
        "latency_caveat": (
            "Measured local controller overhead only; synthetic adapters do not "
            "approximate disk, network, protected evidence, or classroom latency."
        ),
        "observed": values,
        "delta": {
            "inputs_named_minus_legacy": values["named"]["inputs"]
            - values["legacy"]["inputs"],
            "technical_prompts_named_minus_legacy": values["named"][
                "technical_id_prompts"
            ]
            - values["legacy"]["technical_id_prompts"],
            "catalog_reads_named_minus_legacy": values["named"]["catalog_reads_total"]
            - values["legacy"]["catalog_reads_total"],
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=21)
    parser.add_argument("--pairs", type=int, default=2)
    parser.add_argument("--warmups", type=int, default=3)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    report = benchmark(repeats=args.repeats, pairs=args.pairs, warmups=args.warmups)
    content = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.write_text(content, encoding="utf-8")
    print(content, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
