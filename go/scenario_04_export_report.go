// Scenario 04: Read a bounded history page and save an explicit HTML export.
package main

import (
	"context"
	"errors"
	"path/filepath"
)

// exportReport reads one history page and saves an explicitly requested HTML export.
func exportReport(ctx context.Context, a api, s *state) error {
	const number = "04"
	docPath := s.documentPath()
	page, err := a.json(ctx, "GET", docPath+"/versions?limit=20&offset=0", nil)
	if err != nil {
		return err
	}
	items, validItems := page["items"].([]any)
	_, validMore := page["hasMore"].(bool)
	if !validItems || !validMore {
		return errors.New("malformed history page; export stopped")
	}
	if len(items) > 0 {
		first, _ := items[0].(map[string]any)
		version := stringField(first, "id")
		if version == "" {
			return errors.New("version result missing ID")
		}
		if _, err = a.json(ctx, "GET", docPath+"/versions/"+idPath(version), nil); err != nil {
			return err
		}
	}
	raw, err := a.request(ctx, "GET", docPath+"/renders/html", nil)
	if err != nil {
		return err
	}
	if err = saveBytes("report.html", raw); err != nil {
		return err
	}
	return output(object{"scenario": number, "versionsOnPage": len(items), "hasMore": page["hasMore"], "exportFile": filepath.Join(stateDir(), "report.html")})
}
