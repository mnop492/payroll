# Project Direction

Last updated: 2026-07-14

## Product Positioning

This payroll system should treat Excel import as a transitional input source, not the final operating model.

The web application should be the authoritative platform for:

- payroll review
- calculation validation
- manual correction
- audit trail
- final payroll output

## Why Excel Import Still Exists

Excel import currently serves two transitional purposes:

1. It allows users to validate Excel-calculated payroll against the web app.
2. It helps users gradually move from Excel-based operations into the web workflow.

## Strategic Direction

The long-term direction is:

- use Excel as a bootstrap channel for historical and transitional data entry
- use the web app as the official review-and-correction layer
- reduce Excel dependency over time
- move operational ownership into the web app

## Workflow Interpretation

The intended workflow is:

1. Import monthly Excel data when needed.
2. Review imported attendance, sales, monthly rates, and overrides in the web UI.
3. Correct records directly in the web app.
4. Recalculate payroll using the system rules.
5. Validate system output against Excel when necessary.
6. Use audit logs and generated outputs as the official traceable result.

## Priority Areas

### 1. Post-import guided workflow

After a successful import, the UI should guide users to the next review steps:

- review attendance
- review sales
- review monthly hourly rates and commission overrides
- run validation
- generate payroll result

### 2. Stronger Excel vs Web comparison

The system should make it easy to answer:

- what Excel calculated
- what the web app calculated
- where they differ
- why they differ

### 3. Faster correction and recalculation loop

Users should feel that correcting data in the web app is faster and safer than fixing Excel manually.

### 4. Gradual migration to web-first data entry

Priority web-first data areas:

- new employee maintenance
- sales record entry
- monthly commission overrides
- attendance adjustments
- payroll review and approval

## Decision Rule

When making product or UI decisions:

- do not optimize only for import convenience
- optimize for review accuracy, correction speed, traceability, and long-term web adoption

## Success Indicator

This direction is succeeding when:

- users rely less on Excel for final correction work
- more month-end corrections happen inside the web app
- validation becomes easier and faster
- audit visibility is better than the old spreadsheet process
