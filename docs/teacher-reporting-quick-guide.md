# Teacher reporting quick guide

Meridian's eight reports are read-only views of existing teacher-controlled
Meridian records. They do not calculate or select a new Grade, create a new
proficiency judgment, change evidence, author a checkpoint, or write to an SIS,
LMS, or district gradebook.

## Start a report

1. Start `meridian` and choose **9. Reports**.
2. Choose the question that matches the task.
3. Choose the class and marking period by their displayed names.
4. Choose only the additional item the report needs, such as a student,
   assessment, checkpoint, or external-gradebook mapping file.
5. Review the context and choose **Generate preview**.

The preview begins with a compact summary and up to ten rows. **View all rows**
expands the table. **Details / Audit Trail** shows the preview digest, generation
time, and bounded source references without displaying producer-private student
work.

Some Grade reports use the one exact ReportingSnapshot explicitly selected for
current use in the **Snapshots** task. If no single current-use checkpoint can be
resolved safely, Meridian asks the teacher to select one; it never guesses the
newest snapshot.

## The eight questions

1. **What do I need to update in my gradebook?** Select an explicit,
   teacher-authored mapping JSON file. Meridian validates its class, marking
   period, exact proficiency scale, revision, and external-system label. Values
   are vendor-neutral representation values; there is no Genesis dependency and
   no external write.
2. **Why does this student have this grade?** Explain one student's exact Grade,
   policy, proficiency/evidence basis, freshness, and override state from the
   selected reporting checkpoint.
3. **How is my class doing on each standard?** Show the current class matrix and
   distributions. Missing judgments stay missing; custom scale labels are used.
4. **How has this student progressed?** Show exact proficiency-result lineage,
   including upward, downward, unchanged, insufficient, or superseded states.
5. **Who needs more evidence?** Show missing, pending, excluded, unmapped, or
   insufficient evidence using configured policy thresholds only.
6. **What changed since our last checkpoint?** Compare one chosen exact checkpoint
   with current Grade state using Meridian's existing Grade comparison taxonomy.
7. **Am I ready to close the marking period?** Summarize unresolved Meridian
   reporting conditions. This is not official close, SIS-ready, or district
   approval authority.
8. **What did this assignment or assessment contribute?** Describe recorded
   participation and associated changes without claiming unsupported causality.

Use **B** for Back, **M** for Main Menu, and **Q** to quit. If authority moves
during selection or generation, Meridian fails closed and asks for refreshed
choices instead of silently switching records.

## Save a local teacher copy

Choose **Save a local teacher copy**, then choose Markdown, CSV, TSV, or JSON and
type a full destination path in an existing real folder. Saving is explicit.
Meridian rejects linked destination directories and never silently replaces a
different existing file. It rebuilds the report with the original timestamp and
verifies the preview digest immediately before writing, then reads the file back
to verify exact bytes.

The saved file is a local teacher copy. Its existence does not mean an external
system received, accepted, synchronized, or published anything.

## Direct noninteractive commands

Power users and qualification automation can use `meridian reports --help`.
All eight report families support deterministic JSON plus practical Markdown,
CSV, or TSV rendering. File-output options use the same exact-byte,
non-overwriting writer as the menu. Direct commands remain explicit and never
open the interactive menu.

> Exact release artifacts prove what Meridian tested. Reader contracts determine
> what Meridian may consume.

> Meridian reports explain and transfer teacher-controlled Meridian state. They
> do not become official SIS/LMS records and do not write to external systems.
