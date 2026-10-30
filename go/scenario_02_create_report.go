// Scenario 02: Store generated Markdown once and keep the returned document ID and revision.
package main

import (
	"context"
	"errors"
	"os"
	"unicode/utf8"
)

// createReport stores generated Markdown once and keeps its document ID and revision.
func createReport(ctx context.Context, a api, s *state) error {
	const number = "02"
	projectPath := s.projectPath()
	content, err := os.ReadFile(env("MDLOGIC_INPUT", "fixtures/report.md"))
	if err != nil {
		return errors.New("cannot read generated report input")
	}
	if !utf8.Valid(content) {
		return errors.New("report input must be valid UTF-8; original file is preserved")
	}

	// ifNotExists prevents replacing a same-name artifact; the journal handles
	// an unknown response outcome in this application, rather than retrying POST.
	body := object{
		"name":        "report.md",
		"content":     string(content),
		"format":      "markdown",
		"ifNotExists": true,
	}
	if err = beginCreate(number, projectPath+"/artifacts", body); err != nil {
		return err
	}
	result, err := a.json(ctx, "POST", projectPath+"/artifacts", body)
	if err != nil {
		return err
	}
	doc := objectField(result, "artifact")
	s.DocumentID = stringField(doc, "id")
	s.Revision = stringField(doc, "revision")
	if s.DocumentID == "" || s.Revision == "" {
		return errors.New("create response missing stable document ID/revision; reconcile pending create")
	}
	if err = saveJSON("state.json", s); err != nil {
		return err
	}
	if err = completeCreate(number); err != nil {
		return err
	}
	return output(object{"scenario": number, "documentId": s.DocumentID})
}
