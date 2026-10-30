// Scenario 03: Read the live revision and use it as an atomic replacement guard.
package main

import (
	"context"
	"errors"
	"os"
	"unicode/utf8"
)

// updateReport reads the live revision and uses it as an atomic replacement guard.
func updateReport(ctx context.Context, a api, s *state) error {
	const number = "03"
	docPath := s.documentPath()
	content, err := os.ReadFile(env("MDLOGIC_INPUT", "fixtures/report-updated.md"))
	if err != nil {
		return errors.New("cannot read updated report input")
	}
	if !utf8.Valid(content) {
		return errors.New("report input must be valid UTF-8; original file is preserved")
	}
	current, err := a.json(ctx, "GET", docPath, nil)
	if err != nil {
		return err
	}
	revision := stringField(objectField(current, "document"), "revision")
	if revision == "" {
		return errors.New("live read is missing its revision; stop and review")
	}
	// The synthetic correction is already reviewed. A real application must compare
	// the live content with its last accepted source before replacing user edits.
	// A 409 must return to that review; never fetch a new revision and blindly retry.
	body := object{
		"content":          string(content),
		"expectedRevision": revision,
		"changeNote":       "Refresh generated report",
	}
	result, err := a.json(ctx, "PUT", docPath, body)
	if err != nil {
		return err
	}
	s.Revision = stringField(objectField(result, "document"), "revision")
	if s.Revision == "" {
		return errors.New("write response missing revision; reconcile current document")
	}
	if err = saveJSON("state.json", s); err != nil {
		return err
	}
	return output(object{"scenario": number, "documentId": s.DocumentID, "decision": stringField(result, "decision")})
}
