// Dispatch the six scenarios after validating the local mapping and saved results.
package main

import (
	"context"
	"errors"
	"os"
	"path/filepath"
)

func scenario(ctx context.Context, number string) error {
	if number != "01" && number != "02" && number != "03" && number != "04" && number != "05" && number != "06" {
		return errors.New("choose scenario01..06 or webhook")
	}
	s, err := loadState()
	if err != nil {
		return err
	}
	if number == "01" && s.ProjectID != "" {
		return errors.New("project already mapped; reuse it rather than creating a duplicate")
	}
	if number == "02" && s.DocumentID != "" {
		return errors.New("report already mapped; use scenario03 to update")
	}
	if number != "01" && number != "06" && s.ProjectID == "" {
		return errors.New("run scenario01 first")
	}
	if number != "01" && number != "02" && number != "06" && s.DocumentID == "" {
		return errors.New("run scenario02 first")
	}

	if number == "05" || number == "06" {
		filename := "share.json"
		if number == "06" {
			filename = "webhook.json"
		}
		if _, err := os.Stat(filepath.Join(stateDir(), filename)); err == nil {
			return errors.New("a private response already exists; inspect and reconcile it before creating another share or webhook")
		} else if !errors.Is(err, os.ErrNotExist) {
			return errors.New("cannot inspect private output before creating")
		}
	}
	a, err := connect(ctx)
	if err != nil {
		return err
	}
	switch number {
	case "01":
		return createProject(ctx, a, &s)
	case "02":
		return createReport(ctx, a, &s)
	case "03":
		return updateReport(ctx, a, &s)
	case "04":
		return exportReport(ctx, a, &s)
	case "05":
		return shareReport(ctx, a, &s)
	case "06":
		return registerWebhook(ctx, a, &s)
	default:
		return errors.New("choose scenario01..06 or webhook")
	}
}
