// Scenario 05: Create a share only when explicitly requested; never print the private link.
package main

import (
	"context"
	"errors"
	"path/filepath"
)

// shareReport creates a share and saves the private link without printing it.
func shareReport(ctx context.Context, a api, s *state) error {
	const number = "05"
	docPath := s.documentPath()
	path := docPath + "/shares"
	body := object{"expiresInDays": 30}
	if err := beginCreate(number, path, body); err != nil {
		return err
	}
	result, err := a.json(ctx, "POST", path, body)
	if err != nil {
		return err
	}
	// Retain even a malformed success response: the share may already exist.
	if err = saveJSON("share.json", result); err != nil {
		return err
	}
	if stringField(objectField(result, "share"), "id") == "" || stringField(objectField(result, "share"), "url") == "" {
		return errors.New("unusable share response retained privately; reconcile pending operation")
	}
	if err = completeCreate(number); err != nil {
		return err
	}
	return output(object{"scenario": number, "shareId": stringField(objectField(result, "share"), "id"), "privateFile": filepath.Join(stateDir(), "share.json")})
}
