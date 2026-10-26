# Changelog

## Unreleased

- Added scheduled relay acknowledgement sweeps and one operator ping per overdue expectation: pages only open overdue rows from `--pending --json`, sanitized and clipped, under one 90 s deadline and a non-blocking lock; a reused ID pages again after its earlier expectation closed. (#236)
