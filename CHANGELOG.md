# Changelog

## Unreleased

- Added scheduled relay acknowledgement sweeps and one operator ping per overdue expectation: pages only open overdue rows from `--pending --json` (nothing when that list is unavailable), sanitized and clipped, under one 90 s deadline and a non-blocking lock; a ping killed by its timeout is not retried; a reused ID pages again after its earlier expectation closed. (#236)
