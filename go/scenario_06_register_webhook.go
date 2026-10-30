// Scenario 06: Check available event names before registering a destination as an administrator.
package main

import (
	"context"
	"errors"
	"net/url"
	"path/filepath"
)

// registerWebhook checks available event names before registering a destination as an administrator.
func registerWebhook(ctx context.Context, a api, s *state) error {
	const number = "06"
	team, err := required("MDLOGIC_TEAM")
	if err != nil {
		return err
	}
	destination, err := required("MDLOGIC_WEBHOOK_URL")
	if err != nil {
		return err
	}
	u, err := url.Parse(destination)
	if err != nil || u.Scheme != "https" || u.Hostname() == "" || u.User != nil {
		return errors.New("webhook destination must be an explicit HTTPS URL without credentials")
	}
	catalogue, err := a.json(ctx, "GET", "/api/v1/webhooks/events", nil)
	if err != nil {
		return err
	}
	available := map[string]bool{}
	catalogueEvents, ok := catalogue["events"].([]any)
	if !ok {
		return errors.New("unexpected event catalogue response; registration stopped")
	}
	for _, v := range catalogueEvents {
		if text, ok := v.(string); ok {
			available[text] = true
		}
	}
	events := []string{
		"document.created",
		"document.updated",
		"project.created",
		"project.updated",
		"share.created",
	}
	for _, event := range events {
		if !available[event] {
			return errors.New("required lifecycle event absent from the live catalogue")
		}
	}
	path := "/api/v1/teams/" + idPath(team) + "/webhooks"
	body := object{
		"url":         destination,
		"events":      events,
		"description": "Generated report lifecycle",
	}
	if err = beginCreate(number, path, body); err != nil {
		return err
	}
	result, err := a.json(ctx, "POST", path, body)
	if err != nil {
		return err
	}
	// The signing secret is shown once; save the response privately before validation.
	if err = saveJSON("webhook.json", result); err != nil {
		return err
	}
	if stringField(objectField(result, "webhook"), "id") == "" || stringField(result, "secret") == "" {
		return errors.New("unusable webhook response retained privately; reconcile pending operation")
	}
	if err = completeCreate(number); err != nil {
		return err
	}
	return output(object{"scenario": number, "webhookId": stringField(objectField(result, "webhook"), "id"), "secretFile": filepath.Join(stateDir(), "webhook.json")})
}
