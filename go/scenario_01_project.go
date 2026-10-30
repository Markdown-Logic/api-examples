// Scenario 01: Create a project, save its stable ID, then list and rename it.
package main

import (
	"context"
	"errors"
)

// createProject saves the stable ID before any follow-up request can fail.
func createProject(ctx context.Context, a api, s *state) error {
	const number = "01"
	team, err := required("MDLOGIC_TEAM")
	if err != nil {
		return err
	}
	base := "/api/v1/teams/" + idPath(team) + "/projects"
	body := object{"name": "Report integration example", "mode": "document"}
	if err = beginCreate(number, base, body); err != nil {
		return err
	}
	result, err := a.json(ctx, "POST", base, body)
	if err != nil {
		return err
	}
	s.ProjectID = stringField(objectField(result, "project"), "id")
	if s.ProjectID == "" {
		return errors.New("create response missing project ID; reconcile pending create")
	}
	// Persist the mapping before clearing the create journal or making later calls.
	if err = saveJSON("state.json", s); err != nil {
		return err
	}
	if err = completeCreate(number); err != nil {
		return err
	}
	if _, err = a.json(ctx, "GET", base+"?limit=50&offset=0", nil); err != nil {
		return err
	}
	if _, err = a.json(ctx, "PATCH", "/api/v1/projects/"+idPath(s.ProjectID), object{"name": "Report integration example"}); err != nil {
		return err
	}
	return output(object{"scenario": number, "projectId": s.ProjectID})
}
