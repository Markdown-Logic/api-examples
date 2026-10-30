// Private local mappings and create-operation journals; these are not API idempotency keys.
package main

import (
	"encoding/json"
	"errors"
	"net/url"
	"os"
	"path/filepath"
)

type object = map[string]any

// state maps one application report to stable remote IDs and its last saved revision.
type state struct {
	ProjectID  string `json:"projectId,omitempty"`
	DocumentID string `json:"documentId,omitempty"`
	Revision   string `json:"revision,omitempty"`
}

func stateDir() string {
	return env("MDLOGIC_STATE_DIR", ".local/go")
}

func (s state) projectPath() string {
	return "/api/v1/projects/" + idPath(s.ProjectID)
}

func (s state) documentPath() string {
	return s.projectPath() + "/documents/" + idPath(s.DocumentID)
}

// privateDir protects mappings, generated text and once-only secrets from other users.
func privateDir(path string) error {
	if err := os.MkdirAll(path, 0700); err != nil {
		return err
	}
	return os.Chmod(path, 0700)
}

// saveJSON writes private structured state without exposing it in console output.
func saveJSON(name string, value any) error {
	raw, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		return err
	}
	return saveBytes(name, append(raw, '\n'))
}

// saveBytes syncs a complete temporary file before replacing the saved result.
// A failed response never leaves a partial HTML export at the destination.
func saveBytes(name string, raw []byte) error {
	if err := privateDir(stateDir()); err != nil {
		return errors.New("cannot create private state directory")
	}
	f, err := os.CreateTemp(stateDir(), ".save-*")
	if err != nil {
		return err
	}
	defer os.Remove(f.Name())
	if _, err = f.Write(raw); err == nil {
		err = f.Sync()
	}
	closeErr := f.Close()
	if err != nil {
		return err
	}
	if closeErr != nil {
		return closeErr
	}
	return os.Rename(f.Name(), filepath.Join(stateDir(), name))
}

// loadState treats a missing mapping as the first run and a malformed mapping as an error.
func loadState() (state, error) {
	var s state
	raw, err := os.ReadFile(filepath.Join(stateDir(), "state.json"))
	if errors.Is(err, os.ErrNotExist) {
		return s, nil
	}
	if err != nil {
		return s, errors.New("cannot read state")
	}
	// A JSON null is not an empty first-run mapping. Treat it as damaged state
	// rather than allowing scenario 01 to create another remote project.
	var saved *state
	if json.Unmarshal(raw, &saved) != nil || saved == nil {
		return s, errors.New("state is malformed; reconcile before replacing it")
	}
	return *saved, nil
}

// beginCreate records the original target and payload before any network write.
// Exclusive creation blocks a second invocation until the first outcome is reconciled.
func beginCreate(scenario, path string, body object) error {
	apiOrigin, err := origin(env("MDLOGIC_API_ORIGIN", "https://api.markdownlogic.com"))
	if err != nil {
		return err
	}
	if err := privateDir(stateDir()); err != nil {
		return err
	}
	f, err := os.OpenFile(filepath.Join(stateDir(), "pending-"+scenario+".json"), os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if errors.Is(err, os.ErrExist) {
		return errors.New("a create operation is pending; reconcile it before removing its marker")
	}
	if err != nil {
		return err
	}
	intent := object{
		"scenario":  scenario,
		"apiOrigin": apiOrigin,
		"status":    "reconcile-before-repeat",
		"method":    "POST",
		"path":      path,
		"body":      body,
	}
	err = json.NewEncoder(f).Encode(intent)
	if err == nil {
		err = f.Sync()
	}
	_ = f.Close()
	return err
}

// completeCreate is called only after the response has been validated and saved.
func completeCreate(scenario string) error {
	return os.Remove(filepath.Join(stateDir(), "pending-"+scenario+".json"))
}

// stringField rejects numbers and other JSON types instead of coercing them into IDs.
func stringField(m object, key string) string {
	value, _ := m[key].(string)
	return value
}

// objectField returns nil for an unexpected envelope; stringField then returns empty.
func objectField(m object, key string) object {
	value, _ := m[key].(map[string]any)
	return value
}

func idPath(value string) string {
	return url.PathEscape(value)
}

// output is limited to the safe scenario summary, never a share URL or signing secret.
func output(value any) error {
	return json.NewEncoder(os.Stdout).Encode(value)
}
