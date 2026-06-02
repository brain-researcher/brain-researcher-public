# Disabled Tests

This folder holds tests that target removed or retired surfaces. Keep files here
only when the old test is useful context for a possible restoration; otherwise
delete the test instead of hiding it from the default suite.

Currently empty. The previous occupants targeted removed modules
(`contrast_annotation`, `brainmap_integration`) or retired legacy
agent/BR-KG smoke surfaces and were deleted in the OSS-prep cleanup;
see `git log --oneline -- tests/_disabled/` for the history.
